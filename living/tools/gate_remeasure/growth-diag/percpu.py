#!/usr/bin/env python3
"""Every second until killed: each CPU's busy share (from /proc/stat) and the 1-min load. Usage: percpu.py OUT.jsonl"""
import json, sys, time
def read():
    out = {}
    for l in open("/proc/stat"):
        if l.startswith("cpu") and l[3].isdigit():
            f = l.split(); v = list(map(int, f[1:9])); out[int(f[0][3:])] = (sum(v) - v[3] - v[4], sum(v))
    return out
prev = read()
with open(sys.argv[1], "a") as fh:
    while True:
        time.sleep(1); cur = read(); t = time.time()
        busy = {c: round((cur[c][0] - prev[c][0]) / max(1, cur[c][1] - prev[c][1]), 3) for c in cur}
        prev = cur
        fh.write(json.dumps({"t": round(t, 2), "load1": float(open("/proc/loadavg").read().split()[0]), "busy": busy}) + "\n"); fh.flush()
