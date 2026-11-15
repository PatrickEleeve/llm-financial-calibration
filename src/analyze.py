"""Step 6b: metrics, cluster-bootstrap CIs and figures from results/scored.csv.

All tables -> results/metrics_*.csv, figures -> results/figures/*.png.
Definitions (fixed before looking at results):
  n            questions in the cell
  coverage     share answered (not abstained, value given)
  acc1_all     share correct within 1% over ALL questions (abstain = not correct)
  acc1_ans     share correct within 1% over answered questions
  acc5_*       same at 5% (accuracy only; confidence was asked for the 1% event)
  guess1       share whose value is within 1% including abstained guesses (over questions with a value)
  conf_ans     mean stated confidence over answered
  overconf     conf_ans - acc1_ans
  ece          10 equal-width bins, answered only, vs correct-within-1%
  brier        answered only
  auroc        confidence discriminating correct vs wrong, answered only
  cw_all       P(answered, conf >= 80, wrong) over all questions
  cw_given80   P(wrong | answered, conf >= 80), with n80
  ece_guess, auroc_guess  same as ece/auroc but over every guess with a value, abstained included
                          (comparable across models with different coverage)
CIs: 95% percentile, cluster bootstrap over companies (cik), B=1000, seed 2026.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask import MAIN_MODELS, ROOT  # noqa: E402

OUT = ROOT / "results"
FIG = OUT / "figures"
B = 1000
SEED = 2026
COLORS = dict(zip(MAIN_MODELS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]))
MIN_N = 5
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def auroc(y, s):
    pos, neg = s[y], s[~y]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    r = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def ece(c, y, nb=10):
    if len(c) == 0:
        return np.nan
    idx = np.minimum((c * nb).astype(int), nb - 1)
    tot = 0.0
    for b in range(nb):
        m = idx == b
        if m.any():
            tot += m.sum() * abs(c[m].mean() - y[m].mean())
    return tot / len(c)


def metrics(g):
    """g: dict of numpy arrays for one cell. Returns dict of point metrics."""
    n = len(g["answered"])
    a = g["answered"]
    c, y1 = g["conf"][a], g["correct1"][a]
    hv = g["has_value"]
    hi = c >= 0.8
    return dict(
        n=n, n_ans=int(a.sum()), coverage=a.mean() if n else np.nan,
        acc1_all=g["correct1"].mean() if n else np.nan, acc5_all=g["correct5"].mean() if n else np.nan,
        acc1_ans=y1.mean() if a.any() else np.nan, acc5_ans=g["correct5"][a].mean() if a.any() else np.nan,
        guess1=g["within1"][hv].mean() if hv.any() else np.nan,
        conf_ans=c.mean() if a.any() else np.nan,
        conf_all=g["conf"].mean() if n else np.nan,
        overconf=(c.mean() - y1.mean()) if a.any() else np.nan,
        ece=ece(c, y1), brier=((c - y1) ** 2).mean() if a.any() else np.nan, auroc=auroc(y1, c),
        cw_all=(hi & ~y1).sum() / n if n else np.nan, n80=int(hi.sum()),
        cw_given80=(~y1[hi]).mean() if hi.any() else np.nan,
        # same calibration over every guess with a value (abstained guesses included): comparable across coverage
        ece_guess=ece(g["conf"][hv], g["within1"][hv]), auroc_guess=auroc(g["within1"][hv], g["conf"][hv]))


COLS = ["answered", "conf", "correct1", "correct5", "within1", "has_value"]
CI_KEYS = ["coverage", "acc1_all", "acc5_all", "acc1_ans", "conf_ans", "overconf", "ece", "brier", "auroc",
           "cw_all", "cw_given80", "ece_guess", "auroc_guess"]


def arrays(df):
    return {k: df[k].to_numpy() for k in COLS}


def boot_cell(df, rng, b=B):
    """Point metrics + cluster-bootstrap percentile CIs for one cell."""
    point = metrics(arrays(df))
    groups = [ix for ix in df.groupby("cik").indices.values()]
    A = arrays(df)
    draws = []
    for _ in range(b):
        pick = rng.integers(0, len(groups), len(groups))
        ix = np.concatenate([groups[i] for i in pick])
        draws.append(metrics({k: v[ix] for k, v in A.items()}))
    D = pd.DataFrame(draws)
    for k in CI_KEYS:
        point[f"{k}_lo"], point[f"{k}_hi"] = np.nanpercentile(D[k], [2.5, 97.5]) if D[k].notna().any() else (np.nan, np.nan)
    return point


def table(df, by, rng, b=B):
    rows = []
    for key, g in df.groupby(by, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), **boot_cell(g.reset_index(drop=True), rng, b)})
    return pd.DataFrame(rows)


def paired_web_vs_none(df, rng):
    """s300 only: same questions, same resampled companies in both conditions."""
    rows = []
    s = df[df.in_s300]
    for m in MAIN_MODELS:
        w = s[(s.model == m) & (s.condition == "web")].set_index("qid")
        n = s[(s.model == m) & (s.condition == "none")].set_index("qid").loc[w.index]
        ciks = w.cik.to_numpy()
        groups = list(pd.Series(range(len(w))).groupby(ciks).indices.values())
        A, N = arrays(w.reset_index()), arrays(n.reset_index())
        def diff(ix):
            mw, mn = metrics({k: v[ix] for k, v in A.items()}), metrics({k: v[ix] for k, v in N.items()})
            return {k: mw[k] - mn[k] for k in ("acc1_all", "acc1_ans", "conf_ans", "coverage", "ece", "cw_all")}
        pt = diff(np.arange(len(w)))
        D = pd.DataFrame([diff(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))]))
                          for _ in range(B)])
        row = dict(model=m, n=len(w))
        for k, v in pt.items():
            row[f"d_{k}"] = v
            row[f"d_{k}_lo"], row[f"d_{k}_hi"] = np.nanpercentile(D[k], [2.5, 97.5])
        rows.append(row)
    return pd.DataFrame(rows)


def reliability(df):
    rows = []
    a = df[df.answered]
    for (m, c), g in a.groupby(["model", "condition"]):
        b = np.minimum((g.conf * 10).astype(int), 9)
        for k, h in g.groupby(b):
            rows.append(dict(model=m, condition=c, bin_lo=k / 10, bin_hi=(k + 1) / 10, n=len(h),
                             mean_conf=h.conf.mean(), acc1=h.correct1.mean()))
    return pd.DataFrame(rows)


def changepoint(df, rng, ycol="correct1", b=500):
    """Secondary: best single step in P(ycol) as a function of filing date (no-tools, all questions).
    Split candidates = month starts with >= 5% of questions on each side. Fit = max Bernoulli likelihood."""
    rows = []
    for m in MAIN_MODELS:
        g = df[(df.model == m) & (df.condition == "none")].sort_values("filed").reset_index(drop=True)
        t = g.filed.to_numpy()
        months = pd.date_range(g.filed.min(), g.filed.max(), freq="MS")
        def fit(ix):
            tt, yy = t[ix], g[ycol].to_numpy()[ix]
            best = None
            for s in months:
                L = tt < np.datetime64(s)
                if L.mean() < 0.05 or L.mean() > 0.95:
                    continue
                ll = 0.0
                for part in (yy[L], yy[~L]):
                    p = np.clip(part.mean(), 1e-6, 1 - 1e-6)
                    ll += part.sum() * np.log(p) + (len(part) - part.sum()) * np.log(1 - p)
                if best is None or ll > best[0]:
                    best = (ll, s, yy[L].mean(), yy[~L].mean())
            return best
        ll, s, pre, post = fit(np.arange(len(g)))
        groups = list(g.groupby("cik").indices.values())
        bs = []
        for _ in range(b):
            ix = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
            bs.append(fit(ix)[1])
        bs = pd.to_datetime(pd.Series(bs))
        rows.append(dict(model=m, y=ycol, split=s.date(), pre=pre, post=post,
                         split_lo=bs.quantile(0.025).date(), split_hi=bs.quantile(0.975).date()))
    return pd.DataFrame(rows)


def gt_disagreements(df):
    """s300 web answers: >= 4 of 6 models agree within 1% of each other but not with ground truth."""
    w = df[(df.condition == "web") & df.value_usd.notna()]
    rows = []
    for q, g in w.groupby("qid"):
        v = g.value_usd.to_numpy()
        for x in v:
            agree = np.abs(v - x) <= 0.01 * abs(x) if x != 0 else v == 0
            if agree.sum() >= 4 and abs(x - g.true.iloc[0]) > 0.01 * abs(g.true.iloc[0]):
                r = g.iloc[0]
                rows.append(dict(qid=q, ticker=r.ticker, metric=r.metric, end=r.end.date(), filed=r.filed.date(),
                                 gt_value=r.true, consensus_value=np.median(v[agree]), n_agree=int(agree.sum()),
                                 models=";".join(g.model[agree]), ratio=np.median(v[agree]) / r.true))
                break
    return pd.DataFrame(rows)


def gt_suspect_companies(df):
    """Company x metric where pooled model guesses (any model/condition) are off by >2x in >= 80% of >= 10 guesses:
    a sign of a definitional mismatch (e.g. a bank whose revenue tag covers fee income only), not a fix."""
    a = df[df.value_usd.notna() & (df.true != 0)].copy()
    a["lr"] = np.log10((a.value_usd / a.true).abs().clip(1e-6, 1e6))
    c = a.groupby(["ticker", "name", "metric"]).agg(
        n=("lr", "size"), median_ratio=("lr", lambda x: 10 ** x.median()),
        share_off_2x=("lr", lambda x: (x.abs() > np.log10(2)).mean())).reset_index()
    return c[(c.n >= 10) & (c.share_off_2x >= 0.8)].sort_values("median_ratio")


def gt_sign_flips(df):
    """No-tools: >= 2 models answer the NEGATED ground truth within 1% (possible sign convention issue)."""
    n = df[(df.condition == "none") & df.value_usd.notna()]
    n = n[(-n.value_usd - n.true).abs() <= 0.01 * n.true.abs()]
    g = n.groupby(["qid", "ticker", "metric", "true"]).agg(n_models=("model", "size"),
                                                             models=("model", ";".join),
                                                             mean_conf=("conf", "mean")).reset_index()
    return g[g.n_models >= 2]


def gt_10k_quarter_rows():
    """Quarter flow rows whose source is a 10-K, with the ratio to the company's median 10-Q value."""
    gt = pd.read_csv(ROOT / "data/derived/ground_truth.csv", dtype={"cik": str})
    q = gt[gt.period_type == "quarter"]
    tenq = q[~q.form.str.startswith("10-K")].groupby(["cik", "metric"]).val.median().rename("median_10q")
    k = q[q.form.str.startswith("10-K")].join(tenq, on=["cik", "metric"])
    k["ratio_to_median_10q"] = k.val / k.median_10q
    return k[["cik", "ticker", "name", "metric", "start", "end", "filed", "form", "accn", "val", "median_10q",
              "ratio_to_median_10q"]].sort_values("ratio_to_median_10q")


