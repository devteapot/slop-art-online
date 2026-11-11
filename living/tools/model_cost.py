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

Part 2 (planning, reorganization, internalization; docs/MODEL_COST.md "Part 2"):
  sample2  think by situation (combat/survival/social) with the compile that followed, reorganize, internalize
  chain    compile prompts built from each config's own think replies (person_compile_own)
  batch    one Mistral batch job per config (inline, or an uploaded file above ~2.5 MiB)
  judge    blind N-way judge files (labels shuffled per prompt; keys in keys/)
  verdicts join judge verdicts with the key
  patches  reorganize/internalize: what memory.rs patch_from keeps and what it would change
  ids      experience ids written as strings (patch_from drops them)
  planning € per person-hour for think × compile pairs, on and off stage
  nights   sleep-aligned reorganization simulated on real consolidation timelines
Config suffixes: +key (prompt_cache_key), +24k (max_tokens 24000), +batch (answers from `batch`).

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

from journal_io import restore
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
    # Part 2 (planning, reorganization, internalization)
    "deepseek-flash@low": ("deepseek-v4-1-flash-1017", "low"),
    "deepseek-flash@max": ("deepseek-v4-1-flash-1017", "max"),
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
# Batch jobs: "a 50% discount" (docs.mistral.ai/capabilities/batch); no per-model batch price is
# published and billing was not checked, so batch costs here are list price × 0.5.
BATCH_DISCOUNT = 0.5
EUR_PER_USD = 0.85  # the user's EUR figures are exactly 0.85 × the USD list prices

CLASSES = ["person_think", "person_compile", "talk", "person_consolidate", "animal_think", "animal_compile", "animal_consolidate",
           # Part 2: a compile of each config's own think reply, the sleep-like reorganization
           # (journal purpose `consolidate`) and player memory (`internalize`).
           "person_compile_own", "reorganize", "internalize"]


def purpose_of(cls):
    """The purpose the mind sends for a class (llm.rs picks reasoning_effort and the cache key by it).
    Reorganization goes out as `consolidate` (mind.rs reorganize), so it shares consolidation's effort."""
    return {"person_think": "think", "talk": "talk", "internalize": "internalize"}.get(cls, "consolidate" if cls in ("person_consolidate", "animal_consolidate", "reorganize") else "deliberate")

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
                    e = restore(json.loads(line), os.path.dirname(f))
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


def stream_call(key, model, effort, messages, cache_key=None, max_tokens=8000):
    body = {"model": model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages], "max_tokens": max_tokens, "response_format": {"type": "json_object"}, "stream": True}
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
    samples = [s for s in samples if not s.get("pool")]  # batch-only reorganizations
    configs = a.configs or list(CONFIGS)
    bad = [c for c in configs if base_config(c) not in CONFIGS]
    if bad:
        sys.exit(f"unknown configs {bad}")
    path = os.path.join(a.dir, "replays.jsonl")
    done = set()
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            if not r.get("error"):
                done.add((r["id"], r["config"], r["run_n"]))
    runs = (1,) if a.once else (1, 2)
    # a chained sample (person_compile_own) belongs to the config whose think it compiles
    jobs = [(s, c) for s in samples for c in configs if s.get("only", c) == c and not all((s["id"], c, n) in done for n in runs)]
    print(f"{len(jobs)} sample×config jobs ({len(samples)} samples, {len(configs)} configs), 2 calls each", file=sys.stderr)

    def job(sc):
        s, c = sc
        model, effort = CONFIGS[base_config(c)]
        # "+24k": max_tokens 24000 instead of the mind's 8000 (a profile's `max_tokens`)
        max_tokens = 24000 if "+24k" in c else 8000
        # "+key": send prompt_cache_key as llm.rs request_body does with `prompt_cache_key: true`
        # (sao:<len>:<profile>:<purpose>; purpose = the journal purpose of the class).
        purpose = purpose_of(s["cls"])
        profile = base_config(c)
        cache_key = f"sao:{len(profile)}:{profile}:{purpose}" if "+key" in c else None
        for n in runs:  # twice in a row: the second shows prefix caching
            if (s["id"], c, n) in done:
                continue
            rec = {"id": s["id"], "cls": s["cls"], "kind": s["kind"], "config": c, "model": model, "effort": effort, "run_n": n, "at": time.time()}
            for attempt in range(6):
                try:
                    rec.update(stream_call(key, model, effort, s["messages"], cache_key, max_tokens))
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
    if cls in ("reorganize", "internalize"):
        # mind.rs reorganize / lived.rs lived_finish: any JSON object is applied (summary has a default)
        return True, None
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
    recs = load_replays(a.dir)
    # the journals' original replies, validated the same way, as a baseline
    known = {sid: prompt_known(s) for sid, s in samples.items()}
    items = [{"id": f"orig|{s['id']}", "cls": s["cls"], "kind": s["kind"], "reply": s["orig_reply"], "known": known[s["id"]]} for s in samples.values() if s.get("orig_reply")]
    items += [{"id": rkey(r), "cls": r["cls"], "kind": r["kind"], "reply": r.get("reply") or "", "known": known.get(r["id"], []), "sample": r["id"]} for r in recs if not r.get("error")]
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
        row = {"id": x["id"], "cls": x["cls"], "usable": ok, "why": why or o.get("parse_error"), "graph": g, "warnings": len(o.get("warnings") or []), "warning_text": o.get("warnings"), "nodes": o.get("nodes"), "routines_ok": o.get("routines_ok"), "routines_failed": o.get("routines_failed")}
        if o.get("patch") is not None:
            sid = x["id"].split("|", 1)[1] if x["id"].startswith("orig|") else x["sample"]
            row["patch"] = grounding(samples[sid], o["patch"])
        out.append(row)
    with open(os.path.join(a.dir, "validated.jsonl"), "w") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")
    print(f"{len(out)} validated → {a.dir}/validated.jsonl")


