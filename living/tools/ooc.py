"""Out-of-character words: a cheap detector for lines in which a character steps outside the
world (talk of players, the game, AI, NPCs, prompts, simulation, role-play).

Made for the player-frame experiment (`LIVING_FRAME=player`, docs/TRIALS.md "The player
frame"): the frame tells the model it is an AI playing the person, and asks that whatever the
person says or writes stays in the person's own words. This measures what that costs. It is a
word list, not a judge: it over-counts ("a flute player", "the online ledger") and misses
paraphrase, so the lab reads the examples it keeps. Hunting "game" (wild game, game trails) is
not counted.

    python3 living/tools/ooc.py .local/living/trials/<batch>          # per instance, from summary.json
    python3 living/tools/ooc.py --text "As an AI I can't eat berries"  # one line
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# (term, pattern). Case-insensitive unless the pattern sets (?-i:...).
TERMS = [
    ("player", r"\bplayers?\b|\bplayable\b"),
    ("game", r"\bgameplay\b|\bvideo ?games?\b|\b(?<!wild )(?<!small )(?<!big )(?<!hunt )(?<!hunting )(?<!for )(?<!fresh )game\b(?!\s+(?:trails?|animals?|meat|birds?|tracks?|paths?))"),
    ("AI", r"(?-i:\bAIs?\b)|\bA\.I\.|artificial intelligence|language model|\bLLMs?\b|chat ?bot"),
    ("NPC", r"\bNPCs?\b|non-player"),
    ("prompt", r"\bprompts?\b"),
    ("simulation", r"\bsimulat(?:ion|ions|ed|or)\b"),
    ("character", r"\b(?:my|this|your|a player) character\b|\b(?:in|out of|break(?:ing)?) character\b|\bOOC\b"),
    ("role-play", r"\brole-?play"),
    ("mechanics", r"\brespawn|\bXP\b|\blevel(?:ed|ing)? up\b|\blog(?:ged|ging)? (?:in|out|off)\b|\bserver\b|\bonline\b"),
]
_COMPILED = [(name, re.compile(p, re.I)) for name, p in TERMS]


def hits(text):
    """The terms a line matches, in TERMS order (empty: in character as far as words go)."""
    if not text:
        return []
    return [name for name, rx in _COMPILED if rx.search(text)]


def scan(lines, keep=5):
    """Count flagged lines among `lines` (strings): {lines, flagged, terms, examples}."""
    lines = [x for x in lines if isinstance(x, str) and x.strip()]
    terms, examples, flagged = Counter(), [], 0
    for line in lines:
        h = hits(line)
        if h:
            flagged += 1
            terms.update(h)
            if len(examples) < keep:
                examples.append(f"[{', '.join(h)}] {line[:200]}")
    return {"lines": len(lines), "flagged": flagged, "terms": dict(terms.most_common()), "examples": examples}


def private_texts(reply):
    """The free-text fields of a model reply that only the mind sees: a thought, intentions,
    a consolidation's summary and gists, an identity's narrative, goals and why."""
    out = []
    if not isinstance(reply, dict):
        return out
    for k in ("thought", "summary", "plan"):
        if isinstance(reply.get(k), str):
            out.append(reply[k])
    out += [x for x in reply.get("intend") or [] if isinstance(x, str)]
    out += [m.get("gist") for m in reply.get("remember") or [] if isinstance(m, dict)]
    ident = reply.get("identity")
    if isinstance(ident, dict):
        out += [ident.get("narrative"), ident.get("why"), ident.get("calling")]
        out += [x for x in (ident.get("goals") or []) + (ident.get("values") or []) if isinstance(x, str)]
    return [x for x in out if isinstance(x, str)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", nargs="?", help="a trial batch directory (reads each instance's summary.json)")
    ap.add_argument("--text", help="check one line")
    a = ap.parse_args()
    if a.text is not None:
        print(json.dumps(hits(a.text)))
        return
    if not a.batch:
        ap.error("give a batch directory or --text")
    for p in sorted(Path(a.batch).glob("*/summary.json")):
        s = json.loads(p.read_text())
        o = s.get("out_of_character") or {}
        sp, pr = o.get("spoken") or {}, o.get("private") or {}
        print(f"{p.parent.name}: frame {s.get('prompt_frame')}; spoken/written {sp.get('flagged', '?')}/{sp.get('lines', '?')}, private {pr.get('flagged', '?')}/{pr.get('lines', '?')} {sp.get('terms') or ''}")
        for e in sp.get("examples") or []:
            print(f"    {e}")


if __name__ == "__main__":
    sys.exit(main())