def web_tool_errors(df):
    w = df[df.condition == "web"]
    return w.groupby(["model", "rate_limited"]).agg(
        n=("qid", "size"), any_tool_err=("n_tool_err", lambda x: (x > 0).mean()), searched=("searches", lambda x: (x > 0).mean()),
        acc1_all=("correct1", "mean"), abstain=("abstain", "mean")).reset_index()


# ------------------------------------------------------------------ figures
def style(ax):
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)


def fig_boundary(byq, cond, fname, title, xlabel="filing date (median per fiscal quarter of the period)"):
    """Small multiples per model: accuracy (all), mean confidence (answered), coverage vs filing date."""
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.2), sharex=True, sharey=True)
    for ax, m in zip(axes.flat, MAIN_MODELS):
        g = byq[(byq.model == m) & (byq.condition == cond)].sort_values("x")
        col = COLORS[m]
        ax.fill_between(g.x, g.acc1_all_lo, g.acc1_all_hi, color=col, alpha=0.18, lw=0)
        ax.plot(g.x, g.acc1_all, color=col, lw=2, label="accuracy (within 1%, all q.)")
        full, hol = g[g.flow_share >= 0.5], g[g.flow_share < 0.5]
        hol_label = "hollow: quarter is mostly total assets" if len(hol) else None
        ax.scatter(full.x, full.acc1_all, s=16, color=col, zorder=3)
        ax.scatter(hol.x, hol.acc1_all, s=16, facecolor="#fcfcfb", edgecolor=col, lw=1.2, zorder=3,
                   label=hol_label)
        gc = g[g.n_ans >= MIN_N]  # mean confidence is shown only where >= MIN_N answers exist
        ax.plot(gc.x, gc.conf_ans, color=INK, lw=1.5, ls="--", marker="s", ms=3,
                label=f"mean confidence (answered; bins with n>={MIN_N})")
        ax.plot(g.x, g.coverage, color=INK2, lw=1, ls=":", label="share answered")
        ax.set_title(m, fontsize=10, color=INK, loc="left")
        ax.set_ylim(0, 1)
        style(ax)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, fontsize=8, frameon=False, loc="lower right", ncol=3, bbox_to_anchor=(0.99, 0.0))
    fig.supxlabel(xlabel, fontsize=9, color=INK2, x=0.01, ha="left")
    fig.suptitle(title, fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=200)
    plt.close(fig)


