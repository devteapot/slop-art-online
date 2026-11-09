#!/usr/bin/env python3
"""Model cost per task: replay real mind prompts on several models and reasoning efforts.

Research tool (docs/MODEL_COST.md). Paid calls: `replay` sends real requests to the Mistral
platform with the key in MISTRAL_API_KEY. Output lives under .local/living/model-cost/<name>/.

  sample   pick real past prompts from the mind journals, per call class, exact messages kept
  rates    measured calls per character-minute per class from the same journals
  replay   send each sample to each config twice in a row (stream: first token, last token, usage)
  validate run every reply through the mind's parse_json and the rules' graph normalizer
           (a small Rust harness, .local/living/model-cost/harness)
  pairs    blind A/B pairs (sides randomised) for talk and consolidation, with a key file
  report   cost per call, latency p50/p95, usable rate, caching
  hourly   € per character-hour for model mixes and call-rate scenarios (after report)
  spend    what the replays cost

Call classes (purpose in the journal → class):
  think                                   person_think    (decision, no grammar)
  deliberate, "You are the mind of the person"  person_compile  (graph grammar)
  deliberate, "You are the mind of the <animal>"  animal_think
  deliberate, "You turn the current impulse"  animal_compile
  consolidate, person / animal            person_consolidate / animal_consolidate
  talk                                    talk
The request shape is the mind's own (llm.rs request_body): model, messages, max_tokens 8000,
response_format json_object, and reasoning_effort when the config sets one. Replays add
`stream: true` so first-token latency can be read; content is assembled like
llm.rs content_text (text parts only), thinking parts are kept separately.
"""
import argparse
import concurrent.futures as cf
import glob
import gzip
import json
import os
import random
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, ".local/living/model-cost")
HARNESS = os.path.join(OUT, "harness")

# Configs: name → (model, reasoning_effort or None to omit the field).
CONFIGS = {
    "ministral-3b": ("ministral-3b-latest", None),
    "ministral-8b": ("ministral-8b-latest", None),
    "ministral-14b": ("ministral-14b-latest", None),
    "glm-flash": ("zai-glm-5-3-flash", None),  # as models.json sends it today: no effort field
    "glm-flash@low": ("zai-glm-5-3-flash", "low"),
    "glm-flash@high": ("zai-glm-5-3-flash", "high"),
    "glm-flash@max": ("zai-glm-5-3-flash", "max"),
    "deepseek-flash": ("deepseek-v4-1-flash-1017", None),  # platform default: no thinking
    "deepseek-flash@high": ("deepseek-v4-1-flash-1017", "high"),
}

# USD per million tokens (input, cached input, output), docs.mistral.ai/inference/pricing,
# read 2026-11-09. Reasoning tokens are part of completion_tokens and billed as output.
PRICES_USD = {
    "zai-glm-5-3-flash": (0.15, 0.03, 0.50),
    "deepseek-v4-1-flash-1017": (0.30, 0.007, 1.20),
    "ministral-3b-latest": (0.10, 0.01, 0.10),
    "ministral-8b-latest": (0.15, 0.015, 0.15),
    "ministral-14b-latest": (0.20, 0.02, 0.20),
    "mistral-small-2603": (None, None, None),
}
EUR_PER_USD = 0.85  # the user's EUR figures are exactly 0.85 × the USD list prices

CLASSES = ["person_think", "person_compile", "talk", "person_consolidate", "animal_think", "animal_compile", "animal_consolidate"]

# Calls per character per minute (docs/LIVING_CORE.md "Minds at scale"): on stage = the labs'
# measured mean (stage3-village, stage4-two); off stage = the LOD replay with nobody on stage.
RATES_PERSON = {
    "on": {"person_think": 0.74, "person_compile": 0.79, "talk": 0.35, "person_consolidate": 0.63},
    "off": {"person_think": 0.125, "person_compile": 0.125, "talk": 0.14, "person_consolidate": 0.06},
}


