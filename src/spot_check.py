"""Spot-check random ground-truth rows against the human-readable filing on sec.gov.

For each sampled row we open the filing (by accession number), pull the primary
document's text, and look for the XBRL value rendered as it would appear in the
statements (in units, thousands or millions, with or without parentheses).
Output: results/spot_check.csv (one row per checked fact, with the URL to verify by hand).
"""
import argparse, html, re, sys
from pathlib import Path
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edgar  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def primary_doc_url(cik, accn):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}"
    idx = edgar.fetch_json(f"{base}/index.json")
    docs = [i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith((".htm", ".html"))]
    docs = [d for d in docs if not d.lower().startswith(("r", "fs")) or "10" in d.lower()]
    # primary doc: largest htm that is not an exhibit or index page
    sizes = [(int(i.get("size") or 0), i["name"]) for i in idx["directory"]["item"]
             if i["name"] in docs and "ex" not in i["name"].lower().split("_")[-1][:3]
             and "index" not in i["name"].lower()]
    return base, f"{base}/{max(sizes)[1]}"


def text_of(url):
    edgar.fetch_json  # rate limit shared via module state
    r = requests.get(url, headers=edgar._headers(), timeout=60)
    r.raise_for_status()
    t = re.sub(r"<[^>]+>", " ", r.text)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)


def renderings(v):
    a = abs(int(v))
    out = {"units": f"{a:,}"}
    if a % 1000 == 0 or a >= 10_000:
        out["thousands"] = f"{round(a / 1e3):,}"
    if a >= 1_000_000:
        m = a / 1e6
        out["millions"] = f"{round(m):,}"
        out["millions_1dp"] = f"{m:,.1f}"
    return out


def find(t, v):
    for unit, s in renderings(v).items():
        if re.search(r"(?<![\d,.])" + re.escape(s) + r"(?![\d]|,\d|\.\d)", t):
            return unit, s
    return None, None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    df = pd.read_csv(ROOT / "data/derived/ground_truth.csv", dtype={"cik": str})
    samp = df.sample(a.n, random_state=a.seed)
    rows = []
    for _, r in samp.iterrows():
        try:
            base, url = primary_doc_url(r.cik, r.accn)
            unit, s = find(text_of(url), r.val)
        except Exception as e:  # report, don't hide
            base, url, unit, s = "", "", f"ERROR {type(e).__name__}", None
        rows.append(dict(ticker=r.ticker, metric=r.metric, end=r.end, form=r.form, accn=r.accn,
                         val=r.val, found=unit is not None and not str(unit).startswith("ERROR"),
                         matched_as=unit, matched_text=s, doc_url=url))
        print(rows[-1]["ticker"], r.metric, r.end, r.val, "->", unit, s, flush=True)
    out = pd.DataFrame(rows)
    (ROOT / "results").mkdir(exist_ok=True)
    out.to_csv(ROOT / "results/spot_check.csv", index=False)
    print(f"found {out.found.sum()}/{len(out)}")
