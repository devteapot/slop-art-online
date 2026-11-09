#!/usr/bin/env python3
"""Animal minds A/B: calls and tokens per animal-hour for each `LIVING_ANIMAL_MINDS` variant
(docs/MIND_HARNESS.md, item 3), on scratch databases through the shared verify harness.

  living/tools/animal_minds.py run --tag T [--seed stage1-wolves] [--minutes 20]
                                   [--variants today salient choose pack all] [--real PROFILE]
  living/tools/animal_minds.py report --tag T

Each variant gets its own `verify-animals-<tag>-<variant>` database from the same seed, its own
mind service thinking for the animals only (`LIVING_ONLY`; the people live by instinct, so
animals near them ask for thoughts as in a lab) and, unless `--real`, its own fake model server
(.agents/skills/verify-llm/scripts/fake_llm.py, which rotates animal choices). Variants run at
the same time. Evidence: `.local/living/verify/animals-<tag>-<variant>/` (journal copy, fake
requests, mind log, thoughts) and `.local/living/animal-minds/<tag>/report.{json,md}`.

With `--real PROFILE` the minds call that profile of living/configs/models.json (paid; the
key comes from the environment). Neo4j is off in every variant, so recall is empty alike.
"""
import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / ".agents/skills/verify/scripts/verify.py"
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
STDB = ROOT / "living/tools/stdb"
MIND = Path(os.environ.get("LIVING_MIND_BIN") or Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target") / "release/living-mind")
OUT = ROOT / ".local/living/animal-minds"
SWITCHES = {"today": "", "salient": "salient", "choose": "choose", "pack": "pack,choose", "all": "salient,choose,pack"}
STDB_URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300")


def sh(args, **kw):
    return subprocess.run([str(a) for a in args], cwd=ROOT, capture_output=True, text=True, **kw)


def harness(run, *args):
    r = sh([VERIFY, args[0], "--run", run, *args[1:]], timeout=900)
    if r.returncode:
        raise RuntimeError(f"verify.py {args[0]} {run}: {r.stderr[-2000:]}{r.stdout[-2000:]}")
    return r.stdout


def sql(run, q):
    return json.loads(harness(run, "sql", q))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def token():
    r = sh([STDB, "login", "show", "--token"], timeout=30)
    m = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", r.stdout)
    if len(m) != 1:
        sys.exit("no admin token from living/tools/stdb login show --token")
    return m[0]


def models_for(port, real):
    if real:
        m = json.loads((ROOT / "living/configs/models.json").read_text())
        m["default"] = real
        m["species"] = {k: {"think": real, "remember": real, "compile": real} for k in ("deer", "wolf")}
        m["groups"], m["stages"], m["assign"], m["rotate"] = {}, {}, {}, []
        return m
    p = {"base_url": f"http://127.0.0.1:{port}/v1", "model": "fake-animal", "key_env": "LIVING_VERIFY_FAKE_KEY", "max_tokens": 2048, "requests_per_minute": 6000}
    return {"default": "fake", "profiles": {"fake": p}}


def cmd_run(a):
    tok = token()
    out = OUT / a.tag
    out.mkdir(parents=True, exist_ok=True)
    runs = {}
    for v in a.variants:
        run = f"animals-{a.tag}-{v}"
        d = ROOT / ".local/living/verify" / run
        harness(run, "launch", "--seed", a.seed, "--target-dir", str(Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target") / f"seed-{a.seed}"))
        harness(run, "doctor")
        animals = [r["id"] for r in sql(run, "SELECT id, kind, alive FROM character WHERE kind != 'person'") if r["alive"]]
        procs = []
        port = free_port()
        if not a.real:
            log = (d / "fake-server.log").open("w")
            procs.append(subprocess.Popen([sys.executable, str(FAKE), "--port", str(port), "--log", str(d / "fake-requests.jsonl")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT))
            time.sleep(1.5)
        (d / "models.json").write_text(json.dumps(models_for(port, a.real), indent=2))
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=STDB_URL, LIVING_DB=f"verify-{run}", LIVING_RUN=f"verify-{run}", LIVING_SEED=a.seed,
                   LIVING_MODELS=str(d / "models.json"), LIVING_NEO4J="off", LIVING_NEO4J_PASSWORD="", LIVING_ONLY=",".join(map(str, animals)),
                   LIVING_LLM_PER_MIN="0", LIVING_CONCURRENCY="16", LIVING_TOKEN=tok, LIVING_VERIFY_FAKE_KEY="local-only", LIVING_LOD="0",
                   LIVING_ANIMAL_MINDS=SWITCHES[v], LIVING_PLAYER_MEMORY="0", NO_PROXY="127.0.0.1,localhost", RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
        log = (d / "mind.log").open("w")
        procs.append(subprocess.Popen([str(MIND)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT))
        runs[v] = {"run": run, "dir": str(d), "animals": animals, "pids": [p.pid for p in procs], "procs": procs, "started": time.time()}
        print(f"{v}: {run}, {len(animals)} animals, switches '{SWITCHES[v]}'", flush=True)
    try:
        time.sleep(a.minutes * 60)
    finally:
        for v, r in runs.items():
            d = Path(r["dir"])
            r["seconds"] = time.time() - r["started"]
            try:
                (d / "thoughts.json").write_text(json.dumps(sql(r["run"], "SELECT actor, kind, summary, detail, model, tokens FROM thought"), indent=1))
                (d / "animals-end.json").write_text(json.dumps(sql(r["run"], "SELECT id, kind, alive, stage FROM character WHERE kind != 'person'")))
            except Exception as e:  # keep cleaning up
                print(f"{v}: snapshot failed: {e}", flush=True)
            for p in reversed(r["procs"]):
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
            journal = ROOT / ".local/living/journal" / f"verify-{r['run']}"
            if journal.exists():
                shutil.copytree(journal, d / "journal", dirs_exist_ok=True)
                shutil.rmtree(journal)
            harness(r["run"], "cleanup")
            r.pop("procs")
        (out / "runs.json").write_text(json.dumps({"seed": a.seed, "minutes": a.minutes, "real": a.real, "runs": runs}, indent=2))
    cmd_report(a)


def cmd_report(a):
    out = OUT / a.tag
    meta = json.loads((out / "runs.json").read_text())
    rows = {}
    for v, r in meta["runs"].items():
        d = Path(r["dir"])
        hours = r["seconds"] / 3600
        n = len(r["animals"])
        ex = [json.loads(l) for p in (d / "journal").glob("*.jsonl") for l in p.read_text().splitlines() if l.strip()] if (d / "journal").exists() else []
        thoughts = json.loads((d / "thoughts.json").read_text()) if (d / "thoughts.json").exists() else []
        animals = set(r["animals"])
        th = [t for t in thoughts if t["actor"] in animals]
        chars = lambda e: sum(len(m["content"]) for m in e["request"]["messages"])
        delib = [e for e in ex if e["purpose"] == "deliberate"]
        modes = {}
        picks = {}
        valid = 0
        for t in th:
            try:
                det = json.loads(t["detail"]) if t["detail"] else {}
            except ValueError:
                det = {}
            mode = det.get("mode") or ("legacy" if t["kind"] == "deliberate" else t["kind"])
            modes[mode] = modes.get(mode, 0) + 1
            if det.get("mode") == "choose":
                valid += bool(det.get("valid_pick"))
                lab = det["options"][det["pick"]] if det.get("pick") is not None else "invalid"
                verb = lab.split(" ")[0]
                picks[verb] = picks.get(verb, 0) + 1
        real_in = sum(e.get("prompt_tokens") or 0 for e in delib)
        real_out = sum(e.get("completion_tokens") or 0 for e in delib)
        rows[v] = {
            "animals": n, "hours": round(hours, 3), "animal_hours": round(n * hours, 2),
            "calls": len(ex), "deliberate_calls": len(delib), "consolidate_calls": sum(e["purpose"] == "consolidate" for e in ex),
            "errors": sum(bool(e.get("error")) for e in ex),
            "deliberate_calls_per_animal_hour": round(len(delib) / max(n * hours, 1e-9), 2),
            "calls_per_animal_hour": round(len(ex) / max(n * hours, 1e-9), 2),
            "prompt_chars_per_animal_hour": round(sum(chars(e) for e in delib) / max(n * hours, 1e-9)),
            "est_prompt_tokens_per_animal_hour": round(sum(chars(e) for e in delib) / 3.6 / max(n * hours, 1e-9)),
            "real_prompt_tokens": real_in, "real_completion_tokens": real_out,
            "thoughts": len(th), "thought_modes": modes, "errors_thoughts": sum(t["kind"] == "error" for t in th),
            "choices": picks, "valid_picks": valid,
            "installed": sum(t["kind"] == "deliberate" for t in th),
        }
    (out / "report.json").write_text(json.dumps(rows, indent=2))
    cols = ["animals", "animal_hours", "deliberate_calls", "deliberate_calls_per_animal_hour", "est_prompt_tokens_per_animal_hour", "consolidate_calls", "thoughts", "installed", "errors_thoughts", "thought_modes", "choices"]
    md = "| variant | " + " | ".join(cols) + " |\n|" + " --- |" * (len(cols) + 1) + "\n"
    for v, r in rows.items():
        md += f"| {v} | " + " | ".join(str(r[c]) for c in cols) + " |\n"
    (out / "report.md").write_text(md)
    print(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("run")
    p.add_argument("--tag", required=True)
    p.add_argument("--seed", default="stage1-wolves")
    p.add_argument("--minutes", type=float, default=20)
    p.add_argument("--variants", nargs="+", default=list(SWITCHES), choices=list(SWITCHES))
    p.add_argument("--real", help="a profile of living/configs/models.json (paid)")
    p.set_defaults(f=cmd_run)
    p = sub.add_parser("report")
    p.add_argument("--tag", required=True)
    p.set_defaults(f=cmd_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