def prompt_known(s):
    """Experience ids the mind passes as `known`: for internalize, the batch shown under
    # New experiences; for reorganize, the unintegrated inbox, which the prompt does not show
    (an empty list here: every `because` id a reorganization cites is dropped either way)."""
    if s["cls"] != "internalize":
        return []
    u = s["messages"][1]["content"]
    i = u.find("# New experiences to integrate")
    return [int(m) for m in __import__("re").findall(r"^- \[(\d+)\]", u[i:], __import__("re").M)] if i >= 0 else []


def prompt_mind(u):
    """Concept keys and open edges (from, REL, to) a reorganize prompt shows, and every person id it mentions."""
    import re
    concepts, edges = set(), set()
    sec = None
    for line in u.splitlines():
        if line.startswith("# "):
            sec = "c" if line.startswith("# Your concepts") else "e" if line.startswith("# Your current beliefs") else None
            continue
        if not line.startswith("- "):
            continue
        if sec == "c":
            concepts.add(line[2:].split(" ", 1)[0].strip())
        elif sec == "e":
            m = re.match(r"^- (\S+) —([A-Za-z0-9_]+)", line)
            tail = line.rsplit("→ ", 1)
            if m and len(tail) == 2:
                edges.add((m.group(1), m.group(2).upper(), tail[1].split(" ", 1)[0]))
    people = {int(x) for x in re.findall(r"(?:#|person:)(\d+)\b", u)}
    return concepts, edges, people


def grounding(sample, p):
    """What a sanitized patch would actually change, against the mind the prompt shows
    (store.apply: a merge whose `from` does not exist and a retract of an absent edge are no-ops;
    edges and nodes MERGE, so unknown keys create concepts)."""
    u = sample["messages"][1]["content"]
    concepts, edges, people = prompt_mind(u)
    if sample["cls"] == "internalize":
        concepts = set()
    merges = [tuple(m) for m in p["merges"]]
    retract = [tuple(r) for r in p["retract"]]
    new_edges = [tuple(e) for e in p["edges"]]
    eff_merges = [m for m in merges if m[0] in concepts]
    merged_away = {m[0] for m in eff_merges}
    touched = {k for e in new_edges for k in (e[0], e[2])} | set(p["nodes"]) | {m[1] for m in merges}
    created = {k for k in touched if k not in concepts and k != "self"}
    stranger = sorted(k for k in touched if k.startswith("person:") and k[7:].isdigit() and int(k[7:]) not in people)
    out = {
        "given": p["given"], "notes": len(p["notes"]), "refused_merges": sum("refused" in n for n in p["notes"]), "skipped": sum("skipped" in n or "unreadable" in n or "without a usable key" in n for n in p["notes"]),
        "merges": len(merges), "merges_effective": len(eff_merges), "merges_into_new": sum(1 for m in eff_merges if m[1] not in concepts),
        "retract": len(retract), "retract_matched": sum(1 for r in retract if r in edges),
        "edges": len(new_edges), "edges_reasserted": sum(1 for e in new_edges if e in edges), "nodes": len(p["nodes"]), "nodes_existing": sum(1 for k in p["nodes"] if k in concepts),
        "created": len(created), "stranger_people": stranger, "remember": p["remember"], "judgments": p["judgments"],
        "because_given": p["because_given"], "because_kept": p["because_kept"],
    }
    if sample["cls"] == "reorganize":
        out["concepts_before"], out["edges_before"] = len(concepts), len(edges)
        out["concepts_after"] = len(concepts) - len(merged_away) + len(created - merged_away)
        out["edges_after"] = len(edges) - out["retract_matched"] + (len(new_edges) - out["edges_reasserted"])
    return out


# ---------------------------------------------------------------- pairs


def cmd_pairs(a):
    """Blind pairs: for each talk/consolidation sample, the reference reply vs each candidate."""
    rng = random.Random(a.seed)
    samples = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))}
    recs = load_replays(a.dir)
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


# ---------------------------------------------------------------- part 2: sample2, chain

# The situation a person is thinking in, from the first line of `# Why you are thinking now`
# that says something about it (a request merges several reasons; the first listed is the
# newest). Lines that say only that a decided act failed, or that it is dawn, are skipped.
SITUATIONS = [
    ("combat", ("threatening you", "attacks you", "attacked you", "is attacking", "hits you", "hit you", "bites you", "bit you", "fight", "is hunting you", "struck you")),
    ("survival", ("freezing", "very hungry", "starving", "badly hurt", "exhausted", "lose health")),
    ("social", ("asks you", "said to you", "wants to", "offers you", "long for", "crying", "asked you", "proposes", "would like")),
]


def why_section(u):
    i = u.find("# Why you are thinking now")
    if i < 0:
        return ""
    j = u.find("\n# ", i + 5)
    return u[i:j if j > 0 else None]


def situation(u, detail=False):
    """(situation, the matching word) for the first telling line; bodily alarms count only on
    a `Your body:` line (a failed seize says "or be badly hurt")."""
    for line in why_section(u).splitlines()[1:]:
        low = line.lower()
        for name, words in SITUATIONS:
            if name == "survival" and not low.startswith("your body"):
                continue
            w = next((w for w in words if w in low), None)
            if w:
                return (name, w) if detail else name
    return ("other", None) if detail else "other"


