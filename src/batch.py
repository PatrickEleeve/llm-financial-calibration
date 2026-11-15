"""Batch-API runner (50% token price) that writes the same records as ask.py.

  python src/batch.py submit --conditions none --sample full --cap-anthropic 150 --cap-openai 150 [--limit 2]
  python src/batch.py status
  python src/batch.py collect      # writes results/raw/... for every ended batch; safe to re-run

Safety:
- A (model, condition, qid) already answered, or sitting in an uncollected batch, is never resubmitted.
- Before submitting, projected cost (saved spend + estimates for open batches + this batch) must
  stay under the per-provider cap. Estimates use the mean per-call cost of that model/condition
  in results/raw/ (synchronous pilot calls), with tokens at the batch discount.
- Unparseable answers get exactly one retry: run `submit` again after `collect`; those jobs go
  out as attempt 2 and the first attempt is kept inside the record.
- errored / expired / canceled requests write nothing, so the next `submit` resubmits them.
State: results/batches/state.json + one <batch_id>.manifest.json per batch.
"""
import argparse, io, json, sys, time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ask  # noqa: E402
from prices import cost_usd, SEARCH_USD_PER_CALL, BATCH_TOKEN_DISCOUNT  # noqa: E402

BDIR = ask.ROOT / "results" / "batches"
STATE = BDIR / "state.json"


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else []


def save_state(st):
    BDIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def manifest(b):
    return json.loads((BDIR / f"{b['id']}.manifest.json").read_text())


def pending_keys(st):
    keys = set()
    for b in st:
        if not b.get("collected"):
            for q in manifest(b).values():
                if b.get("prompt_version", "v1") == ask.PROMPT_VERSION:
                    keys.add((b["model"], b["condition"], q))
    return keys


def est_per_call(model, condition):
    """Mean batch-priced cost per call from saved synchronous v1 calls of this model/condition
    (variants have similar prompts; their own saved calls are used once they exist)."""
    tok, srch, n = 0.0, 0.0, 0
    own = [f for f in (ask.RAW / ask.PROMPT_VERSION / model / condition).glob("*.json")
           if not json.loads(f.read_text()).get("batch")]
    for f in own or (ask.RAW / "v1" / model / condition).glob("*.json"):
        d = json.loads(f.read_text())
        if d.get("error") or d.get("batch"):
            continue
        u = d["usage"]
        tok += cost_usd(model, u["input"], u["output"], u["cache_read"], u["cache_write"], 0)
        srch += u["searches"]
        n += 1
    if n == 0:
        raise SystemExit(f"no saved calls for {model}/{condition} to estimate cost from")
    return tok / n * BATCH_TOKEN_DISCOUNT + srch / n * SEARCH_USD_PER_CALL


def select_rows(sample):
    gt = pd.read_csv(ask.ROOT / "data/derived/ground_truth.csv", dtype={"cik": str})
    gt["qid"] = gt.apply(ask.qid, axis=1)
    if sample != "full":
        gt = gt[gt.qid.isin(set(pd.read_csv(ask.SAMPLES / f"{sample}.csv").qid))]
    return gt


# ---------------------------------------------------------------- submit
def submit(a):
    st = load_state()
    caps = {"anthropic": a.cap_anthropic, "openai": a.cap_openai}
    models = ask.MAIN_MODELS if a.models == "all" else a.models.split(",")
    rows = select_rows(a.sample)
    busy = pending_keys(st)
    open_est = {p: 0.0 for p in caps}
    for b in st:
        if not b.get("collected"):
            open_est[b["provider"]] += b["est_usd"]
    spent = {p: ask.spent_so_far(p) for p in caps}

    plan = []
    for m in models:
        for c in a.conditions.split(","):
            todo = [r for _, r in rows.iterrows()
                    if (m, c, r.qid) not in busy and not ask.done(ask.raw_path(m, c, r.qid))]
            if a.limit:
                todo = todo[:a.limit]
            if todo:
                plan.append((m, c, todo, est_per_call(m, c) * len(todo)))
    proj = {p: spent[p] + open_est[p] for p in caps}
    for m, c, todo, est in plan:
        proj[ask.provider(m)] += est
        print(f"plan {m:18s} {c:4s} n={len(todo):5d} est ${est:7.2f}")
    print(f"saved spend {spent}; open-batch estimates {open_est}; projected {proj}; caps {caps}")
    over = [p for p in caps if proj[p] > caps[p]]
    if over:
        raise SystemExit(f"REFUSING: projected spend over cap for {over}")
    if a.dry_run:
        print("dry run: nothing submitted")
        return
    for m, c, todo, est in plan:
        b = submit_anthropic(m, c, todo) if ask.provider(m) == "anthropic" else submit_openai(m, c, todo)
        b.update(model=m, condition=c, provider=ask.provider(m), n=len(todo), est_usd=est,
                 prompt_version=ask.PROMPT_VERSION,
                 submitted_at=time.strftime("%Y-%m-%dT%H:%M:%S"), collected=False)
        st.append(b)
        save_state(st)  # after every batch, so a crash never loses track of a submitted batch
        print(f"submitted {b['id']} {m} {c} n={len(todo)}")


