# Do Language Models Know When They Don't Know a Company's Numbers? Calibration of Reported Financial Figures Across the Knowledge Boundary

*Draft v0 (2026-11-15). Claude drafted this text and the user is editing it. Every number comes from a file in `results/`. The source is given in the bracketed comments, which should be removed before submission. Items marked [VERIFY] still need checking by the user.*

## Abstract

Users increasingly ask language models for specific company figures, such as last quarter's revenue, and act on the answers. We test whether the confidence a model states for such a figure tracks whether the figure is right, and what happens for periods the model cannot have seen.

We built 2,285 questions from SEC XBRL filings. They cover revenue, net income and total assets for 140 US-listed companies, with filing dates from February 2023 to November 2026. We asked six models from two providers for each figure along with a probability that it is within 1% of the originally reported value.

Without tools, accuracy within 1% ranges from 3.6% to 31.2% across models. Every model's accuracy falls to at most 6.3% for figures filed in the first half of 2026. The main way models respond to that boundary is by abstaining, not by lowering their confidence. Calibration differs widely between models: expected calibration error ranges from 0.018 to 0.231. One model is wrong in 59% of the answers it gives with at least 80% confidence.

With web search, five of six models reach 94–99% accuracy. The sixth searches in only 65% of cases and reaches 66%. These results hold under a reworded prompt, a prompt that forbids abstention, and a prompt that asks for confidence at a 5% tolerance.

## 1 Introduction

Financial figures suit the study of model epistemics well. They are precise, they have an authoritative public source, and the date each one became public is recorded. A model that quotes a quarterly net income with 90% confidence is making a claim that can be checked exactly. The filing date also tells us whether the figure could have been in the model's training data. This lets us observe how a model behaves as it crosses its own knowledge boundary, without relying on its stated training cutoff.

We ask three questions:

- (i) Does stated confidence track correctness for recall of reported financial figures?
- (ii) What happens to accuracy, confidence and willingness to answer for figures filed after the model's knowledge boundary?
- (iii) How does access to web search change both?

Our contributions are:

1. A reproducible benchmark of 2,285 figures, each with the originally reported value and the date it became public, built from SEC XBRL company facts.
2. A calibration study of six current models with and without web search. It includes an empirical estimate of each model's knowledge boundary from the data, using cluster-bootstrap confidence intervals.
3. Evidence that models handle the boundary mostly by declining to answer rather than by reporting low confidence. Models differ greatly in how well their stated probabilities can be trusted, and these patterns survive three prompt variants.

## 2 Related Work

**Calibration of language models.** Work on neural network calibration (Guo et al., 2017) and on language models' self-knowledge (Kadavath et al., 2022) shows that models can sometimes estimate their own correctness. Verbalized confidence can be better calibrated than token probabilities for instruction-tuned models (Tian et al., 2023). We measure verbalized confidence on a numeric recall task where correctness is objective.

**Honesty and hallucination.** MASK separates honesty from accuracy. "Why Language Models Hallucinate" argues that training and evaluation reward guessing over abstaining. Our abstention results speak directly to that argument.

**Financial fact verification.** FinDVer (EMNLP 2024), FinAuditing and FinVerBench (2026) evaluate models on financial documents given in context. We test recall without the document, and retrieval with web search, against as-reported values.

**Temporal generalization.** ForecastBench evaluates forecasts of events after the training cutoff. We instead test recall of facts that were already public at query time but may lie beyond the training data.

## 3 Methods

**Ground truth.** We used SEC XBRL company-facts data.
- **Companies:** 140 companies in three size groups (48 large, 46 mid, 46 small) defined by total assets at the end of 2025.
- **Metrics:** total revenue, net income attributable to the parent, and total assets. Each company contributes up to six periods between January 2023 and September 2026.
- **Questions:** 2,285 in total (687 revenue, 777 net income, 821 total assets). Filing dates run from 2023-02-16 to 2026-11-13. [`data/derived/ground_truth.csv`]
- **Original values:** for each period we take the value from the earliest filing, so later restatements are excluded. A fact counts only if it was filed within 150 days of the period end.
- **Period types:** flow metrics are restricted to 80–100-day quarters; total assets are point-in-time values. Q4 flow figures are rarely reported as standalone quarters, so most December-quarter questions are about total assets.
- **Spot check:** 12 random values were found in the primary filing documents [`results/spot_check.csv`].
- **Data fixes:** problems we found and fixed while building the data are listed in Appendix A.

