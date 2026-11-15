"""Step 6a: join every study answer to the ground truth and score it.

Output: results/scored.csv (one row per model x condition x question, no raw API payload)
        results/scoring_checks.txt (what was dropped and why, sanity checks)
Analysis set: MAIN_MODELS; condition none = all ground-truth questions, web = s300.
Correct = |pred - true| / |true| <= tol and not abstained. Unit/sign errors count as wrong
(they are reported separately as diagnostics).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask import MAIN_MODELS, RAW, ROOT, PROMPT_VERSION, SAMPLES, filing_bin, qid, question, parse_answer  # noqa: E402

OUT = ROOT / "results"
TOLS = (0.01, 0.05)
SCALES = {"x1e3": 1e3, "x1e6": 1e6, "/1e3": 1e-3, "/1e6": 1e-6, "sign": -1.0}


def load_gt():
    gt = pd.read_csv(ROOT / "data/derived/ground_truth.csv", dtype={"cik": str})
    gt["qid"] = gt.apply(qid, axis=1)
    assert gt.qid.is_unique, "qid not unique in ground truth"
    gt["bin"] = filing_bin(gt.filed).astype(str)
    assert not gt.bin.isin(["nan"]).any(), "filing date outside bins"
    return gt


def load_records(gt, log):
    s300 = set(pd.read_csv(SAMPLES / "s300.csv").qid)
    s100 = set(pd.read_csv(SAMPLES / "s100.csv").qid)
    gtq = gt.set_index("qid")
    rows, dropped = [], {}
    for model in MAIN_MODELS:
        for cond in (("none", "web") if PROMPT_VERSION == "v1" else ("none",)):  # variants: no-tools on s300
            want = set(gt.qid) if (cond == "none" and PROMPT_VERSION == "v1") else s300
            d = RAW / PROMPT_VERSION / model / cond
            n_stale = 0
            for p in sorted(d.glob("*.json")):
                q = p.stem
                if q not in want:
                    dropped[(model, cond, "not in analysis set")] = dropped.get((model, cond, "not in analysis set"), 0) + 1
                    continue
                r = json.loads(p.read_text())
                if r["prompt"] != question(gtq.loc[q].rename(q), cond):
                    n_stale += 1
                # parser re-check: saved fields must equal a fresh parse of the saved text
                fresh = parse_answer(r.get("text"))
                same = (fresh["parse_ok"] == r["parse_ok"] and fresh["value_usd"] == r["value_usd"]
                        and fresh["confidence_pct"] == r["confidence_pct"])
                meta = r.get("meta") or {}
                rawtxt = json.dumps(r.get("raw"))
                n_tool_err = rawtxt.count("_tool_result_error")   # Anthropic server-tool error blocks
                rate_limited = "too_many_requests" in rawtxt
                rows.append(dict(
                    model=model, condition=cond, qid=q, error=r.get("error"), parse_ok=r["parse_ok"],
                    parse_note=r.get("parse_note", ""), reparse_same=same,
                    value_usd=r["value_usd"], confidence_pct=r["confidence_pct"], abstain=r["abstain"],
                    attempt=r.get("attempt", 1), batch=bool(r.get("batch")), cost_usd=r.get("cost_usd"),
                    searches=(r.get("usage") or {}).get("searches", 0),
                    stop_reason=meta.get("stop_reason"), text=(r.get("text") or "")[-400:],
                    n_tool_err=n_tool_err, rate_limited=rate_limited,
                    in_s300=q in s300, in_s100=q in s100))
            log.append(f"{model:18s} {cond:4s}: stale prompts {n_stale}")
            assert n_stale == 0, f"{model}/{cond}: {n_stale} prompts differ from current ground truth"
    for k, v in sorted(dropped.items()):
        log.append(f"dropped {v:4d} records {k}")
    return pd.DataFrame(rows)


def score(df, gt):
    df = df.merge(gt[["qid", "cik", "ticker", "name", "stratum", "metric", "period_type", "end", "filed",
                      "bin", "val"]], on="qid", how="left", validate="many_to_one")
    df["true"] = df.val.astype(float)
    df = df.drop(columns="val")
    df["abstain"] = df.abstain.astype("boolean").fillna(False).astype(bool)
    df["answered"] = ~df.abstain & df.value_usd.notna()
    df["rel_err"] = (df.value_usd - df.true).abs() / df.true.abs()
    for t in TOLS:
        tag = f"{round(t * 100)}"
        df[f"within{tag}"] = df.rel_err <= t                       # the guess itself (incl. abstained guesses)
        df[f"correct{tag}"] = df[f"within{tag}"] & df.answered     # what we score
    # diagnostics: would the answer be within 1% after a unit rescale or sign flip?
    for name, k in SCALES.items():
        df[f"fix_{name}"] = ~df.within1 & ((df.value_usd * k - df.true).abs() / df.true.abs() <= 0.01)
    df["unit_error"] = df[[f"fix_{n}" for n in SCALES if n != "sign"]].any(axis=1)
    df["sign_error"] = df["fix_sign"]
    df["conf"] = df.confidence_pct / 100.0
    df["filed"] = pd.to_datetime(df.filed)
    df["end"] = pd.to_datetime(df.end)
    df["period_q"] = df.end.dt.to_period("Q").astype(str)
    return df


def checks(df, log):
    for (m, c), g in df.groupby(["model", "condition"]):
        n_expected = 2285 if (c == "none" and PROMPT_VERSION == "v1") else 300
        # a parse failure is allowed only after the one retry; it then counts as not answered
        ok = (len(g) == n_expected and g.error.isna().all() and g.qid.is_unique
              and (g.parse_ok | (g.attempt >= 2)).all())
        log.append(f"{m:18s} {c:4s}: n={len(g)} errors={g.error.notna().sum()} unparsed={(~g.parse_ok).sum()}"
                   f" reparse_diff={(~g.reparse_same).sum()} -> {'OK' if ok else 'FAIL'}")
        assert ok, (m, c)
    log.append("")
    log.append("abstain x value_usd null (all models, both conditions):")
    log.append(pd.crosstab(df.abstain, df.value_usd.isna(), rownames=["abstain"],
                           colnames=["value_null"]).to_string())
    cp = df.confidence_pct
    log.append(f"confidence_pct: null={cp.isna().sum()} >100={(cp > 100).sum()} <0={(cp < 0).sum()} "
               f"in (0,1)={((cp > 0) & (cp < 1)).sum()} ==1={(cp == 1).sum()}")
    log.append(f"answered with null confidence: {(df.answered & cp.isna()).sum()}")
    log.append(f"parse notes: {df.parse_note.value_counts().to_dict()}")


if __name__ == "__main__":
    log = []
    gt = load_gt()
    df = score(load_records(gt, log), gt)
    checks(df, log)
    suffix = "" if PROMPT_VERSION == "v1" else f"_{PROMPT_VERSION}"  # run with PROMPT_VERSION=<variant> for step 7
    df["prompt_version"] = PROMPT_VERSION
    df.to_csv(OUT / f"scored{suffix}.csv", index=False)
    (OUT / f"scoring_checks{suffix}.txt").write_text("\n".join(log) + "\n")
    print("\n".join(log))
    print("wrote", OUT / f"scored{suffix}.csv", len(df))
