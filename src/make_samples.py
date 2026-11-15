"""Nested stratified question subsamples for the expensive conditions.

Stratified by filing-date bin x metric (15 cells, equal count per cell), so every
subsample covers the knowledge-boundary range evenly. Nested: s100 is a subset of
s300, which is a subset of the full set, so paired comparisons stay paired.
Output: data/derived/samples/<name>.csv (one qid per row + strata columns).
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask import ROOT, SAMPLES, filing_bin, qid  # noqa: E402

SIZES = {"s300": 300, "s100": 100}  # largest first; smaller ones are prefixes of each shuffled cell
SEED = 2026

if __name__ == "__main__":
    gt = pd.read_csv(ROOT / "data/derived/ground_truth.csv", dtype={"cik": str})
    gt["qid"] = gt.apply(qid, axis=1)
    gt["bin"] = filing_bin(gt.filed).astype(str)
    cells = {k: g.sample(frac=1, random_state=SEED) for k, g in gt.groupby(["bin", "metric"])}
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for name, n in SIZES.items():
        per = n // len(cells)
        extra = n - per * len(cells)
        parts = [g.head(per + (1 if i < extra else 0)) for i, (k, g) in enumerate(sorted(cells.items()))]
        s = pd.concat(parts)[["qid", "ticker", "stratum", "metric", "end", "filed", "bin"]]
        s.to_csv(SAMPLES / f"{name}.csv", index=False)
        print(name, len(s), s.groupby(["bin", "metric"]).size().unstack().to_dict())
    a, b = (set(pd.read_csv(SAMPLES / f"{x}.csv").qid) for x in ("s300", "s100"))
    print("s100 subset of s300:", b <= a)
