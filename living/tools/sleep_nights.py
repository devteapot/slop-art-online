#!/usr/bin/env python3
"""How many people reorganize per game night (docs/MIND_HARNESS.md, item 2), on scratch
databases through the shared verify harness, with a fake model.

  living/tools/sleep_nights.py --tag T [--seed world] [--minutes 45] [--modes timer night-batch]

Each mode gets its own `verify-sleep-<tag>-<mode>` database and a mind service thinking for
every person (LIVING_ONLY), Neo4j off (whether a mind is due depends only on how many
integrations it made and when it last slept, which the service tracks itself). The count is
read from the service's `sleep:` log lines (one per completed reorganization, with its night)
and its `night N:` lines (how many were due and sent). Evidence:
`.local/living/verify/sleep-<tag>-<mode>/` and `.local/living/sleep-nights/<tag>/report.json`.
"""
import argparse, json, os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / ".agents/skills/verify/scripts/verify.py"
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
STDB = ROOT / "living/tools/stdb"
MIND = Path(os.environ.get("LIVING_MIND_BIN") or Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target") / "release/living-mind")
STDB_URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300")


def harness(run, *args):
    r = subprocess.run([str(VERIFY), args[0], "--run", run, *args[1:]], cwd=ROOT, capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise RuntimeError(f"verify.py {args[0]} {run}: {r.stderr[-1500:]}{r.stdout[-1500:]}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seed", default="world")
    ap.add_argument("--minutes", type=float, default=45)
    ap.add_argument("--modes", nargs="+", default=["timer", "night-batch"])
    a = ap.parse_args()
    tok = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", subprocess.run([str(STDB), "login", "show", "--token"], capture_output=True, text=True).stdout)[0]
    out = ROOT / ".local/living/sleep-nights" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    runs = {}
    target = ["--target-dir", str(Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target") / f"seed-{a.seed}")] if a.seed != "world" else []
    try:
        for mode in a.modes:
            run = f"sleep-{a.tag}-{mode}"
            d = ROOT / ".local/living/verify" / run
            runs[mode] = {"run": run, "dir": d, "procs": []}
            harness(run, "launch", "--seed", a.seed, *target)
            people = [r["id"] for r in json.loads(harness(run, "sql", "SELECT id, kind, alive, stage FROM character")) if r["kind"] == "person" and r["alive"] and r["stage"] >= 1]
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            log = (d / "fake-server.log").open("w")
            runs[mode]["procs"].append(subprocess.Popen([sys.executable, str(FAKE), "--port", str(port), "--log", str(d / "fake-requests.jsonl")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT))
            time.sleep(1.5)
            models = {"default": "fake", "profiles": {"fake": {"base_url": f"http://127.0.0.1:{port}/v1", "model": "fake-town", "key_env": "LIVING_VERIFY_FAKE_KEY", "max_tokens": 1024, "requests_per_minute": 60000}}}
            (d / "models.json").write_text(json.dumps(models))
            env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=STDB_URL, LIVING_DB=f"verify-{run}", LIVING_RUN=f"verify-{run}", LIVING_SEED=a.seed,
                       LIVING_MODELS=str(d / "models.json"), LIVING_NEO4J="off", LIVING_NEO4J_PASSWORD="", LIVING_ONLY=",".join(map(str, people)), LIVING_LLM_PER_MIN="0",
                       LIVING_CONCURRENCY="64", LIVING_TOKEN=tok, LIVING_VERIFY_FAKE_KEY="local-only", LIVING_LOD="0", LIVING_PLAYER_MEMORY="0",
                       LIVING_REORGANIZE=mode, NO_PROXY="127.0.0.1,localhost", RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
            mlog = (d / "mind.log").open("w")
            runs[mode]["procs"].append(subprocess.Popen([str(MIND)], cwd=ROOT, env=env, stdout=mlog, stderr=subprocess.STDOUT))
            runs[mode]["people"] = len(people)
            runs[mode]["started"] = time.time()
            print(f"{mode}: {run}, {len(people)} people", flush=True)
        time.sleep(a.minutes * 60)
    finally:
        for mode, r in runs.items():
            r["seconds"] = time.time() - r.get("started", time.time())
            for p in reversed(r["procs"]):
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    p.kill()
            j = ROOT / ".local/living/journal" / f"verify-{r['run']}"
            if j.exists():
                shutil.rmtree(j)  # fake exchanges; the mind log is the evidence
            harness(r["run"], "cleanup")
    report = {}
    for mode, r in runs.items():
        text = (r["dir"] / "mind.log").read_text()
        slept = re.findall(r"sleep: (.+?) slept \((\w+), night (Some\((\d+)\)|None), after (\d+) integrations\)", text)
        per_night = {}
        for name, how, _, night, n in slept:
            per_night.setdefault(night or "day", set()).add(name)
        sent = [dict(zip(("night", "sent", "of", "batch", "direct", "due"), map(int, m))) for m in re.findall(r"night (\d+): (\d+) of (\d+) minds go to sleep \((\d+) in a batch, (\d+) direct; (\d+) due\)", text)]
        report[mode] = {"people": r["people"], "minutes": round(r["seconds"] / 60, 1), "reorganizations": len(slept), "distinct_people": len({s[0] for s in slept}),
                        "by_night": {k: len(v) for k, v in sorted(per_night.items())}, "sends": sent,
                        "integrations": len(re.findall(r" integrated \d+ experiences", text))}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