def fig_boundary_metric(byqm, fname):
    fig, axes = plt.subplots(3, 6, figsize=(15, 7), sharex=True, sharey=True)
    for i, met in enumerate(["revenue", "net_income", "total_assets"]):
        for j, m in enumerate(MAIN_MODELS):
            ax = axes[i, j]
            g = byqm[(byqm.model == m) & (byqm.metric == met) & (byqm.n >= MIN_N)].sort_values("x")
            ax.fill_between(g.x, g.acc1_all_lo, g.acc1_all_hi, color=COLORS[m], alpha=0.18, lw=0)
            ax.plot(g.x, g.acc1_all, color=COLORS[m], lw=2, marker="o", ms=3)
            gc = g[g.n_ans >= MIN_N]
            ax.plot(gc.x, gc.conf_ans, color=INK, lw=1.2, ls="--")
            ax.set_ylim(0, 1)
            style(ax)
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%y"))
            if i == 0:
                ax.set_title(m, fontsize=9, color=INK, loc="left")
            if j == 0:
                ax.set_ylabel(met, fontsize=9, color=INK)
    fig.suptitle("No tools, by metric: accuracy within 1% (solid, 95% CI) and mean confidence of answered (dashed); cells with n>=5 only",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=200)
    plt.close(fig)


def fig_reliability(rel, fname):
    fig, axes = plt.subplots(2, 6, figsize=(15, 5.4), sharex=True, sharey=True)
    for i, cond in enumerate(["none", "web"]):
        for j, m in enumerate(MAIN_MODELS):
            ax = axes[i, j]
            g = rel[(rel.model == m) & (rel.condition == cond)]
            ax.plot([0, 1], [0, 1], color=GRID, lw=1)
            big, small = g[g.n >= MIN_N], g[g.n < MIN_N]
            ax.scatter(big.mean_conf, big.acc1, s=np.clip(big.n, 8, 300), color=COLORS[m], edgecolor="#fcfcfb",
                       lw=1.5, zorder=3)
            ax.scatter(small.mean_conf, small.acc1, s=14, facecolor="none", edgecolor=COLORS[m], lw=1, zorder=3)
            ax.plot(big.mean_conf, big.acc1, color=COLORS[m], lw=1)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            style(ax)
            if i == 0:
                ax.set_title(m, fontsize=9, color=INK, loc="left")
            if j == 0:
                ax.set_ylabel(f"{cond}: accuracy", fontsize=9, color=INK)
    fig.supxlabel(f"stated confidence (answered only; marker area ~ n; hollow = bin with n<{MIN_N}, not joined)", fontsize=9, color=INK2)
    fig.suptitle("Reliability: stated P(within 1%) vs observed", fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    df = pd.read_csv(OUT / "scored.csv", dtype={"cik": str}, parse_dates=["filed", "end"])
    df["has_value"] = df.value_usd.notna()
    df["conf"] = df.conf.fillna(0.0)  # never null for answered (checked in score.py)
    none, web = df[df.condition == "none"], df[df.condition == "web"]
    s300none = none[none.in_s300]

    # sensitivity set: drop quarter rows sourced from 10-Ks and the two definitional-mismatch revenue series
    k10 = gt_10k_quarter_rows()
    k10.to_csv(OUT / "gt_10k_quarter_rows.csv", index=False)
    drop = set(k10.cik + "_" + k10.metric + "_quarter_" + k10.end) | set(
        none[(none.ticker.isin(["CAC", "IBKR"])) & (none.metric == "revenue")].qid)
    overall = pd.concat([table(none, ["model", "condition"], rng).assign(set="full"),
                         table(none[~none.qid.isin(drop)], ["model", "condition"], rng).assign(set="full_excl_suspect"),
                         table(s300none, ["model", "condition"], rng).assign(set="s300"),
                         table(web, ["model", "condition"], rng).assign(set="s300"),
                         table(web[~web.rate_limited], ["model", "condition"], rng).assign(
                             set="s300_web_not_rate_limited (diagnostic, selected)")])
    overall["n_excluded"] = np.where(overall.set == "full_excl_suspect", len(drop), 0)
    overall.to_csv(OUT / "metrics_overall.csv", index=False)
    table(df, ["model", "condition", "bin"], rng).to_csv(OUT / "metrics_by_bin.csv", index=False)
    table(df, ["model", "condition", "metric"], rng).to_csv(OUT / "metrics_by_metric.csv", index=False)
    table(df, ["model", "condition", "stratum"], rng).to_csv(OUT / "metrics_by_stratum.csv", index=False)
    table(none, ["model", "condition", "metric", "bin"], rng, b=300).to_csv(OUT / "metrics_by_metric_bin.csv", index=False)

    # fiscal-quarter bins, plotted at the median filing date of the bin
    comp = df[(df.model == MAIN_MODELS[0])].groupby(["condition", "period_q", "bin", "metric", "stratum"]).size()
    comp.rename("n").reset_index().to_csv(OUT / "composition_counts.csv", index=False)
    xq = df.groupby("period_q").filed.median().rename("x")
    fs = none[none.model == MAIN_MODELS[0]].groupby("period_q").period_type.apply(
        lambda x: (x == "quarter").mean()).rename("flow_share")
    byq = table(df, ["model", "condition", "period_q"], rng, b=300).merge(xq, on="period_q").merge(fs, on="period_q")
    byq.to_csv(OUT / "metrics_by_period_quarter.csv", index=False)
    byqm = table(none, ["model", "metric", "period_q"], rng, b=300).merge(xq, on="period_q")
    byqm.to_csv(OUT / "metrics_by_metric_period_quarter.csv", index=False)

    paired_web_vs_none(df, rng).to_csv(OUT / "metrics_web_vs_none_paired.csv", index=False)
    rel = reliability(df)
    rel.to_csv(OUT / "reliability_bins.csv", index=False)

    sr = web.assign(searched=web.searches > 0).groupby(["model", "searched"]).agg(
        n=("qid", "size"), acc1_all=("correct1", "mean"), coverage=("answered", "mean")).reset_index()
    sr["share"] = sr.n / sr.groupby("model").n.transform("sum")
    sr.to_csv(OUT / "web_search_use.csv", index=False)

    pd.concat([changepoint(df, rng, "correct1"), changepoint(df, rng, "within1")]).to_csv(
        OUT / "changepoint_none.csv", index=False)
    diag = df.groupby(["model", "condition"]).agg(unit_error=("unit_error", "mean"),
                                                   sign_error=("sign_error", "mean"),
                                                   n_unit=("unit_error", "sum"), n_sign=("sign_error", "sum")).reset_index()
    diag.to_csv(OUT / "diag_unit_sign.csv", index=False)
    gt_disagreements(df).to_csv(OUT / "gt_disagreements.csv", index=False)
    gt_suspect_companies(df).to_csv(OUT / "gt_suspect_companies.csv", index=False)
    gt_sign_flips(df).to_csv(OUT / "gt_sign_flips.csv", index=False)
    web_tool_errors(df).to_csv(OUT / "web_tool_errors.csv", index=False)
    # metric-mix-free view: equal-weight average of the per-metric accuracies in each filing-date bin
    mb = pd.read_csv(OUT / "metrics_by_metric_bin.csv")
    mb.groupby(["model", "bin"]).agg(acc1_all_eqw=("acc1_all", "mean"), conf_ans_eqw=("conf_ans", "mean"),
                                     min_cell_n=("n", "min")).reset_index().to_csv(OUT / "metrics_bin_equalweight.csv", index=False)

    fig_boundary(byq, "none", "fig1_boundary_none.png",
                 "No tools (all 2,285 questions): accuracy within 1% with 95% cluster-bootstrap CI, "
                 "mean confidence, share answered")
    # web: s300 has ~20 questions per fiscal quarter, so use the 5 filing-date bins (60 each) instead
    bybin = pd.read_csv(OUT / "metrics_by_bin.csv")
    xb = df.groupby("bin").filed.median().rename("x")
    fig_boundary(bybin.merge(xb, on="bin").assign(flow_share=1.0), "web", "fig2_boundary_web.png",
                 "Web search (s300, 60 questions per filing-date bin): accuracy within 1%, mean confidence, share answered",
                 xlabel="filing date (median of bin: 2023, 2024, 2025, 2026H1, 2026H2)")
    fig_boundary_metric(byqm, "fig3_boundary_by_metric_none.png")
    fig_reliability(rel, "fig4_reliability.png")
    print("done")