def _write_manifest(bid, mani):
    BDIR.mkdir(parents=True, exist_ok=True)
    (BDIR / f"{bid}.manifest.json").write_text(json.dumps(mani))


def submit_anthropic(model, condition, rows):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    mani, reqs = {}, []
    for i, r in enumerate(rows):
        cid = f"q{i:05d}"
        mani[cid] = r.qid
        reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(
            **ask.anthropic_params(model, ask.question(r, condition), condition))))
    b = ask._client("anthropic").messages.batches.create(requests=reqs)
    _write_manifest(b.id, mani)
    return {"id": b.id}


def submit_openai(model, condition, rows):
    mani, lines = {}, []
    for i, r in enumerate(rows):
        cid = f"q{i:05d}"
        mani[cid] = r.qid
        lines.append(json.dumps({"custom_id": cid, "method": "POST", "url": "/v1/responses",
                                 "body": ask.openai_params(model, ask.question(r, condition), condition)}))
    c = ask._client("openai")
    f = c.files.create(file=("batch.jsonl", io.BytesIO("\n".join(lines).encode())), purpose="batch")
    b = c.batches.create(input_file_id=f.id, endpoint="/v1/responses", completion_window="24h")
    _write_manifest(b.id, mani)
    return {"id": b.id, "input_file_id": f.id}


# ---------------------------------------------------------------- status / collect
def remote_status(b):
    if b["provider"] == "anthropic":
        r = ask._client("anthropic").messages.batches.retrieve(b["id"])
        return r.processing_status == "ended", r.processing_status, r.request_counts.to_dict()
    r = ask._client("openai").batches.retrieve(b["id"])
    ended = r.status in ("completed", "failed", "expired", "cancelled")
    return ended, r.status, (r.request_counts.to_dict() if r.request_counts else {})


def status(a):
    for b in load_state():
        if b.get("collected"):
            print(f"{b['id']} {b.get('prompt_version', 'v1'):13s} {b['model']:18s} {b['condition']:4s} n={b['n']:5d} collected")
            continue
        ended, s, counts = remote_status(b)
        print(f"{b['id']} {b.get('prompt_version', 'v1'):13s} {b['model']:18s} {b['condition']:4s} n={b['n']:5d} {s} {counts}")


def write_record(rec):
    """Same file and retry bookkeeping as ask.ask_one."""
    p = ask.raw_path(rec["model"], rec["condition"], rec["qid"])
    earlier = []
    if p.exists():
        old = json.loads(p.read_text())
        if old.get("error") is None and old.get("parse_ok"):
            return False  # already answered; never overwrite a good answer
        if old.get("error") is None:
            earlier = old.get("earlier_attempts", []) + [{k: v for k, v in old.items() if k != "earlier_attempts"}]
    rec["attempt"] = len(earlier) + 1
    rec["earlier_attempts"] = earlier
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, default=str, indent=1))
    return True


def base_rec(b, qid, cid):
    r = ask_rows()[qid]
    return dict(qid=qid, model=b["model"], condition=b["condition"], prompt_version=ask.PROMPT_VERSION,
                effort=ask.EFFORT, max_tokens=ask.MAX_TOKENS, prompt=ask.question(r, b["condition"]),
                error=None, asked_at=b["submitted_at"], batch=True, batch_id=b["id"], custom_id=cid)


_rows = None


def ask_rows():
    global _rows
    if _rows is None:
        gt = select_rows("full")
        _rows = {r.qid: r for _, r in gt.iterrows()}
    return _rows


def finish(rec, text, u, meta, raw):
    rec.update(text=text, usage=u, meta=meta, raw=raw, **ask.parse_answer(text))
    rec["cost_usd"] = cost_usd(rec["model"], u["input"], u["output"], u["cache_read"], u["cache_write"],
                               u["searches"], batch=True)
    rec["latency_s"] = None
    return rec


