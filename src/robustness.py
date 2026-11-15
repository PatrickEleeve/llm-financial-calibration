"""Step 7: prompt-variant robustness on s300, no tools, 6 models.

Inputs: results/scored.csv (v1) and results/scored_<variant>.csv (from PROMPT_VERSION=<variant> python src/score.py).
Outputs:
  results/robust_variants.csv  per model x version: metrics (same definitions as analyze.py) with cluster-bootstrap CIs.
                               target=1% scores confidence against within-1%; target=5% against within-5%
                               (v4_conf5 asked for P(within 5%), so its natural target is 5%).
  results/robust_paired.csv    per model x variant: paired differences variant - v1 on the same questions
                               (same resampled companies), for the same target.
  results/robust_by_bin.csv    per model x version x filing-date bin (target 1%; v4 at 5%).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask import MAIN_MODELS, ROOT  # noqa: E402
from analyze import B, SEED, arrays, boot_cell, metrics  # noqa: E402

OUT = ROOT / "results"
VARS = ["v2_forced", "v3_paraphrase", "v4_conf5"]
DIFF_KEYS = ["coverage", "acc1_all", "acc1_ans", "guess1", "conf_ans", "conf_all", "ece", "ece_guess", "auroc_guess",
             "cw_all"]


def load(version):
    f = OUT / ("scored.csv" if version == "v1" else f"scored_{version}.csv")
    d = pd.read_csv(f, dtype={"cik": str}, parse_dates=["filed", "end"])
    d = d[(d.condition == "none") & d.in_s300].copy()
    d["version"] = version
    d["has_value"] = d.value_usd.notna()
    d["conf"] = d.conf.fillna(0.0)
    return d


def at_target(d, target):
    """Re-point the 'correct1/within1' columns used by metrics() at the chosen tolerance."""
    d = d.copy()
    if target == "5%":
        d["correct1"], d["within1"] = d["correct5"], d["within5"]
    return d


def paired(a, b, rng):
    a, b = a.set_index("qid"), b.set_index("qid")
    q = a.index.intersection(b.index)
    a, b = a.loc[q].reset_index(), b.loc[q].reset_index()
    groups = list(a.groupby("cik").indices.values())
    A, Bb = arrays(a), arrays(b)

    def diff(ix):
        ma, mb = metrics({k: v[ix] for k, v in A.items()}), metrics({k: v[ix] for k, v in Bb.items()})
        return {k: mb[k] - ma[k] for k in DIFF_KEYS}
    pt = diff(np.arange(len(a)))
    D = pd.DataFrame([diff(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))]))
                      for _ in range(B)])
    row = {"n": len(a)}
    for k, v in pt.items():
        row[f"d_{k}"] = v
        row[f"d_{k}_lo"], row[f"d_{k}_hi"] = np.nanpercentile(D[k], [2.5, 97.5])
    return row


def fig_variants(b):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from analyze import FIG, INK, INK2, style
    col = {"v1": "#2a78d6", "v2_forced": "#eb6834", "v3_paraphrase": "#1baf7a", "v4_conf5": "#eda100"}
    lab = {"v1": "v1 main (1%)", "v2_forced": "v2 no abstain (1%)", "v3_paraphrase": "v3 paraphrase (1%)",
           "v4_conf5": "v4 confidence for 5% (scored at 5%)"}
    bins = ["2023", "2024", "2025", "2026H1", "2026H2"]
    fig, axes = plt.subplots(2, 6, figsize=(15, 5.6), sharex=True, sharey=True)
    for j, m in enumerate(MAIN_MODELS):
        for i, (y, name) in enumerate([("acc1_all", "accuracy (all q.)"), ("conf_all", "mean confidence (all q.)")]):
            ax = axes[i, j]
            for v in col:
                g = b[(b.model == m) & (b.version == v)].set_index("bin").reindex(bins)
                ax.plot(range(5), g[y], color=col[v], lw=2, marker="o", ms=4, label=lab[v])
            ax.set_ylim(0, 1)
            ax.set_xticks(range(5), bins, fontsize=7)
            style(ax)
            if i == 0:
                ax.set_title(m, fontsize=9, color=INK, loc="left")
            if j == 0:
                ax.set_ylabel(name, fontsize=9, color=INK)
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, fontsize=8, frameon=False, loc="lower center", ncol=4)
    fig.suptitle("Prompt-variant robustness (no tools, s300; 60 questions per filing-date bin)", fontsize=11,
                 color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIG / "fig5_prompt_variants.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    rng = np.random.default_rng(SEED)
    data = {v: load(v) for v in ["v1"] + VARS}
    for v, d in data.items():
        assert d.groupby("model").size().eq(300).all() and set(d.model) == set(MAIN_MODELS), v
    rows, prow, brow = [], [], []
    for m in MAIN_MODELS:
        for v, d in data.items():
            for target in ("1%", "5%"):
                g = at_target(d[d.model == m], target).reset_index(drop=True)
                rows.append({"model": m, "version": v, "target": target, **boot_cell(g, rng)})
        for v in VARS:
            for target in ("1%", "5%"):
                base = at_target(data["v1"][data["v1"].model == m], target)
                var = at_target(data[v][data[v].model == m], target)
                prow.append({"model": m, "variant": v, "target": target, **paired(base, var, rng)})
        for v, d in data.items():
            target = "5%" if v == "v4_conf5" else "1%"
            for bn, g in at_target(d[d.model == m], target).groupby("bin"):
                brow.append({"model": m, "version": v, "target": target, "bin": bn,
                             **boot_cell(g.reset_index(drop=True), rng, b=300)})
    pd.DataFrame(rows).to_csv(OUT / "robust_variants.csv", index=False)
    pd.DataFrame(prow).to_csv(OUT / "robust_paired.csv", index=False)
    pd.DataFrame(brow).to_csv(OUT / "robust_by_bin.csv", index=False)
    fig_variants(pd.DataFrame(brow))
    print("done")
