#!/usr/bin/env python3
"""feedback-1 comparison (docs/MIND_FEEDBACK.md): feedback_report.py <root> <batch> [<root> <batch> ...] -> per instance and per arm.
Reads evidence only (no model calls): .local/living/trials/<batch>/<inst>/ and .local/living/journal/<db>/."""
import json, re, sys, glob, os, statistics as st
SIGHT = 11.0
PRICE = {"deepseek-v4-1-flash-1017": (0.30, 1.20, 0.007), "zai-glm-5-3-flash": (0.15, 0.50, 0.03)}
def jl(p):
    out = []
    try:
        for l in open(p, errors="replace"):
            try: out.append(json.loads(l))
            except Exception: pass
    except FileNotFoundError: pass
    return out
def failed_at(text):
    m = re.search(r"did not work out: (.*?): (.*)$", text)
    if not m: return None
    label, why = m.group(1), m.group(2).rstrip(".")
    mi = re.search(r"→ #(\d+)$", label.strip())
    if not mi: return None
    i = mi.group(1)
    if why == f"no #{i} in sight" or why.endswith(" is depleted") or why == "it is gone": return (i, why)
    return None
def instance(root, batch, inst):
    d = os.path.join(root, ".local/living/trials", batch, inst)
    db = f"verify-trial-{batch}-{inst}"
    cast = json.load(open(os.path.join(d, "cast.json")))
    subj = cast["roles"]["subject"][0]; sid, sname = subj["id"], subj["name"]
    samples = jl(os.path.join(d, "samples.jsonl"))
    t_end = samples[-1]["t"] if samples else 0
    ghours = t_end / 30.0
    thoughts = jl(os.path.join(d, "thoughts.jsonl"))
    delib = sum(1 for t in thoughts if t.get("kind") == "deliberate" and t.get("actor") == sid)
    exps = jl(os.path.join(d, "experiences.jsonl"))
    exps = [e for e in exps if e.get("observer") == sid]
    chron = jl(os.path.join(d, "chronicle.jsonl"))
    idpos = json.load(open(os.path.join(root, ".local/living/trials", batch, "idpos.json"))).get(inst, {}) if os.path.exists(os.path.join(root, ".local/living/trials", batch, "idpos.json")) else {}
    # Failed steps at remembered things, and how many of them were false (the thing was in sight).
    fails, false_fails, people_fails = 0, 0, 0
    for e in exps:
        if e.get("kind") != "act": continue
        f = failed_at(e.get("text", ""))
        if not f: continue
        pos = idpos.get(f[0], {})
        # A thing of that id in sight comes first (the step failed at it); otherwise an id that is
        # also a character's was most likely a person who walked off, not a thing.
        seen = any(pos.get(t) and ((pos[t]["x"] - e["x"]) ** 2 + (pos[t]["y"] - e["y"]) ** 2) ** 0.5 <= SIGHT for t in ("structure", "resource_node"))
        if pos.get("character") and not seen:
            people_fails += 1
            continue
        fails += 1
        if seen and f[1].startswith("no #"):
            false_fails += 1
    # Asking: subject lines addressed to someone; re-asks while the previous one went unanswered.
    speech = [c for c in chron if c.get("kind") == "speech"]
    streak, reasks, maxstreak, addressed, unaddressed = {}, 0, 0, 0, 0
    answers = 0
    for c in speech:
        a, b = c.get("a"), c.get("b")
        if a == sid:
            if b:
                addressed += 1
                streak[b] = streak.get(b, 0) + 1
                if streak[b] > 1: reasks += 1
                maxstreak = max(maxstreak, streak[b])
            else:
                unaddressed += 1
        else:
            if a in streak: streak[a] = 0
            if b == sid: answers += 1
    # Asks to someone who has never answered the subject: in earshot (no silence percept for
    # the line) beyond the second, and out of earshot (a silence percept came back).
    silences = {round(e["t"]) for e in exps if e.get("kind") == "silence"}
    answered_by, asked = set(), {}
    never_in_earshot, out_of_earshot = 0, 0
    for c in speech:
        a, b = c.get("a"), c.get("b")
        if a != sid:
            if b == sid or b == 0: answered_by.add(a)
            continue
        if not b or b in answered_by: continue
        if any(abs(round(c["t"]) - t) <= 1 for t in silences): out_of_earshot += 1; continue
        asked[b] = asked.get(b, 0) + 1
        if asked[b] > 2: never_in_earshot += 1
    acts_to = sum(1 for c in chron if c.get("b") == sid and c.get("kind") not in ("speech",) and c.get("a") != sid)
    gate_notices = sum(1 for e in exps if e.get("text", "").startswith("You notice a gate"))
    gate_first5 = sum(1 for e in exps if e.get("text", "").startswith("You notice a gate") and e.get("t", 0) <= 300)
    text_speech = sum(1 for c in speech if "“text”" in c.get("text", ""))
    # Tokens from journals.
    jdir = os.path.join(root, ".local/living/journal", db)
    tok = {"subject": 0, "residents": 0}; calls = {"subject": 0, "residents": 0}; cost = 0.0
    prompt_by_purpose = {}
    woken = 0
    for f in glob.glob(os.path.join(jdir, "*.jsonl")):
        who = "subject" if os.path.basename(f).startswith(sname) else "residents"
        if who == "residents": woken += 1
        for r in jl(f):
            if not r.get("purpose"): continue
            calls[who] += 1; tok[who] += r.get("tokens") or 0
            pr = PRICE.get(r.get("model"), (0.3, 1.2, 0.007))
            pt, ct, ca = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0
            cost += ((pt - ca) * pr[0] + ca * pr[2] + ct * pr[1]) / 1e6
            if who == "subject":
                prompt_by_purpose.setdefault(r["purpose"], []).append(pt)
    alive = samples[-1].get("alive") if samples else None
    ate = sum(1 for e in exps if e.get("kind") == "act" and "You did what you had decided: eat" in e.get("text", ""))
    return {"inst": inst, "minutes": round(t_end / 60, 1), "game_hours": round(ghours, 1), "alive": alive,
            "deliberations": delib, "delib_per_game_hour": round(delib / ghours, 2) if ghours else None,
            "addressed_lines": addressed, "unaddressed_lines": unaddressed, "reasks_unanswered": reasks, "max_unanswered_streak": maxstreak,
            "answers_to_subject": answers, "reasks_never_answered_in_earshot": never_in_earshot, "asks_out_of_earshot": out_of_earshot, "acts_to_subject": acts_to,
            "failed_at_things": fails, "of_which_in_sight": false_fails, "failed_at_people": people_fails, "gate_notices": gate_notices, "gate_notices_first5min": gate_first5, "said_text": text_speech,
            "residents_woken": woken, "calls_subject": calls["subject"], "tokens_subject": tok["subject"], "calls_residents": calls["residents"], "tokens_residents": tok["residents"],
            "cost_usd": round(cost, 3), "prompt_tokens_p50": {k: int(st.median(v)) for k, v in prompt_by_purpose.items()}}
