#!/usr/bin/env python3
"""`just living-check` with step stamps and a shared compile cache (docs/TOOLING.md).

The check is the Justfile's steps: the authority (wasm), the mind and the native viewer,
the game in release and its unit tests (release too, on the same tree), the browser viewer
(wasm), the rules tests, the seed-laws test and the script fuel (living/tools/script_bench, its own cargo workspace and target folder). Each step's
inputs are the files of the packages it builds (its path-dependency closure, from `cargo
metadata`), the shared inputs below and its own, the toolchain, the step's command and the
build environment. After a step passes, its stamp is written under that digest in a store shared
by every worktree on this machine. A later check whose step has the same digest skips it:
that step has already passed, on this machine, on byte-identical inputs.

Each passing step also audits the compiler's dep-info and the build scripts' declarations:
every file a workspace crate read must lie inside that package's declared inputs and not be
git-ignored. A step that fails the audit runs and passes as usual but writes no stamp, so an
input map that has fallen behind the code costs time, never a false skip.

When `sccache` is installed (the pinned copy from living/tools/install_sccache.sh; an
sccache on PATH is never used), rustc runs through `living/tools/sccache-rustc`, with its
own cache directory and server port, so worktrees on one machine share compiled
dependencies. A RUSTC_WRAPPER already set to that wrapper (a link to it or a copy of it) is
used as it is, with the cache settings and stats; any other pre-set wrapper is used as it is,
without the cache, and enters the step digest (a plain `sccache` does not).

Every cargo runs in a process group of its own. A watchdog process, which the check alone
holds a pipe to, stops those groups when the check ends in any way, a SIGKILL included.

Steps in different cargo build directories run at once (four lanes: release, debug,
wasm-dev and script-bench), under one jobserver of CARGO_BUILD_JOBS (default: all cores) jobs; each step's
output then goes to <target>/living-check/<step>.log, and a failing step's log is printed.

Usage: check.py [--full] [--plan] [--serial] [--steps a,b] [--no-sccache] [--json PATH]
  --full        run every step, ignoring stamps (stamps are still written)
  --serial      run the steps one after another, output to the terminal (LIVING_CHECK_SERIAL=1)
  --plan        print what would run or be skipped, and why; build nothing
  --steps       run only these steps (names as printed by --plan)
  --no-sccache  do not wrap rustc (also LIVING_SCCACHE=0)
  --json PATH   write the run record (per-step times, skips, digests) to PATH
Environment: LIVING_CHECK_FULL=1 is --full; LIVING_CHECK_STORE overrides the stamp store;
SLOP_SCCACHE_DIR, SLOP_SCCACHE_SIZE (default 20G) and SLOP_SCCACHE_PORT (default 4237) set
the compile cache.
"""
import fcntl
import hashlib
import json
import re
import urllib.parse
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time

# Bump when how a step is keyed or judged changes (hashing, environment, audit rules).
TOOL_VERSION = 2
HOME = os.path.expanduser("~")
CACHE = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
STORE = os.environ.get("LIVING_CHECK_STORE") or os.path.join(CACHE, "slop-check")
# The compile cache: our wrapper, and the sccache install_sccache.sh pins (never one on PATH).
OUR_WRAPPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sccache-rustc")
WRAPPER_MARK = b"RUSTC_WRAPPER that runs rustc through sccache (living/tools/check.py"
PINNED_SCCACHE = os.path.join(HOME, ".local/share/slop-tools/bin/sccache")

# The steps of `just living-check`, in its order. `packages`: what the step builds; its
# inputs are those packages' path-dependency closure. `lane`: steps in different lanes write
# different cargo build directories (each locked by cargo), so lanes run at once, sharing
# one jobserver; steps in a lane run in this order. `dirs`: the target sub-directories it
# writes. A step may also have `cmd` as a list of cargo commands run in turn; `workspace`, the
# cargo workspace its relative dep-info paths start from (default living); `target`, a target
# sub-directory used as its CARGO_TARGET_DIR; `inputs`, files beyond its packages and the
# shared ones; and `gate`, a script run after its builds, which must pass too.
STEPS = [
    {"name": "authority", "lane": "release", "packages": ["living-authority"], "dirs": ["wasm32-unknown-unknown/release", "release"],
     "cmd": ["cargo", "build", "--manifest-path", "living/Cargo.toml", "-p", "living-authority", "--target", "wasm32-unknown-unknown", "--release"]},
    {"name": "mind+viewer", "lane": "debug", "packages": ["living-mind", "living-viewer"], "dirs": ["debug"],
     "cmd": ["cargo", "build", "--manifest-path", "living/Cargo.toml", "-p", "living-mind", "-p", "living-viewer"]},
    # The game in release only: the build that is run, without a second ~10 GB debug tree.
    {"name": "game", "lane": "release", "packages": ["living-game"], "dirs": ["release"],
     "cmd": ["cargo", "build", "--release", "--manifest-path", "living/Cargo.toml", "-p", "living-game"]},
    # The game client's unit tests, in release so they reuse the game step's tree (no second
    # debug Bevy tree). The client reads the rules (verbs.rs's offered(), the checks), so a rules
    # change can break it: verbs::tests::make_is_offered_at_a_furnace_only_while_it_burns_with_fuel
    # went red on main (f0061a07) while the check only built the game. They run headless, without
    # a display, a GPU or the generated (git-ignored) assets; a test that cannot is skipped here by
    # name in GAME_TEST_SKIPS, with its reason, and listed in the verify-ui skill to run by hand.
    {"name": "game-tests", "lane": "release", "packages": ["living-game"], "dirs": ["release"],
     "cmd": ["cargo", "test", "--release", "--manifest-path", "living/Cargo.toml", "-p", "living-game", "--", "--color", "never"]},
    {"name": "viewer-wasm", "lane": "wasm-dev", "packages": ["living-viewer"], "dirs": ["wasm32-unknown-unknown/wasm-dev", "debug"],
     "cmd": ["cargo", "build", "--manifest-path", "living/viewer/Cargo.toml", "--target", "wasm32-unknown-unknown", "--profile", "wasm-dev", "--bin", "living-viewer"]},
    # `inputs`: the rules' ratchet `ui::tests::the_game_client_names_no_new_skills` reads the
    # game client's sources at run time (no dep-info names them), so a client-only change must
    # run it again: fov-client (9ddd2b6d) failed it on main while the step's stamp was reused.
    {"name": "rules-tests", "lane": "debug", "packages": ["living-rules"], "dirs": ["debug"],
     "inputs": ["living/game/src"],
     "cmd": ["cargo", "test", "--manifest-path", "living/Cargo.toml", "-p", "living-rules"]},
    # A seed's own laws are in force after `init` (the authority's path, natively): what a
    # harness installing another script over them would take away (fix-laws).
    {"name": "seed-laws", "lane": "debug", "packages": ["living-authority"], "dirs": ["debug"],
     "cmd": ["cargo", "test", "--manifest-path", "living/Cargo.toml", "-p", "living-authority", "--lib", "seed::tests::a_seeds_laws_are_in_force_after_init"]},
    # The fuel budget gate (docs/LIVING_CORE.md, "Fuel budgets"): the Rhai bench module and
    # sb-host, then gate.py over budgets.json. Its packages' closure is the bench and its
    # fixtures (bench), the module, sb-host with wasmtime's configuration (host/src/main.rs)
    # and the rules crate; the shared inputs hold the shipped script (living/scripts).
    {"name": "script-gate", "lane": "script-bench", "packages": ["sb-module", "sb-host"], "dirs": ["script-bench"],
     "workspace": "living/tools/script_bench", "target": "script-bench",
     "inputs": ["living/tools/script_bench/Cargo.toml",  # the bench's profile; wasmtime's version (=39.0.1) is host/Cargo.toml's
                "living/tools/script_bench/Cargo.lock",  # every crate's locked version, wasmtime's and rhai's included
                "living/tools/script_bench/budgets.json", "living/tools/script_bench/gate.py"],
     "cmd": [["cargo", "build", "--manifest-path", "living/tools/script_bench/Cargo.toml", "-p", "sb-module", "--target", "wasm32-unknown-unknown",
              "--release", "--features", "rhai"],
             # sb-host alone, without the native engines (Lua's C build, the wasmi guest)
             ["cargo", "build", "--manifest-path", "living/tools/script_bench/Cargo.toml", "-p", "sb-host", "--bin", "sb-host", "--release",
              "--no-default-features"]],
     "gate": {"script": "living/tools/script_bench/gate.py", "host": "release/sb-host", "module": "wasm32-unknown-unknown/release/sb_module.wasm"}},
]

