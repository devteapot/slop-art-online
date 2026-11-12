#!/usr/bin/env python3
"""The rethink gate's quality against its cost, on recorded deliberations (docs/GATE_QUALITY.md).

Subcommands (all read trial evidence; only `ask` makes paid calls, under a hard dollar cap):
  points  OUT  --jev FILE --llm FILE [--jev FILE --llm FILE ...]
          merge `living-mind rethink-replay` outputs of both arms into one row per trigger
          point, with the recorded think call (exact messages and reply) from the journal.
  ask     POINTS OUT --profile NAME --models MODELS.json --cap USD [--only IDS] [--max N]
          re-send each point's recorded think messages to a profile (same request body as
          llm.rs, the model and effort swapped), journaling replies, tokens and cost.
  items   POINTS ASKED... OUT_DIR --seed N
          blind judge items: (a) the value of the recorded deliberation, (b) pairs of think
          replies in random order, with a hidden key.
  curve   POINTS LABELS... --key KEY
          the cost-against-harm curve over gate settings and model setups.
"""
import argparse, glob, gzip, json, os, random, sys, time, urllib.request, urllib.error
from pathlib import Path

PRICES = {"deepseek-v4-1-flash-1017": (0.30, 1.20, 0.007), "zai-glm-5-3-flash": (0.15, 0.50, 0.03), "mistral-small-latest": (0.20, 0.60, 0.20)}