**Prompt.** Each question names the company, ticker, metric and period, and asks for the figure "as originally reported in its SEC 10-Q or 10-K filing". The model answers with JSON: `value_usd`, `confidence_pct` (its probability that the value is within 1% of the originally reported figure) and `abstain`. Abstaining models may still give a best guess. The full prompt is in Appendix B.

**Models and conditions.**
- **Models:** claude-opus-5-5, claude-sonnet-5-5 and claude-haiku-5-5 (Anthropic); gpt-6.1-sol, gpt-6.1-terra and gpt-5.6-sol (OpenAI). All use medium reasoning effort and a 16,000-token output limit.
- **No tools:** all 2,285 questions.
- **Web search:** a stratified subsample of 300 questions (s300; 60 per filing-date bin, balanced by metric). Each model gets its provider's web search tool, limited to 3 uses.
- **Execution:** almost all calls ran through the providers' Batch APIs. An answer that could not be parsed was retried once.
- **Rate-limit re-run:** 108 claude-sonnet-5-5 web answers hit a server-side rate-limit error inside the search tool. They were re-run synchronously (Appendix A).

**Scoring.**
- **Correctness:** an answer is correct if |answer − truth| / |truth| ≤ 1% and the model did not abstain. We also report accuracy at 5%.
- **Two kinds of accuracy:** "accuracy" is over all questions, with abstentions counted as not correct. "Accuracy when answering" is over answered questions only.
- **Calibration metrics:** expected calibration error (ECE, 10 equal-width bins), AUROC of confidence for separating correct from incorrect answers, and the confident-wrong rate P(wrong | confidence ≥ 80%). All are computed on answered questions only. Appendix C repeats them over every guess, including abstained ones.
- **Confidence intervals:** 95% percentile intervals from a cluster bootstrap over companies (1,000 resamples).
- **Knowledge boundary:** for each model we fit a single step in accuracy as a function of filing month (maximum likelihood), with a bootstrap interval for the step date.

## 4 Results

### 4.1 Without tools, accuracy is low and calibration differs widely between models

**Table 1. No tools, all 2,285 questions.** [`results/metrics_overall.csv`, set=full]

| Model | Answered | Accuracy (1%) [95% CI] | Acc. when answering | Mean conf. (answered) | ECE | AUROC | P(wrong \| conf ≥ 80) (n) |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | 0.605 | 0.312 [0.279, 0.349] | 0.516 | 0.393 | 0.123 | 0.799 | 0.056 (125) |
| claude-sonnet-5-5 | 0.768 | 0.122 [0.100, 0.146] | 0.159 | 0.390 | 0.231 | 0.746 | 0.593 (231) |
| claude-haiku-5-5 | 0.498 | 0.036 [0.027, 0.047] | 0.073 | 0.205 | 0.132 | 0.649 | 0.500 (8) |
| gpt-6.1-sol | 0.331 | 0.279 [0.246, 0.311] | 0.841 | 0.838 | 0.018 | 0.813 | 0.070 (546) |
| gpt-6.1-terra | 0.203 | 0.136 [0.111, 0.161] | 0.670 | 0.599 | 0.074 | 0.848 | 0.058 (189) |
| gpt-5.6-sol | 0.636 | 0.309 [0.281, 0.337] | 0.485 | 0.486 | 0.020 | 0.901 | 0.079 (468) |

The best models recall fewer than a third of the figures to within 1%. Calibration splits the models into three groups:
- **Well calibrated:** gpt-6.1-sol and gpt-5.6-sol have ECE of about 0.02, and their mean confidence nearly equals their accuracy when answering. The differences are −0.003 and +0.001.
- **Underconfident:** claude-opus-5-5's mean confidence is 0.123 below its accuracy when answering.
- **Overconfident:** claude-sonnet-5-5 is 0.231 above its accuracy, and claude-haiku-5-5 is 0.132 above. Sonnet gave 231 answers with confidence of at least 80%, and 59.3% of them were wrong.

The models also answer at very different rates, from 20.3% of questions (gpt-6.1-terra) to 76.8% (claude-sonnet-5-5). The two gpt-6.1 models are highly selective: they answer few questions but are right on most of those they answer (0.841 and 0.670). Fig. 4 shows the reliability diagrams.

Accuracy also depends on the question:
- **By metric:** revenue is the easiest. Every model's revenue accuracy is above its net-income and total-assets accuracy [`metrics_by_metric.csv`].
- **By company size:** accuracy falls from large to small companies for every model [`metrics_by_stratum.csv`].
- **No unit or scale errors:** no answer becomes correct after rescaling by a factor of 1,000 or 1,000,000. Sign errors are rare, at most 4 per model [`diag_unit_sign.csv`].

### 4.2 At the knowledge boundary, models mainly stop answering

