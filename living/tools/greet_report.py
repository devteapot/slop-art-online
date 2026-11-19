#!/usr/bin/env python3
"""How residents answer a stranger, and what it costs (docs/TRIALS.md, "The greeting trial").

  greet_report.py BATCH [BATCH...] [--root DIR] [--examples N]

Read-only, no model calls. For each run of the `greet` trial (evidence written by trials.py with
`record.speech`, `record.talk` and `record.audience`), from `events.jsonl` (the scripted player's
`human_line` events), `speech.jsonl` (every line said), `talk.jsonl` (every conversation turn:
whom it answered and the line heard), `audience.jsonl` (who heard each line, how far, how far
off the speaker's facing) and the journal (tokens):

- per kind of the player's line (`unaddressed`: to no one; `addressed`: `to` the nearest resident
  within earshot, 12 m): lines, how many had two or more residents within the address distance (6 m) when
  said (the owner's case: the authority then marks no one addressed), `answered` (a resident
  spoke to the player, `to` = the player, within ANSWER_S of the line and before the player's
  next line; or a talk turn answering that very line spoke, since the chronicle merges a line
  repeated word for word into its earlier row), `answered_5s`, answer latency median and p90 (s), and who answered: `by_nearest`
  (the resident nearest the player when it spoke), `by_addressed` (the one the line was for),
  `by_turn` (the answer came from a conversation turn rather than a deliberation);
- `false_replies` (since 2026-11-12, `strangers-measures`; `reply_kind`): conversation turns that
  answered a resident's line naming someone else, addressed (`to`) to another person or saying
  another's name, and never one whose words name the answerer; `group_talk`: turns answering a
  remark to the room that names no one; `overheard_turns`: all turns on residents' lines said to
  no one; false replies also per listening window of the player (`listen_false`). Only the
  player's own turns are left out: the joined newcomer (cast role `newcomer`) where there is one,
  else the subject (the greeting and arrival trials' player); a resident who is a trial's subject
  (Aldous in the strangers trials) is counted. Before, a room line said while its speaker was in
  an exchange with another (within EXCHANGE_S) was false too, a line naming the answerer could be,
  and the subject was always left out (docs/TRIALS.md, "Analysis of st2b");
- `turns_min`: residents' conversation turns per minute; `talk_tok_min` and `tok_min`: model tokens
  per minute for talk turns and for everything, and `usd_h`: estimated dollars per hour at
  trials.py's prices (fake runs: 0).

A mean (range) per batch x variant follows the per-run table, then `--examples` answered and
unanswered lines with their journal-free evidence (speech and talk rows).
"""
import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (prices: trials.cost)

OUT = Path(__file__).resolve().parents[2] / ".local/living/trials"
ANSWER_S = 60
EXCHANGE_S = 60
ADDRESS_M = 6.0


def jl(p):
    out = []
    if not p.exists():
        return out
    for line in p.read_bytes().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def words(text):
    """The words of a chronicle line: inside “…”, without a repeat count."""
    base = re.sub(r" \(×\d+\)$", "", text or "")
    m = re.search(r"“(.*)”", base, re.S)
    return (m.group(1) if m else base).strip()


def named_in(text, names):
    """Ids of the people whose name (full, or first name) the words of a line say."""
    out = set()
    for pid, name in names.items():
        if not name:
            continue
        first = name.split()[0]
        if re.search(rf"\b{re.escape(name)}\b", text) or (len(first) > 2 and re.search(rf"\b{re.escape(first)}\b", text)):
            out.add(pid)
    return out


def reply_kind(text, to, speaker, answerer, names):
    """What a turn by `answerer` on `speaker`'s line (its words `text`, addressed to `to`, 0 for
    the room) was: "false" when the line names someone else (addressed to another, or saying
    another's name), "group_talk" when it is a remark to the room that names no one, None when it
    was for the answerer (addressed to them, or saying their name: never false)."""
    said = named_in(text, names) - {speaker}
    if answerer in said or to == answerer:
        return None
    if (to and to != answerer) or said:
        return "false"
    return "group_talk"


