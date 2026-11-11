#!/usr/bin/env python3
"""Self-test of living/tools/check.py's compile-cache choice and its watchdog (docs/TOOLING.md).

In a throwaway home with a fake pinned sccache, checks which RUSTC_WRAPPER the check uses:
its own sccache-rustc; a pre-set one that is ours (the path, a link, a copy under another
name, a bare name on PATH), with the caller's cache settings kept; a foreign wrapper and a
plain sccache, used as they are without the cache settings (the foreign one in the digest);
and no cache at all when only an sccache on PATH exists. Then SIGKILLs a process that
registered a process group with the watchdog and checks the group and the registered folder
are gone.

The script fuel gate step (`script-gate`), in a clone of this worktree (its uncommitted files
under living/ included): an empty stamp store runs it; a stamp at its digest skips it; an
edited script, budgets.json or sb-host's wasmtime configuration runs it again, an edited README
does not; and gate.py, over a stand-in bench, passes laws within budget and fails one over it
or not measured, naming the law, its fuel and its budget. With --gate it also runs the real
step there (builds the bench, a few minutes cold): it passes and is stamped, is skipped on a
second run, fails the check under a lowered budget with that message, and runs again after an
edit to the script. Otherwise builds nothing; touches nothing outside the temporary directory.
Usage: check_selftest.py [--gate]   (CHECK_SELFTEST_TARGET: the --gate build's target folder)
"""
import json
import os
import shutil
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


def clone_worktree(home):
    """A clone of this worktree's HEAD with its uncommitted files under living/ copied in."""
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=TOOLS, stdout=subprocess.PIPE, text=True, check=True).stdout.strip()
    repo = os.path.join(home, "repo")
    subprocess.run(["git", "clone", "-q", "--shared", root, repo], check=True)
    subprocess.run(["git", "checkout", "-q", "--detach", subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, stdout=subprocess.PIPE, text=True).stdout.strip()],
                   cwd=repo, check=True)
    ls = lambda *a: [n for n in subprocess.run(["git", "ls-files", "-z", *a, "--", "living"], cwd=root, stdout=subprocess.PIPE, text=True).stdout.split("\0") if n]
    for rel in ls("-d"):
        if os.path.lexists(os.path.join(repo, rel)):
            os.remove(os.path.join(repo, rel))
    for rel in ls("-m", "-o", "--exclude-standard"):
        if os.path.isfile(os.path.join(root, rel)):
            os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
            shutil.copy2(os.path.join(root, rel), os.path.join(repo, rel))
    return repo