def cmd_sample2(a):
    """Part 2 samples: person think stratified by situation, each with the compile request that
    followed it; reorganizations; internalize prompts built from real consolidation contexts."""
    rng = random.Random(a.seed)
    old = set()
    if a.exclude and os.path.exists(a.exclude):
        old = {(json.loads(l)["file"], json.loads(l)["at_ms"]) for l in open(a.exclude)}
    think = {k: [] for k, _ in SITUATIONS}
    reorg, consol = [], []
    for run in a.runs:
        es = list(entries(run))
        t0, t1 = min(e["at_ms"] for e in es), max(e["at_ms"] for e in es)
        by_actor = {}
        for e in es:
            by_actor.setdefault(e["actor"], []).append(e)
        for actor, xs in by_actor.items():
            xs.sort(key=lambda e: e["at_ms"])
            for i, e in enumerate(xs):
                c = classify(e)
                if not e.get("reply") or e.get("error") or len(e["request"]["messages"]) != 2 or (e["_file"], e["at_ms"]) in old:
                    continue
                e["_run"] = run
                if c == "reorganize":
                    reorg.append(e)
                    continue
                if e["at_ms"] < t0 + (t1 - t0) * a.after:
                    continue
                if c == "person_consolidate":
                    consol.append(e)
                if c != "person_think":
                    continue
                sit, word = situation(e["request"]["messages"][1]["content"], detail=True)
                e["_word"] = word
                if sit not in think:
                    continue
                # the compile of this decision: the actor's next deliberate call, within 2 min
                nxt = next((x for x in xs[i + 1:i + 6] if classify(x) == "person_compile" and x["at_ms"] - e["at_ms"] < 120000), None)
                if not nxt or not nxt.get("reply") or len(nxt["request"]["messages"]) != 2:
                    continue
                nxt["_run"] = run
                think[sit].append((e, nxt))

    def rec(cid, cls, e, kind="person", **extra):
        return {"id": cid, "cls": cls, "kind": kind, "run": e["_run"], "file": e["_file"], "at_ms": e["at_ms"], "actor": e["actor"],
                "orig_model": e.get("model"), "orig_prompt_tokens": e.get("prompt_tokens"), "orig_completion_tokens": e.get("completion_tokens"),
                "orig_cached_tokens": e.get("cached_tokens"), "orig_latency_ms": e.get("latency_ms"),
                "messages": e["request"]["messages"], "orig_reply": e["reply"], **extra}

    def distinct(pool, n):
        rng.shuffle(pool)
        seen, pick = set(), []
        for x in pool:
            actor = (x[0] if isinstance(x, tuple) else x)["actor"]
            if actor not in seen:
                pick.append(x)
                seen.add(actor)
            if len(pick) >= n:
                break
        return pick + [x for x in pool if x not in pick][: n - len(pick)]

    def spread(pool, n):
        """Distinct characters, round-robin over the reason words (social would otherwise be
        mostly babies crying)."""
        groups = {}
        for x in pool:
            groups.setdefault(x[0]["_word"], []).append(x)
        for g in groups.values():
            rng.shuffle(g)
        pick, seen = [], set()
        while len(pick) < n and any(groups.values()):
            for w in sorted(groups):
                g = groups[w]
                while g and g[-1][0]["actor"] in seen:
                    g.pop()
                if g and len(pick) < n:
                    x = g.pop()
                    pick.append(x)
                    seen.add(x[0]["actor"])
        return pick

    out = []
    for sit, pool in think.items():
        for i, (t, c) in enumerate(spread(pool, a.per_situation)):
            tid = f"person_think-{sit}-{i:02d}"
            out.append(rec(tid, "person_think", t, situation=sit, reason_word=t["_word"]))
            out.append(rec(f"person_compile-{sit}-{i:02d}", "person_compile", c, situation=sit, think_id=tid))
        print(f"think/compile {sit}: {min(len(pool), a.per_situation)} of {len(pool)} pairs", file=sys.stderr)
    rpick = distinct(reorg, a.reorganize + a.reorganize_pool)
    for i, e in enumerate(rpick):
        out.append(rec(f"reorganize-{i:03d}", "reorganize", e, pool=i >= a.reorganize))
    print(f"reorganize: {len(rpick)} of {len(reorg)} ({a.reorganize} replayed directly, the rest only in the batch turnaround job)", file=sys.stderr)
    # Internalize: the system prompt the mind sends today (taken verbatim from a real
    # internalize request) over real consolidation contexts; consolidate_user is the user
    # message of both (lived.rs). Plus the real request itself.
    real = [restore(json.loads(l), os.path.dirname(a.internalize_journal)) for l in open(a.internalize_journal) if json.loads(l).get("purpose") == "internalize"][0]
    isys = real["request"]["messages"][0]["content"]
    for i, e in enumerate(distinct(consol, a.internalize - 1)):
        r = rec(f"internalize-{i:02d}", "internalize", e, built_from="person_consolidate")
        r["messages"] = [{"role": "system", "content": isys}, e["request"]["messages"][1]]
        r["orig_reply"] = None  # the journal's reply answered the consolidation system prompt
        out.append(r)
    out.append({"id": f"internalize-{a.internalize - 1:02d}", "cls": "internalize", "kind": "person", "run": "knowledge-pmem-real-132616", "file": os.path.relpath(a.internalize_journal, ROOT),
                "at_ms": real["at_ms"], "actor": real["actor"], "orig_model": real.get("model"), "messages": real["request"]["messages"], "orig_reply": real.get("reply"), "built_from": "real"})
    os.makedirs(a.dir, exist_ok=True)
    with open(os.path.join(a.dir, "samples.jsonl"), "w") as f:
        for x in out:
            f.write(json.dumps(x) + "\n")
    print(f"{len(out)} samples → {a.dir}/samples.jsonl")