args = sys.argv[1:]
rows = []
for root, batch in zip(args[::2], args[1::2]):
    for inst in sorted(os.path.basename(p) for p in glob.glob(os.path.join(root, ".local/living/trials", batch, "*-r*"))):
        r = instance(root, batch, inst); r["batch"] = batch; rows.append(r); print(json.dumps(r))
print()
keys = ["minutes", "game_hours", "deliberations", "delib_per_game_hour", "addressed_lines", "unaddressed_lines", "reasks_unanswered", "max_unanswered_streak", "reasks_never_answered_in_earshot", "asks_out_of_earshot", "answers_to_subject", "acts_to_subject",
        "failed_at_things", "of_which_in_sight", "failed_at_people", "gate_notices", "gate_notices_first5min", "said_text", "residents_woken", "calls_subject", "tokens_subject", "calls_residents", "tokens_residents", "cost_usd"]
batches = sorted(set(r["batch"] for r in rows), key=lambda b: [r["batch"] for r in rows].index(b))
print("| metric | " + " | ".join(batches) + " |"); print("|---|" + "---|" * len(batches))
for k in keys:
    cells = []
    for b in batches:
        v = [r[k] for r in rows if r["batch"] == b and r[k] is not None]
        cells.append(f"{st.mean(v):.2f} ({min(v)}–{max(v)})" if v else "–")
    print(f"| {k} | " + " | ".join(cells) + " |")
print("| alive at end | " + " | ".join(f"{sum(1 for r in rows if r['batch']==b and r['alive'])}/{sum(1 for r in rows if r['batch']==b)}" for b in batches) + " |")
