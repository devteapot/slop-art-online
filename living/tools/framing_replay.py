#!/usr/bin/env python3
"""The think prompt's framing, replayed on recorded prompts (docs/FRAMING.md). Nothing here ships:
it rewrites recorded messages and sends them again; the mind service is untouched.

Arms (the same recorded think messages, the same model and request body):
  T   today's framing, sent again (the noise floor against the recorded reply R).
  N1  neutral: the system sentence replaced (NEUTRAL_SYS) and the reason moved beside the scene
      under "# What just happened" (after "# What you perceive right now").
  N2  neutral, in place: the same system sentence, the section renamed "# What just happened"
      where it stood (first).

Subcommands:
  collect OUT  [--fs1e DIR] [--urgent ROOT ...] [--slept ROOT ...] --seed N
          the prompt set: fs1e's first-sight-only thinks, and a seeded sample of urgent reasons
          (attacked, body, offer) and lines said to the thinker (addressed), each with its
          recorded think call (exact messages, body, reply).
  ask     SET OUT --arm T|N1|N2 --cap USD [--root DIR]
          send each prompt's messages, rewritten for the arm, with its recorded body; keys from
          the run's models.json profile and DIR/.env; a hard dollar cap over everything in OUT.
  asks    SET ASKED...
          first-sight prompts: the share whose reply speaks to the newcomer, or means to.
  items   SET ASKED... OUT_DIR --seed N --judges K --double F
          blind judge items for the urgent prompts: one reply each, arm hidden, with a key.
  score   SET KEY LABELS...
          per arm and reason class: matters, addressed, harm; agreement on doubly judged items.
"""
import argparse, glob, json, os, random, re, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_quality as gq  # noqa: E402  (rows, resolve, cost, load_env, situation, reply_view)

OLD_SYS = "Start from why you are thinking now: that is what this moment of thought is about. Think about it as that person: what you make of it, and what you mean to do."
NEUTRAL_SYS = "What just happened is shown beside what you perceive. Think as that person about whatever matters to you now, which may or may not be what just happened, and decide what you mean to do."
WHY = "\n# Why you are thinking now\n"
JUST = "\n# What just happened\n"
FS = "For the first time you see "

ORDINARY = {
    "finished": r"^I finished my plan\.$",
    "quiet": r"^A quiet moment to take stock of how things are going\.$",
    "need": r"^You feel something: ",
}

CLASSES = {
    "attacked": r"attacking you|The fight with|shot you|struck you|is attacking|threatens you|threatened you",
    "body": r"^Your body:|You are starving|badly hurt|bleeding|You are freezing",
    "offer": r"offers you .* for |proposes an agreement",
    "addressed": r"said to you: “",
}


def why_of(text):
    if WHY not in text:
        return ""
    return text.split(WHY, 1)[1].split("\n\n", 1)[0]


def rewrite(messages, arm):
    """The recorded messages as arm `arm` would have sent them."""
    if arm in ("R", "T"):
        return messages
    out = []
    for m in messages:
        c = m["content"]
        if m["role"] == "system":
            if OLD_SYS not in c:
                raise ValueError("today's framing sentence not in the system prompt")
            c = c.replace(OLD_SYS, NEUTRAL_SYS)
        elif WHY in c:
            head, rest = c.split(WHY, 1)
            reason, _, after = rest.partition("\n\n")
            if arm == "N2":
                c = head + JUST + reason + "\n\n" + after
            else:  # N1: beside the scene
                body = head + "\n" + after.lstrip("\n")
                marker = "\n# What you perceive right now\n"
                if marker not in body:
                    raise ValueError("no scene section")
                pre, scene_rest = body.split(marker, 1)
                scene, nl, tail = scene_rest.partition("\n#")
                c = pre + marker + scene + "\n" + JUST.lstrip("\n").rstrip("\n") + "\n" + reason + "\n" + (nl + tail if nl else "")
        out.append({"role": m["role"], "content": c})
    return out


def think_entries(run):
    """Every recorded think call of a run, with its why-section."""
    for f in sorted(glob.glob(os.path.join(run, "journal", "*.jsonl"))):
        for e in gq.rows(f):
            if e.get("purpose") != "think" or e.get("error") or not e.get("request") or not e.get("reply"):
                continue
            msgs = gq.resolve(e, os.path.join(run, "journal"))
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            yield e, msgs, why_of(user)


