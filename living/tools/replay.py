#!/usr/bin/env python3
"""Replay recorded model requests from lab journals, to test prompt changes in minutes.

Picks deliberation (or talk) requests from `.local/living/journal/<run>/` whose reason for
thinking contains `--reason` (and optionally only by day), sends them again to the model as
recorded, or with the current mind's deliberation prompt rebuilt is out of scope: this sends
the recorded messages, optionally transformed by `--variant`, and counts replies matching
`--count` (a regex), e.g. acts of a kind.

  living/tools/replay.py --reason "long for" --day --count '"do"\\s*:\\s*"conceive"' --n 12
  living/tools/replay.py --purpose talk --reason "family" --variant why_first

Variants: `as_recorded` (default) and `why_first` (the reason moved to the top). Add more
in VARIANTS. The API key is read from `.env` (MISTRAL_API_KEY) and never printed.
"""
import argparse
import concurrent.futures as cf
import glob
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WHY = "# Why you are thinking now"


def why_first(msgs):
    u = msgs[-1]["content"]
    if WHY not in u or u.startswith(WHY):
        return msgs
    head, why = u.split(WHY, 1)
    msgs[-1]["content"] = WHY + why.split("Respond with")[0] + "\n\n" + head + "\nRespond with the JSON object."
    return msgs


VARIANTS = {"as_recorded": lambda m: m, "why_first": why_first}


def reason_of(u):
    return u.split(WHY, 1)[1][:400] if WHY in u else u[-400:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labs", default="stage1-base,stage1-scarce,stage1-wolves")
    ap.add_argument("--purpose", default="deliberate")
    ap.add_argument("--reason", default="", help="substring of the reason for thinking")
    ap.add_argument("--day", action="store_true", help="only requests made by day")
    ap.add_argument("--count", default=r'"do"\s*:\s*"conceive"', help="regex counted in replies")
    ap.add_argument("--variant", action="append", help="variant(s) to run (default as_recorded)")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--model", default="mistral-small-latest")
    a = ap.parse_args()
    key = next(l.split("=", 1)[1].strip().strip('"') for l in open(ROOT / ".env") if l.startswith("MISTRAL_API_KEY="))
    reqs = []
    for lab in a.labs.split(","):
        for run in sorted(glob.glob(str(ROOT / f".local/living/journal/{lab}-*")))[-3:]:
            for f in glob.glob(run + "/*.jsonl"):
                for line in open(f):
                    r = json.loads(line)
                    if r.get("purpose") != a.purpose or not r.get("request"):
                        continue
                    u = r["request"]["messages"][-1]["content"]
                    if a.reason not in reason_of(u) or (a.day and '"night":false' not in u.replace(" ", "")):
                        continue
                    reqs.append(r["request"]["messages"])
    reqs = reqs[: a.n]
    print(f"{len(reqs)} requests")

    def call(msgs):
        body = json.dumps({"model": a.model, "messages": msgs, "response_format": {"type": "json_object"}}).encode()
        req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", body, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            return f"ERR {str(e)[:80]}"

    for v in a.variant or ["as_recorded"]:
        with cf.ThreadPoolExecutor(8) as ex:
            outs = list(ex.map(lambda m: call(VARIANTS[v]([dict(x) for x in m])), reqs))
        hits = sum(1 for o in outs if re.search(a.count, o))
        print(f"{v}: {hits}/{len(outs)} match {a.count!r}")
        for o in outs[:3]:
            try:
                j = json.loads(o)
                print("   ", (j.get("thought") or "")[:220], "| acts:", j.get("acts"))
            except ValueError:
                print("   ", o[:220])


if __name__ == "__main__":
    main()