def hearers(row):
    """An audience row's hearers as dicts (the SQL API gives a product as a list)."""
    out = []
    for h in row.get("hearers") or []:
        if isinstance(h, dict):
            out.append({"id": h["id"], "d": h["d"], "off": h["off"]})
        else:
            out.append({"id": h[0], "d": h[1], "off": h[2]})
    return out


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def run(d):
    cast = json.loads((d / "cast.json").read_text()) if (d / "cast.json").exists() else {}
    # The player: the joined newcomer where a trial has one (the strangers trials, whose subject
    # is a resident), else the subject (the greeting and arrival trials' joined player).
    roles = cast.get("roles", {})
    P = (roles.get("newcomer") or roles.get("subject") or [{}])[0].get("id")
    events = jl(d / "events.jsonl")
    lines = [e["human_line"] for e in events if "human_line" in e]
    listens = [(e["human_listen"]["from_ms"], e["human_listen"]["from_ms"] + e["human_listen"]["s"] * 1000) for e in events if "human_listen" in e]
    speech = sorted(jl(d / "speech.jsonl"), key=lambda r: (r["at_ms"], r["id"]))
    talk = sorted(jl(d / "talk.jsonl"), key=lambda r: r["at_ms"])
    aud = {(a["speaker"], a["at_ms"]): hearers(a) for a in jl(d / "audience.jsonl")}
    names = {}
    for c in jl(d / "census.jsonl")[:1]:
        names = {p["id"]: p["name"] for p in c.get("people", []) if p.get("kind", "person") == "person"}
    mine = [r for r in speech if r["a"] == P]
    out = {"run": d.name, "player": P, "lines": {}, "examples": []}
    for kind in ("unaddressed", "addressed"):
        said = [l for l in lines if l["kind"] == kind and l.get("ok")]
        rows = []
        for l in said:
            # The chronicle row of this line: the player's, same words, nearest in time.
            cand = [r for r in mine if words(r["text"]) == l["text"] and abs(r["at_ms"] - l["at_ms"]) < 5000]
            if not cand:
                continue
            r = min(cand, key=lambda r: abs(r["at_ms"] - l["at_ms"]))
            nxt = min([m["at_ms"] for m in mine if m["at_ms"] > r["at_ms"]] or [r["at_ms"] + ANSWER_S * 1000])
            until = min(nxt, r["at_ms"] + ANSWER_S * 1000)
            ans = next((s for s in speech if s["a"] != P and s["b"] == P and r["at_ms"] < s["at_ms"] <= until), None)
            # A talk turn that answered this very line (the chronicle merges a line repeated word
            # for word into its earlier row, "(×n)", so a repeated answer has no new speech row).
            turn = next((t for t in talk if t["actor"] != P and r["at_ms"] < t["at_ms"] <= until and "says nothing" not in t.get("summary", "")
                         and json.loads(t.get("detail") or "{}").get("with") == P and json.loads(t.get("detail") or "{}").get("heard") == l["text"]), None)
            if turn and (not ans or turn["at_ms"] < ans["at_ms"]):
                said = json.loads(turn.get("detail") or "{}").get("reply") or {}
                ans = {"a": turn["actor"], "at_ms": turn["at_ms"], "text": "“" + str(said.get("say") if isinstance(said, dict) else "") + "”"}
            hs = aud.get((P, r["at_ms"]))
            near = [(h["d"], h["id"]) for h in hs] if hs is not None else [(n[0], n[1]) for n in l.get("near", [])]
            near.sort()
            close = sum(1 for dd, _ in near if dd <= ADDRESS_M)
            via_turn = bool(ans) and any(t["actor"] == ans["a"] and abs(t["at_ms"] - ans["at_ms"]) < 3000 and json.loads(t.get("detail") or "{}").get("with") == P for t in talk)
            rows.append({"at_ms": r["at_ms"], "text": l["text"], "close": close, "to": l.get("to") or 0,
                         "answered": bool(ans), "latency": (ans["at_ms"] - r["at_ms"]) / 1000 if ans else None,
                         "by": ans["a"] if ans else None, "nearest": near[0][1] if near else None, "turn": via_turn,
                         "answer": words(ans["text"]) if ans else None})
        lat = [x["latency"] for x in rows if x["latency"] is not None]
        got = [x for x in rows if x["answered"]]
        out["lines"][kind] = {
            "n": len(rows),
            "crowded": sum(1 for x in rows if x["close"] >= 2),
            "answered": round(len(got) / len(rows), 2) if rows else None,
            "answered_5s": round(sum(1 for x in lat if x <= 5) / len(rows), 2) if rows else None,
            "lat_med": round(statistics.median(lat), 1) if lat else None,
            "lat_p90": round(pct(lat, 0.9), 1) if lat else None,
            "by_nearest": sum(1 for x in got if x["by"] == x["nearest"]),
            "by_addressed": sum(1 for x in got if x["to"] and x["by"] == x["to"]),
            "by_turn": sum(1 for x in got if x["turn"]),
        }
        out["examples"] += [{"kind": kind, **x, "by_name": names.get(x["by"]), "nearest_name": names.get(x["nearest"])} for x in rows]
    # Turns on residents' lines.
    false, group, overheard, in_listen = 0, 0, 0, 0
    false_ex = []
    for t in talk:
        det = json.loads(t.get("detail") or "{}")
        a, heard = det.get("with"), det.get("heard")
        if a in (None, P) or t["actor"] == P:
            continue
        line = next((s for s in reversed(speech) if s["a"] == a and s["at_ms"] <= t["at_ms"] and words(s["text"]) == heard), None)
        if not line:
            continue
        C, to = t["actor"], line["b"]
        if to == 0:
            overheard += 1
        kind = reply_kind(heard, to, a, C, names)
        if kind == "group_talk":
            group += 1
        elif kind == "false":
            false += 1
            in_listen += any(f <= line["at_ms"] <= e for f, e in listens)
            others = sorted(named_in(heard, names) - {a, C}) or ([to] if to else [])
            false_ex.append({"by": names.get(C, C), "line_by": names.get(a, a), "meant_for": ", ".join(str(names.get(o, o)) for o in others), "heard": heard, "said": det.get("reply", {}).get("say") if isinstance(det.get("reply"), dict) else None})
    out["false_replies"], out["group_talk"], out["overheard_turns"], out["listen_false"] = false, group, overheard, in_listen
    out["false_examples"] = false_ex[:5]
    # Cost: the journal's calls over the run's span.
    j = [r for f in sorted((d / "journal").glob("*.jsonl")) for r in jl(f)] if (d / "journal").exists() else []
    at = [r["at_ms"] for r in j if r.get("at_ms")] + [s["at_ms"] for s in speech]
    span_min = (max(at) - min(at)) / 60000 if len(at) > 1 else None
    tok = sum(r.get("tokens") or 0 for r in j)
    ttok = sum(r.get("tokens") or 0 for r in j if r.get("purpose") == "talk")
    usd = sum((trials.cost(r.get("model"), r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0) or 0) for r in j)
    turns = sum(1 for t in talk if t["actor"] != P)
    out["turns_min"] = round(turns / span_min, 2) if span_min else None
    out["tok_min"] = round(tok / span_min) if span_min else None
    out["talk_tok_min"] = round(ttok / span_min) if span_min else None
    out["usd_h"] = round(usd / span_min * 60, 3) if span_min else None
    out["minutes"] = round(span_min, 1) if span_min else None
    return out


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"
    return str(v)


