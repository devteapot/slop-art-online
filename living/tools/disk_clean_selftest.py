#!/usr/bin/env python3
"""Self-test of living/tools/disk_clean.py in a throwaway home (docs/TOOLING.md, "Disk").

Builds a fake HOME with a repository, worktrees and fake Cargo target folders aged by
setting their times, then runs disk_clean.py (dry run, then --apply) and checks what went:
a merged worktree's idle target goes; a target a process works in, a fresh worktree on
main's line, a protected checkout, an untagged evidence folder, a folder with a foreign
CACHEDIR.TAG, a symlink and a nested repository stay; a target holding a log keeps the log.
The machine's protected paths: worktrees named in ~/.config/slop-disk/protect.txt or with
--protect, and a target holding a protected path, stay and are reported with their source;
an invalid protect file stops the run with nothing removed. A glob line in the protect file
protects what it matches (an evidence folder's build inside an idle worktree, an outside
target). Of the target folders outside the worktrees that targets.txt names, an idle one
goes; a protected, an active and a busy one stay, and a matching folder that is no Cargo
target is untouched; without targets.txt none is a candidate.
The container part (fake /proc, fake podman, docker, ps and lsof; no real container is asked
anything): SpacetimeDB servers' deleted files held open and deleted databases' directories,
Docker Desktop's VM (Docker.raw, the trim and its back-off, all as macOS), and every refusal and
run of --restart-stdb; the fakes' call logs show nothing but the allowed calls.
Touches nothing outside the temporary directory. Usage: disk_clean_selftest.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

CLEAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disk_clean.py")
SIG = "Signature: 8a477f597d28d172789f06886806bc55\n# This file is a cache directory tag created by cargo.\n"
failures = []

CONTAINERS = r"""
import json, platform, sys
sys.path.insert(0, sys.argv[1])
import disk_clean
platform.system = lambda: sys.argv[2]
srcs = disk_clean.container_mounts()
print(json.dumps({"srcs": srcs, "notes": disk_clean.NOTES, "warnings": disk_clean.WARNINGS}))
"""
NO_MACHINE = ("#!/bin/sh\ncase \"$1 $2\" in 'machine list') {machines}; exit 0 ;; esac\n"
              "echo 'Cannot connect to Podman. Please verify your connection to the Linux system using `podman system connection list`, "
              "or try `podman machine init` and `podman machine start` to manage a new Linux VM' >&2\nexit 125\n")
DOCKER_UP = "#!/bin/sh\nexit 0\n"
DOCKER_DOWN = "#!/bin/sh\necho 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?' >&2\nexit 1\n"


def containers(home, system, podman, docker):
    bin_ = os.path.join(home, "fakebin-" + str(len(os.listdir(home))))
    os.makedirs(bin_)
    for name, text in (("podman", podman), ("docker", docker)):
        if text is None:
            continue  # not installed
        with open(os.path.join(bin_, name), "w") as f:
            f.write(text)
        os.chmod(os.path.join(bin_, name), 0o755)
    r = subprocess.run([sys.executable, "-I", "-c", CONTAINERS, os.path.dirname(CLEAN), system], env={**os.environ, "HOME": home, "PATH": bin_},  # only the fakes
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": r.stdout}


def container_cases(home):
    r = containers(home, "Darwin", NO_MACHINE.format(machines="true"), None)
    expect("podman with no machine (macOS), no docker: a note, not a warning", not r.get("warnings") and any("no machine" in n for n in r.get("notes", [])), r)
    r = containers(home, "Darwin", NO_MACHINE.format(machines="echo podman-machine-default"), DOCKER_UP)
    expect("podman down but docker answers: a note, not a warning", not r.get("warnings") and any("docker answered" in n for n in r.get("notes", [])), r)
    r = containers(home, "Linux", NO_MACHINE.format(machines="true"), DOCKER_DOWN)
    expect("neither answers (Linux): still a warning", r.get("warnings") and not r.get("srcs"), r)


SECTION = r"""
import json, platform, sys, time
sys.path.insert(0, sys.argv[1])
import disk_clean as d
cfg = json.loads(sys.argv[2])
platform.system = lambda: cfg["system"]
d.PROC = cfg.get("proc", d.PROC)
d.TRIM_SETTLE_S, d.STOP_WAIT_S, d.SQL_WAIT_S, d.POLL_S = 0, 1, 1, 0.05
if cfg.get("free_file"):  # free space comes from a file the fake fstrim raises
    d.free_bytes = lambda p="/": int(open(cfg["free_file"]).read())
opts = {"apply": cfg["apply"], "floor": cfg.get("floor", 40), "trim_margin": 10, "docker_raw": cfg.get("raw"), "protected": [],
        "restart_stdb": cfg.get("restart"), "stdb_db": cfg.get("stdb_db", []), "keep_dirs": cfg.get("keep_dirs", False)}