def check_env(home, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LIVING_CHECK", "CARGO_TARGET_DIR"))}
    env.update({"LIVING_CHECK_STORE": os.path.join(home, "store"), "CARGO_TARGET_DIR": os.path.join(home, "target"), **extra})
    return env


def gate_plan(repo, home):
    out = os.path.join(home, "plan.json")
    r = subprocess.run([sys.executable, os.path.join(repo, "living/tools/check.py"), "--plan", "--steps", "script-gate", "--json", out], cwd=repo,
                       env=check_env(home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.load(open(out))["plan"][0], r.stdout
    except (OSError, ValueError, KeyError, IndexError):
        return {}, r.stdout


def edited(path, text):
    """Append text to a file; returns a function that puts it back."""
    old = open(path, "rb").read()
    with open(path, "ab") as f:
        f.write(text.encode())
    return lambda: open(path, "wb").write(old)


STUB_HOST = r"""#!/usr/bin/env python3
import json, sys
fuel = json.loads(sys.argv[-1]) if sys.argv[-1].startswith("{") else {}
laws = sys.argv[sys.argv.index("--laws") + 1].split(",")
for law in laws:
    if law in fuel:
        # a number: key set 0's fuel, with two other sets around it; a list: every set's fuel
        seeds = fuel[law] if isinstance(fuel[law], list) else [fuel[law], fuel[law] - 5, fuel[law] + 5]
        print(json.dumps({"engine": "rhai", "law": law, "fuel_per_call": sum(seeds) / len(seeds), "fuel_seeds": seeds, "p50_ns": 1000.0}))
"""


def gate_judge_cases(home, repo):
    stub = os.path.join(home, "stub-host")
    script(stub, STUB_HOST)
    budgets = os.path.join(home, "budgets.json")
    with open(budgets, "w") as f:
        json.dump({"fuel_per_call": {"rates": 9000, "rates-law": 245000}}, f)
    gate = os.path.join(repo, "living/tools/script_bench/gate.py")

    def judge(fuel):
        # the stub reads the fuel to report from its last argument; gate.py passes its own
        # arguments after the module, so wrap the stub with a fixed answer
        wrapper = os.path.join(home, "stub-answer")
        script(wrapper, f"#!/bin/sh\nexec {sys.executable} {stub} \"$@\" '{json.dumps(fuel)}'\n")
        verdict = os.path.join(home, "verdict.json")
        r = subprocess.run([sys.executable, gate, "--host", wrapper, "--module", "/dev/null", "--budgets", budgets, "--json", verdict],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return r.returncode, r.stdout, json.load(open(verdict)) if os.path.exists(verdict) else None

    rc, out, v = judge({"rates": 8588, "rates-law": 211847})
    expect("gate.py: every law within its budget passes", rc == 0 and v and v["ok"] and "every law within its budget" in out, out)
    rc, out, v = judge({"rates": 8588, "rates-law": 250000})
    expect("gate.py: a law over its budget fails, naming the law, its fuel and its budget",
           rc == 1 and v and not v["ok"] and "rates-law takes 250,000 fuel a call, over its budget of 245,000" in out, out)
    # Judged on key set 0, the game's own keys (HASHING_SEED), not the mean over the sets.
    rc, out, v = judge({"rates": 8588, "rates-law": [246000, 200000, 200000]})
    expect("gate.py: judges the game's key set, not the mean (over budget there, under on the mean)",
           rc == 1 and v and not v["ok"] and "rates-law takes 246,000 fuel a call, over its budget of 245,000" in out, out)
    rc, out, v = judge({"rates": 8588})
    expect("gate.py: a budgeted law not measured fails", rc == 1 and "not measured: rates-law" in out, out)


def gate_cases(home, build):
    repo = clone_worktree(home)
    sb = os.path.join(repo, "living/tools/script_bench")
    p, out = gate_plan(repo, home)
    expect("script-gate: an empty stamp store runs it", p.get("digest") and not p.get("skip"), out)
    inputs = set(p.get("inputs", []))
    expect("script-gate: its inputs hold the script, the bench, the rules crate, budgets.json and wasmtime's pin",
           {"living/scripts", "living/rules", "living/tools/script_bench/bench", "living/tools/script_bench/host", "living/tools/script_bench/module",
            "living/tools/script_bench/budgets.json", "living/tools/script_bench/Cargo.lock"} <= inputs, sorted(inputs))
    d = p.get("digest") or "0" * 64
    stamp = os.path.join(home, "store", "stamps", d[:2], d + ".json")
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp, "w") as f:
        json.dump({"step": "script-gate", "at": "selftest", "worktree": repo, "commit": "0" * 40}, f)
    p, out = gate_plan(repo, home)
    expect("script-gate: a stamp at its digest skips it", p.get("skip") is True and p.get("digest") == d, out)
    for what, rel, text, runs in (("an edited script", "living/scripts/skills.rhai", "\n// check_selftest\n", True),
                                   ("an edited budgets.json", "living/tools/script_bench/budgets.json", "\n", True),
                                   ("an edited wasmtime configuration (sb-host)", "living/tools/script_bench/host/src/main.rs", "\n// check_selftest\n", True),
                                   ("an edited README", "living/tools/script_bench/README.md", "\ncheck_selftest\n", False)):
        undo = edited(os.path.join(repo, rel), text)
        p, out = gate_plan(repo, home)
        undo()
        ok = (not p.get("skip") and p.get("digest") not in (None, d)) if runs else (p.get("skip") is True and p.get("digest") == d)
        expect(f"script-gate: {what} {'runs it again' if runs else 'still skips it'}", ok, out)
    gate_judge_cases(home, repo)
    if not build:
        return
    shutil.rmtree(os.path.join(home, "store"))
    target = os.environ.get("CHECK_SELFTEST_TARGET") or os.path.join(home, "target")
    run = lambda: subprocess.run([sys.executable, "living/tools/check.py", "--steps", "script-gate"], cwd=repo, env=check_env(home, CARGO_TARGET_DIR=target),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    r = run()
    expect("script-gate (built): passes and is stamped", r.returncode == 0 and "script-gate: passed" in r.stdout and "stamped [" in r.stdout, r.stdout[-3000:])
    r = run()
    expect("script-gate (built): skipped on a second run", r.returncode == 0 and "script-gate: skip" in r.stdout, r.stdout[-3000:])
    path = os.path.join(sb, "budgets.json")
    old = open(path).read()
    b = json.loads(old)
    b["fuel_per_call"]["rates-law"] = 1000
    with open(path, "w") as f:
        json.dump(b, f)
    r = run()
    open(path, "w").write(old)
    expect("script-gate (built): a budget under the law's fuel fails the check, naming the law, its fuel and its budget",
           r.returncode != 0 and "script-gate: FAILED" in r.stdout and "rates-law takes " in r.stdout and "over its budget of 1,000" in r.stdout, r.stdout[-3000:])
    undo = edited(os.path.join(repo, "living/scripts/skills.rhai"), "\n// check_selftest\n")
    r = run()
    undo()
    expect("script-gate (built): an edited script runs it again, and it passes", r.returncode == 0 and "script-gate: passed" in r.stdout
           and "script-gate: skip" not in r.stdout, r.stdout[-3000:])


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


def main(argv):
    with tempfile.TemporaryDirectory(prefix="check-selftest-") as home:
        wrapper_cases(home)
        watchdog_case(home)
    with tempfile.TemporaryDirectory(prefix="check-selftest-gate-") as home:
        gate_cases(home, "--gate" in argv)
    print("check_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
