#!/usr/bin/env python3
"""Every second until killed: which CPU each busy thread of the SpacetimeDB server (and of the
run's host-side processes: gate-load, relay_proto, battle_viewers, poller) last ran on, its CPU ms
in that second, and the cpufreq of every core. Usage: cores.py CONTAINER OUT.jsonl"""
import json, os, subprocess, sys, time
C, OUT = sys.argv[1], sys.argv[2]
HZ = os.sysconf("SC_CLK_TCK")

def tasks(pid):
    out = {}
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return out
    for tid in tids:
        try:
            s = open(f"/proc/{pid}/task/{tid}/stat").read()
        except OSError:
            continue
        name = s[s.index("(") + 1:s.rindex(")")]
        f = s[s.rindex(")") + 2:].split()
        out[(pid, tid)] = (name, int(f[11]) + int(f[12]), int(f[36]))
    return out

def host_pids():
    r = subprocess.run(["pgrep", "-f", "slop-gate216-marker/target|slop-gate216-marker/src/living/tools"], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split() if int(x) != os.getpid()]

def freqs():
    d = {}
    for c in range(20):
        try:
            d[c] = int(open(f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq").read()) // 1000
        except OSError:
            pass
    return d

spid = int(subprocess.run(["docker", "inspect", C, "--format", "{{.State.Pid}}"], capture_output=True, text=True).stdout.strip())
prev = {}
with open(OUT, "a") as fh:
    while True:
        t = time.time()
        cur = tasks(spid)
        hp = host_pids()
        for p in hp:
            cur.update(tasks(p))
        busy = []
        for k, (name, ticks, cpu) in cur.items():
            d = ticks - prev.get(k, (None, ticks, None))[1]
            if d > 0 or name.startswith("wasm"):
                busy.append({"pid": k[0], "tid": int(k[1]), "name": name, "cpu": cpu, "ms": round(d * 1000 / HZ), "server": k[0] == spid})
        prev = cur
        fh.write(json.dumps({"t": round(t, 3), "load1": float(open("/proc/loadavg").read().split()[0]), "freq_mhz": freqs(), "threads": busy}) + "\n")
        fh.flush()
        time.sleep(max(0.0, 1.0 - (time.time() - t)))