def classify(e):
    m = e["request"]["messages"]
    s = m[0]["content"]
    p = e.get("purpose")
    if p == "talk":
        return "talk"
    if p == "think":
        return "person_think"
    if p == "consolidate":
        if s.startswith("You are the memory of the"):
            return "animal_consolidate"
        if "resting. Tidy" in s[:200]:
            return "reorganize"
        return "person_consolidate"
    if p == "deliberate":
        if s.startswith("You turn the current impulse"):
            return "animal_compile"
        if s.startswith("You are the mind of the person"):
            return "person_compile"
        if s.startswith("You are the mind of the"):
            return "animal_think"
    return None


def animal_kind(e):
    s = e["request"]["messages"][0]["content"]
    for k in ("deer", "wolf", "boar", "hare", "bear", "fox"):
        if f" a {k}" in s[:200] or f"the {k} " in s[:200] or f"of a {k}" in s[:200]:
            return k
    return "person"


def entries(run):
    for f in sorted(glob.glob(os.path.join(ROOT, ".local/living/journal", run, "*.jsonl*"))):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("request"):
                    e["_file"] = os.path.relpath(f, ROOT)
                    yield e


# ---------------------------------------------------------------- sample


def cmd_sample(a):
    rng = random.Random(a.seed)
    pools = {c: [] for c in CLASSES}
    span = {}
    for run in a.runs:
        es = list(entries(run))
        t0, t1 = min(e["at_ms"] for e in es), max(e["at_ms"] for e in es)
        span[run] = (t0, t1)
        for e in es:
            c = classify(e)
            if c not in pools or not e.get("reply") or e.get("error"):
                continue
            if len(e["request"]["messages"]) != 2:  # first attempts only (no correction turns)
                continue
            if e["at_ms"] < t0 + (t1 - t0) * a.after:  # mature contexts
                continue
            e["_run"] = run
            pools[c].append(e)
    out = []
    for c in CLASSES:
        pool = pools[c]
        rng.shuffle(pool)
        seen, pick = set(), []
        for e in pool:  # distinct characters first
            if e["actor"] not in seen:
                pick.append(e)
                seen.add(e["actor"])
            if len(pick) >= a.per:
                break
        for e in pool:
            if len(pick) >= a.per:
                break
            if e not in pick:
                pick.append(e)
        for i, e in enumerate(pick):
            out.append({
                "id": f"{c}-{i:02d}", "cls": c, "kind": animal_kind(e) if c.startswith("animal") else "person",
                "run": e["_run"], "file": e["_file"], "at_ms": e["at_ms"], "actor": e["actor"],
                "orig_model": e.get("model"), "orig_prompt_tokens": e.get("prompt_tokens"), "orig_completion_tokens": e.get("completion_tokens"),
                "orig_cached_tokens": e.get("cached_tokens"), "orig_latency_ms": e.get("latency_ms"),
                "messages": e["request"]["messages"], "orig_reply": e["reply"],
            })
        print(f"{c}: {len(pick)} of {len(pool)} candidates", file=sys.stderr)
    os.makedirs(a.dir, exist_ok=True)
    with open(os.path.join(a.dir, "samples.jsonl"), "w") as f:
        for s in out:
            f.write(json.dumps(s) + "\n")
    print(f"{len(out)} samples → {a.dir}/samples.jsonl")


# ---------------------------------------------------------------- rates


def cmd_rates(a):
    for run in a.runs:
        counts, actors, t = {}, {}, []
        for e in entries(run):
            c = classify(e)
            if not c:
                continue
            counts[c] = counts.get(c, 0) + 1
            kind = "animal" if c.startswith("animal") else "person"
            actors.setdefault(kind, set()).add(e["actor"])
            t.append(e["at_ms"])
        minutes = (max(t) - min(t)) / 60000
        print(f"{run}: {minutes:.0f} min, {len(actors.get('person', ()))} people, {len(actors.get('animal', ()))} animals with calls")
        for c, n in sorted(counts.items()):
            kind = "animal" if c.startswith("animal") else "person"
            print(f"  {c:20s} {n:6d} calls  {n / minutes / max(1, len(actors.get(kind, ()))):.3f} /character/min")


