#!/usr/bin/env python3
"""Every second until killed: wall time, the server's per-thread CPU (clock ticks, by name), and
the tick reducer's count/sum and duration histogram buckets from /v1/metrics. JSON lines."""
import json, os, re, subprocess, sys, time, urllib.request
container, url, path = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
pid = int(subprocess.run(["docker", "inspect", container, "--format", "{{.State.Pid}}"], capture_output=True, text=True, check=True).stdout.strip())
def threads():
    out = {}
    for tid in os.listdir(f"/proc/{pid}/task"):
        try:
            st = open(f"/proc/{pid}/task/{tid}/stat").read()
        except OSError:
            continue
        name = st[st.index("(") + 1: st.rindex(")")]
        f = st[st.rindex(")") + 2:].split()
        out[tid] = [name, int(f[11]) + int(f[12]), int(f[36]) if len(f) > 36 else None]
    return out
with open(path, "a") as fh:
    while True:
        t = time.time()
        rec = {"t": round(t, 3), "threads": threads()}
        try:
            text = urllib.request.urlopen(f"{url}/v1/metrics", timeout=10).read().decode()
            rec["tick"] = {l.rsplit(" ", 1)[0]: float(l.rsplit(" ", 1)[1]) for l in text.splitlines()
                           if 'reducer="tick"' in l and not l.startswith("#")}
        except Exception as e:
            rec["err"] = str(e)
        fh.write(json.dumps(rec) + "\n"); fh.flush()
        time.sleep(max(0.0, 1.0 - (time.time() - t)))