def collect_anthropic(b, mani):
    n_ok, n_bad = 0, 0
    for res in ask._client("anthropic").messages.batches.results(b["id"]):
        q = mani[res.custom_id]
        if res.result.type != "succeeded":
            n_bad += 1
            continue
        msg = res.result.message
        tv = ask.WEB_TOOL_ANTHROPIC if b["condition"] == "web" else None
        rec = finish(base_rec(b, q, res.custom_id), *ask.summarize_anthropic([msg], tv, [b["id"]]))
        n_ok += write_record(rec)
    return n_ok, n_bad


def summarize_openai_dict(body, condition, request_id):
    """Same fields as ask.summarize_openai, read from the raw JSON body. The SDK's strict Response
    model rejects some batch outputs (e.g. a web_search_call with status 'searching')."""
    out = body.get("output") or []
    text = "".join(p.get("text", "") for o in out if o.get("type") == "message"
                   for p in o.get("content") or [] if p.get("type") == "output_text")
    us = body.get("usage") or {}
    cached = (us.get("input_tokens_details") or {}).get("cached_tokens") or 0
    queries, urls = [], []
    for o in out:
        if o.get("type") == "web_search_call":
            q = (o.get("action") or {}).get("query")
            if q:
                queries.append(q)
        if o.get("type") == "message":
            for p in o.get("content") or []:
                urls += [a["url"] for a in p.get("annotations") or [] if a.get("url")]
    u = dict(input=(us.get("input_tokens") or 0) - cached, output=us.get("output_tokens") or 0,
             cache_read=cached, cache_write=0,
             searches=sum(1 for o in out if o.get("type") == "web_search_call"),  # counts every call (upper bound)
             reasoning=(us.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)
    meta = dict(stop_reason=body.get("status"), incomplete=body.get("incomplete_details"),
                tool_variant="web_search" if condition == "web" else None, n_turns=1,
                queries=queries, urls=urls, request_ids=[request_id],
                odd_search_status=[o.get("status") for o in out
                                   if o.get("type") == "web_search_call" and o.get("status") != "completed"])
    return text, u, meta, [body]


def collect_openai(b, mani):
    c = ask._client("openai")
    r = c.batches.retrieve(b["id"])
    n_ok, n_bad = 0, 0
    if r.error_file_id:
        n_bad += sum(1 for ln in c.files.content(r.error_file_id).text.splitlines() if ln.strip())
    if not r.output_file_id:
        return n_ok, n_bad
    for ln in c.files.content(r.output_file_id).text.splitlines():
        if not ln.strip():
            continue
        line = json.loads(ln)
        q = mani[line["custom_id"]]
        resp = line.get("response") or {}
        if line.get("error") or resp.get("status_code") != 200:
            n_bad += 1
            continue
        rec = finish(base_rec(b, q, line["custom_id"]),
                     *summarize_openai_dict(resp["body"], b["condition"], resp.get("request_id")))
        n_ok += write_record(rec)
    return n_ok, n_bad


def collect(a):
    st = load_state()
    for b in st:
        if b.get("collected"):
            continue
        ended, s, counts = remote_status(b)
        if not ended:
            print(f"{b['id']} {b['model']} {b['condition']}: still {s} {counts}")
            continue
        mani = manifest(b)
        ask.PROMPT_VERSION = b.get("prompt_version", "v1")  # records go to results/raw/<that version>/
        fn = collect_anthropic if b["provider"] == "anthropic" else collect_openai
        n_ok, n_bad = fn(b, mani)
        b.update(collected=True, collected_at=time.strftime("%Y-%m-%dT%H:%M:%S"), final_status=s,
                 n_written=n_ok, n_failed=n_bad)
        save_state(st)
        print(f"{b['id']} {b['model']} {b['condition']}: {s}; wrote {n_ok}, failed {n_bad} (resubmit with submit)")
    print({p: round(ask.spent_so_far(p), 2) for p in ("anthropic", "openai")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("submit")
    s.add_argument("--models", default="all")
    s.add_argument("--conditions", default="none,web")
    s.add_argument("--sample", default="full")
    s.add_argument("--limit", type=int, default=0, help="max requests per model/condition (for a test batch)")
    s.add_argument("--cap-anthropic", type=float, required=True)
    s.add_argument("--cap-openai", type=float, required=True)
    s.add_argument("--dry-run", action="store_true")
    sp.add_parser("status")
    sp.add_parser("collect")
    a = ap.parse_args()
    {"submit": submit, "status": status, "collect": collect}[a.cmd](a)
