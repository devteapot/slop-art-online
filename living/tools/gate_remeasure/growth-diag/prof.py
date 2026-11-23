#!/usr/bin/env python3
"""growth-diag sampler, beside one long gate-case run on a private server holding ONE database.

Waits for RUN_DIR/v0/load.log (battle_viewers' window start), then every PERIOD s (k = 0, 1, ...):
  at t0 + k*P        a snapshot S0: the database's /metrics lines (every table's rows and bytes,
                     reducer wasm time, rows scanned/inserted/deleted, wasm memory), jemalloc/page
                     pool, server thread CPU by thread name (/proc), cgroup memory.current;
  at t0 + k*P + 20   snapshot S1, then set_profile(true) (admin, the profile_detail law decides L2);
  at t0 + k*P + 20+ON set_profile(false), snapshot S2.
So [S2(k), S1(k+1)] is an unprofiled 50 s interval and [S1, S2] the profiled one (spans in the
replica's module log, read afterwards). Ends when the database is gone from /metrics.
Usage: prof.py CONTAINER URL RUN_DIR OUT.jsonl [PERIOD=60] [ON=10]"""
import json, os, re, subprocess, sys, time, urllib.request

C, URL, RUN, OUT = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3], sys.argv[4]
P = float(sys.argv[5]) if len(sys.argv) > 5 else 60.0
ON = float(sys.argv[6]) if len(sys.argv) > 6 else 10.0
fh = open(OUT, "a")


def out(rec):
    fh.write(json.dumps(rec) + "\n")
    fh.flush()


def metrics():
    return urllib.request.urlopen(f"{URL}/v1/metrics", timeout=30).read().decode()


def ident_of(text):
    ids = set(re.findall(r'spacetime_worker_wasm_memory_bytes\{database_identity="([0-9a-f]+)"', text))
    return ids


def token():
    s = subprocess.run(["docker", "exec", C, "spacetime", "login", "show", "--token"], capture_output=True, text=True).stdout
    f = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", s)
    assert len(f) == 1
    return f[0]


def call(db, reducer, args, tok):
    req = urllib.request.Request(f"{URL}/v1/database/{db}/call/{reducer}", data=json.dumps(args).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code


info = subprocess.run(["docker", "inspect", C, "--format", "{{.State.Pid}} {{.Id}}"], capture_output=True, text=True).stdout.split()
spid, cid = int(info[0]), info[1]
cg = next((p for p in (f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/memory.current", f"/sys/fs/cgroup/docker/{cid}/memory.current") if os.path.exists(p)), None)


def threads():
    d = {}
    for tid in os.listdir(f"/proc/{spid}/task"):
        try:
            st = open(f"/proc/{spid}/task/{tid}/stat").read()
        except OSError:
            continue
        name = st[st.index("(") + 1: st.rindex(")")]
        f = st[st.rindex(")") + 2:].split()
        key = re.sub(r"\d+$", "N", name)
        d[key] = d.get(key, 0) + int(f[11]) + int(f[12])
    return d


def snap(tag, k, db):
    t = time.time()
    try:
        text = metrics()
    except Exception as e:
        out({"t": t, "tag": tag, "k": k, "error": str(e)})
        return None
    lines = [l for l in text.splitlines() if l and not l.startswith("#") and (db in l or l.startswith(("jemalloc_", "page_pool", "bsatn_rlb")))]
    rec = {"t": round(t, 3), "tag": tag, "k": k, "threads": threads(), "metrics": lines}
    if cg:
        try:
            rec["cgroup_bytes"] = int(open(cg).read())
        except OSError:
            pass
    try:
        rec["load1"] = float(open("/proc/loadavg").read().split()[0])
    except OSError:
        pass
    out(rec)
    return db in text


load_log = os.path.join(RUN, "v0", "load.log")
while not os.path.exists(load_log):
    time.sleep(0.5)
t0 = time.time()
ids = ident_of(metrics())
assert len(ids) == 1, f"one database expected, found {ids}"
db = ids.pop()
tok = token()
out({"t": t0, "tag": "start", "db": db, "period": P, "on": ON})


def until(t):
    time.sleep(max(0.0, t - time.time()))


k = 0
while True:
    base = t0 + k * P
    until(base)
    if not snap("S0", k, db):
        break
    until(base + 20)
    snap("S1", k, db)
    ton = time.time()
    s_on = call(db, "set_profile", [True], tok)
    until(base + 20 + ON)
    s_off = call(db, "set_profile", [False], tok)
    toff = time.time()
    out({"t": toff, "tag": "prof", "k": k, "on_t": ton, "off_t": toff, "on_status": s_on, "off_status": s_off})
    if s_off not in (200, 204) and s_on not in (200, 204):
        snap("S2", k, db)
        break
    if not snap("S2", k, db):
        break
    k += 1
out({"t": time.time(), "tag": "end", "k": k})
