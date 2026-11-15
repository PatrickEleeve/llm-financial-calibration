"""Build the XBRL ground-truth question set (no WRDS needed).

Strata come from total assets at one reference date (SEC frames API).
For each sampled company and metric we keep originally-reported values
(earliest filing per period) with accession numbers so every row can be
verified on sec.gov. Output: data/derived/ground_truth.csv
"""
import argparse, json, random
from datetime import date
from pathlib import Path
import pandas as pd
import edgar

ROOT = Path(__file__).resolve().parent.parent
DER = ROOT / "data" / "derived"
SLIM = DER / "slim_v2"  # v2 keeps facts for every candidate tag (slim/ kept only the winning tag)
SLIM.mkdir(parents=True, exist_ok=True)

# Priority order: total revenue first. RevenueFromContractWithCustomer* is often only the ASC 606
# contract-revenue line, which excludes other revenue (e.g. NiSource Q3-2024: 1,046.1M vs total 1,076.3M).
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]
METRICS = {"revenue": (REV_TAGS, "flow"),
           "net_income": (["NetIncomeLoss"], "flow"),
           "total_assets": (["Assets"], "instant")}
START, END = date(2023, 1, 1), date(2026, 9, 30)
STRATA = {"large": (50e9, 1e15), "mid": (2e9, 50e9), "small": (2e8, 2e9)}


def sample_companies(per_stratum, seed):
    frame = edgar._get_json(
        "https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY2025Q4I.json",
        "frame_Assets_CY2025Q4I.json")["data"]
    tick = {}
    for t, c in edgar.ticker_map().items():
        tick.setdefault(c, t)
    rng = random.Random(seed)
    out = []
    for name, (lo, hi) in STRATA.items():
        pool = [d for d in frame if lo <= d["val"] < hi and str(d["cik"]).zfill(10) in tick]
        pool = list({d["cik"]: d for d in pool}.values())
        rng.shuffle(pool)
        for d in pool[:per_stratum]:
            cik = str(d["cik"]).zfill(10)
            out.append(dict(cik=cik, ticker=tick[cik], stratum=name, ref_assets=d["val"]))
    return out


def slim_facts(cik):
    f = SLIM / f"{cik}.json"
    if f.exists():
        return json.loads(f.read_text())
    raw = edgar.fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    g = raw["facts"].get("us-gaap", {})
    rows = []
    for metric, (tags, kind) in METRICS.items():
        best = []
        for tag in tags:
            cand = []
            for r in g.get(tag, {}).get("units", {}).get("USD", []):
                if r["form"] not in ("10-Q", "10-K"):
                    continue
                end = date.fromisoformat(r["end"])
                if not (START <= end <= END):
                    continue
                if kind == "flow":
                    if "start" not in r:
                        continue
                    d = (end - date.fromisoformat(r["start"])).days
                    if 80 <= d <= 100:
                        ptype = "quarter"
                    elif 350 <= d <= 380:
                        ptype = "annual"
                    else:
                        continue
                else:
                    if "start" in r:
                        continue
                    ptype = "instant"
                cand.append(dict(metric=metric, tag=tag, period_type=ptype, start=r.get("start"),
                                 end=r["end"], filed=r["filed"], form=r["form"], accn=r["accn"], val=r["val"]))
            for c in cand:
                c["tag_prio"] = tags.index(tag)
            best += cand
        rows += best
    res = {"name": raw.get("entityName"), "rows": rows}
    f.write_text(json.dumps(res))
    return res


# Entities whose ticker and XBRL identity disagree, so the question would be ambiguous.
EXCLUDE_CIKS = {
    # ticker map says EAI (Entergy Arkansas) but companyfacts names it ENTERGY CORPORATION,
    # with only 2026 facts filed under Entergy Corp's accession numbers.
    "0000007323",
}
MAX_LAG_DAYS = 150  # filed - period end; larger means a later comparative/restatement, not the original


def pick_periods(rows, n):
    """Originally reported value per period; n periods spread evenly over time.

    Only facts from the filing that covers that period are eligible (lag <= MAX_LAG_DAYS).
    Without this, a missing original fact falls back to a comparative in next year's
    filing (often restated, e.g. discontinued ops) with a misleading `filed` date.
    """
    rows = [r for r in rows
            if (date.fromisoformat(r["filed"]) - date.fromisoformat(r["end"])).days <= MAX_LAG_DAYS]
    # per period: highest-priority tag, then earliest filing (= originally reported)
    rows = sorted(rows, key=lambda r: (r["end"], r.get("tag_prio", 0), r["filed"]))
    seen, uniq = set(), []
    for r in rows:
        k = (r["metric"], r["period_type"], r["start"], r["end"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    uniq = [r for r in uniq if r["period_type"] in ("quarter", "instant")]
    if len(uniq) <= n:
        return uniq
    idx = [round(i * (len(uniq) - 1) / (n - 1)) for i in range(n)]
    return [uniq[i] for i in sorted(set(idx))]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-stratum", type=int, default=50)
    ap.add_argument("--periods", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    comps = sample_companies(a.per_stratum, a.seed)
    print(f"sampled {len(comps)} companies", flush=True)
    out = []
    for i, c in enumerate(comps, 1):
        try:
            s = slim_facts(c["cik"])
        except Exception as e:
            print("skip", c["ticker"], type(e).__name__, flush=True)
            continue
        for metric in METRICS:
            for r in pick_periods([x for x in s["rows"] if x["metric"] == metric], a.periods):
                out.append({**c, "name": s["name"], **r})
        if i % 10 == 0:
            print(f"{i}/{len(comps)}", flush=True)
    df = pd.DataFrame(out)
    n0 = len(df)
    df = df[~df.cik.isin(EXCLUDE_CIKS)]
    df = df[df.val != 0]  # relative error undefined at 0
    print(f"excluded {n0 - len(df)} rows (entity exclusions + zero values)")
    df.to_csv(DER / "ground_truth.csv", index=False)
    print("rows:", len(df))
    print(df.groupby(["stratum", "metric"]).size().unstack())
    df["filed_year"] = df["filed"].str[:4]
    print(df.groupby("filed_year").size())