def record(run, e, msgs, why, cls):
    return {"id": f"{Path(run).parent.name}/{Path(run).name}/{e['actor']}/{e['at_ms']}", "run": run, "actor": e["actor"], "class": cls,
            "reason": why, "messages": msgs, "body": {k: v for k, v in e["request"].items() if k != "messages"}, "model": e.get("model"),
            "profile": e.get("profile"), "reply": e.get("reply"),
            "cost_usd": gq.cost(e.get("model"), e.get("prompt_tokens"), e.get("completion_tokens"), e.get("cached_tokens"))}


def cmd_collect(a):
    rnd = random.Random(a.seed)
    out = []
    if a.fs1e:
        for run in sorted(glob.glob(os.path.join(a.fs1e, "*/"))):
            for e, msgs, why in think_entries(run.rstrip("/")):
                lines = [l for l in why.split("\n") if l.strip()]
                if lines and all(l.startswith(FS) for l in lines) and any("a stranger" in l for l in lines):
                    out.append(record(run.rstrip("/"), e, msgs, why, "first_sight"))
    pools = {k: [] for k in CLASSES}
    for root in a.urgent or []:
        for run in sorted(glob.glob(os.path.join(root, "*/"))):
            for e, msgs, why in think_entries(run.rstrip("/")):
                lines = why.split("\n")
                for k in ("attacked", "body", "offer"):
                    if any(re.search(CLASSES[k], l) for l in lines):
                        pools[k].append((run.rstrip("/"), e, msgs, why))
                        break
    for root in a.slept or []:
        for run in sorted(glob.glob(os.path.join(root, "*/"))):
            for e, msgs, why in think_entries(run.rstrip("/")):
                if any(re.search(CLASSES["addressed"], l) for l in why.split("\n")):
                    pools["addressed"].append((run.rstrip("/"), e, msgs, why))
    caps = {"attacked": a.n, "body": a.n, "offer": a.n, "addressed": a.n_addressed}
    for k, pool in pools.items():
        rnd.shuffle(pool)
        for run, e, msgs, why in pool[: caps[k]]:
            out.append(record(run, e, msgs, why, k))
        print(f"{k}: {min(len(pool), caps[k])} of {len(pool)}")
    print(f"first_sight: {sum(1 for r in out if r['class'] == 'first_sight')}")
    with open(a.out, "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")


def cmd_collect_ordinary(a):
    """Ordinary thinks: a seeded sample of prompts whose only reason is a finished plan, a quiet
    moment, or a felt need, each with what it was doing."""
    rnd = random.Random(a.seed)
    pools = {k: [] for k in ORDINARY}
    for root in a.roots:
        for run in sorted(glob.glob(os.path.join(root, "*/"))):
            for e, msgs, why in think_entries(run.rstrip("/")):
                lines = [l for l in why.split("\n") if l.strip()]
                if len(lines) != 1:
                    continue
                for k, pat in ORDINARY.items():
                    if re.search(pat, lines[0]):
                        pools[k].append((run.rstrip("/"), e, msgs, why))
    out = []
    for k, pool in pools.items():
        rnd.shuffle(pool)
        for run, e, msgs, why in pool[: a.n]:
            out.append(record(run, e, msgs, why, k))
        print(f"{k}: {min(len(pool), a.n)} of {len(pool)}")
    with open(a.out, "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")