# Game tests that need a display, a GPU or the generated assets: skipped by game-tests only (name ->
# reason), run by hand on the laptop (`cargo test --release -p living-game -- --exact NAME`), and
# listed in .agents/skills/verify-ui/SKILL.md. None today: all 103 run headless (2026-11-12, the
# Spark, no assets). `ik::spots::uneven_ground_spots` is #[ignore]d in the source: a tool that
# lists photo spots (`-- --ignored uneven_ground_spots --nocapture`), not a check.
GAME_TEST_SKIPS = {}
for _s in STEPS:
    if _s["name"] == "game-tests":
        _s["cmd"] = _s["cmd"] + (["--exact"] if GAME_TEST_SKIPS else []) + [x for name in sorted(GAME_TEST_SKIPS) for x in ("--skip", name)]

# The cargo workspaces whose packages the steps build: the living core's, and the script
# bench's (standalone, not a member of living/Cargo.toml).
WORKSPACES = ["living/Cargo.toml", "living/tools/script_bench/Cargo.toml"]


def cmds_of(step):
    """A step's cargo commands, in order."""
    return step["cmd"] if isinstance(step["cmd"][0], list) else [step["cmd"]]

# Inputs of every step besides its packages' own directories: the workspace manifest and
# lock, the seeds and scripts the crates include (include_str!, the authority's build
# script), and toolchain and Cargo configuration files. (This file is not an input: the
# digest holds each step's command and input list, and TOOL_VERSION covers the rest.)
SHARED_INPUTS = [
    "living/Cargo.toml", "living/Cargo.lock", "living/seeds", "living/scripts",
    "rust-toolchain", "rust-toolchain.toml", "living/rust-toolchain", "living/rust-toolchain.toml",
    ".cargo", "living/.cargo",
]

# Files a package compiles from outside its own directory besides the shared inputs (the
# audit finds any that are missing here): the game's #[path] modules from the viewer, and the
# script bench's Rust port of the laws.
# The game's character types (living/tools/characters/types.json, include_str!) too.
EXTRA_INPUTS = {"living-game": ["living/viewer/src/clock.rs", "living/viewer/src/sync.rs", "living/tools/characters/types.json"],
                "sb-bench": ["living/tools/script_bench/port.rs"]}

