# Handoff: calibration of LLM-reported financial figures (written 2026-11-14 ~00:45 CT)

## Research question
When an LLM states a company's reported financial figure with a stated confidence, does confidence track correctness,
and does that change for filing periods after the model's knowledge boundary? With vs without web search.
Track 1 (Model Epistemics evals). Ground truth: SEC XBRL (public, as-reported, reproducible).
WRDS is optional, only for covariates; raw WRDS data is licensed and must not be redistributed. Not needed so far.

## Done
- src/edgar.py: SEC client (reads SEC_USER_AGENT from env; rate limit ~4 req/s). Verified working.
- src/ground_truth.py -> data/derived/ground_truth.csv: 150 companies (50 each large/mid/small by total assets
  at CY2025Q4I), metrics revenue / net_income / total_assets, up to 6 periods each spread over 2023-01..2026-09,
  2,285 rows after fixes on 2026-11-14 (see results/attempts_log.md). Columns include ticker, name, stratum, metric, period_type(quarter|instant), start, end, filed (public
  availability date), form, accn (verify on sec.gov), val (originally reported value = earliest filing per period).
- API keys for Anthropic and OpenAI are in .env and validated.

## Known data gotchas (put in Methods)
- XBRL mixes quarterly, year-to-date and annual durations; we keep only 80-100 day quarters (+ instants for assets).
  Q4 flow figures are not reported standalone in 10-Ks, so they are mostly absent (23 quarter rows do come from 10-Ks;
  see results/gt_10k_quarter_rows.csv). Dec-31 quarters are therefore mostly total assets. Say so in Limitations.
- Use `filed` date (not period end) as when the number became public.
- Companies switch revenue tags; we use the tag with most facts per company.

## Status 2026-11-14 (steps 1-4 done, WAITING FOR USER APPROVAL of the full-run budget)
- Step 1: lag filter + EAI exclusion + zero-value drop; spot check 12/12 (results/spot_check.csv).
- Step 2: src/ask.py + src/prices.py (prices fetched 2026-11-14, sources in file). Raw responses are in results/raw/v1/.
- Step 4: pilot done ($7.19 spent). Summary: results/pilot_summary.csv, per call: results/pilot_calls.csv,
  extrapolation: results/pilot_cost_extrapolation.csv, budget options: results/budget_options.csv.
  Full plan as written is about $1,585, over the $60 cap.
- User decisions 2026-11-14: cap raised to $100 total; Fable 5.2 dropped; gpt-5.5 in; retry once when an
  answer can't be parsed; refusal fallbacks stay off. ask.py now caps CUMULATIVE spend over results/raw/.
- Budget update 2026-11-14: separate budgets, $200 Anthropic and $200 OpenAI (replaces the $100 total).
  ask.py takes --cap-anthropic / --cap-openai (cumulative per provider over results/raw/).
- 2026-11-14: gpt-5.5 replaced by gpt-5.6-sol (user asked; same 10 pilot questions: no-tools $0.012/call vs $0.059,
  ~540 vs ~1,930 output tokens). gpt-5.6-sol price is promotional until 2026-11-30. gpt-5.5 pilot data kept, not in main study.
  Pilot questions are frozen in data/derived/samples/pilot10.csv (re-drawing after the GT fix gave a different set).
- Proposed plan, awaiting go-ahead: same questions for all 6 models (Opus, Sonnet, Haiku, gpt-6.1-sol, gpt-6.1-terra,
  gpt-5.6-sol): no-tools full 2,285 q; web on s300. Estimates incl. pilot: Anthropic ~$94, OpenAI ~$79.
- 2026-11-14 full run switched to the Batch APIs (50% tokens) via src/batch.py after ~90 sync web calls.
  Test batch (24 req) OK incl. OpenAI web_search in batch. Full batches submitted (state: results/batches/state.json);
  a background job waits, collects, runs one retry round and collects again (log: results/batch_full_run.log).
  Projected total incl. everything so far: Anthropic ~$53, OpenAI ~$51 (search fees counted at full price).
  If the session dies: `python src/batch.py status` then `python src/batch.py collect`, then re-run the two submit
  commands (web --sample s300, none --sample full) once for retries and collect again.
- 2026-11-14 FULL RUN COMPLETE (step 5 done): 6 models x (no-tools 2,285 q + web s300), 0 API errors, one retry round
  done; every answer parses (15,580 records for the 6 models incl. pilot extras). Estimated spend: Anthropic $56.10, OpenAI $48.88
  (check against the consoles). Next: step 6 scoring (no API cost).

## TODO (in order)
1. Spot-check ~10 random rows against the filing at sec.gov using accn. Fix any parsing issue before spending money.
2. Write src/ask.py: question template "What was <name> (<ticker>)'s reported <metric> for the <quarter ending DATE>?
   Answer JSON: {value_usd, confidence_pct, abstain(bool)}". Parse robustly; save every raw response to results/raw/.
3. Models: anthropic claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5 (maybe claude-fable-5-2);
   openai gpt-6.1-sol (MORE EXPENSIVE: run on a random 1/3 subsample), gpt-6.1-terra, gpt-5.5 (older reference).
   Conditions: no tools vs web search (OpenAI search tool / Anthropic web_search tool). Newer models may need
   reasoning/effort or max_completion_tokens params: discover with the pilot.
4. PILOT: 10 questions per model/condition, record tokens and $ per call, extrapolate full cost, then STOP and report
   the estimate to the user for approval.