now = time.time()
rl, rd = d.restart_stdb(opts, now) if opts["restart_stdb"] else ([], {})
lines, data = d.container_section(opts, now, restarted=rd.get("restarted", False))
print(json.dumps({"lines": rl + lines, "data": data, "restart": rd}, default=str))
"""
# A fake docker or podman: logs every call, answers from files in its control folder.
FAKE_TOOL = r"""#!/bin/sh
CTL={ctl}
PATH=/usr/bin:/bin  # the fake's own tools; the tool under test sees only the fakes
printf '%s\n' "$(printf '%s' "$*" | tr '\n' ' ')" >> "$CTL/calls"
case "$1" in
  info) [ -e "$CTL/down" ] && {{ echo 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?' >&2; exit 1; }}
        echo "Docker Desktop"; exit 0 ;;
  ps) [ -e "$CTL/ps-fails" ] && {{ echo 'Error: database is locked' >&2; exit 125; }}
      cat "$CTL/ps" 2>/dev/null; exit 0 ;;
  inspect) case "$*" in
             *State.Running*) [ -e "$CTL/stopped" ] && echo false || echo true; exit 0 ;;
             *Mounts*) cat "$CTL/mounts"; exit 0 ;;
           esac
           [ -e "$CTL/inspect-fails" ] && {{ echo 'Error: no such container' >&2; exit 125; }}
           cat "$CTL/inspect"; exit 0 ;;
  unshare) shift; chmod -R u+rx "$CTL"/proc/*/fd 2>/dev/null; exec "$@" ;;
  kill) [ "$2 $3" = "-s INT" ] || {{ echo "fake: kill without -s INT: $*" >&2; exit 98; }}
        [ -e "$CTL/stop-hangs" ] || touch "$CTL/stopped"; exit 0 ;;
  start) rm -f "$CTL/stopped"; [ -e "$CTL/after-paused" ] && cp "$CTL/after-paused" "$CTL/paused"; exit 0 ;;
  exec) case "$*" in
          *" spacetime list"*) [ -e "$CTL/list-fails" ] && {{ echo 'Error: 500 Internal Server Error' >&2; exit 1; }}
                               cat "$CTL/list"; exit 0 ;;
          *" spacetime sql "*) [ -e "$CTL/stopped" ] && {{ echo 'Error: connection refused' >&2; exit 1; }}
                               [ -e "$CTL/sql-fails" ] && {{ echo 'Error: no such table world' >&2; exit 1; }}
                               printf ' paused \n--------\n %s\n' "$(cat "$CTL/paused")"; exit 0 ;;
        esac ;;
  run) case "$*" in
         *fstrim*) [ -e "$CTL/trim-fails" ] && {{ echo 'fstrim: /var/lib: FITRIM ioctl failed: Operation not permitted' >&2; exit 1; }}
                   echo $(( $(cat "$CTL/free") + $(cat "$CTL/trim-gain") )) > "$CTL/free"; echo '/var/lib: 18 GiB (19327352832 bytes) trimmed'; exit 0 ;;
         *" python3 - "*) while [ $# -gt 0 ] && [ "$1" != python3 ]; do shift; done; shift; exec python3 "$@" ;;
         *" rm -rf -- "*) [ -e "$CTL/rm-fails" ] && {{ echo 'rm: cannot remove: Permission denied' >&2; exit 1; }}
                          while [ "$1" != "--" ]; do shift; done; shift
                          for p in "$@"; do rm -rf "$CTL/vol${{p#/data}}"; done; exit 0 ;;
       esac ;;
esac
echo "fake: unexpected call: $*" >&2; exit 99
"""
# Calls that would stop, signal, prune or force anything beyond the one restart under test.
TOUCHY = (" restart ", " stop ", " rm ", " prune ", " pause ", " unpause ", " volume ", " system ", " update ", " --force ", " -a ", " -f ", "-s KILL", "-s TERM")
DATA = "/home/spacetime/.local/share/spacetime/data"
STD = ["/opt/spacetime/spacetimedb-standalone", "start", "--data-dir", DATA]


def tcp(rows):
    head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    return head + "".join(f"   {i}: {l} {r} {st} 00000000:00000000 00:00000000 00000000  1000        0 {ino} 1 0\n" for i, (l, r, st, ino) in enumerate(rows))


LISTEN = ("00000000:0BB8", "00000000:0000", "0A", "9001")  # the server listens on 3000


def fake_proc(root, store, procs):
    """A /proc tree. procs is {pid: {ppid, argv, files: [(name, bytes, deleted)], links: [container
    paths it holds open], sockets: [inodes], tcp: [rows], rootfs, environ}}. Deleted files are real
    files named '<name> (deleted)', so the fd link reads like a deleted file and stat works."""
    os.makedirs(store, exist_ok=True)
    for pid, p in procs.items():
        d = os.path.join(root, str(pid))
        os.makedirs(os.path.join(d, "fd"))
        argv = p["argv"]
        open(os.path.join(d, "stat"), "w").write(f"{pid} ({os.path.basename(argv[0])[:15]}) S {p.get('ppid', 1)} 1 1 0 -1\n")
        open(os.path.join(d, "cmdline"), "wb").write(b"\0".join(a.encode() for a in argv) + b"\0")
        open(os.path.join(d, "environ"), "wb").write(p.get("environ", "HOME=/root").encode() + b"\0")
        n = 3
        for name, size, deleted in p.get("files", []):
            if name.startswith("/memfd:"):
                os.symlink(f"{name} (deleted)", os.path.join(d, "fd", str(n)))
            elif name.startswith("@"):  # a second fd on the file of another fd
                os.symlink(os.readlink(os.path.join(d, "fd", name[1:])), os.path.join(d, "fd", str(n)))
            else:
                path = os.path.join(store, str(pid), name.strip("/") + (" (deleted)" if deleted else ""))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(os.urandom(size))
                os.symlink(path, os.path.join(d, "fd", str(n)))
            n += 1
        for target in p.get("links", []) + [f"socket:[{i}]" for i in p.get("sockets", [])]:
            os.symlink(target, os.path.join(d, "fd", str(n)))
            n += 1
        if "tcp" in p:
            os.makedirs(os.path.join(d, "net"))
            open(os.path.join(d, "net", "tcp"), "w").write(tcp(p["tcp"]))
        if p.get("rootfs"):
            os.symlink(p["rootfs"], os.path.join(d, "root"))


def replicas(vol, live, dead, recent):
    """A server's volume (mounted at /home/spacetime): replica directories, dead ones two hours
    old; returns the container paths the server holds open (live: db.lock, module log, segment;
    dead: the segment only, as SpacetimeDB 2.14.1 leaves it)."""
    links = []
    base = os.path.join(vol, ".local/share/spacetime/data/replicas")
    for r in live + dead + recent:
        for f in ("clog/00000000000000000000.stdb.log", "db.lock", "module_logs/2026-11-13.log", "snapshots/x/snap"):
            os.makedirs(os.path.dirname(os.path.join(base, r, f)), exist_ok=True)
            open(os.path.join(base, r, f), "wb").write(os.urandom(100_000))
        links.append(f"{DATA}/replicas/{r}/clog/00000000000000000000.stdb.log")
        if r in live:
            links += [f"{DATA}/replicas/{r}/db.lock", f"{DATA}/replicas/{r}/module_logs/2026-11-13.log"]
        if r in dead:
            age(os.path.join(base, r), 2)
    return links


def rootfs(ctl, vol):
    fs = os.path.join(ctl, "rootfs-" + os.path.basename(vol))
    os.makedirs(os.path.join(fs, "home"))
    os.makedirs(vol, exist_ok=True)
    os.symlink(vol, os.path.join(fs, "home", "spacetime"))
    os.makedirs(os.path.join(fs, "var", "lib"))
    return fs


def section(home, ctl, cfg, tools):
    """Run restart_stdb and container_section under a fake platform with only the fakes on PATH."""
    bin_ = os.path.join(ctl, "bin")
    os.makedirs(bin_, exist_ok=True)
    for name in os.listdir(bin_):  # only this case's tools
        os.remove(os.path.join(bin_, name))
    for name, kind in tools.items():
        p = os.path.join(bin_, name)
        if kind == "fake":
            open(p, "w").write(FAKE_TOOL.format(ctl=ctl))
        elif kind.startswith("#!"):  # a script of its own (ps, lsof)
            open(p, "w").write(kind)
        else:  # a link to another fake (docker -> podman)
            os.symlink(os.path.join(bin_, kind), p)
            continue
        os.chmod(p, 0o755)
    env = {"HOME": home, "XDG_STATE_HOME": os.path.join(home, "state"), "PATH": bin_}
    before = len(calls(ctl))
    r = subprocess.run([sys.executable, "-I", "-c", SECTION, os.path.dirname(CLEAN), json.dumps(cfg)], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"lines": [], "data": {}, "restart": {}, "text": r.stdout, "calls": []}
    out["text"] = "\n".join(out["lines"])
    out["calls"] = calls(ctl)[before:]
    return out


def calls(ctl):
    try:
        return open(os.path.join(ctl, "calls")).read().splitlines()
    except OSError:
        return []


def vm_cases(home):
    """macOS Docker Desktop, faked: Docker.raw's allocated size, the VM's df, the servers inside
    the VM (probed by this file's own code, as the VM would run it), and the trim (dry run,
    apply, back-off, failure, not needed, not running), then a restart followed by a trim."""
    vhome = os.path.join(home, "mac")
    raw = os.path.join(vhome, "Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw")
    os.makedirs(os.path.dirname(raw))
    with open(raw, "wb") as f:  # sparse: 100 GB apparent, 3 MB allocated
        f.truncate(100 * 1024 ** 3)
        f.seek(0)
        f.write(os.urandom(3 * 1024 ** 2))
    ctl = os.path.join(home, "vmctl")
    os.makedirs(ctl)
    vol = os.path.join(ctl, "vol")
    fs = rootfs(ctl, vol)
    links = replicas(vol, ["2000049"], ["2000001"], [])
    fake_proc(os.path.join(ctl, "proc"), os.path.join(ctl, "store"), {
        1: {"argv": ["/sbin/init"], "rootfs": fs},
        42: {"argv": STD, "rootfs": fs, "links": links, "sockets": ["9001"], "tcp": [LISTEN],
             "files": [("/stdb/data/replicas/7/clog/00001.stdb.log", 2_000_000, True), ("/stdb/data/replicas/9/snap/00001.snap", 1_000_000, True),
                       ("@3", 0, True), ("/memfd:wasm-memory-image", 0, True), ("/stdb/data/control-db/db", 10_000, False)]},
        50: {"argv": ["/usr/bin/containerd"], "files": [("/var/lib/old.log", 500_000, True)]}})
    open(os.path.join(ctl, "ps"), "w").write("aaa\n")
    open(os.path.join(ctl, "inspect"), "w").write("/stdb-laptop\t42\n")
    open(os.path.join(ctl, "mounts"), "w").write(json.dumps([{"Type": "volume", "Name": "stdb-data", "Destination": "/home/spacetime"}])
                                                 + "\t" + json.dumps({"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}]}) + "\n")
    open(os.path.join(ctl, "list"), "w").write(" name | identity \n------+----------\n verify-laptop | c200aa \n")
    open(os.path.join(ctl, "paused"), "w").write("false")
    free = os.path.join(ctl, "free")
    state = os.path.join(vhome, "state", "slop-disk", "vm-trim.json")
    os.makedirs(os.path.dirname(state))
    base = {"system": "Darwin", "apply": False, "floor": 40, "free_file": free, "proc": os.path.join(ctl, "proc")}
    mac_tools = {"docker": "fake", "ps": "#!/bin/sh\nexit 0\n", "lsof": "#!/bin/sh\nexit 1\n"}

    def run(apply=False, gain=0.5, free_gb=34, tools=None, **extra):
        open(free, "w").write(str(int(free_gb * 1024 ** 3)))
        open(os.path.join(ctl, "trim-gain"), "w").write(str(int(gain * 1024 ** 3)))
        r = section(vhome, ctl, {**base, "apply": apply, **extra}, tools or mac_tools)
        r["trims"] = sum("fstrim" in c for c in r["calls"])
        return r

    r = run()
    expect("vm: Docker.raw's allocated size, not its apparent size", "Docker.raw allocated 3 MB (apparent size 100.0 GB)" in r["text"], r["text"])
    expect("vm: the VM's df of /var/lib", re.search(r"/var/lib in the VM: [\d.]+ [GM]B used of [\d.]+ [GM]B, [\d.]+ [GM]B free", r["text"]), r["text"])
    expect("vm: dry run near the floor says it would trim and does not", "would trim /var/lib (dry run)" in r["text"] and r["trims"] == 0, r)
    expect("vm: the servers inside the VM: deleted files (deduplicated; memfd, live files and other programs left out) and deleted databases' dirs",
           "spacetimedb in stdb-laptop (docker, pid 42): 1 live database, 0 clients connected" in r["text"]
           and "holds 2 deleted files (3 MB) of 2 replicas; a restart at a quiet moment frees them" in r["text"]
           and "1 directory of deleted databases still on disk" in r["text"] and "00001.stdb.log" in r["text"]
           and "containerd" not in r["text"] and "old.log" not in r["text"], r["text"])
    r = run(apply=True, gain=0.5)
    st = json.load(open(state)) if os.path.exists(state) else []
    expect("vm: --apply near the floor trims once, free space before and after recorded",
           r["trims"] == 1 and "trimmed /var/lib" in r["text"] and "free 34.0 GB -> 34.5 GB" in r["text"]
           and len(st) == 1 and st[0]["ok"] and st[0]["freed"] == 512 * 1024 ** 2, (r, st))
    r = run(apply=True, gain=20)
    expect("vm: a trim within the hour that freed under 1 GB: back off, no trim", r["trims"] == 0 and "backing off" in r["text"], r)
    os.remove(state)
    open(os.path.join(ctl, "trim-fails"), "w").close()
    r = run(apply=True)
    st = json.load(open(state)) if os.path.exists(state) else []
    expect("vm: a failing trim is reported, recorded, and the report goes on", r["trims"] == 1 and "TRIM FAILED (exit 1" in r["text"]
           and "FITRIM" in r["text"] and len(st) == 1 and not st[0]["ok"] and "holds 2 deleted files" in r["text"], r)
    r = run(apply=True)
    expect("vm: after a failed trim, back off", r["trims"] == 0 and "backing off: the trim at" in r["text"] and "failed" in r["text"], r)
    os.remove(os.path.join(ctl, "trim-fails"))
    os.remove(state)
    r = run(apply=True, free_gb=55)
    expect("vm: free space over floor + margin: no trim", r["trims"] == 0 and "no trim: free 55.0 GB" in r["text"], r)
    open(os.path.join(ctl, "down"), "w").close()
    r = run(apply=True)
    expect("vm: Docker Desktop not running: no trim, said so", r["trims"] == 0 and "Docker Desktop is not running" in r["text"]
           and "not looked at" in r["text"], r)
    os.remove(os.path.join(ctl, "down"))
    r = run(raw=os.path.join(vhome, "elsewhere.raw"))
    expect("vm: --docker-raw that does not exist: said, no trim", "no Docker.raw found (~/elsewhere.raw" in r["text"] and r["trims"] == 0, r["text"])
    r = section(vhome, ctl, {**base, "system": "Linux", "proc": os.path.join(ctl, "none")}, {"docker": "fake"})
    expect("vm: skipped on Linux, and said so", "docker desktop vm: skipped (Linux, not macOS" in r["text"] and "Docker.raw" not in r["text"], r["text"])
    r = run(apply=True, free_gb=55, restart="stdb-laptop", tools={**mac_tools, "lsof": "#!/bin/sh\nprintf 'p777\\ncliving-mind\\n'\n"})
    expect("vm: restart refused while a host process is connected to the published port (lsof)",
           "REFUSED: in use through port 3000: pid 777 (living-mind) is connected to port 3000" in r["text"] and not any(c.startswith(("kill", "start")) for c in r["calls"]), r["text"])
    r = run(apply=True, free_gb=55, restart="stdb-laptop")
    vdir = os.path.join(vol, ".local/share/spacetime/data/replicas")
    expect("vm: a restart inside Docker Desktop removes the deleted database's dir, then trims though free space is over the margin",
           "kill -s INT stdb-laptop" in r["calls"] and not os.path.exists(os.path.join(vdir, "2000001")) and os.path.isdir(os.path.join(vdir, "2000049"))
           and r["trims"] == 1 and "trimmed /var/lib (after the restart" in r["text"], r)
    bad = [c for c in calls(ctl) if c.split()[0] not in ("info", "ps", "inspect", "run", "exec", "kill", "start")
           or (c.startswith("run") and not c.startswith(("run --rm --privileged --pid=host", "run --rm -v stdb-data:/data alpine rm -rf -- /data/")))
           or (c.startswith("exec") and not c.startswith(("exec stdb-laptop spacetime list", "exec stdb-laptop spacetime sql")))
           or any(t in f" {c} " for t in TOUCHY if t != " rm ")]
    expect("vm: docker was asked only to read, probe, trim and the one restart (kill -s INT, rm of listed dirs, start)", not bad, bad)


def held_cases(home):
    """Linux: SpacetimeDB servers' deleted files held open and deleted databases' directories,
    from a fake /proc and fake podman."""
    ctl = os.path.join(home, "heldctl")
    os.makedirs(ctl)
    proc = os.path.join(ctl, "proc")
    vol = os.path.join(ctl, "vol")
    fs = rootfs(ctl, vol)
    links = replicas(vol, ["2000049"], ["2000001", "2000003"], ["2000051"])
    fake_proc(proc, os.path.join(ctl, "store"), {
        90: {"ppid": 1, "argv": ["conmon"]},
        100: {"ppid": 90, "argv": ["/usr/bin/tini", "--"]},  # the container's init; the server is its child
        101: {"ppid": 100, "argv": STD, "rootfs": fs, "links": links, "sockets": ["9001"], "tcp": [LISTEN],
              "files": [("/stdb/data/replicas/c200001/clog/00000.stdb.log", 3_000_000, True), ("/stdb/data/replicas/c200002/clog/00000.stdb.log", 1_000_000, True),
                        ("@3", 0, True), ("/memfd:wasm-memory-image", 0, True), ("/stdb/data/control-db/db", 20_000, False)]},
        200: {"ppid": 190, "argv": STD, "files": [("/stdb/data/control-db/db2", 20_000, False)], "tcp": [LISTEN], "sockets": ["9001"]},
        300: {"argv": ["/usr/bin/python3", "x.py"], "files": [("/tmp/gone", 500_000, True)]},
        400: {"argv": STD, "files": [("/home/me/.local/share/spacetime/data/replicas/1/x", 1_000_000, True)]},
        500: {"ppid": 495, "argv": ["spacetime", "start"], "files": [("/stdb/data/replicas/c2000aa/clog/00000.stdb.log", 2_000_000, True)]},
        602: {"argv": ["/usr/bin/pasta", "-t", "127.0.0.1/3341-3341:3000-3000"]}})  # the port forwarder: not a user
    os.chmod(os.path.join(proc, "500", "fd"), 0)  # a rootless container's sub-uid: unreadable until unshare
    open(os.path.join(ctl, "ps"), "w").write("a\nb\nc\n")
    open(os.path.join(ctl, "inspect"), "w").write("coord-stdb\t100\nquiet-stdb\t200\nlocked-stdb\t500\n")
    cfg = {"system": "Linux", "apply": True, "proc": proc}
    r = section(home, ctl, cfg, {"podman": "fake", "docker": "podman"})
    t = r["text"]
    expect("held: a container's server (a child of its init): deleted files with count, size, top paths, restart advice",
           "spacetimedb in coord-stdb (podman, pid 100): 1 live database, 0 clients connected" in t
           and "holds 2 deleted files (4 MB) of 2 replicas; a restart at a quiet moment frees them" in t
           and "replicas/c200001/clog/00000.stdb.log" in t and t.count("spacetimedb in coord-stdb") == 1, t)
    expect("held: deleted databases' directories (not the live one, not one written in the last 15 min)",
           "2 directories of deleted databases still on disk" in t and "--restart-stdb coord-stdb" in t
           and r["data"]["held"][0]["dead"] == ["2000001", "2000003"] and r["data"]["held"][0]["recent"] == ["2000051"], (t, r["data"]))
    expect("held: memfd, live files and other programs are left out", "wasm-memory" not in t and "control-db" not in t and "/tmp/gone" not in t, t)
    expect("held: an unreadable fd folder is read through podman unshare", "spacetimedb in locked-stdb (podman, pid 500)" in t
           and "holds 1 deleted file (2 MB) of 1 replica;" in t and any(c.startswith("unshare ") for c in r["calls"]), t)
    expect("held: a server outside any container, and one with nothing to free", "spacetimedb on the host (pid 400)" in t
           and "holds 1 deleted file (1 MB) of 1 replica;" in t and "no deleted files or deleted databases' directories: quiet-stdb" in t, t)
    open(os.path.join(ctl, "inspect-fails"), "w").close()
    r = section(home, ctl, cfg, {"podman": "fake", "docker": "podman"})
    expect("held: a failing podman is reported and the report goes on", "note: podman inspect failed (exit 125): Error: no such container" in r["text"]
           and "spacetimedb on the host (pid 400)" in r["text"], r["text"])
    os.remove(os.path.join(ctl, "inspect-fails"))
    os.chmod(os.path.join(proc, "500", "fd"), 0)
    r = section(home, ctl, cfg, {"docker": "fake"})  # no podman: no unshare
    expect("held: unreadable without podman: said, not guessed", "cannot see its files (permission denied" in r["text"]
           and "run the report as root" in r["text"] and "holds 2 deleted files (4 MB)" in r["text"], r["text"])
    os.chmod(os.path.join(proc, "500", "fd"), 0o755)
    bad = [c for c in calls(ctl) if c.split()[0] not in ("ps", "inspect", "unshare") or any(t in f" {c} " for t in TOUCHY)]
    expect("held: the report only asks ps, inspect and unshare (never restart, stop, signal or prune)", not bad, bad)
    restart_cases(home, ctl, proc, vol)


def restart_cases(home, ctl, proc, vol):
    """--restart-stdb on Linux, faked: every refusal, the dry run, a stop that hangs, a failing
    removal, databases that differ afterwards, and a full restart."""
    import fcntl
    tools = {"podman": "fake", "docker": "podman"}
    open(os.path.join(ctl, "mounts"), "w").write(json.dumps([{"Type": "volume", "Name": "coord-stdb-data", "Destination": "/home/spacetime"},
                                                              {"Type": "bind", "Source": "/srv/wasm", "Destination": "/wasm"}])
                                                 + "\t" + json.dumps({"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3341"}]}) + "\n")
    open(os.path.join(ctl, "list"), "w").write(" name | identity \n------+----------\n verify-coord-1 | c200aa \n")
    open(os.path.join(ctl, "paused"), "w").write("true")
    vdir = os.path.join(vol, ".local/share/spacetime/data/replicas")
    cfg = {"system": "Linux", "apply": True, "proc": proc, "restart": "coord-stdb"}
    acts = ("kill", "start", "run")

    def run(**extra):
        r = section(home, ctl, {**cfg, **extra}, tools)
        r["acted"] = [c for c in r["calls"] if c.startswith(acts)]
        return r

    def refused(name, r, text):
        expect(f"restart refused: {name}", f"REFUSED: {text}" in r["text"] and not r["acted"] and os.path.isdir(os.path.join(vdir, "2000001")), r["text"])

    r = run(restart="sao-living_spacetimedb_1")
    refused("the reference worlds' server is never restarted", r, "sao-living_spacetimedb_1 is never restarted")
    expect("restart refused before asking anything for a never-restart name", not r["calls"] or all(not c.startswith("kill") for c in r["calls"]), r["calls"])
    cfgdir = os.path.join(home, ".config", "slop-disk")
    os.makedirs(cfgdir, exist_ok=True)
    open(os.path.join(cfgdir, "never-restart.txt"), "w").write("# this machine\ncoord-stdb\n")
    r = run()
    refused("a container in never-restart.txt", r, "coord-stdb is never restarted")
    expect("report: a never-restart server's hint gives the manual route, not a command it refuses",
           "this tool never restarts coord-stdb" in r["text"] and "--restart-stdb coord-stdb (refused" not in r["text"], r["text"])
    os.remove(os.path.join(cfgdir, "never-restart.txt"))
    refused("a container that is not running", run(restart="gone-stdb"), "no running container is named gone-stdb")
    gate = os.path.join(home, "state", "slop-build", "gate.lock")
    os.makedirs(os.path.dirname(gate), exist_ok=True)
    with open(gate, "w") as g:
        fcntl.flock(g, fcntl.LOCK_EX)
        refused("the scene gate holds gate.lock", run(), "a merge or the scene gate holds ~/state/slop-build/gate.lock")
    merge = os.path.join(home, "state", "slop-merge", "0123456789abcdef.lock")
    os.makedirs(os.path.dirname(merge), exist_ok=True)
    with open(merge, "w") as g:
        fcntl.flock(g, fcntl.LOCK_EX)
        refused("a merge holds its lock", run(), "a merge or the scene gate holds ~/state/slop-merge/0123456789abcdef.lock")
    expect("restart not refused by gate.lock once it is free", "gate.lock" not in run(apply=False)["text"])
    tcpf = os.path.join(proc, "101", "net", "tcp")
    open(tcpf, "w").write(tcp([LISTEN, ("0100007F:0BB8", "0100007F:C738", "01", "9002")]))
    os.symlink("socket:[9002]", os.path.join(proc, "101", "fd", "90"))
    refused("a client is connected (a play session, mind service or observer)", run(), "1 client connected to it (127.0.0.1:51000)")
    os.remove(os.path.join(proc, "101", "fd", "90"))
    open(tcpf, "w").write(tcp([LISTEN]))
    os.rename(tcpf, tcpf + ".x")
    os.rename(os.path.join(proc, "101", "net"), os.path.join(proc, "101", "net.x"))
    refused("its connections cannot be read", run(), "its files or connections cannot be read")
    os.rename(os.path.join(proc, "101", "net.x"), os.path.join(proc, "101", "net"))
    os.rename(tcpf + ".x", tcpf)
    fake_proc(proc, os.path.join(ctl, "store"), {700: {"argv": ["/home/me/bin/living-mind", "--stdb", "http://127.0.0.1:3341"]}})
    refused("a host process names the published port (a mind service)", run(), "in use through port 3341: pid 700")
    shutil.rmtree(os.path.join(proc, "700"))
    fake_proc(proc, os.path.join(ctl, "store"), {701: {"argv": ["python3", "trials.py", "run"], "environ": "LIVING_STDB_URL=http://127.0.0.1:3341"}})
    refused("a host process has the port in its environment (a trial runner)", run(), "in use through port 3341: pid 701")
    shutil.rmtree(os.path.join(proc, "701"))
    open(os.path.join(ctl, "list-fails"), "w").close()
    refused("spacetime list fails (a 64-character name, say)", run(), "spacetime list failed (exit 1): Error: 500")
    os.remove(os.path.join(ctl, "list-fails"))
    lst = open(os.path.join(ctl, "list")).read()
    open(os.path.join(ctl, "list"), "w").write(lst + " aske-coast-5 | c200bb \n")
    refused("it hosts a reference world", run(), "it hosts reference worlds (aske-coast-5)")
    open(os.path.join(ctl, "list"), "w").write("No databases found for c200aa.\n")
    refused("a hosted database the CLI does not list (another identity published it)", run(), "it hosts 1 database but 0 are known by name")
    open(os.path.join(ctl, "sql-fails"), "w").close()
    refused("a database that does not answer SQL before", run(stdb_db=["verify-other"]), "verify-other does not answer SQL before the restart")
    os.remove(os.path.join(ctl, "sql-fails"))
    open(os.path.join(ctl, "list"), "w").write(lst)
    open(os.path.join(cfgdir, "stdb-keep-dirs.txt"), "w").write("coord-stdb\n")
    refused("a server whose deleted databases' dirs are run evidence, without --keep-dirs", run(), "its deleted databases' directories hold run evidence")
    r = run(keep_dirs=True, apply=False)
    expect("restart --keep-dirs on an evidence server: planned without removing", "would: stop (podman kill -s INT), remove 0 directories of deleted databases" in r["text"]
           and "2 directories kept (--keep-dirs)" in r["text"] and not r["acted"], r["text"])
    os.remove(os.path.join(cfgdir, "stdb-keep-dirs.txt"))
    r = run(apply=False)
    expect("restart dry run: says what it would do, does nothing",
           "would: stop (podman kill -s INT), remove 2 directories of deleted databases" in r["text"] and "keeps 1 live database and 1 directory written in the last 15 min" in r["text"]
           and not r["acted"] and os.path.isdir(os.path.join(vdir, "2000001")), r["text"])
    open(os.path.join(ctl, "stop-hangs"), "w").close()
    r = run()
    expect("restart: a server that does not stop after SIGINT is not forced, nothing removed, not started",
           "NOT STOPPED" in r["text"] and r["acted"] == ["kill -s INT coord-stdb"] and os.path.isdir(os.path.join(vdir, "2000001")), r)
    os.remove(os.path.join(ctl, "stop-hangs"))
    open(os.path.join(ctl, "rm-fails"), "w").close()
    r = run()
    expect("restart: a failing removal is reported and the server is started again", "REMOVAL FAILED (exit 1)" in r["text"]
           and "start coord-stdb" in r["acted"] and "1 of 1 database answer SQL with the same paused state" in r["text"], r)
    os.remove(os.path.join(ctl, "rm-fails"))
    open(os.path.join(ctl, "after-paused"), "w").write("false")
    r = run()
    expect("restart: a database whose paused state changed is named", "CHECK THESE: verify-coord-1" in r["text"] and r["restart"].get("error"), r["text"])
    os.remove(os.path.join(ctl, "after-paused"))
    open(os.path.join(ctl, "paused"), "w").write("true")
    os.makedirs(os.path.join(vdir, "2000001", "clog"), exist_ok=True)  # the previous case removed them
    os.makedirs(os.path.join(vdir, "2000003", "clog"), exist_ok=True)
    age(os.path.join(vdir, "2000001"), 2)
    age(os.path.join(vdir, "2000003"), 2)
    r = run()
    expect("restart: stop with SIGINT, remove exactly the deleted databases' dirs, start, confirm the paused world",
           r["acted"] == ["kill -s INT coord-stdb", "run --rm -v coord-stdb-data:/data alpine rm -rf -- /data/.local/share/spacetime/data/replicas/2000001 "
                          "/data/.local/share/spacetime/data/replicas/2000003", "start coord-stdb"]
           and not os.path.exists(os.path.join(vdir, "2000001")) and not os.path.exists(os.path.join(vdir, "2000003"))
           and os.path.isdir(os.path.join(vdir, "2000049")) and os.path.isdir(os.path.join(vdir, "2000051"))
           and "1 of 1 database answer SQL with the same paused state; paused: verify-coord-1" in r["text"] and "free space" in r["text"]
           and r["restart"]["restarted"] and not r["restart"].get("error"), r)
    bad = [c for c in calls(ctl) if any(t in f" {c} " for t in TOUCHY if t != " rm ") or (c.startswith("run") and " rm -rf -- /data/" not in c)
           or (" rm " in f" {c} " and not c.startswith("run --rm -v coord-stdb-data:/data alpine rm -rf -- /data/.local/share/spacetime/data/replicas/"))]
    expect("restart: never --force, stop, restart, prune or another signal; rm only of listed replica dirs", not bad, bad)


def sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd}: {r.stdout}")
    return r.stdout


def target(path, foreign=None, tag=SIG):
    os.makedirs(os.path.join(path, "debug", "deps"), exist_ok=True)
    with open(os.path.join(path, "CACHEDIR.TAG"), "w") as f:
        f.write(tag)
    if tag == SIG:
        open(os.path.join(path, ".rustc_info.json"), "w").write("{}")
        open(os.path.join(path, "debug", ".cargo-lock"), "w").close()
    with open(os.path.join(path, "debug", "deps", "libbig.rlib"), "wb") as f:
        f.write(os.urandom(200_000))
    for name in foreign or []:
        open(os.path.join(path, name), "w").write("evidence\n")


def age(path, hours):
    t = time.time() - hours * 3600
    for d, dirs, files in os.walk(path):
        for x in dirs + files:
            os.utime(os.path.join(d, x), (t, t), follow_symlinks=False)
    os.utime(path, (t, t))


def expect(name, cond, out=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        print(out)


def main():
    with tempfile.TemporaryDirectory(prefix="disk-selftest-") as home:
        env = {**os.environ, "HOME": home, "XDG_STATE_HOME": os.path.join(home, "state"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}  # no podman/docker in PATH
        os.environ.update({k: v for k, v in env.items() if k.startswith("GIT_")})
        origin = os.path.join(home, "origin.git")
        repo = os.path.join(home, "dev", "slop-art-online")
        os.makedirs(os.path.dirname(repo))
        sh(f"git init -q --bare -b main {origin} && git clone -q {origin} {repo}", home)
        sh("echo a > a && git add a && git commit -qm base && git push -q origin HEAD:main", repo)
        wts = os.path.join(home, "wt")
        # merged: a branch with a commit, merged --no-ff into main
        sh(f"git worktree add -q -b done {wts}/done origin/main", repo)
        sh("echo d > d && git add d && git commit -qm done && git push -q origin done", f"{wts}/done")
        sh("git fetch -q && git merge -q --no-ff -m 'Merge done' origin/done && git push -q origin HEAD:main && git fetch -q", repo)
        # busy: merged too, but a process works inside its target
        sh(f"git worktree add -q -b busy {wts}/busy origin/main", repo)
        sh("echo b > b && git add b && git commit -qm busy && git push -q origin busy", f"{wts}/busy")
        sh("git merge -q --no-ff -m 'Merge busy' origin/busy && git push -q origin HEAD:main && git fetch -q", repo)
        # fresh: a worktree sitting on main's own line, no commits of its own
        sh(f"git fetch -q && git worktree add -q -b fresh {wts}/fresh origin/main", repo)
        # old: an unmerged branch idle for two days, its target holds a log
        sh(f"git worktree add -q -b old {wts}/old origin/main", repo)
        sh("echo o > o && git add o && git commit -qm old", f"{wts}/old")
        # protected: ~/dev/slop-game as a worktree
        sh(f"git worktree add -q -b game {home}/dev/slop-game origin/main", repo)
        # protected by this machine: merged worktrees named in the protect file and by --protect,
        # and a merged one whose target holds a protected path
        for w, where in (("trials", f"{home}/dev/slop-trials"), ("play", f"{home}/dev/slop-play"), ("holds", f"{wts}/holds")):
            sh(f"git fetch -q && git worktree add -q -b {w} {where} origin/main", repo)
            sh(f"echo {w} > {w} && git add {w} && git commit -qm {w} && git push -q origin {w}", where)
            sh(f"git fetch -q && git merge -q --no-ff -m 'Merge {w}' origin/{w} && git push -q origin HEAD:main && git fetch -q", repo)
            target(f"{where}/living/target")
            os.makedirs(f"{where}/living/target/release/keep-me")
            age(f"{where}/living/target", 50)
        os.makedirs(f"{home}/.config/slop-disk")
        with open(f"{home}/.config/slop-disk/protect.txt", "w") as f:
            f.write("# never touch these on this machine\n\n~/dev/slop-trials   # 14 GB, the trials\n"
                    f"{wts}/holds/living/target/release/keep-me\n~/wt/*/.local/living\n~/slop-runs-*-target\n~/nothing-*-here\n")
        # target folders outside the worktrees (private CARGO_TARGET_DIRs), named by a glob
        with open(f"{home}/.config/slop-disk/targets.txt", "w") as f:
            f.write("~/slop-*-target   # the agents' private targets\n")
        for name, hours in (("slop-idle-target", 50), ("slop-runs-x-target", 50), ("slop-fresh-target", 0.1), ("slop-busy-target", 50)):
            target(f"{home}/{name}")
            age(f"{home}/{name}", hours)
        os.makedirs(f"{home}/slop-notcargo-target")
        open(f"{home}/slop-notcargo-target/notes.txt", "w").write("keep\n")
        age(f"{home}/slop-notcargo-target", 50)
        # a target with a file written "after" the scan started: idle 0.0 h, never negative
        sh(f"git worktree add -q -b now {wts}/now origin/main", repo)
        target(f"{wts}/now/.local/t")
        t = time.time() + 3600
        os.utime(f"{wts}/now/.local/t/debug/deps/libbig.rlib", (t, t))
        with open(f"{home}/bad-protect.txt", "w") as f:
            f.write("~/dev/slop-trials\ndev/slop-play\n")
        for w in ("done", "busy", "fresh", "old"):
            target(f"{wts}/{w}/.local/t", foreign=["build.log"] if w == "old" else None)
        target(f"{home}/dev/slop-game/living/target")
        target(f"{repo}/living/target")
        os.makedirs(f"{wts}/done/.local/evidence/run1")
        open(f"{wts}/done/.local/evidence/run1/journal.jsonl", "w").write("{}\n")
        target(f"{wts}/done/.local/notcargo", tag="Signature: 8a477f597d28d172789f06886806bc55\n# made by another tool\n")
        os.symlink(f"{wts}/old/.local/t", f"{wts}/done/.local/link-to-target")
        nested = f"{wts}/done/.local/nested"
        sh(f"git init -q {nested}", home)
        target(f"{nested}/target")
        for w in ("done", "busy", "fresh"):
            age(f"{wts}/{w}/.local", 3)
        target(f"{wts}/old/.local/living/verify/run1/target")  # a verify run's build inside evidence
        age(f"{wts}/old/.local", 50)
        idx = sh("git rev-parse --absolute-git-dir", f"{wts}/old").strip()
        for f in ("index", "logs/HEAD", "HEAD"):
            p = os.path.join(idx, f)
            if os.path.exists(p):
                t = time.time() - 50 * 3600
                os.utime(p, (t, t))
        age(f"{home}/dev/slop-game/living/target", 100)
        age(nested, 100)
        busy = subprocess.Popen(["sleep", "300"], cwd=f"{wts}/busy/.local/t/debug")
        busy2 = subprocess.Popen(["sleep", "300"], cwd=f"{home}/slop-busy-target/debug")
        protect = ["--protect", "~/dev/slop-play"]  # expanded by disk_clean, not by a shell
        try:
            bad = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "0", "--protect-file", f"{home}/bad-protect.txt"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            expect("an invalid protect file: exit 2, nothing removed", bad.returncode == 2 and "line 2" in bad.stdout
                   and os.path.isdir(f"{wts}/done/.local/t/debug") and os.path.isdir(f"{home}/dev/slop-play/living/target/debug"), bad.stdout)
            listed = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--list-protected", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            expect("--list-protected: built-in, file and --protect paths with their sources",
                   "~/dev/slop-game  (built in)" in listed and "~/dev/slop-trials  (~/.config/slop-disk/protect.txt, line 3)" in listed
                   and "~/dev/slop-play  (--protect)" in listed, listed)
            dry = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--floor-gb", "0", "--target-gb", "0", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            expect("dry run removes nothing", all(os.path.isdir(f"{wts}/{w}/.local/t/debug") for w in ("done", "busy", "fresh", "old")), dry)
            out = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "0", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            nofile = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--floor-gb", "0", "--target-gb", "0", "--targets-file", f"{home}/none.txt", *protect],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        finally:
            busy.kill()
            busy2.kill()
        expect("without targets.txt no outside folder is a candidate", "outside the worktrees" not in nofile, nofile)
        expect("a protect-file glob: the evidence build in an idle worktree stays", os.path.isdir(f"{wts}/old/.local/living/verify/run1/target/debug")
               and "~/wt/old/.local/living (~/.config/slop-disk/protect.txt, line 5: ~/wt/*/.local/living)" in out, out)
        expect("outside target idle 50 h: removed", not os.path.exists(f"{home}/slop-idle-target"), out)
        expect("outside target matched by a protect glob: never", os.path.isdir(f"{home}/slop-runs-x-target/debug") and "protected: ~/slop-runs-x-target" in out, out)
        expect("outside target active: kept", os.path.isdir(f"{home}/slop-fresh-target/debug"), out)
        expect("outside target with a process inside: kept", os.path.isdir(f"{home}/slop-busy-target/debug"), out)
        expect("outside folder that is no Cargo target: untouched", os.path.isfile(f"{home}/slop-notcargo-target/notes.txt"), out)
        expect("merged and idle: removed", not os.path.exists(f"{wts}/done/.local/t"), out)
        expect("a process inside: kept", os.path.isdir(f"{wts}/busy/.local/t/debug") and "in use" in out, out)
        expect("fresh worktree on main's line: kept", os.path.isdir(f"{wts}/fresh/.local/t/debug"), out)
        expect("idle 50 h with a log: Cargo entries gone, the log kept", not os.path.exists(f"{wts}/old/.local/t/debug") and os.path.isfile(f"{wts}/old/.local/t/build.log"), out)
        expect("protected checkout: never", os.path.isdir(f"{home}/dev/slop-game/living/target/debug") and "never" in out, out)
        expect("the repository's own checkout: never", os.path.isdir(f"{repo}/living/target/debug"), out)
        expect("a worktree in the protect file: never, with its source", os.path.isdir(f"{home}/dev/slop-trials/living/target/debug")
               and "protected: ~/dev/slop-trials (~/.config/slop-disk/protect.txt, line 3)" in out, out)
        expect("a worktree given with --protect: never", os.path.isdir(f"{home}/dev/slop-play/living/target/debug") and "protected: ~/dev/slop-play (--protect)" in out, out)
        expect("a target holding a protected path: never", os.path.isdir(f"{wts}/holds/living/target/release/keep-me") and os.path.isdir(f"{wts}/holds/living/target/debug"), out)
        expect("the report lists the protected paths and the size method", "protected (never removed" in out and "\nsizes: " in out, out)
        expect("evidence without a tag: untouched", os.path.isfile(f"{wts}/done/.local/evidence/run1/journal.jsonl"), out)
        expect("a tag not made by Cargo: untouched", os.path.isdir(f"{wts}/done/.local/notcargo/debug"), out)
        expect("a symlink: untouched", os.path.islink(f"{wts}/done/.local/link-to-target"), out)
        expect("a nested repository: untouched", os.path.isdir(f"{nested}/target/debug"), out)
        expect("a file newer than the scan: idle 0.0 h, not negative", "active (idle 0.0 h)" in out and "-0.0" not in out, out)
        # pressure: free space is always under a huge target, so an applied run measures before
        # each removal and removes the idle folders under that rule (the fresh worktree's)
        hp = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--floor-gb", "0", "--target-gb", "1000000", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        ha = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "1000000", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        expect("pressure: projected in the dry run, measured before each removal when applied",
               "under pressure (free under 1000000 GB)" in hp and "under pressure (free measured at" in ha and not os.path.exists(f"{wts}/fresh/.local/t/debug")
               and os.path.isdir(f"{home}/dev/slop-trials/living/target/debug") and os.path.isdir(f"{wts}/now/.local/t/debug"), hp + ha)
        expect("no aside folders left", not any(".slop-reclaim-" in d for _, ds, _ in os.walk(home) for d in ds), out)
        expect("report written", os.listdir(os.path.join(home, "state", "slop-disk", "reports")), out)
        expect("the report has the container section", "\ncontainers (report only" in out, out)
        container_cases(home)
        vm_cases(home)
        held_cases(home)
        print(out)
    print("disk_clean_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