# ---------------------------------------------------------------- replay

_lock = threading.Lock()


def stream_call(key, model, effort, messages, cache_key=None):
    body = {"model": model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages], "max_tokens": 8000, "response_format": {"type": "json_object"}, "stream": True}
    if effort:
        body["reasoning_effort"] = effort
    if cache_key:
        body["prompt_cache_key"] = cache_key
    req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "text/event-stream"})
    t0 = time.time()
    first_any = first_text = None
    text, thinking, usage, finish = [], [], None, None
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            ch = json.loads(data)
            if ch.get("usage"):
                usage = ch["usage"]
            for c in ch.get("choices", []):
                finish = c.get("finish_reason") or finish
                d = c.get("delta", {}).get("content")
                if not d:
                    continue
                now = time.time() - t0
                first_any = first_any if first_any is not None else now
                parts = [{"type": "text", "text": d}] if isinstance(d, str) else d
                for p in parts:
                    if p.get("type") == "text" and p.get("text"):
                        first_text = first_text if first_text is not None else now
                        text.append(p["text"])
                    elif p.get("type") == "thinking":
                        for t in p.get("thinking", []):
                            thinking.append(t.get("text", ""))
    total = time.time() - t0
    return {"reply": "".join(text), "thinking": "".join(thinking), "usage": usage, "finish": finish, "first_token_s": first_any, "first_text_s": first_text, "total_s": total, "request": {k: v for k, v in body.items() if k != "messages"}}


