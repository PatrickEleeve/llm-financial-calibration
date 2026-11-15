"""Fill the Apart submission template (report/template/template.docx) -> report/submission.docx.

Uses the template's own paragraphs as prototypes (fonts, heading and list styles), removes all guidance text,
and inserts the report text, tables and figures. Numbers in the text were copied from results/*.csv and checked
against them; tables are generated directly from the CSVs here.
Run: python3 report/build_docx.py
"""
import copy
import re
from pathlib import Path

import docx
import pandas as pd
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
FIG = R / "figures"
TPL = ROOT / "report/template/template.docx"
OUT = ROOT / "report/submission.docx"

AUTHORS = [("Luoxiang Pan", "UIUC")]  # (name, affiliation)
TITLE = "Do Language Models Know When They Don't Know a Company's Numbers? Calibration of Reported Financial Figures Across the Knowledge Boundary"

ABSTRACT = (
    "People increasingly ask language models for specific company figures and act on the answers. We test whether a "
    "model's stated confidence in such a figure tracks whether it is right, and what happens for periods the model "
    "cannot have seen. From SEC XBRL filings we built 2,285 questions (revenue, net income and total assets of 140 US "
    "companies, filed February 2023 to November 2026) and asked six models from two providers for each figure plus the "
    "probability that their value is within 1% of the originally reported one. Without tools, accuracy within 1% ranges "
    "from 3.6% to 31.2%, and every model falls to at most 6.3% for figures filed in the first half of 2026. Models "
    "respond to this knowledge boundary mainly by declining to answer rather than by lowering their confidence. "
    "Calibration differs widely: expected calibration error ranges from 0.018 to 0.231, and one model is wrong in 59% "
    "of the answers it gives with at least 80% confidence. With web search, five of six models reach 94-99% accuracy; "
    "the sixth searches on only 65% of questions and reaches 66%. The findings hold under a reworded prompt, a prompt "
    "that forbids abstention, and a prompt that asks for confidence at a 5% tolerance.")