Fig. 1 plots accuracy, mean confidence and the share of questions answered against filing date.

**Table 2. No tools, by filing-date bin.** Each cell gives accuracy (1%, all questions) / share answered. [`results/metrics_by_bin.csv`]

| Model | 2023 (n=547) | 2024 (522) | 2025 (455) | 2026H1 (364) | 2026H2 (397) |
|---|---|---|---|---|---|
| claude-opus-5-5 | 0.302 / 0.888 | 0.538 / 0.895 | 0.538 / 0.826 | 0.063 / 0.146 | 0.000 / 0.003 |
| claude-sonnet-5-5 | 0.132 / 0.987 | 0.144 / 0.979 | 0.231 / 0.949 | 0.058 / 0.580 | 0.015 / 0.151 |
| claude-haiku-5-5 | 0.051 / 0.806 | 0.048 / 0.780 | 0.064 / 0.620 | 0.003 / 0.022 | 0.000 / 0.003 |
| gpt-6.1-sol | 0.548 / 0.640 | 0.448 / 0.521 | 0.215 / 0.284 | 0.014 / 0.016 | 0.000 / 0.000 |
| gpt-6.1-terra | 0.276 / 0.395 | 0.238 / 0.343 | 0.075 / 0.145 | 0.003 / 0.005 | 0.000 / 0.000 |
| gpt-5.6-sol | 0.570 / 0.982 | 0.500 / 0.981 | 0.290 / 0.877 | 0.000 / 0.016 | 0.000 / 0.000 |

Every model's accuracy falls to at most 0.063 in 2026H1. The single-step fit puts the boundary at:
- **Claude models:** January 2026 for opus (95% interval December 2025 to April 2026), March 2026 for sonnet (February to May 2026) and January 2026 for haiku (September 2025 to March 2026).
- **gpt-5.6-sol:** December 2025 (interval December 2025 to January 2026).
- **gpt-6.1-sol:** September 2025, with a wide interval (November 2024 to February 2026).
- **gpt-6.1-terra:** August 2025 (interval September 2024 to August 2025).

[`changepoint_none.csv`] The gpt-6.1 models' accuracy declines through 2024–2025 rather than in one step, so their single split date is poorly identified.

The dominant response at the boundary is abstention. Between 2025 and 2026H1 the share answered falls:

| Model | Share answered, 2025 | Share answered, 2026H1 |
|---|---|---|
| claude-opus-5-5 | 0.826 | 0.146 |
| gpt-5.6-sol | 0.877 | 0.016 |
| claude-haiku-5-5 | 0.620 | 0.022 |

Where models still answer, mean confidence drops for the Claude models and gpt-5.6-sol, for example claude-opus-5-5 from 0.373 to 0.170. Too few post-boundary answers remain for the gpt-6.1 models to measure this (2 to 6 answers in 2026H1).

The exception is claude-sonnet-5-5. It still answers 58.0% of 2026H1 questions with mean confidence 0.185, while its accuracy there is 0.058. Its post-boundary confidence is low but still above its accuracy.

Fig. 3 splits the curves by metric. The 2026 collapse appears for revenue, net income and total assets alike.

### 4.3 Web search mostly closes the gap, but only when the model searches

**Table 3. Web search, s300 (n=300), compared with no tools on the same questions.** [`metrics_overall.csv`, `metrics_web_vs_none_paired.csv`, `web_search_use.csv`]

| Model | Accuracy, web [95% CI] | Change vs no tools [95% CI] | ECE, web | Share of answers with a search |
|---|---|---|---|---|
| claude-opus-5-5 | 0.957 [0.928, 0.979] | +0.673 [0.609, 0.736] | 0.094 | 0.967 |
| claude-sonnet-5-5 | 0.657 [0.597, 0.715] | +0.540 [0.475, 0.604] | 0.096 | 0.647 |
| claude-haiku-5-5 | 0.937 [0.905, 0.965] | +0.903 [0.870, 0.935] | 0.083 | 0.980 |
| gpt-6.1-sol | 0.990 [0.972, 1.000] | +0.737 [0.682, 0.787] | 0.007 | 1.000 |
| gpt-6.1-terra | 0.990 [0.972, 1.000] | +0.857 [0.811, 0.901] | 0.008 | 1.000 |
| gpt-5.6-sol | 0.983 [0.964, 0.997] | +0.693 [0.644, 0.744] | 0.007 | 1.000 |

