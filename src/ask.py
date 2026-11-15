"""Ask LLMs for reported financial figures with a stated confidence.

Every call's full response (no request headers or keys) is saved to
results/raw/<prompt_version>/<model>/<condition>/<qid>.json. Existing files that
parsed without an API error are skipped, so runs can be resumed.

Examples:
  python src/ask.py --pilot 10 --models all --conditions none,web --max-usd 10
  python src/ask.py --models claude-haiku-5-5 --conditions none        # full set
"""
import argparse, json, os, re, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prices import cost_usd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
RAW = ROOT / "results" / "raw"
# Prompt variant, chosen per process via the PROMPT_VERSION env var (default v1 = main study).
# Robustness variants (step 7): v2_forced (no abstain option), v3_paraphrase (same content, reworded),
# v4_conf5 (confidence defined for within 5% instead of 1%). Each writes to results/raw/<version>/.
VARIANTS = ("v1", "v2_forced", "v3_paraphrase", "v4_conf5")
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")
assert PROMPT_VERSION in VARIANTS, PROMPT_VERSION
EFFORT = "medium"          # same nominal effort everywhere; recorded per call
MAX_TOKENS = 16000
MAX_SEARCHES = 3

ANTHROPIC = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]
OPENAI = ["gpt-6.1-sol", "gpt-6.1-terra", "gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
# Main study (user decision 2026-11-14): Fable 5.2 dropped; it stays in the pilot data only.
# gpt-5.5 replaced by gpt-5.6-sol (same role: older-generation reference; ~1/4 the cost per call in the pilot).
MAIN_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-5.6-sol"]

METRIC_TEXT = {
    "revenue": "total revenue",
    "net_income": "net income (loss) attributable to the company (i.e. to the parent, excluding noncontrolling interests)",
    "total_assets": "total assets",
}


def qid(r):
    return f"{r.cik}_{r.metric}_{r.period_type}_{r.end}"


def fmt_date(s):
    d = date.fromisoformat(s)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def question(r, condition, version=None):
    version = version or PROMPT_VERSION
    if r.period_type == "instant":
        what = f"{METRIC_TEXT[r.metric]} as of {fmt_date(r.end)}"
        verb = "were"
    else:
        what = f"{METRIC_TEXT[r.metric]} for the three months ended {fmt_date(r.end)}"
        verb = "was"
    tool_line = ("You may use web search (at most a few searches)."
                 if condition == "web" else "Answer from memory; you have no tools.")
    if version == "v3_paraphrase":
        return (
            f"In the SEC 10-Q or 10-K filing for that period, what did {r['name']} (ticker {r.ticker}) originally "
            f"report as its {what}?\n\n"
            f"{tool_line}\n\n"
            "State the amount in US dollars as a plain number of dollars (for example 1234567000, not 1.23 billion "
            "or 1,234.6 million); a loss is a negative number.\n"
            "For confidence_pct, give how likely you think it is (0-100) that your number is within 1% of the "
            "figure as first reported.\n"
            "You may decline by setting abstain to true; in that case still give your best guess and confidence "
            "if you have one, else set value_usd to null.\n"
            "Output exactly this JSON object and nothing more:\n"
            '{"value_usd": <number or null>, "confidence_pct": <number 0-100>, "abstain": <true|false>}'
        )
    tol = "5%" if version == "v4_conf5" else "1%"
    if version == "v2_forced":
        abstain_line = ("You must give a numeric best guess even if you are unsure; do not decline. "
                        "Use confidence_pct to express uncertainty.\n")
        schema = '{"value_usd": <number>, "confidence_pct": <number 0-100>}'
    else:
        abstain_line = ("If you would rather not answer, set abstain to true; still give your best guess and confidence "
                        "if you have one, otherwise value_usd null.\n")
        schema = '{"value_usd": <number or null>, "confidence_pct": <number 0-100>, "abstain": <true|false>}'
    return (
        f"What {verb} {r['name']} (ticker {r.ticker})'s {what}, as originally reported in its "
        f"SEC 10-Q or 10-K filing for that period?\n\n"
        f"{tool_line}\n\n"
        "Give the figure in full US dollars (not thousands or millions); use a negative number for a loss.\n"
        f"confidence_pct is your probability (0-100) that your value_usd is within {tol} of the originally "
        "reported figure.\n"
        f"{abstain_line}"
        "Reply with only this JSON object and nothing else:\n"
        f"{schema}"
    )


# ---------------------------------------------------------------- parsing
NUM = r"-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?"


def parse_answer(text):
    """Return dict(value_usd, confidence_pct, abstain, parse_ok, parse_note)."""
    out = dict(value_usd=None, confidence_pct=None, abstain=None, parse_ok=False, parse_note="")
    if not text:
        out["parse_note"] = "empty"
        return out
    cands = re.findall(r"\{[^{}]*\}", text, flags=re.S)
    for c in reversed(cands):
        c2 = re.sub(r"(?<=\d),(?=\d{3})", "", c)  # 1,234 -> 1234 inside JSON
        try:
            d = json.loads(c2)
        except json.JSONDecodeError:
            continue
        if "confidence_pct" in d or "value_usd" in d:
            v = d.get("value_usd")
            if isinstance(v, str):
                m = re.search(NUM, v.replace("$", ""))
                mult = next((k for w, k in (("trillion", 1e12), ("billion", 1e9), ("million", 1e6),
                                            ("thousand", 1e3)) if w in v.lower()), 1)
                v = float(m.group().replace(",", "")) * mult if m else None
                out["parse_note"] = "value was string"
            conf = d.get("confidence_pct")
            if isinstance(conf, str):
                m = re.search(NUM, conf)
                conf = float(m.group()) if m else None
            ab = d.get("abstain")
            if isinstance(ab, str):
                ab = ab.strip().lower() == "true"
            out.update(value_usd=None if v is None else float(v),
                       confidence_pct=None if conf is None else float(conf),
                       abstain=bool(ab) if ab is not None else None, parse_ok=True)
            return out
    out["parse_note"] = "no json"
    return out


# ---------------------------------------------------------------- providers
_clients = {}
_lock = threading.Lock()


def _client(kind):
    with _lock:
        if kind not in _clients:
            if kind == "anthropic":
                import anthropic
                _clients[kind] = anthropic.Anthropic(max_retries=4, timeout=600)
            else:
                import openai
                _clients[kind] = openai.OpenAI(max_retries=4, timeout=600)
        return _clients[kind]


WEB_TOOL_ANTHROPIC = "web_search_20260209"  # accepted by every Claude model in the pilot


def anthropic_params(model, prompt, condition):
    # No refusal `fallbacks`: they would silently switch the model being measured.
    kw = dict(model=model, max_tokens=MAX_TOKENS, output_config={"effort": EFFORT},
              messages=[{"role": "user", "content": prompt}])
    if condition == "web":
        kw["tools"] = [{"type": WEB_TOOL_ANTHROPIC, "name": "web_search", "max_uses": MAX_SEARCHES}]
    return kw


def summarize_anthropic(responses, tool_variant, request_ids):
    final = responses[-1]
    text = "".join(b.text for b in final.content if b.type == "text")
    u = dict(input=0, output=0, cache_read=0, cache_write=0, searches=0)
    for r in responses:
        u["input"] += r.usage.input_tokens or 0
        u["output"] += r.usage.output_tokens or 0
        u["cache_read"] += r.usage.cache_read_input_tokens or 0
        u["cache_write"] += r.usage.cache_creation_input_tokens or 0
        stu = getattr(r.usage, "server_tool_use", None)
        u["searches"] += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
    queries = [b.input.get("query") for r in responses for b in r.content
               if b.type == "server_tool_use" and isinstance(getattr(b, "input", None), dict)]
    urls = []
    for r in responses:
        for b in r.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                urls += [getattr(x, "url", None) for x in b.content]
    meta = dict(stop_reason=final.stop_reason, tool_variant=tool_variant,
                stop_details=final.stop_details.to_dict() if getattr(final, "stop_details", None) else None,
                n_turns=len(responses), queries=queries, urls=urls, request_ids=request_ids)
    return text, u, meta, [r.to_dict() for r in responses]


def call_anthropic(model, prompt, condition):
    c = _client("anthropic")
    kw = anthropic_params(model, prompt, condition)
    responses, msgs = [], list(kw["messages"])
    for _ in range(4):  # pause_turn continuation
        r = c.messages.create(**{**kw, "messages": msgs})
        responses.append(r)
        if r.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": r.content}]
    return summarize_anthropic(responses, kw.get("tools", [{}])[0].get("type"),
                               [r._request_id for r in responses])


def openai_params(model, prompt, condition):
    kw = dict(model=model, input=prompt, max_output_tokens=MAX_TOKENS, reasoning={"effort": EFFORT})
    if condition == "web":
        kw.update(tools=[{"type": "web_search"}], max_tool_calls=MAX_SEARCHES)
    return kw


def summarize_openai(r, condition, request_id):
    text = r.output_text or ""
    us = r.usage
    cached = (us.input_tokens_details.cached_tokens or 0) if us.input_tokens_details else 0
    searches = sum(1 for o in r.output if o.type == "web_search_call")
    queries, urls = [], []
    for o in r.output:
        if o.type == "web_search_call":
            a = getattr(o, "action", None)
            q = getattr(a, "query", None) if a else None
            if q:
                queries.append(q)
        if o.type == "message":
            for part in o.content:
                for ann in getattr(part, "annotations", []) or []:
                    if getattr(ann, "url", None):
                        urls.append(ann.url)
    u = dict(input=us.input_tokens - cached, output=us.output_tokens, cache_read=cached, cache_write=0,
             searches=searches,
             reasoning=(us.output_tokens_details.reasoning_tokens or 0) if us.output_tokens_details else 0)
    meta = dict(stop_reason=r.status, incomplete=r.incomplete_details.to_dict() if r.incomplete_details else None,
                tool_variant="web_search" if condition == "web" else None, n_turns=1,
                queries=queries, urls=urls, request_ids=[request_id])
    return text, u, meta, [r.to_dict()]


def call_openai(model, prompt, condition):
    r = _client("openai").responses.create(**openai_params(model, prompt, condition))
    return summarize_openai(r, condition, r._request_id)


# ---------------------------------------------------------------- runner
def raw_path(model, condition, q):
    return RAW / PROMPT_VERSION / model / condition / f"{q}.json"


def done(p):
    """Finished = no API error, and either parsed or already retried once."""
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
    except Exception:
        return False
    return d.get("error") is None and (d.get("parse_ok") or d.get("attempt", 1) >= 2)


def provider(model):
    return "anthropic" if model in ANTHROPIC else "openai"


def spent_so_far(prov=None):
    """Cumulative estimated spend over every saved call (all runs, incl. retried attempts),
    optionally for one provider only."""
    tot = 0.0
    for f in RAW.rglob("*.json"):
        if prov and provider(f.parent.parent.name) != prov:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        tot += d.get("cost_usd") or 0.0
        tot += sum(x.get("cost_usd") or 0.0 for x in d.get("earlier_attempts", []))
    return tot


def _ask_once(model, condition, row, prompt):
    t0 = time.time()
    rec = dict(qid=qid(row), model=model, condition=condition, prompt_version=PROMPT_VERSION, effort=EFFORT,
               max_tokens=MAX_TOKENS, prompt=prompt, error=None, asked_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        fn = call_anthropic if model in ANTHROPIC else call_openai
        text, u, meta, raw = fn(model, prompt, condition)
        rec.update(text=text, usage=u, meta=meta, raw=raw, **parse_answer(text))
        rec["cost_usd"] = cost_usd(model, u["input"], u["output"], u["cache_read"], u["cache_write"], u["searches"])
    except Exception as e:
        rec.update(error=f"{type(e).__name__}: {str(e)[:2000]}", traceback=traceback.format_exc()[-3000:],
                   cost_usd=0.0)
    rec["latency_s"] = round(time.time() - t0, 2)
    return rec


def ask_one(model, condition, row):
    """Ask once; if the answer can't be parsed (e.g. a bogus tool_use stop), retry exactly once.
    Earlier attempts are kept inside the record (their cost counts toward the cap)."""
    p = raw_path(model, condition, qid(row))
    prompt = question(row, condition)
    earlier = []
    if p.exists():  # e.g. pilot call that failed to parse before the retry rule existed
        try:
            old = json.loads(p.read_text())
            if old.get("error") is None and not old.get("parse_ok"):
                earlier = old.get("earlier_attempts", []) + [{k: v for k, v in old.items() if k != "earlier_attempts"}]
        except Exception:
            pass
    rec = _ask_once(model, condition, row, prompt)
    if rec["error"] is None and not rec.get("parse_ok") and not earlier:
        earlier = [rec]
        rec = _ask_once(model, condition, row, prompt)
    rec["attempt"] = len(earlier) + 1
    rec["earlier_attempts"] = earlier
    rec["cost_this_call"] = rec["cost_usd"] + sum(x.get("cost_usd") or 0 for x in earlier if x.get("asked_at", "") >= START_TS)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, default=str, indent=1))
    return rec


