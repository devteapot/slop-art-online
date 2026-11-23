#!/usr/bin/env python3
"""gate216-confirm drift sampler, until killed: every 10 s the SpacetimeDB server's RSS/HWM (host PID of the
container's main process and its children), the container cgroup's memory.current, and the RSS of the run's
relay-proto and gate-load processes; every 60 s the server's /metrics lines about table rows and memory (one
HTTP read, no SQL in the tick). Usage: mem.py CONTAINER URL OUT.jsonl"""
import json, os, re, subprocess, sys, time, urllib.request
C, URL, OUT = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
KEEP = re.compile(r"(row|table|memory|bytes|wasm|instance|heap)", re.I)

def status(pid):
    d = {}
    try:
        for l in open(f"/proc/{pid}/status"):
            if l.startswith(("VmRSS", "VmHWM")):
                d[l.split(":")[0]] = int(l.split()[1])
    except OSError:
        pass
    return d

def tree(pid):
    out = [pid]
    try:
        for t in os.listdir(f"/proc/{pid}/task"):
            for c in open(f"/proc/{pid}/task/{t}/children").read().split():
                out += tree(int(c))
    except OSError:
        pass
    return out

info = subprocess.run(["docker", "inspect", C, "--format", "{{.State.Pid}} {{.Id}}"], capture_output=True, text=True).stdout.split()
spid, cid = int(info[0]), info[1]
cg = next((p for p in (f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/memory.current", f"/sys/fs/cgroup/docker/{cid}/memory.current") if os.path.exists(p)), None)
last_metrics = 0
with open(OUT, "a") as fh:
    while True:
        t = time.time()
        rec = {"t": round(t, 3), "server": {p: status(p) for p in tree(spid)}}
        if cg:
            try:
                rec["cgroup_bytes"] = int(open(cg).read())
            except OSError:
                pass
        for name in ("relay-proto", "gate-load"):
            r = subprocess.run(["pgrep", "-f", f"slop-gate216-marker/target/release/{name}"], capture_output=True, text=True)
            rec[name] = {int(p): status(int(p)).get("VmRSS") for p in r.stdout.split()}
        if t - last_metrics >= 60:
            last_metrics = t
            try:
                body = urllib.request.urlopen(f"{URL}/v1/metrics", timeout=10).read().decode()
                rec["metrics"] = [l for l in body.splitlines() if l and not l.startswith("#") and KEEP.search(l.split("{")[0])]
            except Exception as e:
                rec["metrics_error"] = str(e)
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        time.sleep(max(0.0, 10.0 - (time.time() - t)))