def decided_text(reply):
    """What mind.rs puts under # What you decided from a think reply."""
    try:
        v = json.loads(reply.strip())
    except Exception:
        start, end = reply.find("{"), reply.rfind("}")
        try:
            v = json.loads(reply[start:end + 1])
        except Exception:
            return None
    if not isinstance(v, dict):
        return None
    intend = [x for x in (v.get("intend") or []) if isinstance(x, str)]
    return f"{v.get('thought') or ''}\nIntentions (in order): {'; '.join(intend) if intend else '(nothing new: carry on)'}"


def cmd_chain(a):
    """person_compile_own: the compile request each config would have got from its own think
    reply (first call), i.e. the original compile prompt with # What you decided replaced."""
    path = os.path.join(a.dir, "samples.jsonl")
    samples = [json.loads(l) for l in open(path)]
    samples = [s for s in samples if s["cls"] != "person_compile_own"]
    comp = {s["think_id"]: s for s in samples if s["cls"] == "person_compile" and s.get("think_id")}
    recs = load_replays(a.dir)
    marker = "\n# What you decided (express exactly this: add nothing, drop nothing)\n"
    n = 0
    for r in recs:
        if r["cls"] != "person_think" or r["run_n"] != 1 or r.get("error") or r["id"] not in comp:
            continue
        c = comp[r["id"]]
        d = decided_text(r.get("reply") or "")
        u = c["messages"][1]["content"]
        cut = u.find(marker)
        if d is None or cut < 0:
            continue
        s = dict(c, id=f"{c['id']}|{r['config']}", cls="person_compile_own", only=r["config"], orig_reply=None,
                 messages=[c["messages"][0], {"role": "user", "content": u[:cut] + marker + d + "\n\n"}])
        samples.append(s)
        n += 1
    with open(path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")
    print(f"{n} chained compile samples added to {path}")


# ---------------------------------------------------------------- part 2: batch


def rkey(r):
    """A replay's stable key in validated.jsonl (part 1 keyed by line index, which shifts while a replay appends)."""
    return f"{r['id']}~{r['config']}~{r['run_n']}"


def load_replays(d):
    """Direct replays, then batch answers (`batch`), in a fixed order (validate keys by index)."""
    out = []
    for name in ("replays.jsonl", "batch-replays.jsonl"):
        f = os.path.join(d, name)
        if os.path.exists(f):
            out += [json.loads(l) for l in open(f)]
    return out


def base_config(c):
    """`glm-flash@high+key+batch` → `glm-flash@high` (also drops `+24k`)."""
    return c.split("+", 1)[0]


def api(key, method, path, body=None):
    req = urllib.request.Request(f"https://api.mistral.ai/v1{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: HTTP {e.code}: {e.read()[:600].decode(errors='replace')}") from None
    try:
        return json.loads(raw)
    except Exception:
        return raw


# The inline `requests` body is refused above about 2.5 MiB (measured 2026-11-09: 2,609,266
# bytes accepted, 2,624,891 refused with an HTML 400 from the front proxy, before the API).
INLINE_LIMIT = 2_500_000


def upload_batch_file(key, lines):
    """POST /v1/files (purpose batch) with JSONL {custom_id, body} lines; returns the file id."""
    boundary = "----sao" + str(random.random())[2:]
    data = "".join(json.dumps(l) + "\n" for l in lines).encode()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"batch.jsonl\"\r\nContent-Type: application/jsonl\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://api.mistral.ai/v1/files", data=body, method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["id"]


def cmd_batch(a):
    """One Mistral batch job per config with the class's samples as inline requests, in the
    body llm.rs request_body builds (cache key included); jobs of different configs run at
    the same time, as a night's jobs would. Records the job's timeline and every answer."""
    key = os.environ.get("MISTRAL_API_KEY") or sys.exit("MISTRAL_API_KEY not set")
    samples = [json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))]
    samples = [x for x in samples if x["cls"] == a.cls and (a.pool or not x.get("pool"))]
    if a.limit:
        samples = samples[: a.limit]
    path = os.path.join(a.dir, "batch-replays.jsonl")  # kept apart: a direct replay may be appending to replays.jsonl
    jobs_path = os.path.join(a.dir, "batches.jsonl")

    def one(cfg):
        model, effort = CONFIGS[base_config(cfg)]
        profile = base_config(cfg)
        purpose = purpose_of(a.cls)
        reqs = []
        for x in samples:
            body = {"model": model, "messages": [{"role": m["role"], "content": m["content"]} for m in x["messages"]], "max_tokens": 8000, "response_format": {"type": "json_object"}}
            if effort:
                body["reasoning_effort"] = effort
            if "+key" in cfg:
                body["prompt_cache_key"] = f"sao:{len(profile)}:{profile}:{purpose}"
            reqs.append({"custom_id": x["id"], "body": body})
        t0 = time.time()
        spec = {"model": model, "endpoint": "/v1/chat/completions", "metadata": {"purpose": purpose, "study": "model-cost-part2"}, "timeout_hours": a.timeout_hours}
        size = len(json.dumps(reqs))
        if size > INLINE_LIMIT:
            spec["input_files"] = [upload_batch_file(key, reqs)]
        else:
            spec["requests"] = reqs
        job = api(key, "POST", "/batch/jobs", spec)
        jid = job["id"]
        timeline = [(0.0, job.get("status"))]
        print(f"{cfg}: job {jid}, {len(reqs)} {a.cls} requests", file=sys.stderr)
        while True:
            time.sleep(a.poll)
            j = api(key, "GET", f"/batch/jobs/{jid}")
            st = j.get("status")
            if st != timeline[-1][1]:
                timeline.append((round(time.time() - t0, 1), st))
                print(f"  {cfg} {jid}: {st} at {time.time() - t0:.0f} s ({j.get('completed_requests')}/{j.get('total_requests')})", file=sys.stderr)
            if st in ("SUCCESS", "FAILED", "TIMEOUT_EXCEEDED", "CANCELLED"):
                break
        turnaround = time.time() - t0
        lines = []
        for f in (j.get("output_file"), j.get("error_file")):
            if f:
                text = api(key, "GET", f"/files/{f}/content")
                text = text if isinstance(text, str) else json.dumps(text)
                lines += [json.loads(l) for l in text.splitlines() if l.strip()]
        got = {l.get("custom_id"): l for l in lines}
        with _lock:
            with open(jobs_path, "a") as fh:
                fh.write(json.dumps({"config": cfg, "cls": a.cls, "job": jid, "requests": len(reqs), "bytes": size, "via": "file" if "input_files" in spec else "inline", "turnaround_s": turnaround, "timeline": timeline, "final": {k: v for k, v in j.items() if k not in ("requests",)}}) + "\n")
            with open(path, "a") as fh:
                for x in samples:
                    l = got.get(x["id"]) or {}
                    resp = l.get("response") or {}
                    body = resp.get("body") if isinstance(resp.get("body"), dict) else resp
                    rec = {"id": x["id"], "cls": x["cls"], "kind": x["kind"], "config": cfg + "+batch", "model": model, "effort": effort, "run_n": 1, "at": t0, "mode": "batch", "job": jid, "turnaround_s": turnaround}
                    if body and body.get("choices"):
                        c = body["choices"][0]["message"]["content"]
                        parts = [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])
                        rec.update({"reply": "".join(p_.get("text", "") for p_ in parts if p_.get("type") == "text"),
                                    "thinking": "".join(t.get("text", "") for p_ in parts if p_.get("type") == "thinking" for t in p_.get("thinking", [])),
                                    "usage": body.get("usage"), "finish": body["choices"][0].get("finish_reason"), "first_token_s": None, "first_text_s": None, "total_s": turnaround})
                    else:
                        rec["error"] = f"no answer: {json.dumps(l)[:300]}"
                    fh.write(json.dumps(rec) + "\n")
        return cfg, jid, turnaround, timeline

    with cf.ThreadPoolExecutor(len(a.configs)) as ex:
        for cfg, jid, t, tl in ex.map(one, a.configs):
            print(f"{cfg}: job {jid} done in {t:.0f} s: {tl}")