def cmd_ask(a):
    env = gq.load_env(a.root)
    done = {r["id"]: r for r in gq.rows(a.out)} if Path(a.out).exists() else {}
    spent = sum((r.get("cost_usd") or 0) for r in done.values())
    profiles = {}
    with open(a.out, "a") as out:
        for p in gq.rows(a.set):
            if p["id"] in done:
                continue
            if spent >= a.cap:
                print(f"cap ${a.cap} reached (${spent:.4f}); stopping")
                break
            if p["run"] not in profiles:
                profiles[p["run"]] = json.loads(Path(p["run"], "models.json").read_text())["profiles"]
            prof = profiles[p["run"]][p["profile"]]
            key = os.environ.get(prof["key_env"]) or env.get(prof["key_env"])
            if not key:
                sys.exit(f"no key in {prof['key_env']}")
            body = dict(p["body"])
            body["messages"] = rewrite(p["messages"], a.arm)
            url = prof["base_url"].rstrip("/") + "/chat/completions"
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            rec = {"id": p["id"], "arm": a.arm, "model": body.get("model")}
            t0 = time.time()
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        v = json.loads(resp.read())
                    u = v.get("usage") or {}
                    msg = v["choices"][0]["message"]
                    content = msg.get("content")
                    if isinstance(content, list):
                        content = "".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
                    rec.update({"reply": content, "finish_reason": v["choices"][0].get("finish_reason"), "prompt_tokens": u.get("prompt_tokens"),
                                "completion_tokens": u.get("completion_tokens"), "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                                "latency_ms": int((time.time() - t0) * 1000), "error": None})
                    break
                except urllib.error.HTTPError as e:
                    rec.update({"error": f"HTTP {e.code}: {e.read()[:300]!r}"})
                    if e.code in (429, 500, 502, 503):
                        time.sleep(5 * (attempt + 1))
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    rec.update({"error": repr(e)[:300]})
                    time.sleep(5)
            rec["cost_usd"] = gq.cost(rec["model"], rec.get("prompt_tokens"), rec.get("completion_tokens"), rec.get("cached_tokens"))
            spent += rec["cost_usd"] or 0
            out.write(json.dumps(rec) + "\n")
            out.flush()
    print(f"{a.arm}: spent ${spent:.4f} in {a.out}")


ASK_INTENT = re.compile(r"(greet|hail|ask|welcome|hello|introduc|speak to|talk to|call to|word with).{0,60}(stranger|newcomer|newcomer|them|him|her|traveller)|(stranger|newcomer|traveller).{0,60}(greet|hail|ask|welcome|name|business|who)", re.I)


def parse(raw):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def to_of(say):
    if isinstance(say, dict):
        t = say.get("to")
        try:
            return int(str(t).lstrip("#")) if t not in (None, "") else None
        except ValueError:
            return t
    return None


def asks_of(raw, newcomer):
    v = parse(raw)
    say = v.get("say")
    text = say.get("text") if isinstance(say, dict) else (say or "")
    speaks = bool(text and str(text).strip()) and to_of(say) == newcomer
    intends = any(ASK_INTENT.search(str(x)) for x in (v.get("intend") or []))
    return speaks, speaks or intends


def cmd_asks(a):
    pts = [p for p in gq.rows(a.set) if p["class"] == "first_sight"]
    newcomer = {}
    for p in pts:
        if p["run"] not in newcomer:
            ev = list(gq.rows(os.path.join(p["run"], "events.jsonl")))
            newcomer[p["run"]] = next(e["newcomer_join"]["id"] for e in ev if "newcomer_join" in e)
    arms = {"R": {p["id"]: p["reply"] for p in pts}}
    for f in a.asked:
        for r in gq.rows(f):
            if r.get("reply"):
                arms.setdefault(r["arm"], {})[r["id"]] = r["reply"]
    res = {}
    for arm, rep in arms.items():
        ids = [p for p in pts if p["id"] in rep]
        sp = sum(asks_of(rep[p["id"]], newcomer[p["run"]])[0] for p in ids)
        me = sum(asks_of(rep[p["id"]], newcomer[p["run"]])[1] for p in ids)
        res[arm] = {"n": len(ids), "speaks_to_it": sp, "speaks_or_means_to": me}
        print(f"{arm}: n {len(ids)}; speaks to it {sp} ({sp / max(1, len(ids)):.0%}); speaks or means to {me} ({me / max(1, len(ids)):.0%})")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1) + "\n")


def cmd_items(a):
    rnd = random.Random(a.seed)
    pts = {p["id"]: p for p in gq.rows(a.set) if p["class"] != "first_sight"}
    replies = [(pid, "R", p["reply"]) for pid, p in pts.items()]
    for f in a.asked:
        for r in gq.rows(f):
            if r["id"] in pts and r.get("reply"):
                replies.append((r["id"], r["arm"], r["reply"]))
    rnd.shuffle(replies)
    items, key = [], []
    for i, (pid, arm, raw) in enumerate(replies):
        p = pts[pid]
        user = next(m["content"] for m in p["messages"] if m["role"] == "user")
        # The situation in one neutral form for every arm: the reason as what just happened.
        sit = gq.situation(user).replace("# Why you are thinking now", "# What just happened")
        doing = user.split("\n# What you were doing\n", 1)[1].split("\n#", 1)[0].strip() if "\n# What you were doing\n" in user else ""
        iid = f"f{i:04d}"
        items.append({"item": iid, "situation": sit, "what_just_happened": p["reason"], "what_you_were_doing": doing[:600], "reply": gq.reply_view(raw)})
        key.append({"item": iid, "id": pid, "arm": arm, "class": p["class"]})
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    per = [[] for _ in range(a.judges)]
    for k, it in enumerate(items):
        per[k % a.judges].append(it)
    dbl = rnd.sample(items, int(len(items) * a.double))
    for k, it in enumerate(dbl):
        per[(items.index(it) % a.judges + 1 + k % (a.judges - 1)) % a.judges].append(it)
    for j, its in enumerate(per):
        rnd.shuffle(its)
        with open(out / f"judge-{j + 1}.jsonl", "w") as f:
            for it in its:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with open(out / "key.jsonl", "w") as f:
        for k in key:
            f.write(json.dumps(k) + "\n")
    print(f"{len(items)} items, {len(dbl)} doubly judged, {a.judges} judges → {out}")


