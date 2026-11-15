# Epistemics sprint: do LLMs know when they don't know financial facts?

Question: when a model states a company's reported financial figure with a
stated confidence, does the confidence track correctness, and how does that
change for filing periods before vs after the model's training cutoff, with
and without web search?

Ground truth: SEC XBRL company facts (public, as-reported, reproducible).
Optional: WRDS (Compustat/CRSP/IBES) only for firm size / coverage covariates;
raw WRDS data is licensed and is NOT redistributed.

Setup:
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # then fill in keys + SEC_USER_AGENT yourself
    python src/edgar.py    # self-test

## Reproduce

    python src/ground_truth.py                 # SEC XBRL -> data/derived/ground_truth.csv (2,285 questions)
    python src/make_samples.py                 # stratified subsamples s300 / s100
    # model calls (cost money; caps are cumulative per provider):
    python src/batch.py submit --conditions none --sample full --cap-anthropic 150 --cap-openai 150
    python src/batch.py submit --conditions web  --sample s300 --cap-anthropic 150 --cap-openai 150
    python src/batch.py collect                # repeat until all batches are collected
    PROMPT_VERSION=v2_forced python src/batch.py submit --conditions none --sample s300 ...   # robustness variants
    # scoring and analysis (no API cost):
    python src/score.py                        # -> results/scored.csv
    python src/analyze.py                      # -> results/metrics_*.csv, results/figures/fig1-4
    for v in v2_forced v3_paraphrase v4_conf5; do PROMPT_VERSION=$v python src/score.py; done
    python src/robustness.py                   # -> results/robust_*.csv, results/figures/fig5
    python report/build_docx.py                # fills the report template (template not included)

## What is in the repository

- `data/derived/`: ground truth (`ground_truth.csv`, with SEC accession numbers for checking each value) and samples.
- `results/scored*.csv`: one row per model x condition x question (answer, confidence, abstention, correctness).
- `results/metrics_*.csv`, `robust_*.csv`, `reliability_bins.csv`, `changepoint_none.csv`: all reported numbers.
- `results/gt_*.csv`: ground-truth rows flagged as doubtful (not changed). `results/attempts_log.md`: what didn't work.
- Raw API responses (`results/raw/`, ~210 MB, include fetched web content) are not committed.

Models: claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5, gpt-6.1-sol, gpt-6.1-terra, gpt-5.6-sol.