# Environment that can change what a step builds or how its tests run: exact names and
# prefixes. Variables that build scripts declare (rerun-if-env-changed) and crates read
# (env!) are added from the audit (`envdeps.json` in the store).
ENV_NAMES = {"RUSTC", "RUSTDOC", "RUSTFLAGS", "RUSTDOCFLAGS", "RUSTC_WORKSPACE_WRAPPER", "CC", "CXX", "AR", "LD",
             "CFLAGS", "CXXFLAGS", "LDFLAGS", "TARGET", "HOST", "PKG_CONFIG_PATH", "MACOSX_DEPLOYMENT_TARGET",
             "CARGO_HOME", "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "SDKROOT", "DEVELOPER_DIR"}
ENV_PREFIXES = ("CARGO_PROFILE_", "CARGO_BUILD_", "CARGO_TARGET_", "CARGO_ENCODED_", "CARGO_UNSTABLE_", "CARGO_INCREMENTAL",
                "LIVING_", "RUST_", "CC_", "CFLAGS_", "CXX_", "AR_", "TARGET_")
# Variables that never change outputs: where outputs go, parallelism, terminal and the
# stamp store's own settings.
ENV_IGNORED = {"CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_BUILD_DIR", "CARGO_BUILD_JOBS", "LIVING_CHECK_FULL",
               "LIVING_CHECK_STORE", "LIVING_CHECK_SERIAL", "LIVING_SCCACHE", "LIVING_MERGE_CHECK", "RUST_LOG", "RUST_BACKTRACE"}


def say(msg):
    print(f"living-check: {msg}", flush=True)


def run(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.PIPE, text=True, **kw).stdout


def repo_root():
    return run(["git", "rev-parse", "--show-toplevel"], os.getcwd()).strip()


def target_dir(root):
    t = os.environ.get("CARGO_TARGET_DIR") or os.environ.get("CARGO_BUILD_TARGET_DIR")
    if t:
        return os.path.abspath(t)
    meta = json.loads(run(["cargo", "metadata", "--manifest-path", "living/Cargo.toml", "--no-deps", "--format-version", "1", "--offline"], root))
    return meta["target_directory"]


def closures(root):
    """Package name -> repo-relative directories of it and every path package it depends on,
    and real package directory -> name. Offline: the members and their path dependencies
    come from `cargo metadata --no-deps`; a path package that is no member (a path
    dependency outside the workspace, a [patch] path, seen in Cargo.lock as a package
    without a source) is kept by its directory, absolute when outside the repository, so
    the steps that need it cannot be stamped until it is mapped."""
    dirs, deps, ws_of = {}, {}, {}
    for manifest in WORKSPACES:
        if not os.path.isfile(os.path.join(root, manifest)):
            continue
        meta = json.loads(run(["cargo", "metadata", "--manifest-path", manifest, "--no-deps", "--format-version", "1", "--offline"], root))
        for p in meta["packages"]:
            dirs[p["name"]] = os.path.dirname(p["manifest_path"])
            deps[p["name"]] = [(d["name"], d["path"]) for d in p["dependencies"] if d.get("path")]
            ws_of[p["name"]] = manifest

    def where(d):
        rel = os.path.relpath(d, root)
        return d if rel.startswith("..") else rel

    out = {}
    for name in dirs:
        seen, todo, found = set(), [name], set()
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            found.add(where(dirs[n]))
            found.update(EXTRA_INPUTS.get(n, []))
            for dn, dp in deps.get(n, []):
                if dn in dirs:
                    todo.append(dn)
                else:
                    found.add(where(dp))  # a path dependency outside the workspace
        out[name] = sorted(found)
    for manifest in set(ws_of.values()):
        try:  # [patch] paths and other sourceless packages no workspace's members name
            lock = open(os.path.join(root, os.path.dirname(manifest), "Cargo.lock")).read()
            blocks = lock.split("[[package]]")[1:]
            strays = [re.search(r'name = "([^"]+)"', b).group(1) for b in blocks if "\nsource = " not in b]
            strays = [n for n in strays if n not in dirs]
        except (OSError, AttributeError):
            strays = [f"({os.path.dirname(manifest)}/Cargo.lock unreadable)"]
        if strays:
            for name in out:
                if ws_of[name] == manifest:
                    out[name].append("/(unmapped path packages: " + ", ".join(strays) + ")")
    real = {os.path.realpath(d): n for n, d in dirs.items()}
    return out, real


def cargo_configs(root):
    """Cargo configuration outside the repository that cargo would load for a build run in
    root: every .cargo/config(.toml) in root's parents and in CARGO_HOME, with its bytes' hash."""
    found, d = [], os.path.dirname(root)
    while True:
        for name in ("config", "config.toml"):
            found.append(os.path.join(d, ".cargo", name))
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    home = os.environ.get("CARGO_HOME") or os.path.join(HOME, ".cargo")
    found += [os.path.join(home, "config"), os.path.join(home, "config.toml")]
    out = []
    for f in found:
        if os.path.isfile(f):
            with open(f, "rb") as fh:
                out.append((f, hashlib.sha256(fh.read()).hexdigest()))
    return out


def git_files(root, paths):
    """Sorted (path, "mode:sha256") of every tracked and untracked, not git-ignored, file under
    paths, hashed from the working tree's raw bytes (no git filters, no trust in the index).
    A symlink is hashed by its target text and, for a file, the target's bytes. Raises
    ValueError for a symlinked directory, which this map cannot follow. Writes nothing to the
    repository."""
    paths = [p for p in paths if os.path.lexists(os.path.join(root, p))]
    if not paths:
        return []
    names = set(run(["git", "ls-files", "-z", "--", *paths], root).split("\0"))
    names |= set(run(["git", "ls-files", "-z", "--others", "--exclude-standard", "--", *paths], root).split("\0"))
    # git-ignored files cargo still reads: config and toolchain files, and targets it finds by
    # itself (src/bin, tests, examples, benches, build.rs)
    loaded = [p for p in paths if os.path.basename(p) in (".cargo", "rust-toolchain", "rust-toolchain.toml")]
    for p in paths:
        loaded += [os.path.join(p, sub) for sub in ("src/bin", "tests", "examples", "benches", "build.rs")]
    loaded = [p for p in loaded if os.path.lexists(os.path.join(root, p))]
    if loaded:
        names |= set(run(["git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", *loaded], root).split("\0"))
    files = []
    for rel in sorted(n for n in names if n):
        full = os.path.join(root, rel)
        if not os.path.lexists(full):
            continue  # deleted in the working tree
        if os.path.islink(full):
            if os.path.isdir(full):
                raise ValueError(f"{rel} is a symlinked directory")
            h = hashlib.sha256(os.readlink(full).encode())
            if os.path.isfile(full):
                with open(full, "rb") as f:
                    h.update(f.read())
            files.append((rel, "link:" + h.hexdigest()))
            continue
        if os.path.isdir(full):
            continue  # a submodule or nested repository: not part of any step
        with open(full, "rb") as f:
            digest_ = hashlib.sha256(f.read()).hexdigest()
        files.append((rel, ("x:" if os.access(full, os.X_OK) else "f:") + digest_))
    return files


def toolchain(root):
    """The compiler and cargo that will run, and the native C compiler/linker driver."""
    tc = run([os.environ.get("RUSTC") or "rustc", "-vV"], root) + run(["cargo", "-V"], root)
    for cc in (os.environ.get("CC") or "cc",):
        try:
            tc += subprocess.run([cc, "--version"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.split("\n")[0]
        except OSError:
            tc += f"{cc}: missing"
    return tc


def envdeps(step=None):
    """Environment names each step's build was seen to depend on (build scripts'
    rerun-if-env-changed, crates' env!), kept per step in the store."""
    try:
        with open(os.path.join(STORE, "envdeps.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data if step is None else set(data.get(step, []))


def learn_envdeps(step, names):
    """Add names to a step's learned environment, under a lock shared by every check on the
    machine; returns the step's full set."""
    os.makedirs(STORE, exist_ok=True)
    with open(os.path.join(STORE, "envdeps.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = envdeps()
        known = set(data.get(step, []))
        if names - known:
            data[step] = sorted(known | names)
            write_json(os.path.join(STORE, "envdeps.json"), data)
        return known | names


def build_env(extra_names):
    keep = {}
    for k, v in os.environ.items():
        if k in ENV_IGNORED:
            continue
        if k in ENV_NAMES or k in extra_names or k.startswith(ENV_PREFIXES):
            keep[k] = v
    w = os.environ.get("RUSTC_WRAPPER", "")
    if w and wrapper_kind(w) == "foreign":
        keep["RUSTC_WRAPPER"] = w  # a wrapper other than the cache may change outputs
    # Unset names matter too: record every name considered, with None for unset.
    for k in sorted(ENV_NAMES | extra_names):
        if k not in ENV_IGNORED:
            keep.setdefault(k, None)
    return keep


def digest(step, inputs, files, tc, env):
    h = hashlib.sha256()
    blob = json.dumps({"v": TOOL_VERSION, "step": step["name"], "cmd": step["cmd"], "inputs": inputs, "files": files,
                       "toolchain": tc, "env": env, "os": platform.system(), "arch": platform.machine()}, sort_keys=True)
    h.update(blob.encode())
    return h.hexdigest()


def stamp_path(d):
    return os.path.join(STORE, "stamps", d[:2], d + ".json")


def read_stamp(d):
    try:
        with open(stamp_path(d)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def parse_depinfo(path):
    """Files and env deps in one dep-info file (Makefile syntax, escaped spaces)."""
    files, envs = [], []
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return files, envs
    for line in text.splitlines():
        if line.startswith("# env-dep:"):
            envs.append(line[len("# env-dep:"):].split("=", 1)[0])
            continue
        i = line.find(": ")  # "target: dep dep ..."; a line "file:" names a dep with no deps
        if line.startswith("#") or i < 0:
            continue
        rest = line[i + 2:].replace("\\ ", "\0")
        files.extend(p.replace("\0", " ") for p in rest.split() if p)
    return files, envs


# Names cargo itself sets for rustc and build scripts, whatever the caller's environment.
CARGO_SET = ("CARGO_PKG_", "CARGO_MANIFEST_", "CARGO_CRATE_", "CARGO_BIN_", "CARGO_CFG_", "CARGO_FEATURE_", "CARGO_PRIMARY_",
             "CARGO_TARGET_TMPDIR", "CARGO_RUSTC_CURRENT_DIR", "CARGO_MAKEFLAGS", "CARGO_ENCODED_RUSTFLAGS")
CARGO_SET_NAMES = {"CARGO", "OUT_DIR", "TARGET", "HOST", "NUM_JOBS", "OPT_LEVEL", "DEBUG", "PROFILE", "RUSTC", "RUSTDOC", "RUSTC_LINKER"}


def depinfo_of(path):
    """The dep-info file cargo or rustc wrote beside an artifact, if any."""
    d, base = os.path.split(path)
    stem = base
    for ext in (".rlib", ".rmeta", ".wasm", ".so", ".dylib", ".dll", ".a", ".exe"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
    for cand in (stem, stem[3:] if stem.startswith("lib") else None):
        if cand and os.path.isfile(os.path.join(d, cand + ".d")):
            return os.path.join(d, cand + ".d")
    return None


def audit(root, messages, inputs_by_pkg, pkg_dirs, target, exempt, workspace="living"):
    """Problems with the input map for the path packages this step built or found fresh
    (empty when sound), and the environment names the whole build depends on. `pkg_dirs`:
    real package directory -> package name; `exempt`: directories a workspace crate may read
    from without being an input (the target dir, Cargo's registry and git checkouts, the
    toolchain's sysroot); `workspace`: the cargo workspace the step built in, where rustc's
    relative dep-info paths start."""
    problems, env_names, ignored_cache = [], set(), {}
    root_real = os.path.realpath(root)

    def pkg_of(msg):
        # "path+file:///abs/living/rules#living-rules@0.1.0", "path+file:///abs/x#0.1.0" or
        # the older "name 0.1.0 (path+file:///abs/x)"
        m = re.search(r"path\+file://([^#)\s]+)", msg.get("package_id", ""))
        if not m:
            return None
        d = os.path.realpath(urllib.parse.unquote(m.group(1)))
        name = pkg_dirs.get(d)
        if name is None:
            problems.append(f"unknown path package {d} (not in cargo metadata)")
        return name

    dir_of = {n: d for d, n in pkg_dirs.items()}

    def check(pkg, f, origin):
        # rustc's dep-info is relative to the workspace root; a build script's rerun-if-changed
        # to its package
        base = dir_of.get(pkg, os.path.join(root, workspace)) if origin.startswith("build script") else os.path.join(root, workspace)
        path = os.path.realpath(os.path.normpath(f if os.path.isabs(f) else os.path.join(base, f)))
        if any(path == e or path.startswith(e + os.sep) for e in exempt):
            return  # generated into the target dir (OUT_DIR), registry sources, the toolchain
        rel = os.path.relpath(path, root_real)
        if rel.startswith(".."):
            problems.append(f"{pkg} reads {path} ({origin}), outside the repository")
            return
        allowed = inputs_by_pkg[pkg]
        if not any(rel == a or rel.startswith(a.rstrip("/") + "/") for a in allowed):
            problems.append(f"{pkg} reads {rel} ({origin}), outside its declared inputs")
            return
        if rel not in ignored_cache:
            ignored_cache[rel] = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=root).returncode == 0
        if ignored_cache[rel]:
            problems.append(f"{pkg} reads git-ignored {rel} ({origin}); stamps cannot see it")

    units = 0
    for m in messages:
        reason = m.get("reason")
        pkg = pkg_of(m)
        if reason == "compiler-artifact":
            for f in list(m.get("filenames") or []) + ([m["executable"]] if m.get("executable") else []):
                dep = depinfo_of(f)
                if not dep:
                    continue
                files, envs = parse_depinfo(dep)
                env_names.update(envs)
                if pkg:
                    units += 1
                    for x in files[1:] if files and files[0].endswith(":") else files:
                        check(pkg, x, os.path.basename(dep))
        elif reason == "build-script-executed" and m.get("out_dir"):
            out = os.path.join(os.path.dirname(m["out_dir"]), "output")
            if not os.path.isfile(out):
                continue
            for line in open(out, errors="replace"):
                line = line.strip()
                for pre in ("cargo:rerun-if-env-changed=", "cargo::rerun-if-env-changed="):
                    if line.startswith(pre):
                        env_names.add(line[len(pre):])
                if pkg:
                    for pre in ("cargo:rerun-if-changed=", "cargo::rerun-if-changed="):
                        if line.startswith(pre):
                            check(pkg, line[len(pre):], "build script")
    if units == 0:
        problems.append("no dep-info found for the workspace units (cannot audit)")
    problems = list(dict.fromkeys(problems))  # each once, in the order found
    env_names = {n for n in env_names if n not in CARGO_SET_NAMES and not n.startswith(CARGO_SET)}
    return problems, env_names


try:  # resolved here, not in the forked child: the lanes run in threads
    import ctypes
    _PRCTL = ctypes.CDLL(None).prctl if platform.system() == "Linux" else None
except (OSError, AttributeError, ImportError):
    _PRCTL = None


def _die_with_parent():
    """In the child, before cargo starts (Linux): a SIGKILLed check still stops its cargo,
    which no longer shares the caller's process group."""
    if _PRCTL is not None:
        _PRCTL(1, int(signal.SIGTERM))  # PR_SET_PDEATHSIG


LIVE = set()  # running cargo processes, stopped if the check is interrupted
STOPPING = threading.Event()

# The watchdog: a process in a session of its own that reads a pipe only the check holds.
# Lines "+<pgid>"/"-<pgid>" register and forget a cargo's process group, "d<path>" a
# temporary folder. When the pipe closes, which the kernel does when the check exits in any
# way (SIGKILL included, on Linux and macOS alike), it sends each group still registered
# SIGTERM, then SIGKILL after 10 s, and removes the folders.
WATCHDOG_SRC = r"""
import os, shutil, signal, sys, time
signal.signal(signal.SIGINT, signal.SIG_IGN)  # a Ctrl-C is the check's to handle
fd, groups, dirs, buf = int(sys.argv[1]), set(), set(), b""
while True:
    try:
        chunk = os.read(fd, 4096)
    except InterruptedError:
        continue
    if not chunk:
        break
    buf += chunk
    *lines, buf = buf.split(b"\n")
    for l in lines:
        kind, arg = l[:1], l[1:].decode(errors="surrogateescape")
        if kind == b"+":
            groups.add(int(arg))
        elif kind == b"-":
            groups.discard(int(arg))
        elif kind == b"d":
            dirs.add(arg)
        elif kind == b"r":
            dirs.discard(arg)

def alive(g):
    try:
        os.killpg(g, 0)
        return True
    except OSError:
        return False

for sig in (signal.SIGTERM, signal.SIGKILL):
    for g in list(groups):
        try:
            os.killpg(g, sig)
        except OSError:
            groups.discard(g)
    end = time.time() + 10
    while groups and time.time() < end:
        groups = {g for g in groups if alive(g)}
        time.sleep(0.2)
    if not groups:
        break
for d in dirs:
    shutil.rmtree(d, ignore_errors=True)
"""


class Watchdog:
    def __init__(self):
        r, self.w = os.pipe()  # not inherited: no cargo holds the pipe open
        self.lock = threading.Lock()
        self.p = subprocess.Popen([sys.executable, "-I", "-c", WATCHDOG_SRC, str(r)], pass_fds=(r,), start_new_session=True,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(r)

    def send(self, line):
        with self.lock:
            if self.w is not None:
                try:
                    os.write(self.w, (line + "\n").encode(errors="surrogateescape"))
                except OSError:
                    pass

    def close(self):
        with self.lock:
            if self.w is not None:
                os.close(self.w)
                self.w = None
        try:
            self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass


WATCHDOG = None


def stop(p):
    """Stop a cargo and everything it started (its process group): TERM, then KILL."""
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
        try:
            os.killpg(p.pid, sig)
        except OSError:
            return
        try:
            p.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run_step(cmd, root, env, log=None, cargo=True):
    """Run a cargo step (or, cargo=False, another command); cargo's JSON messages are
    collected, everything else goes to the terminal (serial) or to the step's log (parallel)."""
    full = cmd[:2] + ["--message-format=json-render-diagnostics"] + cmd[2:] if cargo else cmd
    sink = log or sys.stdout
    # its own process group, so stopping the check stops rustc and test binaries too
    p = subprocess.Popen(full, cwd=root, env=env, stdout=subprocess.PIPE, stderr=log or (None if cargo else subprocess.STDOUT), text=True, errors="replace", bufsize=1,
                         start_new_session=True, preexec_fn=_die_with_parent if _PRCTL else None)
    if WATCHDOG:
        WATCHDOG.send(f"+{p.pid}")  # its own session: the group id is its pid
    LIVE.add(p)
    messages = []
    try:
        for line in p.stdout:
            if line.startswith("{\"reason\""):
                try:
                    m = json.loads(line)
                except ValueError:
                    sink.write(line)
                    continue
                if m.get("reason") in ("compiler-artifact", "build-script-executed"):
                    messages.append(m)
                continue
            sink.write(line)
            sink.flush()
        rc = p.wait()
    except BaseException:
        stop(p)
        raise
    finally:
        LIVE.discard(p)
        if WATCHDOG:
            WATCHDOG.send(f"-{p.pid}")
    return rc, messages


class Jobserver:
    """A make-style jobserver (a fifo holding tokens) that every cargo of a parallel check
    joins, so the lanes together use at most `jobs` compile jobs. Each cargo holds one
    implicit token of its own, so the fifo holds jobs minus the number of lanes."""

    def __init__(self, jobs, lanes):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="living-check-js-")
        self.path = os.path.join(self.dir, "fifo")
        os.mkfifo(self.path, 0o600)
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        os.write(self.fd, b"+" * max(jobs - lanes, 0))
        if WATCHDOG:
            WATCHDOG.send("d" + self.dir)  # removed even if the check is killed
        self.env = {"CARGO_MAKEFLAGS": f"-j{jobs} --jobserver-auth=fifo:{self.path}", "MAKEFLAGS": f"-j{jobs} --jobserver-auth=fifo:{self.path}"}

    def close(self):
        os.close(self.fd)
        shutil.rmtree(self.dir, ignore_errors=True)


def run_gate(gate, root, env, step_target, log):
    """Run a step's gate script on what its builds made: (exit code, its verdict or None).
    The script's lines go where the step's output goes."""
    out = os.path.join(step_target, "living-check-gate")
    verdict_path = os.path.join(out, "gate.json")
    if os.path.exists(verdict_path):
        os.remove(verdict_path)  # never judge by an earlier run's verdict
    cmd = [sys.executable, gate["script"], "--host", os.path.join(step_target, gate["host"]), "--module", os.path.join(step_target, gate["module"]),
           "--out", out, "--json", verdict_path]
    if log:
        log.write("+ " + " ".join(cmd) + "\n")
        log.flush()
    code, _ = run_step(cmd, root, env, log, cargo=False)
    try:
        with open(verdict_path) as f:
            verdict = json.load(f)
    except (OSError, ValueError):
        verdict = None
    if code == 0 and not (verdict and verdict.get("ok")):
        code = 1  # a gate that passes must say so
    return code, verdict


def wrapper_kind(w):
    """What a pre-set RUSTC_WRAPPER is: "ours" when it resolves (by PATH, links) to
    living/tools/sccache-rustc or to a copy of it (any worktree's, any name), "sccache" for
    a plain sccache, else "foreign"."""
    path = w if os.sep in w else (shutil.which(w) or w)
    rp = os.path.realpath(path)
    if rp == os.path.realpath(OUR_WRAPPER):
        return "ours"
    try:
        with open(rp, "rb") as f:
            if WRAPPER_MARK in f.read(512):
                return "ours"
    except OSError:
        pass
    return "sccache" if os.path.basename(rp).split(".")[0] == "sccache" else "foreign"


def sccache_env(root):
    """(environment to add, the sccache to ask for stats or None, what was decided)."""
    preset = os.environ.get("RUSTC_WRAPPER")
    if os.environ.get("LIVING_SCCACHE", "1") == "0":
        return {}, None, "off (LIVING_SCCACHE=0)" + (f"; RUSTC_WRAPPER={preset} still applies" if preset else "")
    kind = wrapper_kind(preset) if preset else None
    if kind == "foreign":
        return {}, None, (f"RUSTC_WRAPPER={preset} is set and is not living/tools/sccache-rustc: cargo uses it as it is, "
                          "without this check's cache settings or stats, and it enters every step's digest")
    if kind == "sccache":
        return {}, None, f"RUSTC_WRAPPER={preset} is a plain sccache: cargo uses it as it is, with its own settings; no cache stats"
    # the pinned copy (living/tools/install_sccache.sh), or SLOP_SCCACHE; never one on PATH
    exe = next((p for p in (os.environ.get("SLOP_SCCACHE"), PINNED_SCCACHE) if p and os.access(p, os.X_OK)), None)
    if not exe:
        on_path = shutil.which("sccache")
        return {}, None, (f"no pinned sccache in {PINNED_SCCACHE.replace(HOME, '~')} (living/tools/install_sccache.sh)"
                          + (f"; {on_path} on PATH is not used" if on_path else "")
                          + ("; the pre-set wrapper falls back to an sccache on PATH" if preset else "; compiling without a cache"))
    ours = {
        "SCCACHE_DIR": os.environ.get("SLOP_SCCACHE_DIR") or os.path.join(CACHE, "slop-sccache"),
        "SCCACHE_CACHE_SIZE": os.environ.get("SLOP_SCCACHE_SIZE", "20G"),
        "SCCACHE_SERVER_PORT": os.environ.get("SLOP_SCCACHE_PORT", "4237"),
        "SCCACHE_IGNORE_SERVER_IO_ERROR": "1",  # a cache failure compiles locally, never fails the build
    }
    if preset:  # what the caller set for its wrapper wins, so the stats ask the server it compiles through
        ours.update({k: os.environ[k] for k in ours if os.environ.get(k)})
    env = {"RUSTC_WRAPPER": preset or OUR_WRAPPER, "SLOP_SCCACHE": exe, **ours}
    full_env = {**os.environ, **env}
    probe = lambda: subprocess.run([exe, "--show-stats"], env=full_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not probe():  # no server on the port yet (another check may start one at the same time)
        r = subprocess.run([exe, "--start-server"], env=full_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode != 0 and not probe():
            if preset:
                return {}, None, f"sccache did not start ({r.stdout.strip()[:200]}); the pre-set RUSTC_WRAPPER={preset} stays, no stats"
            return {}, None, f"sccache did not start ({r.stdout.strip()[:200]}); compiling without it"
    return env, exe, (f"the pre-set RUSTC_WRAPPER={preset}" if preset else "living/tools/sccache-rustc")


def stats_delta(a, b):
    if not a or not b:
        return None
    return {k: b[k] - a.get(k, 0) for k in b}


def sccache_stats(exe, env):
    if not exe:
        return None
    r = subprocess.run([exe, "--show-stats", "--stats-format", "json"], env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        s = json.loads(r.stdout).get("stats", {})
    except ValueError:
        return None
    def total(v):  # {"counts": {"Rust": n}, "adv_counts": {...}} counts each once
        if isinstance(v, dict):
            v = v.get("counts", v)
            return sum(x for x in v.values() if isinstance(x, int))
        return v if isinstance(v, int) else 0
    # failed: compiles rustc ran and failed; on a passing check, build scripts' feature probes
    # that are meant to fail on stable (anyhow, thiserror 1 and 2, proc-macro2; docs/TOOLING.md)
    return {"requests": total(s.get("compile_requests", 0)), "hits": total(s.get("cache_hits", {})), "misses": total(s.get("cache_misses", {})),
            "not_cacheable": total(s.get("requests_not_cacheable", 0)), "failed": total(s.get("compile_fails", 0))}


def show_log(path):
    """A failed step's log, without cargo's per-crate progress lines."""
    noise = ("Compiling ", "Fresh ", "Checking ", "Downloaded ", "Downloading ", "Blocking ", "Building ")
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return
    kept = [l for l in lines if not l.strip().startswith(noise)]
    print(f"----- {path} ({len(lines)} lines, progress lines dropped) -----")
    print("\n".join(kept[-400:]))
    print("-----", flush=True)


def main(argv):
    full = os.environ.get("LIVING_CHECK_FULL") == "1"
    plan_only, only, use_sccache, json_out = False, None, True, None
    serial = os.environ.get("LIVING_CHECK_SERIAL") == "1"
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--full":
            full = True
        elif a == "--plan":
            plan_only = True
        elif a == "--steps" and args:
            only = set(args.pop(0).split(","))
        elif a == "--serial":
            serial = True
        elif a == "--no-sccache":
            use_sccache = False
        elif a == "--json" and args:
            json_out = os.path.abspath(args.pop(0))
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"unknown argument {a}\n{__doc__}", file=sys.stderr)
            return 2
    try:
        root = repo_root()
    except (subprocess.CalledProcessError, OSError):
        print("living-check: run it inside the repository", file=sys.stderr)
        return 2
    os.chdir(root)
    t_start = time.time()
    clos, pkg_dirs = closures(root)
    tc = toolchain(root)
    configs = cargo_configs(root)
    steps = [s for s in STEPS if not only or s["name"] in only]
    if only and len(steps) != len(only):
        print(f"unknown step in {sorted(only)}; steps: {[s['name'] for s in STEPS]}", file=sys.stderr)
        return 2
    target = target_dir(root)
    inputs_by_pkg = {p: sorted(set(d) | set(SHARED_INPUTS)) for p, d in clos.items()}
    exempt = [os.path.realpath(target)]
    cargo_home = os.environ.get("CARGO_HOME") or os.path.join(HOME, ".cargo")
    exempt += [os.path.realpath(os.path.join(cargo_home, d)) for d in ("registry", "git")]
    try:
        exempt.append(os.path.realpath(run([os.environ.get("RUSTC") or "rustc", "--print", "sysroot"], root).strip()))
    except (subprocess.CalledProcessError, OSError):
        pass

    def step_key(step, names=None):
        """(digest or None when this step cannot be keyed, inputs, files)."""
        inputs = sorted(set(SHARED_INPUTS).union(*(clos[p] for p in step["packages"]), step.get("inputs", [])))
        outside = [i for i in inputs if os.path.isabs(i)]
        try:
            if outside:
                raise ValueError(f"inputs outside the repository: {outside}")
            files = git_files(root, inputs)
        except ValueError as e:
            return None, inputs, str(e)
        env_names = envdeps(step["name"]) if names is None else names
        return digest(step, inputs, files + [("cargo-config:" + c, h) for c, h in configs], tc, build_env(env_names)), inputs, files

    plan = []
    for s in steps:
        d, inputs, files = step_key(s)
        st = None if full or d is None else read_stamp(d)
        plan.append((s, d, inputs, files, st))
    for s, d, inputs, files, st in plan:
        if st:
            say(f"{s['name']}: skip, passed {st.get('at', '?')} in {st.get('worktree', '?')} at {st.get('commit', '?')[:10]} on identical inputs [{d[:12]}]")
        elif d is None:
            say(f"{s['name']}: run, and no stamp: {files}")
        else:
            say(f"{s['name']}: run{' (--full)' if full else ''} [{d[:12]}]")
    if plan_only:
        if json_out:
            write_json(json_out, {"plan": [{"name": s["name"], "digest": d, "skip": bool(st), "inputs": inputs, "why": None if d else files}
                                           for s, d, inputs, files, st in plan]})
        return 0

    env_extra, exe, how = sccache_env(root) if use_sccache else ({}, None, "off (--no-sccache)")
    env = {**os.environ, **env_extra}
    stats0 = None
    if exe:
        say(f"compile cache: sccache {env_extra['SCCACHE_DIR']} (max {env_extra['SCCACHE_CACHE_SIZE']}, port {env_extra['SCCACHE_SERVER_PORT']}, "
            f"{exe.replace(HOME, '~')}) through {how}")
        stats0 = sccache_stats(exe, env_extra)  # the server is shared: record the difference
    else:
        say(f"compile cache: none: {how}")
    head = run(["git", "rev-parse", "HEAD"], root).strip()
    dirty = bool(run(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=all", "--", "living"], root).strip())
    record = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "worktree": root, "commit": head, "dirty": dirty, "target": target,
              "jobs": os.environ.get("CARGO_BUILD_JOBS"), "load": os.getloadavg()[0], "sccache": bool(exe), "sccache_how": how,
              "rustc_wrapper": env.get("RUSTC_WRAPPER"), "steps": []}
    lock = threading.Lock()
    failed = []
    by_name = {}

    def run_one(s, d, files, log):
        t0 = time.time()
        load0 = os.getloadavg()[0]
        env, step_target = step_env, target
        if s.get("target"):
            step_target = os.path.join(target, s["target"])
            env = {**step_env, "CARGO_TARGET_DIR": step_target}
        code, messages = 0, []
        for cmd in cmds_of(s):
            code, m = run_step(cmd, root, env, log)
            messages += m
            if code != 0:
                break
        verdict = None
        if code == 0 and s.get("gate"):
            code, verdict = run_gate(s["gate"], root, env, step_target, log)
        secs = time.time() - t0
        entry = {"name": s["name"], "skipped": False, "digest": d, "secs": round(secs, 1), "rc": code, "load0": load0,
                 "load1": os.getloadavg()[0], "units": len(messages), "fresh": sum(1 for m in messages if m.get("fresh"))}
        if verdict:
            entry["gate"] = verdict
        by_name[s["name"]] = entry
        if code != 0:
            with lock:
                failed.append(s["name"])
                say(f"{s['name']}: FAILED after {secs:.0f} s (exit {code})")
                for v in (verdict or {}).get("laws", []):
                    if not v["ok"]:
                        say(f"  {v['law']} takes {v['fuel']:,.0f} fuel a call, over its budget of {v['budget']:,} ({s['gate']['script'].rsplit('/', 1)[0]}/budgets.json)"
                            if v["budget"] is not None else f"  {v['law']} has no budget in budgets.json")
                for law in (verdict or {}).get("missing", []):
                    say(f"  {law} has a budget but was not measured")
                if log:
                    log.flush()
                    show_log(log.name)
            return
        problems, names = audit(root, messages, inputs_by_pkg, pkg_dirs, target, exempt, s.get("workspace", "living"))
        with lock:
            d2, _, files2 = step_key(s, learn_envdeps(s["name"], names))
            if d is None or d2 is None:
                entry["audit"] = [str(files2)]
                say(f"{s['name']}: passed in {secs:.0f} s, not stamped: {files2}")
            elif problems:
                entry["audit"] = problems
                say(f"{s['name']}: passed in {secs:.0f} s, NOT stamped: the input map misses what the build read:")
                for p in problems[:20]:
                    say(f"  {p}")
                say("  add the paths to SHARED_INPUTS in living/tools/check.py (or stop reading ignored files)")
            elif files2 != files:
                entry["audit"] = ["inputs changed while the step ran"]
                say(f"{s['name']}: passed in {secs:.0f} s, not stamped: its inputs changed while it ran")
            else:
                write_json(stamp_path(d2), {"step": s["name"], "at": record["at"], "worktree": root, "commit": head, "dirty": dirty,
                                            "secs": round(secs, 1), "host": platform.node()})
                entry["stamp"] = d2
                say(f"{s['name']}: passed in {secs:.0f} s, stamped [{d2[:12]}]")

    def lane(items):
        for s, d, inputs, files, st in items:
            if failed or STOPPING.is_set():
                by_name[s["name"]] = {"name": s["name"], "skipped": False, "not_run": True, "secs": 0}
                continue
            try:
                if parallel:
                    path = os.path.join(logs, s["name"] + ".log")
                    with lock:
                        say(f"{s['name']}: {' && '.join(' '.join(c) for c in cmds_of(s))}{' && gate' if s.get('gate') else ''}  (log {path})")
                    with open(path, "w") as log:
                        run_one(s, d, files, log)
                else:
                    say(f"{s['name']}: {' && '.join(' '.join(c) for c in cmds_of(s))}{' && gate' if s.get('gate') else ''}")
                    run_one(s, d, files, None)
            except BaseException as e:  # a crash in the check is a failed step, never a pass
                with lock:
                    failed.append(s["name"])
                    entry = by_name.setdefault(s["name"], {"name": s["name"], "skipped": False, "secs": 0})
                    entry.update(rc=entry.get("rc") or 1, error=f"{type(e).__name__}: {e}")
                    say(f"{s['name']}: FAILED in the check itself: {type(e).__name__}: {e}")
                if not isinstance(e, Exception):
                    raise

    todo = [x for x in plan if not x[4]]
    for s, d, inputs, files, st in plan:
        if st:
            by_name[s["name"]] = {"name": s["name"], "skipped": True, "digest": d, "secs": 0}
    lanes = {}
    for x in todo:
        lanes.setdefault(x[0]["lane"], []).append(x)
    cores = os.cpu_count() or 4
    try:  # as cargo reads it: a count, a negative count off the cores, or "default"
        jobs = int(os.environ.get("CARGO_BUILD_JOBS") or cores)
        jobs = jobs if jobs > 0 else max(cores + jobs, 1)
    except ValueError:
        jobs = cores
    parallel = serial is False and len(lanes) > 1 and jobs > len(lanes)
    global WATCHDOG
    if todo:
        WATCHDOG = Watchdog()
    step_env = dict(env)
    js = None
    logs = os.path.join(target, "living-check")
    if parallel:
        os.makedirs(logs, exist_ok=True)
        js = Jobserver(jobs, len(lanes))
        step_env.update(js.env)
        say(f"{len(lanes)} lanes at once ({', '.join('/'.join(x[0]['name'] for x in l) for l in lanes.values())}), {jobs} jobs shared")
    try:
        if parallel:
            threads = [threading.Thread(target=lane, args=(l,), daemon=True) for l in lanes.values()]
            for t in threads:
                t.start()
            for t in threads:
                while t.is_alive():
                    t.join(0.5)
        else:
            lane(todo)
    finally:
        STOPPING.set()  # no lane starts a step after this
        for p in list(LIVE):  # interrupted: stop the lanes' cargo processes and their children
            stop(p)
        if js:
            js.close()
            if WATCHDOG:
                WATCHDOG.send("r" + js.dir)
        if WATCHDOG:
            WATCHDOG.close()
    for s in steps:  # every planned step must be accounted for: skipped, passed or failed
        e = by_name.get(s["name"])
        if e is None or (not e.get("skipped") and not e.get("not_run") and e.get("rc") != 0):
            if s["name"] not in failed:
                failed.append(s["name"])
                by_name.setdefault(s["name"], {"name": s["name"], "skipped": False, "secs": 0}).setdefault("rc", 1)
    record["steps"] = [by_name[s["name"]] for s in steps]
    rc = next((by_name[n].get("rc") or 1 for n in failed), 0)
    record["secs"] = round(time.time() - t_start, 1)
    record["sccache_stats"] = stats_delta(stats0, sccache_stats(exe, env_extra)) if exe else None
    record["rc"] = rc
    try:
        os.makedirs(STORE, exist_ok=True)
        with open(os.path.join(STORE, "runs.jsonl"), "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
    if json_out:
        write_json(os.path.abspath(json_out), record)
    ran = [x for x in record["steps"] if not x["skipped"]]
    say(("FAILED" if rc else "ok") + f" in {record['secs']:.0f} s: " + ", ".join(
        f"{x['name']} {'skipped' if x['skipped'] else 'not run' if x.get('not_run') else 'FAILED' if x.get('rc') else str(round(x['secs'])) + ' s'}" for x in record["steps"])
        + (f"; sccache {record['sccache_stats']}" if record["sccache_stats"] and ran else "")
        + ("; the failed compiles of a passing check are build scripts' feature probes (docs/TOOLING.md)"
           if not rc and (record["sccache_stats"] or {}).get("failed") else ""))
    return rc


def _terminate(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    sys.exit(main(sys.argv[1:]))