def cmd_score(a):
    key = {k["item"]: k for k in gq.rows(a.key)}
    labels = {}
    for f in a.labels:
        for l in gq.rows(f):
            labels.setdefault(l["item"], []).append(l)
    agree = {"matters": [0, 0], "addressed": [0, 0], "harm": [0, 0], "abandons": [0, 0]}
    cell = {}
    for iid, ls in labels.items():
        k = key.get(iid)
        if not k:
            continue
        if len(ls) > 1:
            for f in agree:
                agree[f][1] += 1
                agree[f][0] += ls[0].get(f) == ls[1].get(f)
        l = ls[0]
        c = cell.setdefault((k["class"], k["arm"]), {"n": 0, "matters": 0, "addressed_when_matters": 0, "matters_n": 0, "harm": 0, "abandons_with_reason": 0, "abandons_without_reason": 0})
        c["n"] += 1
        c["matters"] += l.get("matters") is True
        if l.get("matters") is True:
            c["matters_n"] += 1
            c["addressed_when_matters"] += l.get("addressed") == "yes"
        c["harm"] += l.get("harm") is True
        c["abandons_with_reason"] += l.get("abandons") == "with reason"
        c["abandons_without_reason"] += l.get("abandons") == "without reason"
    print("| class | arm | n | matters | addressed when it matters | harm | abandons the plan, with reason | without reason |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")
    for (cls, arm), c in sorted(cell.items()):
        print(f"| {cls} | {arm} | {c['n']} | {c['matters']} | {c['addressed_when_matters']} of {c['matters_n']} | {c['harm']} | {c['abandons_with_reason']} | {c['abandons_without_reason']} |")
    for f, (s, n) in agree.items():
        print(f"agreement {f}: {s} of {n}")
    if a.json:
        Path(a.json).write_text(json.dumps({"cells": {f"{k[0]}/{k[1]}": v for k, v in cell.items()}, "agreement": agree}, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("collect"); p.add_argument("out"); p.add_argument("--fs1e"); p.add_argument("--urgent", nargs="*"); p.add_argument("--slept", nargs="*")
    p.add_argument("--seed", type=int, default=1); p.add_argument("--n", type=int, default=15); p.add_argument("--n-addressed", type=int, default=12); p.set_defaults(f=cmd_collect)
    p = sub.add_parser("collect-ordinary"); p.add_argument("out"); p.add_argument("roots", nargs="+"); p.add_argument("--seed", type=int, default=1); p.add_argument("--n", type=int, default=20); p.set_defaults(f=cmd_collect_ordinary)
    p = sub.add_parser("ask"); p.add_argument("set"); p.add_argument("out"); p.add_argument("--arm", required=True, choices=["T", "N1", "N2"])
    p.add_argument("--cap", type=float, required=True); p.add_argument("--root", default="."); p.set_defaults(f=cmd_ask)
    p = sub.add_parser("asks"); p.add_argument("set"); p.add_argument("asked", nargs="*"); p.add_argument("--json"); p.set_defaults(f=cmd_asks)
    p = sub.add_parser("items"); p.add_argument("set"); p.add_argument("asked", nargs="*"); p.add_argument("out_dir"); p.add_argument("--seed", type=int, default=1)
    p.add_argument("--judges", type=int, default=4); p.add_argument("--double", type=float, default=0.1); p.set_defaults(f=cmd_items)
    p = sub.add_parser("score"); p.add_argument("set"); p.add_argument("key"); p.add_argument("labels", nargs="+"); p.add_argument("--json"); p.set_defaults(f=cmd_score)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
