#!/usr/bin/env python3
"""The spacing reflex's ecology check (docs/PACK_MIND.md §7, decision 1): wolves, deer and
people over two game days on the island as shipped, with the reflex on against off.

  living/tools/pack_ecology.py start --run eco-reflex-on-1 --arm on
  living/tools/pack_ecology.py start --run eco-law-off-1 --arm none --seed ../../.local/living/pack-ecology/seeds/island-noreflex
  living/tools/pack_ecology.py sample --run eco-reflex-on-1 --out DIR      (wolf_ecology.py sample)
  living/tools/wolf_ecology.py report DIR...                                  (the numbers)

`start` publishes a fresh island world through the verify harness (`verify.py launch --seed
island`). With `--arm on`, every grown wolf alive then gets its own starting instinct
(`wolf_bold` for a wolf whose background is bold, else `wolf`) with the reflex desire beside each
hunt (`pack_arena_trials.with_reflex`), through `set_behavior`, as an arena installs a graph; the
ids and graphs go to `DIR/arm.json`. Wolves born or grown up during the run live by the shipped
instincts. With `--arm off` or `--arm none` nothing is changed: since `pack-reflex-on`, the world's
own `pack_reflex` law decides what its wolves are given at creation (`none`, with `--seed` naming a
seed whose `rules` turn it off for the off arm). No mind service, no model calls.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
sys.path.insert(0, str(ROOT / "living/tools"))
import verify as V  # noqa: E402


def q(db, token, query):
    code, body = V.http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError(f"{code} {body[:300]}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def start(a):
    out = Path(a.out or ROOT / ".local/living/pack-ecology" / a.run)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "launch.txt", "w") as f:
        r = subprocess.run([sys.executable, str(ROOT / ".agents/skills/verify/scripts/verify.py"), "launch", "--run", a.run, "--seed", a.seed] + (["--target-dir", a.target_dir] if a.target_dir else []),
                           cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.exit(f"launch failed: see {out / 'launch.txt'}")
    st = V.load(a.run)
    db, token = st["db"], V.admin_token()
    record = {"run": a.run, "db": db, "arm": a.arm, "wolves": []}
    if a.arm == "on":
        import pack_arena_trials as T
        graphs = {"wolf_bold": T.with_reflex("wolf_bold"), "wolf": T.with_reflex("wolf")}
        bg = {b["id"]: b["text"] for b in q(db, token, "SELECT id, text FROM background")}
        for w in q(db, token, "SELECT id, stage, alive FROM character WHERE kind = 'wolf'"):
            if not w["alive"] or w["stage"] < 2:
                continue
            which = "wolf_bold" if '"bold":true' in bg.get(w["id"], "") else "wolf"
            code, body = V.http(f"/v1/database/{db}/call/set_behavior", [w["id"], json.dumps(graphs[which])], token)
            record["wolves"].append({"id": w["id"], "instinct": which, "status": code, "error": "" if code == 200 else body[:200]})
        record["graphs"] = graphs
    (out / "arm.json").write_text(json.dumps(record, indent=1) + "\n")
    bad = [w for w in record["wolves"] if w["status"] != 200]
    print(f"{a.run}: {a.arm}, {len(record['wolves'])} wolves given the reflex, {len(bad)} refused")
    if bad:
        sys.exit(f"refused: {bad}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--run", required=True)
    s.add_argument("--arm", choices=["on", "off", "none"], required=True)
    s.add_argument("--seed", default="island")
    s.add_argument("--target-dir")
    s.add_argument("--out")
    s.set_defaults(f=start)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
