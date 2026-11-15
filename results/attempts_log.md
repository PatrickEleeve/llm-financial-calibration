# What didn't work / data fixes (for the report's "what didn't work")

## 2026-11-14
- **Restated comparatives counted as "original" values (fixed).** Taking the earliest filing per period
  sometimes picked a comparative from the *next year's* filing because the original fact was missing under
  the chosen tag (e.g. UPS NI Q2-2025, CRH 2023 quarters, AMT Q4-2023 restated for discontinued ops). The
  `filed` date was then ~1 year late. Fix: only facts with filed - period_end <= 150 days are eligible
  (`MAX_LAG_DAYS` in src/ground_truth.py). The pre-fix file is kept at data/derived/ground_truth_v0_nolagfilter.csv.
  Rows went from 2,321 to 2,292.
- **Ticker/entity mismatch (excluded).** Ticker map gives EAI (Entergy Arkansas) for CIK 7323, but
  companyfacts names it ENTERGY CORPORATION, with only 2026 facts filed under Entergy Corp's accessions.
  Questions would be ambiguous, so that CIK is excluded. No other sampled company has accessions from a
  different registrant in the ticker map.
- **Zero values (excluded).** 6 revenue rows (RCKT, pre-revenue biotech) have val = 0, where relative
  error is undefined, so they are dropped. Final: 2,281 rows. 8 negative revenue rows are kept.
- **Revenue tag choice (fixed).** "Most facts" picked RevenueFromContractWithCustomer* over total Revenues for firms reporting both; that line can exclude other revenue (NiSource Q3-2024 1,046.1M vs 1,076.3M total; CTOS rental revenue; RMR reimbursables). Found because 6 models with web search agreed on 1,076.3M. Fix: per period prefer `Revenues`, else contract revenue. 19 values changed; 2,285 rows. Previous file: data/derived/ground_truth_v1_mostfacts_tag.csv. Caveat: a company can now mix tags across periods.
- **Spot check:** 12 random rows were all found in the primary filing document (results/spot_check.csv).
  Caveat: the check is a string match of the value (in units, thousands or millions). It confirms the
  number appears in the filing, not that it sits in the right row, column or period. Short numbers like
  "451" are weak evidence.
- **Pilot (10 questions x 7 models x 2 conditions, $7.19):** 139/140 parsed. claude-sonnet-5-5 with web
  search once ended with `stop_reason=tool_use`, calling a nonexistent client tool named `json` with empty
  input (qid 0000894315_net_income_quarter_2024-09-30). It is recorded as a parse failure and not retried.
- **Cost surprise:** the web condition adds 14-32K input tokens per call (search results), so it costs
  10-100x the no-tools condition. The full plan in HANDOFF (all 7 models x 2 conditions, full set) is
  estimated at ~$1,585 (results/pilot_cost_extrapolation.csv).
- Note: the pricing page lists gpt-6.1-sol at $2/$10 per MTok, cheaper than gpt-5.5 ($5/$30). HANDOFF's
  "sol is more expensive" premise does not hold (it is more expensive than terra only).
- Refusal `fallbacks` are deliberately left off for the Claude models, because they would silently swap
  the model being measured. No refusals occurred in the pilot.
- **Pilot set re-drawn by accident.** `--pilot 10` re-sampled from the ground truth, which had changed after the
  revenue-tag fix, so the first gpt-5.6 pilot hit 10 different questions (0 overlap). The original 10 are now
  frozen in data/derived/samples/pilot10.csv and gpt-5.6-sol was re-run on them. The extra answers are kept
  and reused by the full run.
- **gpt-5.5 dropped for cost:** ~1,930 output (reasoning) tokens per no-tools answer, $135 for the full set.
  Replaced by gpt-5.6-sol (~540 tokens, $0.012/call) in the same older-generation reference role.
- **Switched from sync to Batch API mid-run** (user's suggestion, budget). The sync web run was stopped after
  ~90 calls (~$3.5); a few in-flight calls may have been billed without being saved (not in our spend estimate).
  Batch records carry `batch: true` and are costed at 50% token prices, search fees at full price.
- Some models (e.g. Sonnet, Haiku) sometimes answer in the web condition without searching. That is kept as
  the model's choice; analysis should report the share of web-condition answers with >= 1 search.
- OpenAI `web_search_call` items include page opens/finds, not only searches; we bill each as a search
  (an upper bound on cost).
- **Batch collect crashed** on an OpenAI web result: a `web_search_call` with status `searching` fails the SDK's
  strict Response model. Fixed by parsing batch bodies as plain JSON (`summarize_openai_dict`), checked identical to
  the SDK path on 160 records. Collect is idempotent, so nothing was lost or re-bought.
- **Full run outcome:** complete coverage, 0 API errors. Unparsed after first pass: 3 (2 Sonnet refusals, 1 Haiku
  `tool_use` stop) plus the pilot Sonnet `tool_use`. After one retry each, all parsed. One Sonnet refusal had
  category `reasoning_extraction` (a false positive on a total-assets question); it answered on retry. My first
  retry check missed two of these because I read a truncated log; caught on recount. Final estimated spend
  Anthropic $56.10 (projected $53), OpenAI $48.88 (projected $51).
- **Scoring (step 6):** figures first plotted mean confidence and reliability points from bins with 1-2 answers,
  which drew misleading spikes; bins with n<5 are now hidden (boundary figures) or hollow and unjoined (reliability).
  A consensus check (>=4 of 6 web answers agree, ground truth differs) flagged 3 questions: CAC revenue x2 (bank,
  contract-revenue tag excludes interest income) and NI Q4-2025 revenue (10-K value ~5x other quarters). A pooled check
  flagged CAC and IBKR as definitional mismatches. Not corrected; listed in results/gt_*.csv for the user.
- **Sonnet web answers hit server-side rate limits (found in scoring).** 108/300 Sonnet web records contain a
  `too_many_requests` error on the `code_execution` step that `web_search_20260209` runs for dynamic filtering (batch
  run). Their accuracy within 1% is 0.324 vs 0.552 for the other 192 (results/web_tool_errors.csv). Opus: 1 record,
  Haiku: 0 (Haiku has 10 `invalid_tool_input` and 1 `unavailable` errors). Not re-run yet; user decision.
- **Sonnet web re-run (user approved).** The 108 rate-limited records were archived to
  results/raw/v1_superseded_ratelimited/ and re-asked synchronously with 2 workers (same prompt and parameters).
  Result: 0 rate limits, 0 errors, 0 unparsed, $11.54. Sonnet web accuracy within 1% went from 0.470 to 0.657
  (results/metrics_overall.csv). Lesson: check server-tool error blocks inside "successful" batch results.
- **Prompt variants (step 7).** One Sonnet v3 answer degenerated into repeated text ("$(splash)...") on both
  attempts (first hit max_tokens); counted as not answered. score.py now allows a parse failure only after the retry.
  31 v2_forced confidences are below 1 (28 gpt-6.1-terra); all accompany wrong guesses, so they are read as percent.