START_TS = time.strftime("%Y-%m-%dT%H:%M:%S")
SAMPLES = ROOT / "data" / "derived" / "samples"


def pilot_sample(df, n, seed):
    """n questions spread across filing-date bins, then metric/stratum."""
    df = df.copy()
    df["bin"] = filing_bin(df.filed)
    bins = list(df["bin"].cat.categories)
    per = [n // len(bins) + (1 if i < n % len(bins) else 0) for i in range(len(bins))]
    picks = []
    for b, k in zip(bins, per):
        sub = df[df["bin"] == b].sample(frac=1, random_state=seed)
        sub = sub.drop_duplicates(["metric", "stratum"])  # diversity first
        picks.append(sub.head(k))
    return pd.concat(picks)


def filing_bin(filed):
    return pd.cut(pd.to_datetime(filed),
                  pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31",
                                  "2026-06-30", "2026-12-31"]),
                  labels=["2023", "2024", "2025", "2026H1", "2026H2"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="all")
    ap.add_argument("--conditions", default="none,web")
    ap.add_argument("--pilot", type=int, default=0, help="n pilot questions (same set for every model)")
    ap.add_argument("--sample", default="full",
                    help="'full' or a name in data/derived/samples/<name>.csv (qid list, see make_samples.py)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cap-anthropic", type=float, required=True,
                    help="CUMULATIVE cap for Anthropic models over everything in results/raw/ (pilot included)")
    ap.add_argument("--cap-openai", type=float, required=True, help="same, for OpenAI models")
    a = ap.parse_args()
    caps = {"anthropic": a.cap_anthropic, "openai": a.cap_openai}

    models = MAIN_MODELS if a.models == "all" else a.models.split(",")
    conds = a.conditions.split(",")
    gt = pd.read_csv(ROOT / "data/derived/ground_truth.csv", dtype={"cik": str})
    gt["qid"] = gt.apply(qid, axis=1)
    if a.pilot:
        frozen = SAMPLES / "pilot10.csv"  # the original pilot questions; re-drawing would change them
        if a.pilot == 10 and frozen.exists():
            gt = gt[gt.qid.isin(set(pd.read_csv(frozen).qid))]
        else:
            gt = pilot_sample(gt, a.pilot, a.seed)
    elif a.sample != "full":
        keep = set(pd.read_csv(SAMPLES / f"{a.sample}.csv").qid)
        gt = gt[gt.qid.isin(keep)]
    # Order: s100, then rest of s300, then everything else shuffled. If a cap stops a run early,
    # what was answered is still a stratified (then random) subset.
    rank = {}
    for name in ("s100", "s300"):
        f = SAMPLES / f"{name}.csv"
        if f.exists():
            for q in pd.read_csv(f).qid:
                rank.setdefault(q, len(rank))
    gt = gt.sample(frac=1, random_state=a.seed)
    gt = gt.assign(_r=gt.qid.map(rank).fillna(10**9)).sort_values("_r", kind="stable")

    jobs = [(m, c, r) for _, r in gt.iterrows() for m in models for c in conds
            if not done(raw_path(m, c, r.qid))]
    spent = {p: spent_so_far(p) for p in caps}
    print(f"{len(jobs)} calls to make; spent so far {spent}; caps {caps}", flush=True)
    stop = {p: threading.Event() for p in caps}
    for p in caps:
        if spent[p] >= caps[p]:
            stop[p].set()
            print(f"{p}: cap already reached, skipping its calls")

    def guarded(*j):
        if stop[provider(j[0])].is_set():
            return None
        return ask_one(*j)

    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(guarded, *j) for j in jobs]
        for f in as_completed(futs):
            rec = f.result()
            if rec is None:
                continue
            p = provider(rec["model"])
            spent[p] += rec["cost_this_call"]
            tag = rec["error"][:80] if rec["error"] else f"v={rec.get('value_usd')} c={rec.get('confidence_pct')}"
            if rec["attempt"] > 1:
                tag += f" (attempt {rec['attempt']}, parse_ok={rec.get('parse_ok')})"
            print(f"A${spent['anthropic']:7.2f} O${spent['openai']:7.2f} {rec['model']:18s} {rec['condition']:4s} "
                  f"{rec['qid']:45s} {tag}", flush=True)
            if spent[p] > caps[p] and not stop[p].is_set():
                print(f"STOP {p}: cumulative ${spent[p]:.2f} exceeded cap; skipping its queued calls", flush=True)
                stop[p].set()
    print(f"done. cumulative: anthropic ${spent_so_far('anthropic'):.3f}, openai ${spent_so_far('openai'):.3f}")


if __name__ == "__main__":
    main()