# ---------------------------------------------------------------- part 2: blind N-way judging


def cmd_judge(a):
    """Blind N-way files: per prompt, the prompt once and every config's reply under a random
    label (R1…Rn, order shuffled per prompt). The key (label → config) is written apart."""
    rng = random.Random(a.seed)
    samples = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))}
    recs = load_replays(a.dir)
    val = {o["id"]: o for o in map(json.loads, open(os.path.join(a.dir, "validated.jsonl")))}
    by = {}
    for i, r in enumerate(recs):
        if r["cls"] != a.cls or r.get("error") or r["config"] not in a.configs or r["run_n"] != 1:
            continue
        if not (val.get(rkey(r)) or val.get(str(i)) or {}).get("usable"):
            continue  # unusable replies are counted by validate, not judged
        sid = r["id"].split("|", 1)[0] if a.cls == "person_compile_own" else r["id"]
        by.setdefault(sid, {})[r["config"]] = r
    jd = os.path.join(a.dir, f"judge-{a.tag or a.cls}")
    os.makedirs(jd, exist_ok=True)
    order = sorted(by)
    rng.shuffle(order)
    key = []
    for ci in range(0, len(order), a.chunk):
        with open(os.path.join(jd, f"{a.tag or a.cls}-{ci // a.chunk}.md"), "w") as f:
            systems = {samples[sid]["messages"][0]["content"] for sid in order[ci:ci + a.chunk]}
            shared_system = systems.pop() if len(systems) == 1 else None
            if shared_system:
                f.write(f"======== SYSTEM PROMPT (the same for every prompt in this file)\n\n{shared_system}\n")
            for sid in order[ci:ci + a.chunk]:
                pid = f"J{len(key):03d}"
                cfgs = list(by[sid])
                rng.shuffle(cfgs)
                labels = {c: f"R{n + 1}" for n, c in enumerate(cfgs)}
                msgs = samples[sid]["messages"]
                system = "(the system prompt at the top of this file)" if shared_system else msgs[0]["content"]
                f.write(f"\n\n======== PROMPT {pid} ({len(cfgs)} replies: {', '.join(labels[c] for c in cfgs)})\n\n--- system ---\n{system}\n\n--- user ---\n{msgs[1]['content']}\n")
                for c in cfgs:
                    f.write(f"\n-------- REPLY {pid}/{labels[c]} --------\n{by[sid][c]['reply']}\n")
                key.append({"prompt": pid, "sample": sid, "labels": {labels[c]: c for c in cfgs}})
    kd = os.path.join(a.dir, "keys")  # apart from what the judges read
    os.makedirs(kd, exist_ok=True)
    with open(os.path.join(kd, f"{a.tag or a.cls}.jsonl"), "w") as f:
        for k in key:
            f.write(json.dumps(k) + "\n")
    print(f"{len(key)} prompts → {jd} ({len(os.listdir(jd))} files; key in {kd}/{a.tag or a.cls}.jsonl)")