With search, accuracy no longer depends on filing date (Fig. 2). The OpenAI models searched on every question and reached 0.983–0.990. claude-sonnet-5-5 did not search on 106 of its 300 questions; its accuracy was 0.189 on those and 0.912 when it searched. Its lower web accuracy therefore comes mainly from deciding not to use the tool. claude-opus-5-5 and claude-haiku-5-5 are underconfident with search: their mean confidence is 0.079 and 0.081 below their accuracy when answering.

### 4.4 Robustness

We re-asked the no-tools s300 questions under three prompt variants [`robust_*.csv`, Fig. 5]:
- **(a) Reworded prompt:** same content, different wording.
- **(b) No abstention:** the model must always give a number.
- **(c) 5% tolerance:** confidence is defined as P(within 5%), and answers are scored at 5%.

Results, compared with the main prompt on the same questions:
- **(a)** Accuracy changed by at most 0.017 for every model, and all six confidence intervals include zero.
- **(b)** Calibration over all guesses did not change significantly for any model. Accuracy rose for gpt-6.1-sol (+0.070 [0.039, 0.102]) and gpt-6.1-terra (+0.040 [0.007, 0.074]). Part of what those models abstain on, they could have answered correctly.
- **(c)** Every model raised its mean confidence, by 0.080 to 0.174. That is, the models responded to the change in tolerance. ECE at 5% (over all guesses) fell significantly for four of the six models.
- **Boundary:** the collapse in 2026 appears under all four prompts (Fig. 5).

Other checks:
- **Tolerance:** accuracy at 5% is reported alongside 1% in every table.
- **Questionable ground truth:** excluding 35 potentially problematic questions changes overall accuracy by at most 0.004. These are 23 quarterly values taken from annual reports, plus two companies whose revenue tag appears to exclude interest income. [`metrics_overall.csv`, set=full_excl_suspect]

## 5 Discussion and Limitations

**What the results mean for trusting model-quoted figures.**
- Stated confidence is informative for most models (AUROC 0.65–0.90 without tools), but its scale is not comparable across models. A 90% from gpt-6.1-sol and a 90% from claude-sonnet-5-5 mean very different things.
- For safety-relevant uses such as financial advice, auditing support or agentic research, the more reliable signal at the knowledge boundary was abstention, not confidence.
- Models that stop answering past the boundary avoid confident errors there. A model that keeps answering (claude-sonnet-5-5) does not lower its confidence enough.
- When forced to answer, the stated probabilities stayed about as well calibrated as before. Abstention and stated confidence therefore appear to carry separate information.

**Abstention and the incentive to guess.** The selective gpt-6.1 models answer few questions but are right most of the time when they answer. Forcing an answer recovered some correct answers without hurting calibration. This bears on the argument that evaluation should not penalize abstention. The best policy depends on the cost of a wrong figure compared with no figure.

**Limitations.**
- **Sample:** 140 US companies, three metrics, and quarterly periods only. Q4 flow figures are mostly absent, so December quarters are mostly total assets.
- **Ground truth:** XBRL tags can differ from the headline figure a model has seen. For banks, contract revenue excludes interest income, and a few values look inconsistent (Appendix A). Excluding these does not change the headline numbers.
- **Web condition:** run on 300 questions only. One provider's search tool returned rate-limit errors during batch processing; affected answers were re-run.
- **Settings:** single sampling and a single effort setting per model. Models may behave differently with other system prompts or tool limits.
- **Boundary estimates:** these come from filing dates, not training data. They mark where recall fails, which need not be the training cutoff.

**Future work.** Extend to more metrics, international filers and segment-level figures. Track the same questions across model releases to measure how a model's knowledge boundary moves. Test whether models can tell users when a figure is beyond their knowledge boundary.

## 6 Conclusion

Without tools, current models recall reported financial figures poorly. They handle their knowledge boundary mostly by abstaining. How well stated confidence can be trusted varies more between models than between prompts. With web search, accuracy is near ceiling for models that actually search. Confidence should be judged per model, and abstention behaviour should be evaluated together with calibration.

## Code and Data

Code: `src/` (`ground_truth.py`, `ask.py`, `batch.py`, `score.py`, `analyze.py`, `robustness.py`). Derived data, per-answer scores and all tables: `results/`. Raw SEC data is public and is re-downloaded by the code. https://github.com/PatrickEleeve/llm-financial-calibration

## References

- Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. ICML, PMLR 70:1321-1330. https://proceedings.mlr.press/v70/guo17a
- Kadavath, S., Conerly, T., Askell, A., et al. (2022). Language Models (Mostly) Know What They Know. arXiv:2207.05221.
- Tian, K., Mitchell, E., Zhou, A., Sharma, A., Rafailov, R., Yao, H., Finn, C., & Manning, C. D. (2023). Just Ask for Calibration. EMNLP 2023, pp. 5433-5442. https://doi.org/10.18653/v1/2023.emnlp-main.330
- Kalai, A. T., Nachum, O., Vempala, S. S., & Zhang, E. (2025). Why Language Models Hallucinate. arXiv:2509.04664.
- Ren, R., Agarwal, A., Mazeika, M., et al. (2025). The MASK Benchmark: Disentangling Honesty From Accuracy in AI Systems. arXiv:2503.03750.
- Karger, E., et al. (2025). ForecastBench: A Dynamic Benchmark of AI Forecasting Capabilities. ICLR 2025. arXiv:2409.19839.
- Zhao, Y., et al. (2024). FinDVer. EMNLP 2024, pp. 14739-14752. https://doi.org/10.18653/v1/2024.emnlp-main.818
- Wang, Y., et al. (2025). FinAuditing. arXiv:2510.08886 (SIGIR 2026 Resource Track).
- Panda, S. (2026). FinVerBench: Benchmark Validity and Calibration in LLM Financial Statement Verification. arXiv:2605.29586.

## Appendix A: Data issues and what didn't work

Source: `results/attempts_log.md`.
- **Restated comparatives:** the earliest filing per period sometimes picked a comparative from the next year's filing. Fixed with a 150-day filing-lag filter.
- **Wrong revenue line:** a revenue tag excluded some revenue lines. This was found because six web-search models agreed on a different value for one company. Fixed by preferring the `Revenues` tag, which changed 19 values.
- **Excluded data:** one company where the ticker and the filing entity disagreed, and 6 zero-revenue rows.
- **Sonnet rate limits:** 108 of 300 claude-sonnet-5-5 web answers contained a `too_many_requests` error from the search tool's code-execution step during batch processing. Their accuracy was 0.324, against 0.552 for the rest. They were re-run synchronously and none of the re-runs hit the error.
- **Other answer failures:** one answer in the reworded-prompt run produced degenerate repeated text on both attempts and was counted as not answered.
- **Flagged ground truth (not changed):**
  - Bank and broker revenue tags (CAC, IBKR): models answer 2.7–6× higher.
  - One quarterly value taken from a 10-K that is about 5× the company's other quarters.
  - One net-income value where two models give the opposite sign.

  [`gt_*.csv`]

## Appendix B: Prompt (main version, no-tools condition)

> What was {company} (ticker {T})'s {metric} for the three months ended {date}, as originally reported in its SEC 10-Q or 10-K filing for that period?
>
> Answer from memory; you have no tools.
>
> Give the figure in full US dollars (not thousands or millions); use a negative number for a loss.
> confidence_pct is your probability (0-100) that your value_usd is within 1% of the originally reported figure.
> If you would rather not answer, set abstain to true; still give your best guess and confidence if you have one, otherwise value_usd null.
> Reply with only this JSON object and nothing else:
> {"value_usd": <number or null>, "confidence_pct": <number 0-100>, "abstain": <true|false>}

## Appendix C: Calibration over all guesses

No tools, all 2,285 questions. "All guesses" includes abstained answers that came with a value. [`metrics_overall.csv`, set=full]

| Model | ECE (answered) | ECE (all guesses) | AUROC (answered) | AUROC (all guesses) |
|---|---|---|---|---|
| claude-haiku-5-5 | 0.132 | 0.090 | 0.649 | 0.669 |
| claude-opus-5-5 | 0.123 | 0.087 | 0.799 | 0.860 |
| claude-sonnet-5-5 | 0.231 | 0.207 | 0.746 | 0.760 |
| gpt-5.6-sol | 0.020 | 0.024 | 0.901 | 0.903 |
| gpt-6.1-sol | 0.018 | 0.030 | 0.813 | 0.916 |
| gpt-6.1-terra | 0.074 | 0.047 | 0.848 | 0.898 |

## Limitations and Dual-Use / Ethical Considerations (required appendix)

[USER TO WRITE OR REVIEW.] Points to cover:
- All data is public SEC filings.
- No personal data is used.
- Misuse risk is low. The main risk is over-trusting model-quoted figures, which this work aims to measure.
- Model outputs are not investment advice.

## LLM Usage Statement

[USER TO EDIT so it is accurate.] Claude (Anthropic, claude-opus-5-5 via Claude Code) was used to:
- write the data pipeline, API runners, scoring and analysis code;
- run the experiments under the author's direction and budget decisions;
- produce the tables and figures;
- draft this report's text, which the author reviewed and edited.

All numbers were generated by code from saved results files. The author chose the research question, approved the design decisions and budgets, and verified the final text.
