#!/usr/bin/env python3
"""Fail a wasm module that embeds a host path (docs/TOOLING.md, "Byte-identical wasm").

A module built through living/tools/rustc-remap names its sources /cargo/..., /src/... and
/out/...; one that holds `/home/`, `/Users/`, this machine's CARGO_HOME, this checkout or $HOME
(each as given and as resolved through links) was built around the remap: a `RUSTC` in the
environment, an sccache wrapper that predates living/tools/sccache-rustc's --remap-flags, or a
cargo run outside the checkout. Such a module differs between machines and checkouts.

Usage: host_paths.py [--max N] MODULE...   exit 1 naming each module with hits and its first N
       host_paths.py --selftest            (default 5) paths; exit 0 when every module is clean

Only the path strings are printed: each hit is cut at the end of its path (the first `.rs`, or
the first byte that cannot be in a path) and at 160 characters, never the bytes around it.
Used by the scene gate's module builds (verify.py launch) and check.py's authority step.
"""
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH_BYTE = re.compile(rb"[A-Za-z0-9._/@+~=,:-]")
MAX_LEN = 160


def needles(root=ROOT, env=None):
    """The byte strings that mark a host path, longest first (so a hit is named by the most
    specific one)."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    cargo_home = env.get("CARGO_HOME") or os.path.join(home, ".cargo")
    out = {"/home/", "/Users/"}
    for p in (cargo_home, root, home):
        for q in (p, os.path.realpath(p)):
            q = q.rstrip("/")
            if len(q) > 1:  # never "/" or empty
                out.add(q + "/")
    return sorted((n.encode() for n in out), key=len, reverse=True)


def path_at(data, start):
    """The path string beginning at `start`: up to its first `.rs`, else to the first byte that
    cannot be in a path, at most MAX_LEN characters."""
    end = start
    limit = min(len(data), start + MAX_LEN)
    while end < limit and PATH_BYTE.match(data, end):
        end += 1
    s = data[start:end]
    rs = s.find(b".rs")
    if rs >= 0:
        s = s[:rs + 3]
    return s.decode("ascii", "replace")


def scan(path, marks=None):
    """(number of host-path hits, distinct hit strings in file order)."""
    with open(path, "rb") as f:
        data = f.read()
    marks = needles() if marks is None else marks
    starts = set()
    for n in marks:
        i = data.find(n)
        while i >= 0:
            starts.add(i)
            i = data.find(n, i + 1)
    # A hit inside an earlier hit's path (a needle matching later in the same string) is the same path.
    hits, seen, covered = [], set(), -1
    for i in sorted(starts):
        if i < covered:
            continue
        s = path_at(data, i)
        covered = i + max(len(s), 1)
        hits.append(s)
    distinct = [s for s in hits if not (s in seen or seen.add(s))]
    return len(hits), distinct


def hint():
    """Why a module would hold host paths, from this environment."""
    why = []
    if os.environ.get("RUSTC"):
        why.append("RUSTC is set, so cargo skipped living/tools/rustc-remap")
    w = os.environ.get("RUSTC_WRAPPER")
    if w:
        ours = os.path.join(ROOT, "living", "tools", "sccache-rustc")
        try:
            with open(w if os.sep in w else (shutil.which(w) or w), "rb") as a, open(ours, "rb") as b:
                same = a.read() == b.read()
        except OSError:
            same = False
        if not same:
            why.append(f"RUSTC_WRAPPER={w} is not this checkout's living/tools/sccache-rustc (an older copy loses the remap)")
    return "; ".join(why)


def check(modules, keep=5, out=sys.stderr):
    """Scan each module; print a line per module with hits. True when all are clean."""
    bad = 0
    for m in modules:
        count, distinct = scan(m)
        if count:
            bad += 1
            more = f" (+{len(distinct) - keep} more distinct)" if len(distinct) > keep else ""
            print(f"host paths: {m} holds {count} host path(s), first: " + ", ".join(distinct[:keep]) + more, file=out)
    if bad:
        h = hint()
        print("host paths: such a module differs between machines and checkouts (docs/TOOLING.md, \"Byte-identical wasm\")"
              + (f"; {h}" if h else ""), file=out)
    return bad == 0


def selftest():
    ok = True

    def expect(what, cond, got=None):
        nonlocal ok
        ok &= bool(cond)
        print(("ok   " if cond else "FAIL ") + what + ("" if cond else f": {got!r}"))

    with tempfile.TemporaryDirectory() as d:
        clean = os.path.join(d, "clean.wasm")
        with open(clean, "wb") as f:
            f.write(b"\0asm\1\0\0\0/cargo/registry/src/index.crates.io-0000/x-1.0/src/lib.rs\0/src/living/rules/src/a.rs"
                    b"/rustc/0123/library/core/src/option.rs called `Option::unwrap()`")
        expect("a remapped module is clean", scan(clean)[0] == 0, scan(clean))
        planted = os.path.join(d, "planted.wasm")
        secret = b"SECRETVALUE"
        with open(planted, "wb") as f:
            f.write(b"\0asm\1\0\0\0" + secret + b"\0/Users/someone/.cargo/registry/src/index.crates.io-1/y-2.0/src/lib.rs"
                    + secret + b"\0" + ROOT.encode() + b"/living/authority/src/lib.rsunwrap on None" + b"\xff" * 4
                    + b"/home/x/" + b"q" * 400 + b"\0/home/someone/.cargo/registry/src/index.crates.io-1/y-2.0/src/lib.rs")
        count, distinct = scan(planted)
        expect("planted host paths are found (/Users/, the checkout, /home/)", count == 4, (count, distinct))
        expect("each hit stops at its path's end (.rs)", distinct[0].endswith("/y-2.0/src/lib.rs")
               and distinct[1] == ROOT + "/living/authority/src/lib.rs", distinct)
        expect("a hit with no end is cut at 160 characters", any(len(s) == MAX_LEN for s in distinct), [len(s) for s in distinct])
        expect("nothing beyond the paths is printed", not any("SECRET" in s or "unwrap" in s for s in distinct), distinct)
        resolved = os.path.join(d, "resolved")
        os.makedirs(os.path.join(resolved, "real"))
        os.symlink(os.path.join(resolved, "real"), os.path.join(resolved, "link"))
        marks = needles(root=os.path.join(resolved, "link"), env={"HOME": "/nonexistent-home", "CARGO_HOME": "/opt/cargo"})
        expect("the checkout is matched as given and as resolved, CARGO_HOME too",
               {(os.path.join(resolved, "link") + "/").encode(), (os.path.realpath(os.path.join(resolved, "real")) + "/").encode(),
                b"/opt/cargo/"} <= set(marks), marks)
        expect("a root of / is never a needle", b"/" not in needles(root="/", env={"HOME": "/"}))
        import io
        buf = io.StringIO()
        expect("check() fails a planted module and names it", not check([clean, planted], out=buf) and planted in buf.getvalue()
               and clean not in buf.getvalue() and "SECRET" not in buf.getvalue(), buf.getvalue())
        expect("check() passes clean modules", check([clean], out=io.StringIO()))
    print("host_paths selftest: " + ("all passed" if ok else "FAILED"))
    return ok


def main(argv):
    if argv[:1] == ["--selftest"]:
        return 0 if selftest() else 1
    keep = 5
    if argv[:1] == ["--max"]:
        keep, argv = int(argv[1]), argv[2:]
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0 if check(argv, keep) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
