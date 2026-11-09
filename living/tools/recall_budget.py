#!/usr/bin/env python3
"""How much recalled Neo4j context goes into each prompt, and how much of it the reply uses
(docs/MIND_HARNESS.md, item 5).

  living/tools/recall_budget.py measure --runs RUN... [--journal DIR] [--per 400] [--out DIR]
  living/tools/recall_budget.py budget  --out DIR [--tokens 300 500 800]

`measure` reads mind journals (`.local/living/journal/<run>/*.jsonl`), takes up to `--per`
first-attempt requests per purpose (think, deliberate, consolidate) with a recall section,
and records for each: the prompt's size, the recall sections' size ("# What comes to mind",
"# Memories this brings back") and, per recalled line in prompt order (the order of
activation: most activated first), whether the reply uses it. A line is used when one of its
distinctive terms (a concept key in parentheses, a name, a word of 6+ letters not in the
system prompt's vocabulary) appears in the reply. This is a proxy for relevance, not a
judgment of it.

`budget` replays the measured lines under token budgets (lines kept in activation order
until the budget is spent, as `recall_for` does with LIVING_RECALL_TOKENS) and reports the
tokens saved and the share of used lines kept. Tokens are estimated as characters / 3.6
(the ratio of GLM Flash's prompt_tokens to prompt characters in these journals is measured
and printed).
"""
import argparse
import glob
import gzip
import math
import sys
import json
import os
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = ("# What comes to mind", "# Memories this brings back")
STOP = set("""about above after again against because before being below between both could
doing during further having itself might myself other ought should their there these those
through under until where which while would yourself people person someone something""".split())


def sections(user):
    """The recall sections of a user message: {header: [lines]}."""
    out = {}
    for head in SECTIONS:
        i = user.find(head)
        if i < 0:
            continue
        rest = user[i:].split("\n", 1)[1] if "\n" in user[i:] else ""
        lines = []
        for l in rest.split("\n"):
            if l.startswith("#") or (not l.strip() and lines):
                break
            if l.strip():
                lines.append(l.strip())
        out[head] = lines
    return out


SITUATION = ("# Why you are thinking now", "# What you perceive right now", "# What you decided", "# New experiences to integrate")


def situation(user):
    """What the moment is about: why the mind is thinking, what it perceives and decided, or
    the experiences it integrates (each section's first 1,500 characters)."""
    out = []
    for head in SITUATION:
        i = user.find(head)
        if i >= 0:
            out.append(user[i:].split("\n# ")[0][:1500])
    return "\n".join(out)


def terms(line):
    keys = re.findall(r"\(([a-z]+:[^)\s]+)\)", line) + re.findall(r"\b(?:person|place|kind|know|idea|stance):[\w-]+", line)
    names = re.findall(r"\b[A-Z][a-z]{2,}\b", line)
    words = [w.lower() for w in re.findall(r"[A-Za-z]{6,}", line) if w.lower() not in STOP]
    t = set()
    for k in keys:
        t.add(k.lower())
        t.add(k.split(":", 1)[1].replace("_", " ").lower())
    t.update(n.lower() for n in names if n not in ("You", "Your", "The", "When", "Day"))
    t.update(words)
    return t


def ends(line):
    """The two endpoints of a rendered fact (`A (key) [...] —REL {...}→ B (key) [...]`)."""
    m = re.match(r"- (.+?) \(([^)]+)\).*?—([A-Z_]+).*?→ (.+?)(?: \(([^)]+)\))?(?: \[|$)", line)
    if not m:
        return None
    return {m[1].lower(), m[2].lower()}, {m[4].lower(), (m[5] or m[4]).lower()}, m[3].lower()


def used(line, reply_l, common, others):
    """A line is used when the reply names something only this line holds (a term no other
    recalled line and no system-prompt word has), or names both of its endpoints."""
    unique = {x for x in terms(line) - common - others if len(x) >= 4}
    if any(x in reply_l for x in unique):
        return True
    e = ends(line)
    if e:
        a, b, _ = e
        named = lambda side: any(x in reply_l for x in side if x not in ("you", "self") and len(x) >= 3)
        return named(a) and named(b)
    return False