def spread(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "–"
    m = statistics.mean(vals)
    return f"{fmt(round(m, 2))} ({fmt(min(vals))}–{fmt(max(vals))})" if len(vals) > 1 else fmt(round(m, 2))


COLS = ["n", "crowded", "answered", "answered_5s", "lat_med", "lat_p90", "by_nearest", "by_addressed", "by_turn"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--root", default=str(OUT))
    ap.add_argument("--examples", type=int, default=3)
    a = ap.parse_args()
    runs = []
    for b in a.batches:
        bdir = Path(b) if Path(b).is_dir() else Path(a.root) / b
        for d in sorted(p for p in bdir.iterdir() if p.is_dir() and (p / "speech.jsonl").exists()):
            s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
            r = run(d)
            r["batch"], r["variant"] = bdir.name, s.get("variant") or re.sub(r"-r\d+$", "", d.name.split("-", 1)[-1])
            runs.append(r)
    if not runs:
        sys.exit("no greet runs (speech.jsonl) found")
    head = ["batch", "run"] + [f"{k[:2]}.{c}" for k in ("unaddressed", "addressed") for c in COLS] + ["false", "overheard", "listen_false", "turns_min", "talk_tok_min", "tok_min", "usd_h", "min"]
    print("Per run (un. = to no one, ad. = addressed):\n")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in runs:
        vals = [r["batch"], r["run"]] + [r["lines"][k][c] for k in ("unaddressed", "addressed") for c in COLS] + [r["false_replies"], r["overheard_turns"], r["listen_false"], r["turns_min"], r["talk_tok_min"], r["tok_min"], r["usd_h"], r["minutes"]]
        print("| " + " | ".join(fmt(v) for v in vals) + " |")
    print("\nMean (range) per batch x variant:\n")
    groups = defaultdict(list)
    for r in runs:
        groups[(r["batch"], r["variant"])].append(r)
    keys = ["answered", "answered_5s", "lat_med", "lat_p90"]
    head = ["batch", "variant", "runs"] + [f"{k[:2]}.{c}" for k in ("unaddressed", "addressed") for c in keys] + ["false", "turns_min", "talk_tok_min", "tok_min", "usd_h"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for (b, v), rs in sorted(groups.items()):
        vals = [b, v, str(len(rs))] + [spread([r["lines"][k][c] for r in rs]) for k in ("unaddressed", "addressed") for c in keys]
        vals += [spread([r[c] for r in rs]) for c in ("false_replies", "turns_min", "talk_tok_min", "tok_min", "usd_h")]
        print("| " + " | ".join(vals) + " |")
    if a.examples:
        print("\nExamples:")
        for r in runs:
            ex = r["examples"]
            shown = [x for x in ex if x["answered"]][: a.examples] + [x for x in ex if not x["answered"]][: a.examples]
            for x in shown:
                who = f"{x['by_name']} after {x['latency']:.1f} s{' (nearest)' if x['by'] == x['nearest'] else ''}{' (turn)' if x['turn'] else ''}: “{x['answer']}”" if x["answered"] else f"no answer (nearest {x['nearest_name']}, {x['close']} within {ADDRESS_M:.0f} m)"
                print(f"- {r['run']} {x['kind']} “{x['text']}” → {who}")
            for f in r["false_examples"][: a.examples]:
                print(f"- {r['run']} false reply: {f['by']} answered {f['line_by']}'s “{f['heard']}” (meant for {f['meant_for']}): “{f['said']}”")


if __name__ == "__main__":
    main()