def rows(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass


def cost(model, prompt, completion, cached):
    pr = PRICES.get(model)
    if not pr or prompt is None:
        return None
    cached = cached or 0
    return ((prompt - cached) * pr[0] + cached * pr[2] + (completion or 0) * pr[1]) / 1e6


def resolve(entry, journal_dir):
    """The request's messages with system texts read back from the journal's content refs."""
    out = []
    for m in entry["request"]["messages"]:
        if "content_ref" in m:
            out.append({"role": m["role"], "content": (Path(journal_dir) / m["content_ref"]).read_text()})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


def think_call(run_dir, name, req_ms):
    """The think call that started closest to the deliberation's request (15 s before to 5 s after)."""
    jdir = Path(run_dir) / "journal"
    f = jdir / (''.join(c if c.isalnum() else '_' for c in name) + ".jsonl")
    if not f.exists():
        return None
    best = None
    for e in rows(f):
        if e.get("purpose") != "think" or e.get("error") or not e.get("request"):
            continue
        start = e["at_ms"] - (e.get("latency_ms") or 0) - (e.get("queue_wait_ms") or 0)
        d = abs(start - req_ms)
        # The deliberation's recorded request time can trail its think call by several seconds
        # (it is the thought's time less the last call's latency): look 15 s back, 5 s ahead.
        if -15000 <= start - req_ms <= 5000 and (best is None or d < best[0]):
            best = (d, e)
    if not best:
        return None
    e = best[1]
    return {"messages": resolve(e, jdir), "body": e["request"], "reply": e.get("reply"), "model": e.get("model"), "profile": e.get("profile"),
            "effort": e.get("effort"), "prompt_tokens": e.get("prompt_tokens"), "completion_tokens": e.get("completion_tokens"),
            "cached_tokens": e.get("cached_tokens"), "latency_ms": e.get("latency_ms"),
            "cost_usd": cost(e.get("model"), e.get("prompt_tokens"), e.get("completion_tokens"), e.get("cached_tokens"))}


def deliberation_cost(run_dir, name, req_ms):
    """Think plus compile cost of the deliberation started at req_ms (the calls in the next 120 s)."""
    jdir = Path(run_dir) / "journal"
    f = jdir / (''.join(c if c.isalnum() else '_' for c in name) + ".jsonl")
    total, seen = 0.0, set()
    for e in rows(f) if f.exists() else []:
        if e.get("purpose") not in ("think", "deliberate") or e.get("error"):
            continue
        start = e["at_ms"] - (e.get("latency_ms") or 0) - (e.get("queue_wait_ms") or 0)
        if req_ms - 15000 <= start <= req_ms + 120000 and e["purpose"] not in seen:
            c = cost(e.get("model"), e.get("prompt_tokens"), e.get("completion_tokens"), e.get("cached_tokens"))
            if c is not None:
                total += c
                seen.add(e["purpose"])
    return total if seen else None


def cmd_points(a):
    arms = {}
    for arm, files in (("jev", a.jev), ("llm", a.llm)):
        for path in files:
            for r in rows(path):
                k = (r["run"].rstrip("/"), r["idx"])
                p = arms.setdefault(k, {"run": r["run"].rstrip("/"), "idx": r["idx"], "req_ms": r["req_ms"], "reason": r["reason"], "state": r["state"], "after": r["after"]})
                p[arm] = {"verdict": r["verdict"], "p": (r.get("judged") or {}).get("p"), "answers": (r.get("judged") or {}).get("answers"),
                          "cost_usd": (r.get("judged") or {}).get("cost_usd"), "error": r.get("error")}
    n = 0
    with open(a.out, "w") as out:
        for k in sorted(arms):
            p = arms[k]
            run = Path(p["run"])
            name = (json.loads((run / "summary.json").read_text()).get("subject") or "").split("#")[0]
            p["batch"] = run.parent.name
            p["instance"] = run.name
            p["subject"] = name
            gated = all(p.get(arm, {}).get("verdict") not in ("urgent", "first") for arm in ("jev", "llm"))
            p["gated"] = gated
            if gated:
                p["think"] = think_call(run, name, p["req_ms"])
                p["deliberation_cost_usd"] = deliberation_cost(run, name, p["req_ms"])
            out.write(json.dumps(p) + "\n")
            n += 1
    print(f"{n} points → {a.out}")


def load_env(root):
    env = {}
    f = Path(root) / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def cmd_ask(a):
    models = json.loads(Path(a.models).read_text())
    prof = models["profiles"][a.profile]
    env = load_env(a.root)
    key = os.environ.get(prof["key_env"]) or env.get(prof["key_env"])
    if not key:
        sys.exit(f"no key in {prof['key_env']}")
    only = None
    if a.only:
        only = set(Path(a.only).read_text().split()) if Path(a.only).exists() else set(a.only.split(","))
    done = {}
    if Path(a.out).exists():
        for r in rows(a.out):
            done[r["pid"]] = r
    spent = sum((r.get("cost_usd") or 0) for r in done.values())
    pts = [p for p in rows(a.points) if p.get("gated") and p.get("think")]
    pts = [p for p in pts if (only is None or pid(p) in only)]
    if a.max:
        pts = pts[: a.max]
    url = prof["base_url"].rstrip("/") + "/chat/completions"
    with open(a.out, "a") as out:
        for p in pts:
            if pid(p) in done:
                continue
            if spent >= a.cap:
                print(f"cap ${a.cap} reached (${spent:.4f}); stopping")
                break
            t = p["think"]
            body = dict(t["body"])
            body["messages"] = t["messages"]
            body["model"] = prof["model"]
            eff = (prof.get("reasoning_effort") or {}).get("think")
            body.pop("reasoning_effort", None)
            if eff:
                body["reasoning_effort"] = eff
            if prof.get("prompt_cache_key"):
                body["prompt_cache_key"] = f"sao:{len(a.profile)}:{a.profile}:think"
            else:
                body.pop("prompt_cache_key", None)
            mt = (prof.get("purpose_max_tokens") or {}).get("think") or prof.get("max_tokens")
            if mt:
                body["max_tokens"] = mt
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            t0 = time.time()
            rec = {"pid": pid(p), "profile": a.profile, "model": prof["model"], "effort": eff}
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
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
                    rec.update({"error": f"HTTP {e.code}: {e.read()[:300]!r}", "latency_ms": int((time.time() - t0) * 1000)})
                    if e.code in (429, 500, 502, 503):
                        time.sleep(5 * (attempt + 1))
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    rec.update({"error": repr(e)[:300]})
                    time.sleep(5)
            rec["cost_usd"] = cost(prof["model"], rec.get("prompt_tokens"), rec.get("completion_tokens"), rec.get("cached_tokens"))
            spent += rec["cost_usd"] or 0
            out.write(json.dumps(rec) + "\n")
            out.flush()
    print(f"asked; spent ${spent:.4f} in {a.out}")


def pid(p):
    return f"{p['batch']}/{p['instance']}/{p['idx']}"


SECTIONS = ("# Why you are thinking now", "# Recent experiences", "# What you perceive right now", "# What you were doing", "# People you know", "# Places you remember", "# Your stances")


def situation(user, limit=5500):
    """What a judge needs from a think prompt: the moment, the scene and whom one knows, in the
    prompt's own words (the persona's long narrative and recalled memories are cut first)."""
    parts = {}
    for sec in user.split("\n# ")[1:]:
        head, _, body = sec.partition("\n")
        parts["# " + head] = body.strip()
    out = []
    who = next((k for k in parts if k.startswith("# Who you are")), None)
    if who:
        out.append(f"{who}\n{parts[who][:1200]}")
    for k in SECTIONS:
        for h, b in parts.items():
            if h.startswith(k):
                out.append(f"{h}\n{b[:3000]}")
    text = "\n\n".join(out)
    return text[:limit]


def reply_view(raw):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {"unparsed": (raw or "")[:1500]}
    if not isinstance(v, dict):
        return {"unparsed": str(v)[:1500]}
    return {k: v.get(k) for k in ("thought", "intend", "say", "judgments", "places", "notice", "project", "projects") if k in v}


def cmd_sample(a):
    """A seeded random sample of gated points that have a recorded think reply, as pids."""
    pts = [pid(p) for p in rows(a.points) if p.get("gated") and p.get("think") and p["think"].get("reply")]
    rnd = random.Random(a.seed)
    rnd.shuffle(pts)
    Path(a.out).write_text("\n".join(pts[: a.n]) + "\n")
    print(f"{min(a.n, len(pts))} of {len(pts)} gated points → {a.out}")


def cmd_items(a):
    rnd = random.Random(a.seed)
    pts = [p for p in rows(a.points) if p.get("gated") and p.get("think") and p["think"].get("reply")]
    asked = {}
    for path in a.asked:
        for r in rows(path):
            if r.get("reply") and not r.get("error"):
                asked.setdefault(r["pid"], {})[r["profile"]] = r
    chosen = Path(a.sample).read_text().split()
    by = {pid(p): p for p in pts}
    pts = [by[i] for i in chosen if i in by]
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    value, pairs, key = [], [], []
    for p in pts:
        i = pid(p)
        vid = f"v{len(value) + 1:04d}"
        value.append({"item": vid, "state": p["state"], "what_the_deliberation_produced": p["after"]})
        key.append({"item": vid, "pid": i, "kind": "value"})
        user = next((m["content"] for m in p["think"]["messages"] if m["role"] == "user"), "")
        for prof, r in sorted(asked.get(i, {}).items()):
            sides = [("recorded", p["think"]["model"], p["think"]["reply"]), (prof, r["model"], r["reply"])]
            rnd.shuffle(sides)
            iid = f"p{len(pairs) + 1:04d}"
            pairs.append({"item": iid, "situation": situation(user), "A": reply_view(sides[0][2]), "B": reply_view(sides[1][2])})
            key.append({"item": iid, "pid": i, "kind": "pair", "A": sides[0][0], "A_model": sides[0][1], "B": sides[1][0], "B_model": sides[1][1], "profile": prof})
    rnd.shuffle(value)
    rnd.shuffle(pairs)
    for name, items in (("value", value), ("pairs", pairs)):
        with open(out / f"{name}-items.jsonl", "w") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with open(out / "key.jsonl", "w") as f:
        for k in key:
            f.write(json.dumps(k) + "\n")
    print(f"{len(value)} value items, {len(pairs)} pair items → {out}")


def gate_settings():
    """Gate rules scored offline from each point's recorded answers: (name, fn(point) -> passes)."""
    def jev(t, unless=1.0, repeat=True):
        def f(p):
            a = (p.get("jev") or {}).get("answers") or {}
            if not a:
                return True  # no answer: the gate falls back to thinking
            base = max(a.get("plan_broken", 0.0), a.get("unhandled", 0.0))
            q = base * (1 - unless * a.get("would_repeat", 0.0)) if repeat else base
            return q >= t
        return f
    def glm(t):
        def f(p):
            q = (p.get("llm") or {}).get("p")
            return True if q is None else q >= t
        return f
    out = [("off", lambda p: True)]
    out += [(f"jev p>={t}", jev(t)) for t in (0.2, 0.3, 0.4, 0.5, 0.6)]
    out += [(f"jev unless x0.5 p>={t}", jev(t, 0.5)) for t in (0.3, 0.4, 0.5)]
    out += [(f"jev no would_repeat p>={t}", jev(t, repeat=False)) for t in (0.5, 0.6, 0.7)]
    out += [(f"glm p>={t}", glm(t)) for t in (0.5, 0.6, 0.7, 0.8, 0.9)]
    return out


def cmd_curve(a):
    pts = {pid(p): p for p in rows(a.points) if p.get("gated")}
    key = {k["item"]: k for k in rows(a.key)}
    value, agree_v = {}, []
    for path in a.value:
        for l in rows(path):
            k = key.get(l.get("item"))
            if not k:
                continue
            if k["pid"] in value:
                agree_v.append((value[k["pid"]], l))
            else:
                value[k["pid"]] = l
    pairs, agree_p = {}, []
    for path in a.pairs:
        for l in rows(path):
            k = key.get(l.get("item"))
            if not k:
                continue
            side = {"A": k["A"], "B": k["B"]}
            models = {k["A"]: k["A_model"], k["B"]: k["B_model"]}
            rec = {"better": side.get(l.get("better"), "same"), "harm": {k["A"]: bool(l.get("A_harm")), k["B"]: bool(l.get("B_harm"))}, "models": models, "profile": k["profile"]}
            kk = (k["pid"], k["profile"])
            if kk in pairs:
                agree_p.append((pairs[kk], rec))
            else:
                pairs[kk] = rec
    asked = {}
    for path in a.asked:
        for r in rows(path):
            asked[(r["pid"], r["profile"])] = r
    gate_cost = {"jev": a.jev_cost, "llm": a.glm_cost}
    res = {"value_agreement": None, "pair_agreement": None, "sets": {}}
    if agree_v:
        res["value_agreement"] = {"n": len(agree_v), "value_same": sum(x["value"] == y["value"] for x, y in agree_v) / len(agree_v),
                                  "hurt_same": sum(bool(x.get("hurt_if_skipped")) == bool(y.get("hurt_if_skipped")) for x, y in agree_v) / len(agree_v)}
    if agree_p:
        res["pair_agreement"] = {"n": len(agree_p), "better_same": sum(x["better"] == y["better"] for x, y in agree_p) / len(agree_p)}
    for set_name, batches in (("all-minds (bi1, st2b)", ("bi1", "st2b")), ("newcomer (b1, w1, w2)", ("b1", "w1", "w2"))):
        ids = [i for i in value if pts.get(i) and pts[i]["batch"] in batches]
        if not ids:
            continue
        n = len(ids)
        wasted = [i for i in ids if value[i]["value"] == "wasted"]
        hurt = [i for i in ids if value[i].get("hurt_if_skipped")]
        dc = [pts[i].get("deliberation_cost_usd") or 0 for i in ids]
        base_cost = sum(dc) / n
        lab = {"n": n, "useful": sum(value[i]["value"] == "useful" for i in ids) / n, "marginal": sum(value[i]["value"] == "marginal" for i in ids) / n,
               "wasted": len(wasted) / n, "hurt_if_skipped": len(hurt) / n,
               "waste_kinds": {w: sum(value[i].get("waste") == w for i in wasted) for w in ("restated_plan", "phantom_target", "asking_loop", "other")},
               "deliberation_usd_mean": base_cost}
        # Harmful replies among the recorded deliberations (from the pairs), for the model axis.
        rows_out = []
        for name, passes in gate_settings():
            held = [i for i in ids if not passes(pts[i])]
            hs = set(held)
            gc = 0.0 if name == "off" else gate_cost["jev" if name.startswith("jev") else "llm"]
            cost = (sum(c for i, c in zip(ids, dc) if i not in hs) / n) + gc
            rows_out.append({"gate": name, "held": len(held) / n, "wasted_caught": (sum(i in hs for i in wasted) / len(wasted)) if wasted else None,
                             "harmful_held": (sum(i in hs for i in hurt) / len(hurt)) if hurt else None,
                             "harm_rate": sum(i in hs for i in hurt) / n, "usd_per_trigger": cost, "cost_vs_off": cost / base_cost if base_cost else None})
        lab["gates"] = rows_out
        # The model axis: the recorded think model against the other cloud model on the same points.
        pk = [(i, prof) for (i, prof) in pairs if i in set(ids)]
        if pk:
            axis = {}
            for (i, prof) in pk:
                r = pairs[(i, prof)]
                rec_model = r["models"]["recorded"]
                alt_model = r["models"][prof]
                kind = "noise" if rec_model == alt_model else f"{rec_model.split('-')[0]} vs {alt_model.split('-')[0]}"
                d = axis.setdefault(kind, {"n": 0, "recorded_better": 0, "alt_better": 0, "same": 0, "recorded_harm": 0, "alt_harm": 0, "recorded_usd": 0.0, "alt_usd": 0.0})
                d["n"] += 1
                d["recorded_better" if r["better"] == "recorded" else "alt_better" if r["better"] == prof else "same"] += 1
                d["recorded_harm"] += r["harm"]["recorded"]
                d["alt_harm"] += r["harm"][prof]
                d["recorded_usd"] += (pts[i].get("think") or {}).get("cost_usd") or 0
                d["alt_usd"] += (asked.get((i, prof)) or {}).get("cost_usd") or 0
            lab["model_axis"] = axis
            # Combined cells: gate x think model, harm = held&hurt + passed&harmful reply.
            cells = []
            for name, passes in gate_settings():
                for setup in ("glm think", "deepseek think"):
                    hv, cv, m = 0, 0.0, 0
                    for (i, prof) in pk:
                        r = pairs[(i, prof)]
                        if r["models"]["recorded"] == r["models"][prof]:
                            continue
                        pref = "zai" if setup.startswith("glm") else "deepseek"
                        side = next((s for s, mm in r["models"].items() if mm.startswith(pref)), None)
                        if side is None:
                            continue
                        m += 1
                        p = pts[i]
                        think_usd = ((p.get("think") or {}).get("cost_usd") or 0) if side == "recorded" else ((asked.get((i, prof)) or {}).get("cost_usd") or 0)
                        compile_usd = max(0.0, (p.get("deliberation_cost_usd") or 0) - ((p.get("think") or {}).get("cost_usd") or 0))
                        if passes(p):
                            hv += r["harm"][side]
                            cv += think_usd + compile_usd
                        else:
                            hv += bool(value.get(i, {}).get("hurt_if_skipped"))
                        cv += 0.0 if name == "off" else gate_cost["jev" if name.startswith("jev") else "llm"]
                    if m:
                        cells.append({"gate": name, "setup": setup, "n": m, "harm_rate": hv / m, "usd_per_trigger": cv / m})
            lab["cells"] = cells
        res["sets"][set_name] = lab
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "sets"}, indent=1))
    for sname, lab in res["sets"].items():
        print(f"\n## {sname}: n={lab['n']}, useful {lab['useful']:.0%}, marginal {lab['marginal']:.0%}, wasted {lab['wasted']:.0%}, hurt if skipped {lab['hurt_if_skipped']:.0%}; waste {lab['waste_kinds']}; ${lab['deliberation_usd_mean']:.4f} a deliberation")
        print("| gate | held | wasted caught | harmful held | harm rate | $ a trigger | cost vs off |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        for r in lab["gates"]:
            f = lambda x: "–" if x is None else f"{x:.0%}"
            print(f"| {r['gate']} | {f(r['held'])} | {f(r['wasted_caught'])} | {f(r['harmful_held'])} | {r['harm_rate']:.1%} | {r['usd_per_trigger']:.4f} | {f(r['cost_vs_off'])} |")
        if lab.get("model_axis"):
            print("model axis:", json.dumps(lab["model_axis"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("points"); s.add_argument("out"); s.add_argument("--jev", action="append", default=[]); s.add_argument("--llm", action="append", default=[])
    s = sub.add_parser("ask"); s.add_argument("points"); s.add_argument("out"); s.add_argument("--profile", required=True); s.add_argument("--models", required=True)
    s.add_argument("--cap", type=float, required=True); s.add_argument("--only"); s.add_argument("--max", type=int); s.add_argument("--root", default=".")
    s = sub.add_parser("sample"); s.add_argument("points"); s.add_argument("out"); s.add_argument("--n", type=int, default=240); s.add_argument("--seed", type=int, default=1112)
    s = sub.add_parser("items"); s.add_argument("points"); s.add_argument("out_dir"); s.add_argument("--sample", required=True); s.add_argument("--asked", action="append", default=[]); s.add_argument("--seed", type=int, default=1112)
    s = sub.add_parser("curve"); s.add_argument("points"); s.add_argument("out"); s.add_argument("--key", required=True)
    s.add_argument("--value", action="append", default=[]); s.add_argument("--pairs", action="append", default=[]); s.add_argument("--asked", action="append", default=[])
    s.add_argument("--jev-cost", type=float, default=0.00006); s.add_argument("--glm-cost", type=float, default=0.00016)
    a = ap.parse_args()
    {"points": cmd_points, "ask": cmd_ask, "sample": cmd_sample, "items": cmd_items, "curve": cmd_curve}[a.cmd](a)


if __name__ == "__main__":
    main()
