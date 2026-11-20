#!/usr/bin/env python3
"""Remove a git worktree only after archiving what git would lose with it.

`git worktree remove --force` deletes a worktree's untracked and git-ignored files, and in
this project those are evidence: `.local/` verification runs, stills, measurement series,
uncommitted edits. This tool archives them first, verifies the archive, and only then removes
the worktree (docs/TOOLING.md, "Removing a worktree"). Never run `git worktree remove --force`
directly.

    wt_remove.py PATH [--dry-run] [--archive-root DIR] [--keep-caches]

What goes in `<archive-root>/worktree-evidence-<YYYYMMDD>/<name>-<HHMMSS>.tar.gz`:
- every untracked and git-ignored file (`git ls-files --others`), so `.local/` and any other
  evidence, except build caches: folders holding a `CACHEDIR.TAG` (Cargo targets, sccache),
  which are regenerable and only listed (`--keep-caches` archives them too);
- `tracked.patch` (`git diff HEAD --binary`) and `status.txt`, so uncommitted edits to tracked
  files survive;
- `manifest.json`: path, branch, HEAD, whether HEAD is on origin/main or any remote branch,
  host, time, counts, sizes and the caches left out.

A `.sha256` sits beside it (`sha256sum -c` / `shasum -a 256 -c` format). The archive is then
read back: every member present with its size, and the digest recomputed. Only after that is
the worktree removed (`git worktree remove --force`, run from another worktree of the same
repository). The branch is kept: removing a worktree never deletes commits.

Refuses, before writing anything: the repository's main worktree, any path under
`~/dev/slop-art-online`, a path that is not a worktree root, the worktree this command runs
in, and a worktree some process is working in (its cwd is inside it).

Python 3 standard library only, so it runs unchanged on the dev-box, the Spark and the laptop
(macOS). Install a copy as `~/.local/share/slop-tools/wt-remove`.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tarfile

PROTECTED = [os.path.realpath(os.path.expanduser("~/dev/slop-art-online"))]


def git(cwd, *args, check=True, text=True):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=text)
    if check and r.returncode != 0:
        sys.exit(f"wt-remove: git {' '.join(args)} failed in {cwd}: {(r.stderr or '').strip()}")
    return r


def inside(child, parent):
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def worktrees(path):
    """(path, branch) of every worktree of the repository, the main worktree first."""
    out, cur = [], {}
    for line in git(path, "worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = os.path.realpath(line[len("worktree "):])
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].removeprefix("refs/heads/")
    return out


def busy(path):
    """Processes whose current directory is inside `path` (not this one)."""
    pids = []
    if os.path.isdir("/proc"):
        for p in os.listdir("/proc"):
            if p.isdigit() and int(p) != os.getpid():
                try:
                    if inside(os.readlink(f"/proc/{p}/cwd"), path):
                        pids.append(int(p))
                except OSError:
                    pass
    else:  # macOS: lsof lists each process's cwd as fd "cwd"
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True)
        pid = None
        for line in r.stdout.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and pid not in (None, os.getpid()) and inside(line[1:], path):
                pids.append(pid)
    return sorted(set(pids))


def caches(root):
    """Folders under root holding a CACHEDIR.TAG (build caches), with their sizes."""
    found = []
    for d, dirs, files in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        if "CACHEDIR.TAG" in files:
            size = 0
            for dd, _, ff in os.walk(d):
                for f in ff:
                    try:
                        size += os.lstat(os.path.join(dd, f)).st_size
                    except OSError:
                        pass
            found.append((os.path.relpath(d, root), size))
            dirs[:] = []
    return found


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true", help="list what would be archived; change nothing")
    ap.add_argument("--archive-root", default=os.path.expanduser("~/archive"))
    ap.add_argument("--keep-caches", action="store_true", help="archive CACHEDIR.TAG folders too")
    a = ap.parse_args()

    path = os.path.realpath(a.path)
    if not os.path.isdir(path):
        sys.exit(f"wt-remove: {path} is not a folder")
    for p in PROTECTED:
        if inside(path, p):
            sys.exit(f"wt-remove: refusing {path}: it is under the protected {p}")
    top = os.path.realpath(git(path, "rev-parse", "--show-toplevel").stdout.strip())
    if top != path:
        sys.exit(f"wt-remove: {path} is not a worktree root (its root is {top})")
    trees = worktrees(path)
    if trees and trees[0]["path"] == path:
        sys.exit(f"wt-remove: refusing {path}: it is the repository's main worktree")
    if inside(os.getcwd(), path):
        sys.exit(f"wt-remove: refusing {path}: this command runs inside it (cd elsewhere first)")
    others = [t["path"] for t in trees if t["path"] != path and os.path.isdir(t["path"])]
    if not others:
        sys.exit("wt-remove: no other worktree of this repository to run the removal from")
    pids = busy(path)
    if pids:
        sys.exit(f"wt-remove: refusing {path}: processes are working in it: {pids}")

    branch = git(path, "branch", "--show-current").stdout.strip()
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    on_main = git(path, "merge-base", "--is-ancestor", head, "origin/main", check=False).returncode == 0
    remotes = [b.strip() for b in git(path, "branch", "-r", "--contains", head).stdout.splitlines() if b.strip()]
    patch = git(path, "diff", "HEAD", "--binary", text=False).stdout
    status = git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout

    skipped = [] if a.keep_caches else caches(path)
    skip_dirs = [s for s, _ in skipped]
    listed = git(path, "ls-files", "-z", "--others").stdout.split("\0")
    files, total = [], 0
    for rel in filter(None, listed):
        if any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in skip_dirs):
            continue
        full = os.path.join(path, rel)
        try:
            st = os.lstat(full)
        except OSError:
            continue
        files.append(rel)
        total += st.st_size if not os.path.islink(full) else 0

    name = os.path.basename(path)
    now = datetime.datetime.now().astimezone()
    out_dir = os.path.join(a.archive_root, f"worktree-evidence-{now:%Y%m%d}")
    out = os.path.join(out_dir, f"{name}-{now:%H%M%S}.tar.gz")
    manifest = {
        "worktree": path, "branch": branch, "head": head, "head_on_origin_main": on_main,
        "head_on_remote_branches": remotes, "host": platform.node(), "time": now.isoformat(),
        "files": len(files), "bytes": total, "tracked_patch_bytes": len(patch),
        "caches_left_out": [{"path": s, "bytes": b} for s, b in skipped], "tool": "living/tools/wt_remove.py",
    }
    print(f"wt-remove: {path} ({branch or 'detached'} at {head[:10]}; on origin/main: {on_main}; on remotes: {', '.join(remotes) or 'none'})")
    print(f"  archive {len(files)} untracked/ignored files, {total / 1e6:.1f} MB, tracked changes {len(patch)} B")
    for s, b in skipped:
        print(f"  leave out build cache {s} ({b / 1e9:.2f} GB)")
    if not remotes and not on_main:
        print("  note: HEAD is on no remote branch; the local branch keeps it (removing a worktree deletes no commits)")
    if a.dry_run:
        print(f"  dry run: would write {out} and then remove the worktree")
        return

    os.makedirs(out_dir, exist_ok=True)
    tmp = out + ".part"
    with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        def add_bytes(arc, data):
            ti = tarfile.TarInfo(arc)
            ti.size, ti.mtime = len(data), int(now.timestamp())
            tar.addfile(ti, io.BytesIO(data))
        add_bytes(f"{name}/manifest.json", json.dumps(manifest, indent=1).encode())
        add_bytes(f"{name}/tracked.patch", patch)
        add_bytes(f"{name}/status.txt", status.encode())
        for rel in files:
            tar.add(os.path.join(path, rel), arcname=f"{name}/files/{rel}", recursive=False)
    os.replace(tmp, out)
    digest = sha256(out)
    with open(out + ".sha256", "w") as f:
        f.write(f"{digest}  {os.path.basename(out)}\n")

    # Read it back before anything is removed.
    want = {f"{name}/files/{rel}": rel for rel in files}
    seen = set()
    with tarfile.open(out, "r:gz") as tar:
        for m in tar:
            if m.name in want:
                rel = want[m.name]
                st = os.lstat(os.path.join(path, rel))
                if m.isfile() and m.size != st.st_size:
                    sys.exit(f"wt-remove: archive check failed: {rel} is {m.size} B in the archive, {st.st_size} B on disk; nothing removed")
                seen.add(m.name)
    missing = set(want) - seen
    if missing:
        sys.exit(f"wt-remove: archive check failed: {len(missing)} files missing (e.g. {sorted(missing)[0]}); nothing removed")
    if sha256(out) != digest:
        sys.exit("wt-remove: archive check failed: digest changed on re-read; nothing removed")
    print(f"  archived and verified: {out} ({os.path.getsize(out) / 1e6:.1f} MB, sha256 {digest[:16]}…)")

    r = git(others[0], "worktree", "remove", "--force", path, check=False)
    if r.returncode != 0:
        sys.exit(f"wt-remove: git worktree remove failed: {r.stderr.strip()} (the archive is kept)")
    print(f"  removed worktree {path}; branch {branch or '(detached)'} kept")


if __name__ == "__main__":
    main()
