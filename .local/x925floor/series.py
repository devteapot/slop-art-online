#!/usr/bin/env python3
"""x925-floor series: 0 vs 16 viewers, L0, pinned X925, interleaved. Holds ~/slop-mq/battle.lock
across the whole plan (taken first, nothing else held while waiting). Per run: merge lock free,
load1 < 4, MemAvailable >= 40 GB, disk >= 45 GB; container pinned to 5-9,15-19 for the run and back
to 0-4,10-14 after; battle_viewers under flock -s trial-activity.lock; redo when the measured
window's load exceeds 8 (up to 3 tries)."""
import fcntl, json, os, shutil, subprocess, sys, time
from pathlib import Path
ROOT = Path("/home/gooning/.t3/worktrees/slop-art-online-t3/t3-eacddf65-5240dd2ef1d69529")
OUT = ROOT / ".local/x925floor/runs"
C, URL = "slop-x925floor-20261122", "http://127.0.0.1:3591"
MQ = Path.home() / "slop-mq"
PLAN = sys.argv[1].split(",") if len(sys.argv) > 1 else ["0", "16", "16", "0", "0", "16"]
LEVEL = os.environ.get("X9F_LEVEL", "L0")
PFX = "" if LEVEL == "L0" else LEVEL.lower() + "-"
A725, X925 = "0-4,10-14", "5-9,15-19"
LOG = OUT / "series.log"

def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def load1():
    return float(open("/proc/loadavg").read().split()[0])

def mem_gb():
    return next(int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemAvailable:")) / 1048576

def disk_gb():
    return shutil.disk_usage("/").free / 1e9

def merge_free():
    fd = os.open(MQ / "lock", os.O_RDONLY | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)

def procs(path):
    with open(path, "w") as f:
        subprocess.run(["ps", "-eo", "pid,psr,pcpu,rss,etimes,comm,args", "--sort=-pcpu"], stdout=f, text=True)

def pin(cpus):
    subprocess.run(["docker", "update", "--cpuset-cpus", cpus, C], check=True, capture_output=True)
    return subprocess.run(["docker", "inspect", C, "--format", "{{.HostConfig.CpusetCpus}}"], capture_output=True, text=True).stdout.strip()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    log(f"plan {PLAN} level {LEVEL} commit {commit} dirty={len(dirty.splitlines())}; waiting for battle.lock")
    w0 = time.time()
    bl = open(MQ / "battle.lock", "a")
    fcntl.flock(bl, fcntl.LOCK_EX)
    log(f"battle.lock taken after {time.time() - w0:.0f} s")
    counts = {}
    try:
        for n in PLAN:
            counts[n] = counts.get(n, 0) + 1
            rep = counts[n]
            for attempt in range(1, 4):
                name = f"{PFX}v{n}-r{rep}a{attempt}"
                said = 0
                while True:
                    ok = merge_free() and load1() < 4 and mem_gb() >= 40 and disk_gb() >= 45
                    if ok:
                        break
                    if time.time() - said > 300:
                        log(f"{name}: waiting (merge free {merge_free()}, load {load1()}, mem {mem_gb():.0f} GB, disk {disk_gb():.0f} GB)")
                        said = time.time()
                    time.sleep(15)
                d = OUT / name
                d.mkdir(parents=True, exist_ok=True)
                placement = pin(X925)
                start = {"load1": load1(), "mem_gb": round(mem_gb(), 1), "disk_gb": round(disk_gb(), 1), "cpuset": placement, "t": time.time()}
                procs(d / "procs-start.txt")
                log(f"{name}: start {start}")
                sp = subprocess.Popen(["taskset", "-c", A725, sys.executable, str(ROOT / ".local/x925floor/sampler.py"), C, URL, str(d / "samples.jsonl")],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=open(d / "sampler.err", "w"))
                env = {**os.environ, "LIVING_STDB_CONTAINER": C, "LIVING_STDB_URL": URL}
                cmd = ["flock", "-s", str(MQ / "trial-activity.lock"), "taskset", "-c", A725, sys.executable, str(ROOT / "living/tools/battle_viewers.py"),
                       "--label", f"x9f{name.replace('-', '')}", "--wasm", "x925-cullet.wasm", "--load", str(Path.home() / "slop-x925floor-bin/gate-load"),
                       "--viewers", n, "--seconds", "60", "--warmup", "20",
                       "--tiers", "--cues", "--motion-tables", "--character-tables", "--fighter-tables", "--combat-feed",
                       "--keep-fighters", "1", "--keep-alive", "0.5", "--paused-placement", "--battle-after-placing", "--ring", "10,10",
                       "--detail", *(["--no-profile"] if LEVEL == "L0" else ["--full-log"]), "--out", str(d)]
                (d / "cmd.json").write_text(json.dumps(cmd) + "\n")
                with open(d / "run.log", "w") as rl:
                    rc = subprocess.run(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=rl, stderr=subprocess.STDOUT).returncode
                sp.terminate(); sp.wait(timeout=30)
                procs(d / "procs-end.txt")
                end_pin = pin(A725)
                # The measured window's load, from battle_viewers' own load.log.
                wl = [float(l.split()[1]) for l in open(d / f"v{n}/load.log")] if (d / f"v{n}/load.log").exists() else []
                res = json.loads((d / f"v{n}/result.json").read_text()) if (d / f"v{n}/result.json").exists() else {}
                rec = {"name": name, "viewers": int(n), "rep": rep, "attempt": attempt, "rc": rc, "start": start,
                       "window_load_max": max(wl) if wl else None, "window_load_median": sorted(wl)[len(wl) // 2] if wl else None,
                       "load_end": load1(), "pinned_after": end_pin, "ticks_per_s": res.get("ticks_per_s")}
                (d / "series-run.json").write_text(json.dumps(rec, indent=1) + "\n")
                log(f"{name}: done {rec}")
                if rc == 0 and wl and max(wl) <= 8:
                    break
                log(f"{name}: invalid (rc {rc}, window load max {max(wl) if wl else None}); redo")
    finally:
        try:
            pin(A725)
        except Exception as e:
            log(f"unpin failed: {e}")
        fcntl.flock(bl, fcntl.LOCK_UN)
        bl.close()
        log("battle.lock released")

if __name__ == "__main__":
    main()