# ---- body: list of (kind, text). kinds: h2, h3, p, num, bullet, fig:<file>|caption, table:<name>|caption
BODY = [
    ("h2", "1. Introduction"),
    ("p", "Financial figures are a clean test bed for model epistemics. Each has an authoritative public source, a precise "
          "value and a recorded date on which it became public. A model that quotes a quarterly net income with 90% "
          "confidence makes a claim that can be checked exactly, and the filing date tells us whether the figure could "
          "have been in its training data. That lets us observe how a model behaves as it crosses its own knowledge "
          "boundary without relying on a stated training cutoff. The failure mode we care about is a confident, wrong "
          "figure that a user, analyst or agent relies on."),
    ("p", "We ask: (i) does stated confidence track correctness when models recall reported financial figures; (ii) what "
          "happens to accuracy, confidence and willingness to answer for figures filed after the knowledge boundary; and "
          "(iii) how does web search change both? Our main contributions are:"),
    ("num", "A reproducible benchmark of 2,285 as-originally-reported figures with public-availability dates, built from SEC XBRL company facts."),
    ("num", "A calibration study of six current models with and without web search, including a data-driven estimate of each model's knowledge boundary with cluster-bootstrap intervals."),
    ("num", "Evidence that models handle the boundary mainly by abstaining rather than by lowering confidence, and that the trustworthiness of stated probabilities differs far more between models than between prompts."),

    ("h2", "2. Related Work"),
    ("p", "**Calibration.** Modern neural networks are often miscalibrated (Guo et al., 2017); language models can partly "
          "estimate their own correctness (Kadavath et al., 2022), and verbalized confidence can be better calibrated "
          "than token probabilities for instruction-tuned models (Tian et al., 2023). We measure verbalized confidence "
          "on a numeric recall task with objective ground truth and a known publication date for every fact."),
    ("p", "**Honesty and hallucination.** MASK (Ren et al., 2025) separates honesty from accuracy, and Kalai et al. (2025) argue that "
          "training and evaluation reward guessing over abstaining. Our abstention results bear directly on this."),
    ("p", "**Financial fact verification and time.** FinDVer (Zhao et al., 2024), FinAuditing (Wang et al., 2025) and FinVerBench (Panda, 2026) evaluate models on "
          "financial documents given in context; we test recall without the document and retrieval with web search, against "
          "as-reported values. ForecastBench (Karger et al., 2025) evaluates forecasts of future events with no known answer; we instead test facts that were "
          "already public at query time but may lie beyond the training data."),

    ("h2", "3. Methods"),
    ("p", "**Ground truth.** From SEC XBRL company facts we drew 140 companies in three size groups by total assets at the "
          "end of 2025 (48 large, 46 mid, 46 small) and up to six periods each between January 2023 and September 2026: "
          "total revenue, net income attributable to the parent, and total assets (687, 777 and 821 questions; 2,285 in "
          "total). For each period we keep the value from the earliest filing, filed within 150 days of period end, so "
          "later restatements are excluded; the filing date is when the figure became public (2023-02-16 to 2026-11-13). "
          "Flows are restricted to 80-100-day quarters, so standalone Q4 flows are mostly absent. A spot check found 12 "
          "of 12 random values in the primary filing documents. Fixes made while building the data, and the "
          "approaches that did not work, are listed in Appendix A."),
    ("p", "**Prompt and models.** Each question names the company, ticker, metric and period and asks for the figure "
          "“as originally reported in its SEC 10-Q or 10-K filing”. The model replies in JSON with the value in "
          "dollars, confidence_pct (its probability that the value is within 1% of the reported figure) and an abstain "
          "flag; an abstaining model may still give a best guess (prompt in Appendix B). We tested claude-opus-5-5, "
          "claude-sonnet-5-5, claude-haiku-5-5, gpt-6.1-sol, gpt-6.1-terra and gpt-5.6-sol, all at medium reasoning "
          "effort with a 16,000-token output limit. The no-tools condition covers all 2,285 questions. The web condition "
          "uses each provider's web search tool (at most 3 uses) on a stratified subsample of 300 questions (s300; 60 per "
          "filing-date bin, balanced by metric). Calls went through the Batch APIs; an unparseable answer was retried once. "
          "We ran a 10-question pilot first, and total API spend was about $128."),
    ("p", "**Scoring.** An answer is correct if |answer − truth| / |truth| ≤ 1% and the model did not abstain; we "
          "also report 5%. Accuracy is over all questions (abstentions count as not correct); accuracy when answering is "
          "over answered questions. On answered questions we compute expected calibration error (ECE, 10 equal-width "
          "bins), AUROC of confidence for separating correct from wrong answers, and the confident-wrong rate "
          "P(wrong | confidence ≥ 80%). Appendix C repeats ECE and AUROC over every guess, including abstained ones. "
          "Intervals are 95% percentile intervals from a cluster bootstrap over companies (1,000 resamples). For the "
          "knowledge boundary we fit, per model, a single step in accuracy as a function of filing month by maximum "
          "likelihood, with a bootstrap interval for the step date."),

    ("h2", "4. Results"),
    ("h3", "4.1 Without tools, accuracy is low and calibration differs widely"),
    ("table:t1", "Table 1. No tools, all 2,285 questions. Answered = share of questions answered (not abstained). "
                 "Accuracy is within 1% over all questions, with 95% cluster-bootstrap interval. Confidence, ECE, AUROC "
                 "and P(wrong | conf ≥ 80%) are over answered questions; n80 = answers with confidence ≥ 80%."),
    ("p", "The best models recall fewer than a third of the figures to within 1% (Table 1). Calibration separates the "
          "models into three groups. gpt-6.1-sol and gpt-5.6-sol are well calibrated (ECE about 0.02; mean confidence "
          "within 0.003 of accuracy when answering). claude-opus-5-5 is underconfident (confidence 0.123 below its "
          "accuracy when answering). claude-sonnet-5-5 and claude-haiku-5-5 are overconfident, by 0.231 and 0.132; "
          "of Sonnet's 231 answers with confidence ≥ 80%, 59.3% are wrong. The models also differ in how often "
          "they answer, from 20.3% (gpt-6.1-terra) to 76.8% (claude-sonnet-5-5); the gpt-6.1 models answer rarely but "
          "are usually right when they do. For every model revenue is the easiest metric and accuracy falls from large "
          "to small companies. No answer becomes correct after rescaling by 10³ or 10⁶, and sign errors are rare "
          "(at most 4 per model), so the errors are not unit mistakes."),
    ("h3", "4.2 At the knowledge boundary, models mainly stop answering"),
    ("fig:fig1_boundary_none.png", "Figure 1. No tools, all 2,285 questions, by fiscal quarter of the period (plotted at "
          "the median filing date). Solid: accuracy within 1% over all questions with 95% cluster-bootstrap band. Dashed: "
          "mean stated confidence of answered questions (quarters with at least 5 answers). Dotted: share of questions "
          "answered. Hollow markers: quarters made up mostly of total-assets questions."),
    ("p", "Every model's accuracy falls to at most 0.063 for figures filed in 2026H1 (Figure 1; Appendix Table C1). The "
          "single-step fit places the boundary in January 2026 for claude-opus-5-5 (95% interval December 2025 to April "
          "2026), March 2026 for claude-sonnet-5-5 (February to May 2026), January 2026 for claude-haiku-5-5 (September "
          "2025 to March 2026) and December 2025 for gpt-5.6-sol (December 2025 to January 2026). For gpt-6.1-sol "
          "(September 2025; November 2024 to February 2026) and gpt-6.1-terra (August 2025; September 2024 to August "
          "2025) accuracy declines gradually through 2024-2025, so a single step is poorly identified."),
    ("p", "The dominant response at the boundary is abstention. From 2025 to 2026H1 the share answered falls from 0.826 "
          "to 0.146 for claude-opus-5-5, 0.877 to 0.016 for gpt-5.6-sol and 0.620 to 0.022 for claude-haiku-5-5. Where "
          "models still answer, mean confidence drops (claude-opus-5-5 from 0.373 to 0.170); the gpt-6.1 models give "
          "only 2-6 answers in 2026H1, too few to measure. The exception is claude-sonnet-5-5, which still answers 58.0% "
          "of 2026H1 questions with mean confidence 0.185 at an accuracy of 0.058. The same collapse appears for each "
          "metric separately (Appendix Figure D2)."),
    ("h3", "4.3 Web search mostly closes the gap, if the model searches"),
    ("table:t2", "Table 2. Web search on s300 (n = 300 per model) and the paired change against no tools on the same "
                 "questions (95% cluster-bootstrap intervals). Searched = share of questions on which the model used "
                 "search at least once."),
    ("p", "With search, accuracy no longer depends on filing date (Appendix Figure D1). The OpenAI models searched on "
          "every question and reached 0.983-0.990. claude-sonnet-5-5 did not search on 106 of 300 questions; its "
          "accuracy was 0.189 on those and 0.912 when it searched, so its lower web accuracy comes mainly from not using "
          "the tool. claude-opus-5-5 and claude-haiku-5-5 remain underconfident with search (confidence 0.079 and 0.081 "
          "below accuracy when answering)."),
    ("h3", "4.4 Robustness"),
    ("p", "We re-asked the no-tools s300 questions with three prompt variants (Appendix Figure D4), each compared with the "
          "main prompt on the same questions. A reworded prompt changed accuracy by at most 0.017 for every model, with "
          "all six intervals including zero. Forbidding abstention left calibration over all guesses unchanged "
          "(no significant change for any model) and raised accuracy for gpt-6.1-sol (+0.070 [0.039, 0.102]) and "
          "gpt-6.1-terra (+0.040 [0.007, 0.074]): those models abstain on some questions they could answer. Defining "
          "confidence as P(within 5%) raised every model's mean confidence, by 0.080 to 0.174, so the models respond to "
          "the tolerance, and ECE at 5% fell significantly for four of six models. The 2026 collapse appears under all "
          "four prompts. Excluding 35 questions with doubtful ground truth (23 quarterly values taken from annual "
          "reports and two companies whose revenue tag appears to exclude interest income) changes overall accuracy "
          "by at most 0.004."),

    ("h2", "5. Discussion and Limitations"),
    ("p", "Stated confidence is informative for most models (AUROC 0.65-0.90 without tools), but its scale is not "
          "comparable across models: 90% from gpt-6.1-sol and 90% from claude-sonnet-5-5 mean very different things. "
          "For safety-relevant uses such as financial advice, audit support or agentic research, the more reliable signal "
          "at the knowledge boundary was abstention rather than confidence. A model that keeps answering past its "
          "boundary does not lower its confidence enough. When forced to answer, models stayed about as well calibrated, "
          "so abstention and confidence appear to carry separate information. This bears on the argument that evaluations "
          "should not penalize abstention: the selective models gave up some correct answers but very few confident "
          "errors. Which policy is better depends on the cost of a wrong figure relative to no figure."),
    ("h3", "Limitations"),
    ("p", "The sample is 140 US companies, three metrics and quarterly periods; standalone Q4 flows are mostly absent, so "
          "December quarters are mostly total assets. XBRL tags can differ from the headline figure a model has seen (for "
          "banks, contract revenue excludes interest income); excluding doubtful rows does not change the headline "
          "numbers. The web condition covers only 300 questions, and 108 Sonnet web answers were re-run after the search "
          "tool returned rate-limit errors during batch processing. We sampled each question once, at one reasoning "
          "effort, without a system prompt. The boundary estimates come from filing dates, not training data: they mark "
          "where recall fails, which need not be the training cutoff. If models had seen the figures through other "
          "sources (news, aggregators) the boundary would shift but the abstention pattern would still describe "
          "behaviour at the edge of recall."),
    ("h3", "Future Work"),
    ("p", "Extend to more metrics, non-US filers and segment-level figures; re-run the same questions on new model "
          "releases to track how the boundary moves; and test whether models tell users when a figure is likely beyond "
          "their knowledge."),

    ("h2", "6. Conclusion"),
    ("p", "Without tools, current models recall reported financial figures poorly and handle their knowledge boundary "
          "mostly by abstaining. How far their stated confidence can be trusted varies far more between models than "
          "between prompts. With web search, accuracy is near ceiling for models that actually search. Confidence should "
          "be interpreted per model, and abstention behaviour should be evaluated together with calibration."),

    ("h2", "Code and Data"),
    ("bullet", "Code repository: https://github.com/PatrickEleeve/llm-financial-calibration (src/; README lists the steps to reproduce every table and figure)"),
    ("bullet", "Data/Datasets: https://github.com/PatrickEleeve/llm-financial-calibration (data/derived/ground_truth.csv with SEC accession numbers; per-answer scores and all "
               "result tables in results/). Raw SEC data is public and is re-downloaded by the code; raw API responses "
               "(~210 MB) are not included."),

    ("h2", "References"),
    ("ref", "Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. Proceedings of the 34th International Conference on Machine Learning (ICML), PMLR 70:1321-1330. https://proceedings.mlr.press/v70/guo17a"),
    ("ref", "Kadavath, S., Conerly, T., Askell, A., et al. (2022). Language Models (Mostly) Know What They Know. arXiv:2207.05221. https://arxiv.org/abs/2207.05221"),
    ("ref", "Tian, K., Mitchell, E., Zhou, A., Sharma, A., Rafailov, R., Yao, H., Finn, C., & Manning, C. D. (2023). Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language Models Fine-Tuned with Human Feedback. EMNLP 2023, pp. 5433-5442. https://doi.org/10.18653/v1/2023.emnlp-main.330"),
    ("ref", "Kalai, A. T., Nachum, O., Vempala, S. S., & Zhang, E. (2025). Why Language Models Hallucinate. arXiv:2509.04664. https://arxiv.org/abs/2509.04664"),
    ("ref", "Ren, R., Agarwal, A., Mazeika, M., et al. (2025). The MASK Benchmark: Disentangling Honesty From Accuracy in AI Systems. arXiv:2503.03750. https://arxiv.org/abs/2503.03750"),
    ("ref", "Karger, E., Bastani, H., Yueh-Han, C., Jacobs, Z., Halawi, D., Zhang, F., & Tetlock, P. E. (2025). ForecastBench: A Dynamic Benchmark of AI Forecasting Capabilities. ICLR 2025. https://arxiv.org/abs/2409.19839"),
    ("ref", "Zhao, Y., Long, Y., Jiang, T., Wang, C., Chen, W., Liu, H., Tang, X., Zhang, Y., Zhao, C., & Cohan, A. (2024). FinDVer: Explainable Claim Verification over Long and Hybrid-content Financial Documents. EMNLP 2024, pp. 14739-14752. https://doi.org/10.18653/v1/2024.emnlp-main.818"),
    ("ref", "Wang, Y., Wang, K., Yang, S., et al. (2025). FinAuditing: A Financial Taxonomy-Structured Multi-Document Benchmark for Evaluating LLMs. arXiv:2510.08886 (accepted to SIGIR 2026 Resource Track). https://arxiv.org/abs/2510.08886"),
    ("ref", "Panda, S. (2026). FinVerBench: Benchmark Validity and Calibration in Large Language Model Financial Statement Verification. arXiv:2605.29586. https://arxiv.org/abs/2605.29586"),

    ("h2", "Appendix"),
    ("h3", "A. Data issues and what didn't work"),
    ("bullet", "Restated comparatives: the earliest filing per period sometimes picked a comparative from the next year's filing; fixed with the 150-day filing-lag filter (2,321 to 2,292 rows)."),
    ("bullet", "Wrong revenue line: preferring the most-used revenue tag picked contract revenue, which can exclude other revenue; found because six models with web search agreed on a different value. Fixed by preferring the Revenues tag (19 values changed)."),
    ("bullet", "Excluded: one company whose ticker and filing entity disagreed, and 6 zero-revenue rows."),
    ("bullet", "Search-tool rate limits: 108 of 300 claude-sonnet-5-5 web answers contained a too_many_requests error from the search tool's code-execution step during batch processing (accuracy 0.324 vs 0.552 for the rest). They were re-run synchronously without errors; the old records are archived."),
    ("bullet", "Cost: the original plan (all models, both conditions, full set) was estimated at about $1,585, so web search was restricted to s300 and the Batch API was used."),
    ("bullet", "Flagged but not changed: bank and broker revenue tags (models answer 2.7-6x higher), one quarterly value from a 10-K about 5x the company's other quarters, and one net-income value where two models give the opposite sign."),
    ("h3", "B. Prompt (main version, no-tools condition)"),
    ("mono", "What was {company} (ticker {T})'s {metric} for the three months ended {date}, as originally reported in its SEC 10-Q or 10-K filing for that period?\n\n"
             "Answer from memory; you have no tools.\n\n"
             "Give the figure in full US dollars (not thousands or millions); use a negative number for a loss.\n"
             "confidence_pct is your probability (0-100) that your value_usd is within 1% of the originally reported figure.\n"
             "If you would rather not answer, set abstain to true; still give your best guess and confidence if you have one, otherwise value_usd null.\n"
             "Reply with only this JSON object and nothing else:\n"
             "{\"value_usd\": <number or null>, \"confidence_pct\": <number 0-100>, \"abstain\": <true|false>}"),
    ("p", "The web condition replaces the second line with “You may use web search (at most a few searches).” "
          "The variants change only the abstention line (v2), the wording (v3) or the tolerance in the confidence "
          "definition (v4); full text in src/ask.py."),
    ("h3", "C. Additional tables"),
    ("table:t3", "Table C1. No tools, by filing-date bin: accuracy within 1% over all questions / share answered."),
    ("table:t4", "Table C2. No tools, all 2,285 questions: ECE and AUROC on answered questions and over every guess "
                 "that came with a value (abstained guesses included)."),
    ("h3", "D. Additional figures"),
    ("fig:fig2_boundary_web.png", "Figure D1. Web search (s300, 60 questions per filing-date bin): accuracy within 1%, mean confidence of answered questions, share answered."),
    ("fig:fig3_boundary_by_metric_none.png", "Figure D2. No tools, by metric: accuracy within 1% (solid, 95% band) and mean confidence of answered questions (dashed); cells with at least 5 questions."),
    ("fig:fig4_reliability.png", "Figure D3. Reliability diagrams: stated confidence against observed accuracy within 1%, answered questions only; marker area proportional to n, hollow markers are bins with fewer than 5 answers."),
    ("fig:fig5_prompt_variants.png", "Figure D4. Prompt-variant robustness (no tools, s300): accuracy and mean confidence over all questions by filing-date bin for the main prompt and three variants."),
    ("h3", "E. Limitations and Dual-Use / Ethical Considerations"),
    ("p", "[AUTHOR TO REVIEW] All data are public SEC filings; no personal data are used. The work measures how far "
          "model-quoted financial figures can be trusted and does not provide a capability that could be misused; the "
          "main risk it addresses is over-reliance on confident but wrong figures. Model outputs in this study are not "
          "investment advice. Raw model responses contain only public information."),

    ("h2", "LLM Usage Statement"),
    ("p", "[AUTHOR TO EDIT so that it is accurate] We used Claude (Anthropic, claude-opus-5-5 via Claude Code) to write "
          "the data pipeline, API runners, scoring and analysis code; to run the experiments under the author's direction "
          "and budget decisions; to produce the tables and figures; and to draft the text of this report, which the "
          "author reviewed and edited. All numbers were produced by code from saved results files and checked against "
          "them. The author chose the research question, approved the design decisions and budgets, and verified the "
          "final text and references."),
]

MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-5.6-sol"]


def f3(x):
    return f"{x:.3f}"


def tables():
    o = pd.read_csv(R / "metrics_overall.csv")
    full = o[o.set == "full"].set_index("model").loc[MODELS]
    t1 = [["Model", "Answered", "Accuracy (1%) [95% CI]", "Acc. when answering", "Mean conf.", "ECE", "AUROC",
           "P(wrong | conf ≥ 80%) (n80)"]]
    for m, r in full.iterrows():
        t1.append([m, f3(r.coverage), f"{f3(r.acc1_all)} [{f3(r.acc1_all_lo)}, {f3(r.acc1_all_hi)}]", f3(r.acc1_ans),
                   f3(r.conf_ans), f3(r.ece), f3(r.auroc), f"{f3(r.cw_given80)} ({int(r.n80)})"])
    web = o[(o.set == "s300") & (o.condition == "web")].set_index("model").loc[MODELS]
    pr = pd.read_csv(R / "metrics_web_vs_none_paired.csv").set_index("model").loc[MODELS]
    su = pd.read_csv(R / "web_search_use.csv")
    su = su[su.searched].set_index("model").share.reindex(MODELS)
    t2 = [["Model", "Accuracy, web [95% CI]", "Change vs no tools [95% CI]", "Mean conf.", "ECE", "Searched"]]
    for m in MODELS:
        r, p = web.loc[m], pr.loc[m]
        t2.append([m, f"{f3(r.acc1_all)} [{f3(r.acc1_all_lo)}, {f3(r.acc1_all_hi)}]",
                   f"+{f3(p.d_acc1_all)} [{f3(p.d_acc1_all_lo)}, {f3(p.d_acc1_all_hi)}]", f3(r.conf_ans), f3(r.ece),
                   f3(su.loc[m])])
    b = pd.read_csv(R / "metrics_by_bin.csv")
    b = b[b.condition == "none"]
    bins = ["2023", "2024", "2025", "2026H1", "2026H2"]
    nb = b[b.model == MODELS[0]].set_index("bin").n
    t3 = [["Model"] + [f"{x} (n={int(nb[x])})" for x in bins]]
    for m in MODELS:
        g = b[b.model == m].set_index("bin")
        t3.append([m] + [f"{f3(g.loc[x].acc1_all)} / {f3(g.loc[x].coverage)}" for x in bins])
    t4 = [["Model", "ECE (answered)", "ECE (all guesses)", "AUROC (answered)", "AUROC (all guesses)"]]
    for m, r in full.iterrows():
        t4.append([m, f3(r.ece), f3(r.ece_guess), f3(r.auroc), f3(r.auroc_guess)])
    return {"t1": t1, "t2": t2, "t3": t3, "t4": t4}


