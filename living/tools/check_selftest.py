#!/usr/bin/env python3
"""Self-test of living/tools/check.py's compile-cache choice and its watchdog (docs/TOOLING.md).

In a throwaway home with a fake pinned sccache, checks which RUSTC_WRAPPER the check uses:
its own sccache-rustc; a pre-set one that is ours (the path, a link, a copy under another
name, a bare name on PATH), with the caller's cache settings kept; a foreign wrapper and a
plain sccache, used as they are without the cache settings (the foreign one in the digest);
and no cache at all when only an sccache on PATH exists. Then SIGKILLs a process that
registered a process group with the watchdog and checks the group and the registered folder
are gone. Builds nothing; touches nothing outside the temporary directory.
Usage: check_selftest.py
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
OURS = os.path.join(TOOLS, "sccache-rustc")
FAKE_SCCACHE = "#!/bin/sh\ncase \"$*\" in *json*) echo '{\"stats\": {}}' ;; esac\nexit 0\n"
failures = []

PROBE = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import check
env, exe, how = check.sccache_env(os.getcwd())
print(json.dumps({"env": env, "exe": exe, "how": how, "digest_wrapper": check.build_env(set()).get("RUSTC_WRAPPER"),
                  "ours": check.OUR_WRAPPER, "pinned": check.PINNED_SCCACHE}))
"""


def expect(name, cond, out=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        print(out)


def script(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)


def choose(home, pinned=True, **env):
    pinned_path = os.path.join(home, ".local/share/slop-tools/bin/sccache")
    if pinned:
        script(pinned_path, FAKE_SCCACHE)
    elif os.path.exists(pinned_path):
        os.remove(pinned_path)
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SCCACHE_", "SLOP_SCCACHE", "RUSTC_WRAPPER", "LIVING_SCCACHE"))}
    base.update(HOME=home, XDG_CACHE_HOME=os.path.join(home, ".cache"), PATH=os.path.join(home, "bin") + ":/usr/bin:/bin")
    base.update(env)
    r = subprocess.run([sys.executable, "-I", "-c", PROBE, TOOLS], cwd=home, env=base, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": r.stdout}


def wrapper_cases(home):
    pinned = os.path.join(home, ".local/share/slop-tools/bin/sccache")
    os.makedirs(os.path.join(home, "bin"))
    link = os.path.join(home, "bin", "sccache-rustc")
    os.symlink(OURS, link)
    copy = os.path.join(home, "other-worktree", "slop-wrap")
    script(copy, open(OURS).read())
    foreign = os.path.join(home, "foreign-wrapper")
    script(foreign, "#!/bin/sh\nexec \"$@\"\n")

    r = choose(home)
    expect("no wrapper set: our sccache-rustc, the pinned sccache", r.get("env", {}).get("RUSTC_WRAPPER") == OURS
           and r["env"].get("SLOP_SCCACHE") == pinned and r["exe"] == pinned and r["env"]["SCCACHE_SERVER_PORT"] == "4237", r)
    for name, w in (("its path", OURS), ("a link to it", link), ("a copy under another name", copy), ("a bare name on PATH", "sccache-rustc")):
        r = choose(home, RUSTC_WRAPPER=w)
        expect(f"pre-set sccache-rustc ({name}): kept, with the cache settings and stats",
               r.get("env", {}).get("RUSTC_WRAPPER") == w and r["exe"] == pinned and r["env"].get("SLOP_SCCACHE") == pinned
               and "pre-set" in r["how"] and r["digest_wrapper"] is None, r)
    r = choose(home, RUSTC_WRAPPER=link, SCCACHE_DIR=os.path.join(home, "slot-cache"), SCCACHE_SERVER_PORT="4400")
    expect("pre-set sccache-rustc: the caller's SCCACHE_DIR and port are kept", r.get("env", {}).get("SCCACHE_DIR") == os.path.join(home, "slot-cache")
           and r["env"].get("SCCACHE_SERVER_PORT") == "4400", r)
    r = choose(home, RUSTC_WRAPPER=foreign)
    expect("a foreign wrapper: used as it is, no cache settings, in the digest", r.get("env") == {} and r["exe"] is None
           and "not living/tools/sccache-rustc" in r["how"] and r["digest_wrapper"] == foreign, r)
    script(os.path.join(home, "bin", "sccache"), FAKE_SCCACHE)
    r = choose(home, RUSTC_WRAPPER="sccache")
    expect("a plain sccache wrapper: used as it is, not in the digest", r.get("env") == {} and r["exe"] is None
           and "plain sccache" in r["how"] and r["digest_wrapper"] is None, r)
    r = choose(home, pinned=False)
    expect("no pinned sccache: an sccache on PATH is not used", r.get("env") == {} and r["exe"] is None and "on PATH is not used" in r["how"], r)


WATCHED = r"""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, sys.argv[1])
import check
check.WATCHDOG = check.Watchdog()
d = tempfile.mkdtemp(prefix="check-selftest-js-", dir=sys.argv[2])
check.WATCHDOG.send("d" + d)
# like a cargo: a session of its own, with children (rustc, a test binary) in its group
p = subprocess.Popen(["sh", "-c", "sleep 300 & sleep 300 & wait"], start_new_session=True)
check.WATCHDOG.send(f"+{p.pid}")
print(p.pid, d, check.WATCHDOG.p.pid, flush=True)
time.sleep(600)
"""


def alive(pgid):
    try:
        os.killpg(pgid, 0)
    except OSError:
        return False
    # zombies left for init to reap count as gone
    out = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], stdout=subprocess.PIPE, text=True).stdout
    return any(l.split()[0] == str(pgid) and not l.split()[1].startswith("Z") for l in out.splitlines() if len(l.split()) == 2)


def watchdog_case(home):
    w = subprocess.Popen([sys.executable, "-I", "-c", WATCHED, TOOLS, home], stdout=subprocess.PIPE, text=True)
    pgid, d, dog = w.stdout.readline().split()
    pgid, dog = int(pgid), int(dog)
    time.sleep(0.5)
    before = alive(pgid) and os.path.isdir(d)
    os.kill(w.pid, signal.SIGKILL)
    w.wait()
    end = time.time() + 15
    while time.time() < end and (alive(pgid) or os.path.isdir(d)):
        time.sleep(0.2)
    expect("SIGKILLed check: the watchdog stops its process groups and removes its folders",
           before and not alive(pgid) and not os.path.isdir(d), f"group {pgid} alive {alive(pgid)}, folder {d} {os.path.isdir(d)}")
    end = time.time() + 5
    while time.time() < end and alive_pid(dog):
        time.sleep(0.2)
    expect("the watchdog itself exits afterwards", not alive_pid(dog))


def alive_pid(pid):
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], stdout=subprocess.PIPE, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


def main():
    with tempfile.TemporaryDirectory(prefix="check-selftest-") as home:
        wrapper_cases(home)
        watchdog_case(home)
    print("check_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