5. After approval: full run with resumable caching (skip already-answered question ids), retries, concurrency limit.
6. Scoring: correct if |pred-true|/|true| <= 1%; also report 5%. Metrics: accuracy, ECE, reliability curve,
   confident-wrong rate (conf>=80 and wrong), abstention rate, by stratum, metric, and filing-date bin.
   KEY FIGURE: accuracy and mean confidence vs filing date, per model (find the knowledge boundary empirically,
   do not trust stated cutoffs).
7. Robustness: prompt wording variants, tolerance 1% vs 5%, numeric units (thousands/millions), bootstrap CIs.
8. Save all figures to results/figures and numbers to results/*.csv. Keep a log of failed attempts (the template asks
   for "what didn't work").

## Report template (the user has the .docx)
Sections: 1 Intro (2-3 contributions), 2 Related Work, 3 Methods, 4 Results (>=1 figure, robustness),
5 Discussion & Limitations & Future Work (link to AI safety), 6 Conclusion, Code and Data, References,
Appendix, LLM Usage Statement. Body <= 8 pages (recommended 4). The sprint REQUIRES an appendix titled
"Limitations and Dual-Use / Ethical Considerations" (the template lacks it). Related work to position against:
FinDVer (EMNLP 2024), FinAuditing, FinVerBench (2026), MASK, ForecastBench, "Why Language Models Hallucinate".

## Status 2026-11-14: step 6 scoring done (no API cost)
- `python3 src/score.py` -> results/scored.csv (15,510 rows = 6 models x (2,285 none + 300 web)) and
  results/scoring_checks.txt. Checks passed: every prompt matches the current ground truth, 0 errors, 0 unparsed,
  re-parsing the saved text gives the same values, 0 unit-scale errors (parser is not mis-scaling).
  Off-study records (pilot extras outside s300) are dropped and counted in scoring_checks.txt.
- `python3 src/analyze.py` (~50 s) -> results/metrics_*.csv, reliability_bins.csv, web_search_use.csv,
  changepoint_none.csv, diag_unit_sign.csv, gt_disagreements.csv, gt_suspect_companies.csv, figures/fig1-4.
  Definitions are in the analyze.py docstring. CIs are 95% cluster bootstrap over companies (B=1000; 300 for
  fine-grained tables). Calibration (ECE/Brier/AUROC) is at 1% only, answered questions only.
- Abstention is large (prompt allowed "abstain + best guess"), so report coverage, accuracy over all questions and
  over answered side by side. `guess1` = accuracy of the guesses including abstained ones.
- Changepoint (single step in accuracy vs filing month) is secondary; some CIs are wide (gpt-6.1-*).
- Ground-truth caveats found (not changed; user decision): CAC and IBKR revenue use a contract-revenue tag that
  likely excludes interest income (models consistently 2.7x-6x higher); NI revenue for Q4-2025 (from the 10-K)
  is 6.52B, about 5x the company's other quarters, possibly an annual figure. LENZ/UPB: models say ~0 revenue.
- SONNET WEB RE-RUN (user approved 2026-11-14): 108/300 Sonnet web answers had hit `too_many_requests` on the
  server-side code_execution step of web_search_20260209 during the batch run. Old records moved to
  results/raw/v1_superseded_ratelimited/ (cost still counted); qids in results/sonnet_web_rerun_qids.csv. Re-run
  synchronously with 2 workers: 0 rate limits, 0 errors, 0 unparsed, cost $11.54 (log: results/sonnet_web_rerun.log).
  Sonnet web acc within 1% is now 0.657 (was 0.470). Sonnet still chose not to search on 106/300 (no error).
  Anthropic cumulative estimated spend: $67.64. Opus has 1 rate-limited web record (answer correct); left as is.
- Also added: ece_guess/auroc_guess (all guesses incl. abstained), set full_excl_suspect (drops 23 10-K quarter rows
  + CAC/IBKR revenue; headline numbers move <=0.004), composition_counts.csv, metrics_bin_equalweight.csv,
  gt_sign_flips.csv (1 row: CRBG Q1-2023 NI, two GPT models give +459M vs ground truth -459M).
- Next: user reviews figures; step 7 robustness (prompt variants cost money; tolerance 1%/5% and units are
  already in the tables for free).

## Status 2026-11-14 late: step 7 prompt variants done (user approved "Run all three")
- Variants (src/ask.py `question(..., version)`, chosen by env PROMPT_VERSION; v1 prompts verified unchanged):
  v2_forced (no abstain option), v3_paraphrase (reworded, same content), v4_conf5 (confidence = P(within 5%)).
  No-tools, s300, 6 models, Batch API (+10-question sync pilot each). Raw: results/raw/<variant>/.
- Outcome: 0 API errors, 0 tool errors; 1 unparsed after retry (Sonnet v3, degenerate repetitive text both
  attempts; counted as not answered). 31 v2 confidences are in (0,1); all on wrong low-confidence guesses, read
  literally as percent.
- Cost of step 7: Anthropic $4.11, OpenAI $7.78. Cumulative estimated: Anthropic $71.75, OpenAI $56.66.
- Scoring: `PROMPT_VERSION=<v> python3 src/score.py` -> results/scored_<v>.csv; `python3 src/robustness.py` ->
  results/robust_variants.csv (metrics at 1% and 5% targets), robust_paired.csv (variant - v1, paired cluster
  bootstrap), robust_by_bin.csv, figures/fig5_prompt_variants.png.