def cmd_verdicts(a):
    """Join judge verdicts (`*.verdicts.jsonl`: prompt, label, score 1–5, acceptable, rank) with the key."""
    jd = os.path.join(a.dir, f"judge-{a.tag}")
    key = {k["prompt"]: k for k in map(json.loads, open(os.path.join(a.dir, "keys", f"{a.tag}.jsonl")))}
    samples = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))}
    rows = {}
    seen = set()
    for f in sorted(glob.glob(os.path.join(jd, "*.verdicts.jsonl"))):
        for l in open(f):
            if not l.strip():
                continue
            v = json.loads(l)
            k = key.get(v["prompt"])
            if not k or v["label"] not in k["labels"] or (v["prompt"], v["label"]) in seen:
                continue
            seen.add((v["prompt"], v["label"]))
            cfg = k["labels"][v["label"]]
            group = samples[k["sample"]].get("situation", "all")
            for g in ("all", group) if group != "all" else ("all",):
                d = rows.setdefault((cfg, g), {"n": 0, "score": 0, "ok": 0, "first": 0, "ranks": []})
                d["n"] += 1
                d["score"] += v["score"]
                d["ok"] += bool(v["acceptable"])
                d["first"] += v.get("rank") == 1
                d["ranks"].append(v.get("rank") or 0)
    out = []
    for (cfg, g), d in sorted(rows.items(), key=lambda x: (x[0][1] != "all", x[0][1], x[0][0])):
        out.append({"config": cfg, "group": g, "n": d["n"], "mean_score": d["score"] / d["n"], "acceptable": d["ok"], "ranked_first": d["first"], "mean_rank": statistics.mean(d["ranks"])})
    with open(os.path.join(jd, "summary.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("| config | group | judged | mean score | acceptable | ranked first | mean rank |\n|---|---|--:|--:|--:|--:|--:|")
    for r in out:
        print(f"| {r['config']} | {r['group']} | {r['n']} | {r['mean_score']:.2f} | {r['acceptable']}/{r['n']} | {r['ranked_first']} | {r['mean_rank']:.2f} |")



def cmd_patches(a):
    """Reorganize/internalize: what the mind's code accepts of each reply and what it would change."""
    recs = load_replays(a.dir)
    val = {o["id"]: o for o in map(json.loads, open(os.path.join(a.dir, "validated.jsonl")))}
    rows = {}
    for r in recs:
        if r["cls"] not in ("reorganize", "internalize") or r.get("error"):
            continue
        v = val.get(rkey(r))
        d = rows.setdefault((r["cls"], r["config"]), {"n": 0, "ok": 0, "cap": 0, "p": []})
        d["n"] += 1
        d["cap"] += r.get("finish") == "length"
        if v and v["usable"] and v.get("patch"):
            d["ok"] += 1
            d["p"].append(v["patch"])
    for k, o in val.items():
        if k.startswith("orig|") and o.get("patch"):
            d = rows.setdefault((o["cls"], "orig (journal)"), {"n": 0, "ok": 0, "cap": 0, "p": []})
            d["n"] += 1
            d["ok"] += 1
            d["p"].append(o["patch"])
    m = lambda xs: statistics.mean(xs) if xs else 0
    out = []
    for (cls, cfg), d in sorted(rows.items()):
        p = d["p"]
        row = {"cls": cls, "config": cfg, "replies": d["n"], "accepted": d["ok"], "hit_cap": d["cap"],
               "merges": m([x["merges"] for x in p]), "merges_effective": m([x["merges_effective"] for x in p]), "refused_merges": m([x["refused_merges"] for x in p]),
               "retract": m([x["retract"] for x in p]), "retract_matched": m([x["retract_matched"] for x in p]),
               "edges": m([x["edges"] for x in p]), "edges_reasserted": m([x["edges_reasserted"] for x in p]), "nodes": m([x["nodes"] for x in p]),
               "created": m([x["created"] for x in p]), "stranger_people": sum(len(x["stranger_people"]) for x in p), "skipped": m([x["skipped"] for x in p]),
               "remember": m([x["remember"] for x in p]), "because_kept_share": (sum(x["because_kept"] for x in p) / max(1, sum(x["because_given"] for x in p))),
               "concepts": (m([x.get("concepts_before", 0) for x in p]), m([x.get("concepts_after", 0) for x in p])),
               "edges_before_after": (m([x.get("edges_before", 0) for x in p]), m([x.get("edges_after", 0) for x in p]))}
        out.append(row)
    json.dump(out, open(os.path.join(a.dir, "patches.json"), "w"), indent=1)
    print("| class | config | accepted | hit cap | merges (effective, refused) | retracts (matching an edge) | edges (re-asserted) | nodes | new concepts | concepts before→after | links before→after | strangers | memories | because kept |")
    print("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in out:
        print(f"| {r['cls']} | {r['config']} | {r['accepted']}/{r['replies']} | {r['hit_cap']} | {r['merges']:.1f} ({r['merges_effective']:.1f}, {r['refused_merges']:.1f}) | {r['retract']:.1f} ({r['retract_matched']:.1f}) | {r['edges']:.1f} ({r['edges_reasserted']:.1f}) | {r['nodes']:.1f} | {r['created']:.1f} | {r['concepts'][0]:.0f}→{r['concepts'][1]:.0f} | {r['edges_before_after'][0]:.0f}→{r['edges_before_after'][1]:.0f} | {r['stranger_people']} | {r['remember']:.1f} | {100 * r['because_kept_share']:.0f}% |")



def cmd_ids(a):
    """How replies write experience ids in `remember[].exp` and `edges[].because`: memory.rs
    patch_from reads them with as_u64, so a string ("392903", "215713-216671") is dropped."""
    out = {}
    for r in load_replays(a.dir):
        if r.get("error") or r["cls"] not in ("person_consolidate", "animal_consolidate", "internalize", "reorganize"):
            continue
        txt = r.get("reply") or ""
        try:
            v = json.loads(txt.strip())
        except Exception:
            try:
                v = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            except Exception:
                continue
        if not isinstance(v, dict):
            continue
        c = out.setdefault((r["cls"], r["config"]), {"replies": 0, "mem": 0, "mem_dropped": 0, "because": 0, "because_dropped": 0})
        c["replies"] += 1
        for m in v.get("remember") or []:
            if isinstance(m, dict):
                c["mem"] += 1
                c["mem_dropped"] += not isinstance(m.get("exp"), int)
        for e in v.get("edges") or []:
            for b in (e.get("because") or []) if isinstance(e, dict) and isinstance(e.get("because"), list) else []:
                c["because"] += 1
                c["because_dropped"] += not isinstance(b, int)
    print("| class | config | replies | memories | not an integer id | because ids | not an integer id |\n|---|---|--:|--:|--:|--:|--:|")
    for (cls, cfg), c in sorted(out.items()):
        print(f"| {cls} | {cfg} | {c['replies']} | {c['mem']} | {100 * c['mem_dropped'] / max(1, c['mem']):.0f}% | {c['because']} | {100 * c['because_dropped'] / max(1, c['because']):.0f}% |")



def cmd_nights(a):
    """Sleep-aligned reorganization, simulated on real consolidation timelines: each game night
    (20:00–06:00; 12 real minutes a day), a person whose integrations since their last
    reorganization meet the rule reorganizes once. The clock is calibrated from the first think
    that lists "Dawn of day N" (06:00 of day N). `--lod` thins integrations to one per 15 real
    minutes, like LIVING_LOD off stage (LIVING_LOD_CONSOLIDATE_S 900 s)."""
    import re
    rows = []
    for run in a.runs:
        es = sorted(entries(run), key=lambda e: e["at_ms"])
        t0 = es[0]["at_ms"]
        first = {}
        for e in es:
            if classify(e) == "person_think":
                m = re.search(r"Dawn of day (\d+)", why_section(e["request"]["messages"][1]["content"]))
                if m:
                    first.setdefault(int(m.group(1)), e["at_ms"])
        off = max(n * 1440 + 360 - 120 * (ms - t0) / 60000 for n, ms in first.items())
        g = lambda ms: off + 120 * (ms - t0) / 60000
        people = sorted({e["actor"] for e in es if classify(e) == "person_think"})
        cons = {}
        reorg_today = {}
        for e in es:
            c = classify(e)
            if c == "person_consolidate":
                cons.setdefault(e["actor"], []).append(e["at_ms"])
            elif c == "reorganize":
                reorg_today.setdefault(e["actor"], []).append(e["at_ms"])
        nights = range(int(g(t0) // 1440) + 1, int(g(es[-1]["at_ms"]) // 1440))
        for rule in a.rules:
            need, gap_min = {"2": (2, 0), "6": (6, 0), "2+20min": (2, 20)}[rule]
            per_night = []
            for lod in (False, True):
                counts = []
                state = {p: {"last": None, "since": 0, "i": 0, "last_int": None} for p in people}
                for n in nights:
                    dusk = n * 1440 + 20 * 60  # 20:00 of day n, game minutes
                    due = 0
                    for p in people:
                        st, xs = state[p], cons.get(p, [])
                        while st["i"] < len(xs) and g(xs[st["i"]]) < dusk:
                            t = xs[st["i"]]
                            if not lod or st["last_int"] is None or t - st["last_int"] >= 900_000:
                                st["since"] += 1
                                st["last_int"] = t
                            st["i"] += 1
                        long_enough = st["last"] is None or (dusk - st["last"]) / 120 >= gap_min
                        if st["since"] >= need and long_enough:
                            due += 1
                            st["since"], st["last"] = 0, dusk
                    counts.append(due)
                per_night.append(counts)
            rows.append({"run": run, "rule": rule, "people": len(people), "nights": len(nights),
                         "due_per_night_mean": statistics.mean(per_night[0]), "due_per_night_max": max(per_night[0]),
                         "lod_due_per_night_mean": statistics.mean(per_night[1]), "lod_due_per_night_max": max(per_night[1]),
                         "today_per_game_day": sum(len(v) for v in reorg_today.values()) / max(1, len(nights))})
    json.dump(rows, open(os.path.join(a.dir, "nights.json"), "w"), indent=1)
    print("| run | rule | people | nights | due per night (mean / max) | off stage, LOD (mean / max) | today, per game day |\n|---|---|--:|--:|--:|--:|--:|")
    for r in rows:
        print(f"| {r['run']} | ≥{r['rule']} integrations | {r['people']} | {r['nights']} | {r['due_per_night_mean']:.1f} / {r['due_per_night_max']} | {r['lod_due_per_night_mean']:.1f} / {r['lod_due_per_night_max']} | {r['today_per_game_day']:.1f} |")



def cmd_planning(a):
    """€ per person-hour for planning (think + compile) on and off stage, for every pair of
    configs measured in `report.json` (first call, caching as measured, retries included), with
    the latency of one decision (think p50 + compile p50)."""
    rep = json.load(open(os.path.join(a.dir, "report.json")))
    t = {(r["cls"], r["config"]): r for r in rep["table"]}

    def spend(cls, cfg):
        r = t[(cls, cfg)]
        p = r["usable"] or 0.0
        return r["eur_1"] * sum((1 - p) ** k for k in range(ATTEMPTS[cls]))

    thinks = [c for (cls, c) in t if cls == "person_think"]
    compiles = [c for (cls, c) in t if cls == "person_compile"]
    rows = []
    for th in thinks:
        for co in compiles:
            per = {sc: 60 * (RATES_PERSON[sc]["person_think"] * spend("person_think", th) + RATES_PERSON[sc]["person_compile"] * spend("person_compile", co)) for sc in ("on", "off")}
            rows.append({"think": th, "compile": co, "on": per["on"], "off": per["off"], "p50_s": t[("person_think", th)]["p50_s"] + t[("person_compile", co)]["p50_s"]})
    json.dump(rows, open(os.path.join(a.dir, "planning.json"), "w"), indent=1)
    print("| think | compile | € per person-hour on stage | off stage | decision latency (p50 think + p50 compile) |\n|---|---|--:|--:|--:|")
    for r in sorted(rows, key=lambda r: r["on"]):
        print(f"| {r['think']} | {r['compile']} | €{r['on']:.3f} | €{r['off']:.3f} | {r['p50_s']:.1f} s |")


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
    recs = load_replays(a.dir)
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
        f = BATCH_DISCOUNT if r.get("mode") == "batch" else 1
        c = cost_eur(r["model"], u)
        c = None if c is None else c * f
        (d["c1"] if r["run_n"] == 1 else d["c2"]).append(c)
        cold = cost_eur(r["model"], u, 0)
        d["cold"].append(None if cold is None else cold * f)
        d["prompt"].append(u.get("prompt_tokens"))
        (d["cached1"] if r["run_n"] == 1 else d["cached2"]).append(cached / max(1, u.get("prompt_tokens", 1)))
        d["out"].append(u.get("completion_tokens"))
        d["reason"].append((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        d["tot"].append(r["total_s"])
        d["ttft"].append(r["first_token_s"])
        d["ttxt"].append(r["first_text_s"])
        v = val.get(rkey(r)) or val.get(str(i))
        if v:
            d["usable"].append(v["usable"])
            if v["graph"] in ("ok",):
                d["warn"].append(v["warnings"])
            d["graph"].append(v["graph"])
    mean = lambda xs: statistics.mean([x for x in xs if x is not None]) if [x for x in xs if x is not None] else None
    table = []
    for (cls, cfg), d in sorted(rows.items(), key=lambda x: (CLASSES.index(x[0][0]), list(CONFIGS).index(base_config(x[0][1])), x[0][1])):
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
    recs = load_replays(a.dir)
    tot, toks = 0.0, [0, 0, 0]
    by = {}
    for r in recs:
        u = r.get("usage")
        if not u:
            continue
        c = (cost_eur(r["model"], u) or 0) * (BATCH_DISCOUNT if r.get("mode") == "batch" else 1)
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
    p.add_argument("--once", action="store_true", help="one call per sample and config instead of two")
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
    s2 = sub.add_parser("sample2")
    s2.add_argument("--runs", nargs="+", required=True)
    s2.add_argument("--per-situation", type=int, default=8)
    s2.add_argument("--reorganize", type=int, default=24)
    s2.add_argument("--reorganize-pool", type=int, default=176, help="more reorganizations for the batch turnaround job only")
    s2.add_argument("--internalize", type=int, default=12)
    s2.add_argument("--internalize-journal", default=os.path.join(ROOT, ".local/living/verify/knowledge-pmem-real-132616/journal/verify-knowledge-pmem-real-132616-glm-flash-direct/Wren.jsonl"))
    s2.add_argument("--exclude", default=os.path.join(OUT, "20261109/samples.jsonl"), help="part 1 samples, not drawn again")
    s2.add_argument("--after", type=float, default=0.5)
    s2.add_argument("--seed", type=int, default=20261110)
    ch = sub.add_parser("chain")
    j = sub.add_parser("judge")
    j.add_argument("--cls", required=True)
    j.add_argument("--configs", nargs="+", required=True)
    j.add_argument("--tag", default="")
    j.add_argument("--chunk", type=int, default=4, help="prompts per judge file")
    j.add_argument("--seed", type=int, default=11)
    vd = sub.add_parser("verdicts")
    vd.add_argument("--tag", required=True)
    pt = sub.add_parser("patches")
    ids = sub.add_parser("ids")
    pl = sub.add_parser("planning")
    nt = sub.add_parser("nights")
    nt.add_argument("--runs", nargs="+", required=True)
    nt.add_argument("--rules", nargs="+", default=["2", "6", "2+20min"])
    b = sub.add_parser("batch")
    b.add_argument("--cls", required=True)
    b.add_argument("--configs", nargs="+", required=True)
    b.add_argument("--pool", action="store_true", help="include the batch-only reorganizations")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--poll", type=float, default=5.0)
    b.add_argument("--timeout-hours", type=int, default=1)
    sub.add_parser("report")
    sub.add_parser("hourly")
    sub.add_parser("spend")
    for x in (s, p, sub.choices["validate"], q, sub.choices["report"], sub.choices["hourly"], sub.choices["spend"], s2, ch, b, j, vd, pt, ids, nt, pl):
        x.add_argument("--dir", default=os.path.join(OUT, "20261109"))
    a = ap.parse_args()
    {"sample": cmd_sample, "sample2": cmd_sample2, "chain": cmd_chain, "batch": cmd_batch, "patches": cmd_patches, "ids": cmd_ids, "nights": cmd_nights, "planning": cmd_planning, "judge": cmd_judge, "verdicts": cmd_verdicts, "rates": cmd_rates, "replay": cmd_replay, "validate": cmd_validate, "pairs": cmd_pairs, "report": cmd_report, "hourly": cmd_hourly, "spend": cmd_spend}[a.cmd](a)


if __name__ == "__main__":
    main()