# ------------------------------------------------------------------ docx helpers
def clear_runs(p):
    for r in list(p._p):
        if r.tag != qn("w:pPr"):
            p._p.remove(r)


def proto_clone(proto, anchor):
    new = copy.deepcopy(proto._p)
    anchor.addnext(new)
    p = docx.text.paragraph.Paragraph(new, proto._parent)
    clear_runs(p)
    return p


def add_text(p, text, size=None, italic=False, font="Old Standard TT"):
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        r = p.add_run(part)
        r.font.name = font
        r._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font)
        r.bold = (i % 2 == 1) or None
        r.italic = italic or None
        if size:
            r.font.size = Pt(size)


def set_borders(tbl):
    tblPr = tbl._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "bottom", "insideH"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single"), e.set(qn("w:sz"), "4"), e.set(qn("w:color"), "808080")
        b.append(e)
    tblPr.append(b)


def build():
    d = docx.Document(TPL)
    # title block
    head = d.tables[0]
    for p in head.cell(0, 0).paragraphs:
        if p.text.strip() == "PROJECT TITLE":
            for r in p.runs[1:]:
                r._r.getparent().remove(r._r)
            p.runs[0].text = TITLE
    # the abstract goes into the template's boxed guidance paragraph (nested table under "Abstract")
    box = next(t for t in head.cell(1, 0).tables if "Summarize your project" in t.cell(0, 0).text)
    target = box.cell(0, 0).paragraphs[0]
    for extra in box.cell(0, 0).paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    clear_runs(target)
    add_text(target, ABSTRACT)
    # authors: the template has a 2x3 grid of placeholders; keep one row, centre the authors in it
    grid = head.cell(1, 0).tables[0].cell(0, 0).tables[0]
    for row in grid.rows[1:]:
        row._tr.getparent().remove(row._tr)
    cells = grid.rows[0].cells
    slots = [1] if len(AUTHORS) == 1 else list(range(len(AUTHORS)))
    for j, c in enumerate(cells):
        run = c.paragraphs[0].runs[0]
        if j in slots:
            name, aff = AUTHORS[slots.index(j)]
            run.text = f"{name}\n{aff}"
        else:
            run.text = ""
    # remove the info box
    d.tables[1]._tbl.getparent().remove(d.tables[1]._tbl)

    paras = d.paragraphs
    find = lambda s: next(p for p in paras if p.text.strip().startswith(s))
    proto = {"h2": find("1. Introduction"), "h3": find("Limitations"), "p": find("What problem"),
             "num": find("[First contribution"), "bullet": find("Number all figures"), "ref": find("[Reference 1]")}
    body = d.element.body
    # remove everything after the title block table (all guidance), keeping sectPr
    started = False
    for el in list(body):
        if el is head._tbl:
            started = True
            continue
        if started and el.tag != qn("w:sectPr"):
            body.remove(el)
    anchor = head._tbl
    blank = OxmlElement("w:p")
    anchor.addnext(blank)
    anchor = blank

    T = tables()
    for kind, text in BODY:
        if kind.startswith("table:"):
            cap = proto_clone(proto["p"], anchor)
            add_text(cap, text, size=9, italic=True)
            rows = T[kind.split(":")[1]]
            tbl = d.add_table(rows=len(rows), cols=len(rows[0]))
            set_borders(tbl)
            for i, row in enumerate(rows):
                for j, v in enumerate(row):
                    c = tbl.cell(i, j)
                    c.paragraphs[0].text = ""
                    add_text(c.paragraphs[0], f"**{v}**" if i == 0 else v, size=8)
            cap._p.addnext(tbl._tbl)
            spacer = OxmlElement("w:p")
            tbl._tbl.addnext(spacer)
            anchor = spacer
            continue
        if kind.startswith("fig:"):
            p = proto_clone(proto["p"], anchor)
            p.add_run().add_picture(str(FIG / kind.split(":")[1]), width=Inches(6.5))
            cap = proto_clone(proto["p"], p._p)
            add_text(cap, text, size=9, italic=True)
            anchor = cap._p
            continue
        if kind == "mono":
            for line in text.split("\n"):
                p = proto_clone(proto["p"], anchor)
                add_text(p, line, size=8, font="Courier New")
                anchor = p._p
            continue
        p = proto_clone(proto[kind], anchor)
        add_text(p, text)
        anchor = p._p
    d.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