def cmd_replay(a):
    key = os.environ.get("MISTRAL_API_KEY") or sys.exit("MISTRAL_API_KEY not set")
    samples = [json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))]
    if a.classes:
        samples = [s for s in samples if s["cls"] in a.classes]
    configs = a.configs or list(CONFIGS)
    bad = [c for c in configs if c.removesuffix("+key") not in CONFIGS]
    if bad:
        sys.exit(f"unknown configs {bad}")
    path = os.path.join(a.dir, "replays.jsonl")
    done = set()
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            if not r.get("error"):
                done.add((r["id"], r["config"], r["run_n"]))
    jobs = [(s, c) for s in samples for c in configs if not all((s["id"], c, n) in done for n in (1, 2))]
    print(f"{len(jobs)} sample×config jobs ({len(samples)} samples, {len(configs)} configs), 2 calls each", file=sys.stderr)

    def job(sc):
        s, c = sc
        model, effort = CONFIGS[c.removesuffix("+key")]
        # "+key": send prompt_cache_key as llm.rs request_body does with `prompt_cache_key: true`
        # (sao:<len>:<profile>:<purpose>; purpose = the journal purpose of the class).
        purpose = {"person_think": "think", "talk": "talk"}.get(s["cls"], "consolidate" if "consolidate" in s["cls"] else "deliberate")
        profile = c.removesuffix("+key")
        cache_key = f"sao:{len(profile)}:{profile}:{purpose}" if c.endswith("+key") else None
        for n in (1, 2):  # twice in a row: the second shows prefix caching
            if (s["id"], c, n) in done:
                continue
            rec = {"id": s["id"], "cls": s["cls"], "kind": s["kind"], "config": c, "model": model, "effort": effort, "run_n": n, "at": time.time()}
            for attempt in range(6):
                try:
                    rec.update(stream_call(key, model, effort, s["messages"], cache_key))
                    rec.pop("error", None)
                    break
                except urllib.error.HTTPError as e:
                    rec["error"] = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
                    if e.code in (429, 500, 502, 503, 504):
                        time.sleep(2 * 2 ** attempt)
                        continue
                    break
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {e}"
                    time.sleep(2 * 2 ** attempt)
            rec["attempts"] = attempt + 1
            with _lock:
                with open(path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
        return s["id"], c

    n = 0
    with cf.ThreadPoolExecutor(a.concurrency) as ex:
        for _ in ex.map(job, jobs):
            n += 1
            if n % 25 == 0:
                print(f"  {n}/{len(jobs)}", file=sys.stderr)
    print(f"replays → {path}")


# ---------------------------------------------------------------- validate


def usable(cls, v):
    """Does a parsed reply have what the mind reads? (see mind.rs / talk.rs)."""
    if v is None:
        return False, "not JSON"
    if cls == "person_think":
        ok = isinstance(v.get("thought"), str) and isinstance(v.get("intend"), list)
        return ok, None if ok else "no thought/intend"
    if cls == "animal_think":
        ok = bool(v.get("impulse"))
        return ok, None if ok else "no impulse"
    if cls in ("person_consolidate", "animal_consolidate"):
        ok = isinstance(v.get("summary"), str) and v["summary"].strip() != ""
        return ok, None if ok else "no summary"
    if cls == "talk":
        say = v.get("say")
        ok = isinstance(say, (str, dict)) or v.get("end") is True
        return ok, None if ok else "no say"
    return True, None


def cmd_validate(a):
    binary = os.path.join(HARNESS, "target/release/model-cost-harness")
    if not os.path.exists(binary):
        subprocess.run(["cargo", "build", "--release", "--manifest-path", os.path.join(HARNESS, "Cargo.toml")], check=True)
    samples = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))}
    recs = [json.loads(l) for l in open(os.path.join(a.dir, "replays.jsonl"))]
    # the journals' original replies, validated the same way, as a baseline
    items = [{"id": f"orig|{s['id']}", "cls": s["cls"], "kind": s["kind"], "reply": s["orig_reply"]} for s in samples.values()]
    items += [{"id": f"{i}", "cls": r["cls"], "kind": r["kind"], "reply": r.get("reply") or ""} for i, r in enumerate(recs) if not r.get("error")]
    p = subprocess.run([binary, os.path.join(ROOT, "living/seeds/species.json")], input="\n".join(json.dumps(x) for x in items), capture_output=True, text=True, check=True)
    res = {}
    for l in p.stdout.splitlines():
        o = json.loads(l)
        res[o["id"]] = o
    out = []
    for x in items:
        o = res[x["id"]]
        v = o.get("parsed")
        ok, why = usable(x["cls"], v)
        g = o.get("graph")
        if g == "failed":
            ok, why = False, o.get("graph_error")
        out.append({"id": x["id"], "cls": x["cls"], "usable": ok, "why": why or o.get("parse_error"), "graph": g, "warnings": len(o.get("warnings") or []), "warning_text": o.get("warnings"), "nodes": o.get("nodes"), "routines_ok": o.get("routines_ok"), "routines_failed": o.get("routines_failed")})
    with open(os.path.join(a.dir, "validated.jsonl"), "w") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")
    print(f"{len(out)} validated → {a.dir}/validated.jsonl")


# ---------------------------------------------------------------- pairs