def cmd_measure(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    ratio = []
    random.seed(7)
    for run in a.runs:
        files = sorted(glob.glob(os.path.join(a.journal, run, "*.jsonl")) + glob.glob(os.path.join(a.journal, run, "*.jsonl.gz")))
        for f in files:
            for line in (gzip.open(f, "rt") if f.endswith(".gz") else open(f)):
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("purpose") not in ("think", "deliberate", "consolidate") or e.get("error") or not e.get("reply"):
                    continue
                msgs = e["request"]["messages"]
                if len(msgs) != 2:
                    continue  # retries carry the rejected reply
                user = msgs[1]["content"]
                secs = sections(user)
                if not secs:
                    continue
                chars = sum(len(m["content"]) for m in msgs)
                if e.get("prompt_tokens"):
                    ratio.append(chars / e["prompt_tokens"])
                rows.append({"run": run, "actor": e["actor"], "purpose": e["purpose"], "at_ms": e["at_ms"], "prompt_chars": chars, "situation": situation(user),
                             "prompt_tokens": e.get("prompt_tokens"), "system": msgs[0]["content"], "sections": secs, "reply": e["reply"]})
    by = {}
    for r in rows:
        by.setdefault(r["purpose"], []).append(r)
    kept = []
    for p, rs in by.items():
        random.shuffle(rs)
        kept.extend(rs[: a.per])
    measured = []
    for r in kept:
        common = set(re.findall(r"[a-z]{3,}", r["system"].lower()))
        reply_l = r["reply"].lower()
        lines = []
        everything = [l for ls in r["sections"].values() for l in ls]
        tset = [terms(l) for l in everything]
        k = 0
        for head, ls in r["sections"].items():
            for i, l in enumerate(ls):
                others = set().union(*[t for j, t in enumerate(tset) if j != k]) if len(tset) > 1 else set()
                lines.append({"section": "mind" if head == SECTIONS[0] else "memories", "rank": i, "chars": len(l) + 3, "used": used(l, reply_l, common, others), "text": l})
                k += 1
        measured.append({k: r[k] for k in ("run", "actor", "purpose", "at_ms", "prompt_chars", "prompt_tokens", "situation")} | {"lines": lines})
    (out / "recall.jsonl").write_text("".join(json.dumps(m) + "\n" for m in measured))
    cpt = sorted(ratio)[len(ratio) // 2] if ratio else 3.6
    report = {"chars_per_token_median": round(cpt, 2), "requests": len(measured), "by_purpose": {}}
    for p in sorted({m["purpose"] for m in measured}):
        ms = [m for m in measured if m["purpose"] == p]
        rc = [sum(l["chars"] for l in m["lines"]) for m in ms]
        n = [len(m["lines"]) for m in ms]
        u = [sum(l["used"] for l in m["lines"]) for m in ms]
        share = [sum(l["chars"] for l in m["lines"]) / m["prompt_chars"] for m in ms]
        rank_use = {}
        for m in ms:
            for l in m["lines"]:
                if l["section"] == "mind":
                    b = min(l["rank"] // 4, 7)
                    rank_use.setdefault(b, [0, 0])
                    rank_use[b][0] += l["used"]
                    rank_use[b][1] += 1
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
        report["by_purpose"][p] = {
            "requests": len(ms), "recall_tokens_median": round(med(rc) / cpt), "recall_tokens_p90": round(sorted(rc)[int(len(rc) * 0.9)] / cpt) if rc else 0,
            "recall_share_of_prompt_median": round(med(share), 3), "lines_median": med(n), "used_lines_median": med(u),
            "used_share": round(sum(u) / max(1, sum(n)), 3),
            "use_by_rank_of_4": {f"{b * 4}-{b * 4 + 3}": round(x[0] / x[1], 3) for b, x in sorted(rank_use.items())},
        }
    (out / "measure.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def cmd_budget(a):
    out = Path(a.out)
    measured = [json.loads(l) for l in open(out / "recall.jsonl")]
    cpt = json.loads((out / "measure.json").read_text())["chars_per_token_median"]
    res = {}
    for p in sorted({m["purpose"] for m in measured}):
        ms = [m for m in measured if m["purpose"] == p]
        res[p] = {}
        for t in a.tokens:
            saved, kept_used, all_used, prompt = 0, 0, 0, 0
            for m in ms:
                budget = t * cpt
                spent = 0
                # Mind lines first in activation order, then memories (as rendered).
                for l in sorted(m["lines"], key=lambda l: (l["section"] != "mind", l["rank"])):
                    all_used += l["used"]
                    if spent + l["chars"] <= budget:
                        spent += l["chars"]
                        kept_used += l["used"]
                    else:
                        saved += l["chars"]
                prompt += m["prompt_chars"]
            res[p][t] = {"tokens_saved_per_request": round(saved / cpt / max(1, len(ms))), "prompt_share_saved": round(saved / max(1, prompt), 3), "used_lines_kept": round(kept_used / max(1, all_used), 3)}
    (out / "budget.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


def embed_all(texts, key, model="mistral-embed"):
    """Embeddings for texts (batches of 64; `POST /v1/embeddings`). Returns vectors and tokens."""
    import urllib.request
    vecs, tokens = [], 0
    for i in range(0, len(texts), 64):
        body = json.dumps({"model": model, "input": [t[:6000] for t in texts[i:i + 64]]}).encode()
        req = urllib.request.Request("https://api.mistral.ai/v1/embeddings", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    v = json.loads(r.read())
                break
            except Exception as e:  # 429s back off
                import time
                time.sleep(2 ** attempt)
        else:
            raise SystemExit(f"embeddings failed at {i}")
        vecs.extend(d["embedding"] for d in v["data"])
        tokens += v["usage"]["prompt_tokens"]
    return vecs, tokens


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def cmd_embed(a):
    """Does similarity to the situation (mistral-embed) predict use better than activation?"""
    out = Path(a.out)
    key = os.environ.get("MISTRAL_API_KEY") or sys.exit("MISTRAL_API_KEY not set")
    measured = [json.loads(l) for l in open(out / "recall.jsonl")]
    if a.limit:
        measured = [m for p in sorted({m["purpose"] for m in measured}) for m in [x for x in measured if x["purpose"] == p][: a.limit]]
    texts = sorted({m["situation"] for m in measured} | {l["text"] for m in measured for l in m["lines"]})
    cache = out / "embeddings.json"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    todo = [t for t in texts if t not in known]
    vecs, tokens = embed_all(todo, key) if todo else ([], 0)
    known.update(dict(zip(todo, vecs)))
    cache.write_text(json.dumps(known))
    cos = lambda u, v: sum(x * y for x, y in zip(u, v)) / (math.sqrt(sum(x * x for x in u)) * math.sqrt(sum(y * y for y in v)) or 1)
    cpt = json.loads((out / "measure.json").read_text())["chars_per_token_median"]
    res = {"embedding_tokens": tokens, "usd": round(tokens * 0.1 / 1e6, 4), "by_purpose": {}}
    for p in sorted({m["purpose"] for m in measured}):
        ms = [m for m in measured if m["purpose"] == p]
        a_act, a_emb, a_mix = [], [], []
        for m in ms:
            sit = known[m["situation"]]
            n = len(m["lines"])
            for l in m["lines"]:
                l["sim"] = cos(known[l["text"]], sit)
                l["act"] = 1 - (l["rank"] + (0 if l["section"] == "mind" else 100)) / (n + 100)
            labels = [l["used"] for l in m["lines"]]
            for store, key_ in ((a_act, "act"), (a_emb, "sim")):
                x = auc([l[key_] for l in m["lines"]], labels)
                if x is not None:
                    store.append(x)
            sims = sorted(l["sim"] for l in m["lines"])
            for l in m["lines"]:
                l["mix"] = l["act"] + (sims.index(l["sim"]) / max(1, n - 1))
            x = auc([l["mix"] for l in m["lines"]], labels)
            if x is not None:
                a_mix.append(x)
        mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
        row = {"prompts": len(ms), "auc_activation": mean(a_act), "auc_embedding": mean(a_emb), "auc_both": mean(a_mix), "budgets": {}}
        for t in a.tokens:
            for order in ("act", "sim", "mix"):
                kept_used, all_used, saved = 0, 0, 0
                for m in ms:
                    spent = 0
                    for l in sorted(m["lines"], key=lambda l: -l[order]):
                        all_used += l["used"]
                        if spent + l["chars"] <= t * cpt:
                            spent += l["chars"]
                            kept_used += l["used"]
                        else:
                            saved += l["chars"]
                row["budgets"].setdefault(str(t), {})[order] = {"used_lines_kept": round(kept_used / max(1, all_used), 3), "tokens_saved_per_request": round(saved / cpt / len(ms))}
        res["by_purpose"][p] = row
    (out / "embed.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


def budgeted(user, tokens, cpt=3.0):
    """The user message as the mind now writes it: recall lines without a `rel` property that
    repeats the type, kept in order while they fit `tokens` (memory::render and
    recall::within_tokens)."""
    left = tokens * cpt
    for head in SECTIONS:
        i = user.find(head)
        if i < 0:
            continue
        start = user.index("\n", i) + 1
        end = start
        lines = []
        rest = user[start:].split("\n")
        for l in rest:
            if l.startswith("#") or (not l.strip() and lines):
                break
            lines.append(l)
            end += len(l) + 1
        kept = []
        for l in lines:
            m = re.search(r"—([A-Z_]+)", l)
            if m:
                l = re.sub(r"(\{[^}]*?)(?:, )?rel: " + m[1] + r"(?=[,}])", r"\1", l).replace("{, ", "{").replace(" {}", "")
            if l.strip() and len(l) + 3 <= left:
                left -= len(l) + 3
                kept.append(l)
        user = user[:start] + "\n".join(kept) + ("\n" if kept else "") + user[end:]
    return user


def cmd_replay(a):
    """Replay real prompts as recorded and as budgeted on one model; write blind pairs."""
    import urllib.request
    out = Path(a.out)
    key = os.environ.get("MISTRAL_API_KEY") or sys.exit("MISTRAL_API_KEY not set")
    random.seed(11)
    picked = []
    for run in a.runs:
        for f in sorted(glob.glob(os.path.join(a.journal, run, "*.jsonl.gz"))):
            for line in gzip.open(f, "rt"):
                e = json.loads(line)
                if e.get("purpose") != a.purpose or e.get("error") or len(e["request"]["messages"]) != 2:
                    continue
                u = e["request"]["messages"][1]["content"]
                if "# What comes to mind" in u and len(sections(u).get(SECTIONS[0], [])) >= 15:
                    picked.append(e)
    random.shuffle(picked)
    seen, chosen = set(), []
    for e in picked:
        if e["actor"] not in seen:
            seen.add(e["actor"])
            chosen.append(e)
        if len(chosen) >= a.n:
            break
    pairs, usage = [], {"prompt": 0, "completion": 0}
    for e in chosen:
        sysm, user = e["request"]["messages"][0]["content"], e["request"]["messages"][1]["content"]
        variants = {"full": user, "budget": budgeted(user, a.tokens)}
        replies = {}
        for name, u in variants.items():
            body = {"model": "zai-glm-5-3-flash", "messages": [{"role": "system", "content": sysm}, {"role": "user", "content": u}], "max_tokens": 8000,
                    "response_format": {"type": "json_object"}, "reasoning_effort": a.effort}
            req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                v = json.loads(r.read())
            c = v["choices"][0]["message"]["content"]
            replies[name] = c if isinstance(c, str) else "".join(p.get("text", "") for p in c if p.get("type") == "text")
            usage["prompt"] += v["usage"]["prompt_tokens"]
            usage["completion"] += v["usage"]["completion_tokens"]
            replies[name + "_prompt_tokens"] = v["usage"]["prompt_tokens"]
        flip = random.random() < 0.5
        pairs.append({"id": f"{e['actor']}-{e['at_ms']}", "user": user, "A": replies["budget" if flip else "full"], "B": replies["full" if flip else "budget"],
                      "key": {"A": "budget" if flip else "full", "B": "full" if flip else "budget"},
                      "prompt_tokens": {"full": replies["full_prompt_tokens"], "budget": replies["budget_prompt_tokens"]}})
    (out / f"replay-{a.purpose}.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pairs))
    # What a judge sees: the original prompt (full recall) and the two replies, unlabeled.
    (out / f"judge-{a.purpose}.md").write_text("".join(f"## Pair {p['id']}\n\n### Prompt\n\n{p['user']}\n\n### Reply A\n\n{p['A']}\n\n### Reply B\n\n{p['B']}\n\n" for p in pairs))
    eur = (usage["prompt"] * 0.1275 + usage["completion"] * 0.425) / 1e6
    print(json.dumps({"pairs": len(pairs), "usage": usage, "eur": round(eur, 4),
                      "prompt_tokens_saved_mean": round(sum(p["prompt_tokens"]["full"] - p["prompt_tokens"]["budget"] for p in pairs) / max(1, len(pairs)))}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("measure")
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--journal", default=str(ROOT / ".local/living/journal"))
    p.add_argument("--per", type=int, default=400)
    p.add_argument("--out", default=str(ROOT / ".local/living/recall-budget"))
    p.set_defaults(f=cmd_measure)
    p = sub.add_parser("budget")
    p.add_argument("--out", default=str(ROOT / ".local/living/recall-budget"))
    p.add_argument("--tokens", nargs="+", type=int, default=[300, 500, 800, 1200])
    p.set_defaults(f=cmd_budget)
    p = sub.add_parser("replay")
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--journal", default=str(ROOT / ".local/living/journal"))
    p.add_argument("--out", default=str(ROOT / ".local/living/recall-budget"))
    p.add_argument("--purpose", default="think")
    p.add_argument("--effort", default="low")
    p.add_argument("--tokens", type=int, default=900)
    p.add_argument("--n", type=int, default=10)
    p.set_defaults(f=cmd_replay)
    p = sub.add_parser("embed")
    p.add_argument("--out", default=str(ROOT / ".local/living/recall-budget"))
    p.add_argument("--tokens", nargs="+", type=int, default=[500, 800])
    p.add_argument("--limit", type=int, default=100, help="prompts per purpose")
    p.set_defaults(f=cmd_embed)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