def cmd_pairs(a):
    """Blind pairs: for each talk/consolidation sample, the reference reply vs each candidate."""
    rng = random.Random(a.seed)
    samples = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))}
    recs = [json.loads(l) for l in open(os.path.join(a.dir, "replays.jsonl"))]
    by = {}
    for r in recs:
        if r["run_n"] == 1 and not r.get("error") and r["cls"] in a.classes:
            by[(r["id"], r["config"])] = r
    def parses(r):
        try:
            return isinstance(json.loads(r["reply"].strip()), dict)
        except Exception:
            return False

    pairs, key = [], []
    taken = {}
    for sid, s in sorted(samples.items()):
        if s["cls"] not in a.classes or (sid, a.reference) not in by:
            continue
        taken[s["cls"]] = taken.get(s["cls"], 0) + 1
        if a.max_samples and s["cls"] != "talk" and taken[s["cls"]] > a.max_samples:
            continue
        for c in a.candidates:
            if (sid, c) not in by or not parses(by[(sid, c)]):  # unusable replies are counted by validate, not judged
                continue
            ref, cand = by[(sid, a.reference)]["reply"], by[(sid, c)]["reply"]
            flip = rng.random() < 0.5
            pid = f"P{len(pairs):03d}"
            pairs.append({"pair": pid, "cls": s["cls"], "system": s["messages"][0]["content"], "user": s["messages"][1]["content"], "A": cand if flip else ref, "B": ref if flip else cand})
            key.append({"pair": pid, "sample": sid, "A": c if flip else a.reference, "B": a.reference if flip else c})
    # judge chunks: per sample, its prompt once and its pairs; nothing about which model is which
    jd = os.path.join(a.dir, "judge" + (f"-{a.tag}" if a.tag else ""))
    os.makedirs(jd, exist_ok=True)
    groups = {}
    for p_, k in zip(pairs, key):
        groups.setdefault((p_["cls"], k["sample"]), []).append(p_)
    order = list(groups)
    rng.shuffle(order)
    for cls in a.classes:
        mine = [g for g in order if g[0] == cls]
        chunk = a.chunk if cls in ("talk", "animal_think") else a.chunk_consolidate
        for ci in range(0, len(mine), chunk):
            with open(os.path.join(jd, f"{cls}-{ci // chunk}.md"), "w") as f:
                for g in mine[ci:ci + chunk]:
                    ps = groups[g]
                    f.write(f"\n\n======== PROMPT {ps[0]['pair']} … (pairs {', '.join(x['pair'] for x in ps)})\n\n--- system ---\n{ps[0]['system']}\n\n--- user ---\n{ps[0]['user']}\n")
                    for x in ps:
                        f.write(f"\n-------- PAIR {x['pair']} --------\n[A]\n{x['A']}\n\n[B]\n{x['B']}\n")
    rng.shuffle(pairs)
    tag = f"-{a.tag}" if a.tag else ""
    with open(os.path.join(a.dir, f"pairs{tag}.jsonl"), "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    with open(os.path.join(a.dir, f"pairs{tag}_key.jsonl"), "w") as f:
        for k in key:
            f.write(json.dumps(k) + "\n")
    print(f"{len(pairs)} pairs → {a.dir}/pairs{tag}.jsonl (key in pairs{tag}_key.jsonl, judge files in {jd})")


# ---------------------------------------------------------------- report


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def cost_eur(model, u, cached_override=None):
    pin, pcache, pout = PRICES_USD[model]
    if pin is None or not u:
        return None
    prompt = u.get("prompt_tokens", 0)
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    if cached_override is not None:
        cached = cached_override
    out = u.get("completion_tokens", 0)
    return ((prompt - cached) * pin + cached * pcache + out * pout) / 1e6 * EUR_PER_USD


def cmd_report(a):
    recs = [json.loads(l) for l in open(os.path.join(a.dir, "replays.jsonl"))]
    val = {o["id"]: o for o in map(json.loads, open(os.path.join(a.dir, "validated.jsonl")))}
    rows = {}
    for i, r in enumerate(recs):
        k = (r["cls"], r["config"])
        d = rows.setdefault(k, {"n": 0, "err": 0, "c1": [], "c2": [], "cold": [], "prompt": [], "cached1": [], "cached2": [], "out": [], "reason": [], "tot": [], "ttft": [], "ttxt": [], "usable": [], "warn": [], "graph": []})
        if r.get("error"):
            d["err"] += 1
            continue
        d["n"] += 1
        u = r.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        c = cost_eur(r["model"], u)
        (d["c1"] if r["run_n"] == 1 else d["c2"]).append(c)
        d["cold"].append(cost_eur(r["model"], u, 0))
        d["prompt"].append(u.get("prompt_tokens"))
        (d["cached1"] if r["run_n"] == 1 else d["cached2"]).append(cached / max(1, u.get("prompt_tokens", 1)))
        d["out"].append(u.get("completion_tokens"))
        d["reason"].append((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        d["tot"].append(r["total_s"])
        d["ttft"].append(r["first_token_s"])
        d["ttxt"].append(r["first_text_s"])
        v = val.get(str(i))
        if v:
            d["usable"].append(v["usable"])
            if v["graph"] in ("ok",):
                d["warn"].append(v["warnings"])
            d["graph"].append(v["graph"])
    mean = lambda xs: statistics.mean([x for x in xs if x is not None]) if [x for x in xs if x is not None] else None
    table = []
    for (cls, cfg), d in sorted(rows.items(), key=lambda x: (CLASSES.index(x[0][0]), list(CONFIGS).index(x[0][1].removesuffix("+key")), x[0][1])):
        table.append({
            "cls": cls, "config": cfg, "calls": d["n"], "errors": d["err"],
            "prompt_tok": mean(d["prompt"]), "out_tok": mean(d["out"]), "reason_tok": mean(d["reason"]),
            "cached_share_1": mean(d["cached1"]), "cached_share_2": mean(d["cached2"]),
            "eur_cold": mean(d["cold"]), "eur_1": mean(d["c1"]), "eur_2": mean(d["c2"]),
            "p50_s": pct(d["tot"], 0.5), "p95_s": pct(d["tot"], 0.95), "ttft_p50_s": pct(d["ttft"], 0.5), "first_text_p50_s": pct(d["ttxt"], 0.5),
            "usable": (sum(d["usable"]) / len(d["usable"])) if d["usable"] else None,
            "graph_keep": d["graph"].count("keep"), "graph_ok": d["graph"].count("ok"), "graph_failed": d["graph"].count("failed"),
            "warnings_per_graph": mean(d["warn"]),
        })
    # baseline: the journals' original replies
    base = {}
    for k, o in val.items():
        if k.startswith("orig|"):
            base.setdefault(o["cls"], []).append(o["usable"])
    json.dump({"table": table, "orig_usable": {c: sum(v) / len(v) for c, v in base.items()}}, open(os.path.join(a.dir, "report.json"), "w"), indent=1)
    f = lambda x, n=2: "–" if x is None else (f"{x:.{n}f}" if isinstance(x, float) else str(x))
    print("| class | config | n | prompt | cached 1st/2nd | out (reason) | € per call cold / 2nd | € per 1k calls (2nd) | total p50 / p95 s | first text p50 s | usable | graph ok/keep/fail | warn/graph |")
    print("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for t in table:
        print(f"| {t['cls']} | {t['config']} | {t['calls']}{'+' + str(t['errors']) + 'err' if t['errors'] else ''} | {f(t['prompt_tok'], 0)} | {f(t['cached_share_1'] and 100 * t['cached_share_1'], 0)}% / {f(t['cached_share_2'] and 100 * t['cached_share_2'], 0)}% | {f(t['out_tok'], 0)} ({f(t['reason_tok'], 0)}) | {f(t['eur_cold'] and t['eur_cold'] * 1e3, 3)}m / {f(t['eur_2'] and t['eur_2'] * 1e3, 3)}m | {f(t['eur_2'] and t['eur_2'] * 1e3, 3)} | {f(t['p50_s'], 1)} / {f(t['p95_s'], 1)} | {f(t['first_text_p50_s'], 1)} | {f(t['usable'] and 100 * t['usable'], 0)}% | {t['graph_ok']}/{t['graph_keep']}/{t['graph_failed']} | {f(t['warnings_per_graph'], 2)} |")
    print("orig (journal) usable:", {c: round(sum(v) / len(v), 2) for c, v in base.items()})


# ---------------------------------------------------------------- hourly

# Calls per character per minute. aske-coast: measured by `rates` on aske-coast-1792435287 and
# -1792391919 (6 h each, ~71 people, ~108 animals with calls, no LOD). labs / LOD off stage:
# docs/LIVING_CORE.md "Minds at scale". Animals near people: 0.14–0.34 calls/animal/min in the
# labs (midpoint 0.24, split think:compile:consolidate like aske-coast, 0.31:0.31:0.38).
SCENARIOS = {
    "person, aske-coast (no LOD)": {"person_think": 0.805, "person_compile": 0.81, "talk": 0.067, "person_consolidate": 0.48},
    "person, labs on stage": {"person_think": 0.74, "person_compile": 0.79, "talk": 0.35, "person_consolidate": 0.63},
    "person, off stage (LOD)": {"person_think": 0.125, "person_compile": 0.125, "talk": 0.14, "person_consolidate": 0.06},
    "animal, aske-coast (all animals)": {"animal_think": 0.0135, "animal_compile": 0.0135, "animal_consolidate": 0.0165},
    "animal, near people (labs)": {"animal_think": 0.074, "animal_compile": 0.074, "animal_consolidate": 0.092},
}

MIXES = {
    "today (models.json: GLM Flash, no effort; animals ministral 8b/14b)": {"person_think": "glm-flash", "person_compile": "glm-flash", "talk": "glm-flash", "person_consolidate": "glm-flash", "animal_think": "ministral-8b", "animal_compile": "ministral-14b", "animal_consolidate": "ministral-14b"},
    "GLM Flash @low everywhere": {c: "glm-flash@low" for c in CLASSES},
    "GLM Flash @high everywhere": {c: "glm-flash@high" for c in CLASSES},
    "DeepSeek Flash (no thinking) everywhere": {c: "deepseek-flash" for c in CLASSES},
    "Ministral 8B everywhere": {c: "ministral-8b" for c in CLASSES},
    "recommended: GLM Flash think/deliberate low, talk/consolidate high": {"person_think": "glm-flash@low", "person_compile": "glm-flash@low", "talk": "glm-flash@high", "person_consolidate": "glm-flash@high", "animal_think": "glm-flash@low", "animal_compile": "glm-flash@low", "animal_consolidate": "glm-flash@high"},
    "later (per-purpose routing): as recommended, talk and person consolidation on DeepSeek Flash": {"person_think": "glm-flash@low", "person_compile": "glm-flash@low", "talk": "deepseek-flash", "person_consolidate": "deepseek-flash", "animal_think": "glm-flash@low", "animal_compile": "glm-flash@low", "animal_consolidate": "glm-flash@high"},
}

# How often the mind asks again after an unusable reply (mind.rs): a compile up to 3 attempts;
# a person's think once more with the default profile; an animal's memory once more with the
# compile profile; a person's consolidation and talk are not retried.
ATTEMPTS = {"person_think": 2, "person_compile": 3, "talk": 1, "person_consolidate": 1, "animal_think": 1, "animal_compile": 3, "animal_consolidate": 2}


def cmd_hourly(a):
    rep = json.load(open(os.path.join(a.dir, "report.json")))
    t = {(r["cls"], r["config"]): r for r in rep["table"]}

    def per_call(cls, cfg, keyed):
        r = (t.get((cls, cfg + "+key")) if keyed else None) or t.get((cls, cfg))
        if not r or r["eur_1"] is None:
            return None
        p = r["usable"] or 0.0
        n = ATTEMPTS[cls]
        attempts = sum((1 - p) ** k for k in range(n))  # expected calls per request
        return r["eur_1"] * attempts, 1 - (1 - p) ** n  # spend per request, share that ends usable

    out = {}
    print("€ spent per character-hour (first-run caching as measured, retries included) and the share of requests that end with no usable reply\n")
    for keyed in (False, True):
        print(f"## {'with prompt_cache_key' if keyed else 'as sent today (no prompt_cache_key)'}\n")
        print("| mix | " + " | ".join(SCENARIOS) + " | lost (worst class) |")
        print("|---|" + "--:|" * (len(SCENARIOS) + 1))
        for m, mix in MIXES.items():
            cells, worst = [], (0.0, "")
            for sc, rates in SCENARIOS.items():
                tot = 0.0
                for cls, rate in rates.items():
                    spend, ok = per_call(cls, mix[cls], keyed)
                    tot += spend * rate * 60
                    worst = max(worst, (1 - ok, cls))
                cells.append(tot)
                out[f"{m}|{sc}|{'key' if keyed else 'nokey'}"] = tot
            print(f"| {m} | " + " | ".join(f"€{c:.3f}" for c in cells) + f" | {100 * worst[0]:.0f}% {worst[1] if worst[0] > 0.005 else ''} |")
        print()
    json.dump(out, open(os.path.join(a.dir, "hourly.json"), "w"), indent=1)


def cmd_spend(a):
    recs = [json.loads(l) for l in open(os.path.join(a.dir, "replays.jsonl"))]
    tot, toks = 0.0, [0, 0, 0]
    by = {}
    for r in recs:
        u = r.get("usage")
        if not u:
            continue
        c = cost_eur(r["model"], u) or 0
        tot += c
        by[r["model"]] = by.get(r["model"], 0) + c
        toks[0] += u.get("prompt_tokens", 0)
        toks[1] += (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        toks[2] += u.get("completion_tokens", 0)
    print(f"{len(recs)} calls, {toks[0]:,} prompt tokens ({toks[1]:,} cached), {toks[2]:,} completion tokens: €{tot:.2f} (${tot / EUR_PER_USD:.2f})")
    for m, c in sorted(by.items(), key=lambda x: -x[1]):
        print(f"  {m}: €{c:.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--runs", nargs="+", required=True)
    s.add_argument("--per", type=int, default=12)
    s.add_argument("--after", type=float, default=0.5, help="only the later part of each run (fraction of its span)")
    s.add_argument("--seed", type=int, default=20261109)
    r = sub.add_parser("rates")
    r.add_argument("--runs", nargs="+", required=True)
    p = sub.add_parser("replay")
    p.add_argument("--configs", nargs="*")
    p.add_argument("--classes", nargs="*")
    p.add_argument("--concurrency", type=int, default=12)
    sub.add_parser("validate")
    q = sub.add_parser("pairs")
    q.add_argument("--classes", nargs="+", default=["talk", "person_consolidate", "animal_consolidate"])
    q.add_argument("--reference", default="glm-flash@high")
    q.add_argument("--candidates", nargs="+", default=["glm-flash@low", "ministral-3b", "ministral-8b", "ministral-14b", "deepseek-flash"])
    q.add_argument("--seed", type=int, default=7)
    q.add_argument("--tag", default="", help="suffix for the pairs/key files and judge directory")
    q.add_argument("--chunk", type=int, default=6, help="talk samples per judge file")
    q.add_argument("--chunk-consolidate", type=int, default=2, help="consolidation samples per judge file")
    q.add_argument("--max-samples", type=int, default=0, help="consolidation samples per class (0 = all); talk keeps all")
    sub.add_parser("report")
    sub.add_parser("hourly")
    sub.add_parser("spend")
    for x in (s, p, sub.choices["validate"], q, sub.choices["report"], sub.choices["hourly"], sub.choices["spend"]):
        x.add_argument("--dir", default=os.path.join(OUT, "20261109"))
    a = ap.parse_args()
    {"sample": cmd_sample, "rates": cmd_rates, "replay": cmd_replay, "validate": cmd_validate, "pairs": cmd_pairs, "report": cmd_report, "hourly": cmd_hourly, "spend": cmd_spend}[a.cmd](a)


if __name__ == "__main__":
    main()
