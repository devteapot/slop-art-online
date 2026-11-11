#!/usr/bin/env python3
"""Remove the project's idle build folders under a written policy (docs/TOOLING.md, "Disk").

What it may remove: Cargo target folders (tagged by Cargo's CACHEDIR.TAG, or holding Cargo's
.rustc_info.json beside tagged or locked build folders) inside the git worktrees of this
repository, and nothing else. A folder is removed when no process has its cwd, executable,
open files or mapped files inside it, no container mounts it, no Cargo lock in it is held,
and one of:
  - merged:   the worktree's HEAD is in origin/main but not on main's own first-parent line
              (so a branch of its own that was merged, not a fresh worktree or a coordinator),
              the worktree has no uncommitted or untracked changes outside .local/, and the
              folder has been idle --merged-idle hours (2);
  - idle:     the folder and the worktree's git state have been idle --idle hours (24);
  - pressure: free space is under --target-gb (floor + 30 GB) and the folder has been idle
              --pressure-idle hours (2); oldest first, until free space reaches the target.
Idle means no file in the folder, and neither the worktree's index nor its HEAD log, changed.

Never touched: the protected checkouts (~/dev/slop-art-online, ~/dev/slop-game,
~/dev/slop-floors, ~/dev/slop-ab-arm1, ~/dev/slop-ab-arm2) and everything under them,
~/archive, container storage and volumes (never pruned), anything that is not a build
folder (evidence in .local included), the worktree roots themselves, and symlinks. A machine
adds its own protected paths in ~/.config/slop-disk/protect.txt (one path per line, `#`
comments, `~` expanded; a path protects everything under it, and a build folder holding it)
or with --protect PATH; these add to the built-in list and never shorten it.

A removal renames the folder aside while holding its Cargo locks, checks again that nothing
uses it, then deletes it. Prints a report and keeps it in ~/.local/state/slop-disk/.

Usage: disk_clean.py [--apply] [--repo PATH] [--floor-gb 40] [--target-gb N] [--idle 24]
                     [--merged-idle 2] [--pressure-idle 2] [--protect PATH]...
                     [--protect-file PATH] [--list-protected] [--json]
  Without --apply it is a dry run: the same report, nothing removed.
  --protect PATH     protect PATH and everything under it (repeatable), besides the file
  --protect-file P   read the machine's protected paths from P (~/.config/slop-disk/protect.txt)
  --list-protected   print every protected path and where it comes from, then stop
Exit status: 0, 2 for a bad argument or an unreadable or invalid protect file (nothing is
removed), or 3 when free space is still under the floor afterwards.
"""
import fcntl
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROTECTED = [os.path.join(HOME, p) for p in ("dev/slop-art-online", "dev/slop-game", "dev/slop-floors", "dev/slop-ab-arm1", "dev/slop-ab-arm2", "archive")]
NEVER = [os.path.join(HOME, p) for p in (".local/share/containers", ".local/share/docker", ".docker", "Library/Containers")] + ["/var/lib/containers", "/var/lib/docker"]
# The machine's own additions to PROTECTED (never a replacement for it).
PROTECT_FILE = os.path.join(HOME, ".config", "slop-disk", "protect.txt")
CARGO_SIG = "Signature: 8a477f597d28d172789f06886806bc55"
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state"), "slop-disk")
SKIP_DIRS = {".git", "node_modules", "__pycache__"}
GB = 1024 ** 3
WARNINGS = []
NOTES = []  # things worth knowing that limit nothing (a container tool with nothing to run)


def real(p):
    return os.path.realpath(p)


def inside(path, base):
    path, base = real(path), real(base)
    return path == base or path.startswith(base.rstrip("/") + "/")


def read_protect_file(path):
    """[(path, source)] from a protect file: one path per line, `#` starts a comment (a whole
    line, or after a space), `~` is expanded. A missing file adds nothing. Raises ValueError
    for an unreadable file or a line that is not an absolute path, so a broken file stops
    the run instead of protecting less than it says."""
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"cannot read the protect file {path}: {e}")
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not line:
            continue
        p = os.path.expanduser(line)
        if not os.path.isabs(p):
            raise ValueError(f"{path} line {n}: {line!r} is not an absolute path (start it with / or ~)")
        out.append((os.path.normpath(p), f"{short(path)}, line {n}"))
    return out


def protected_paths(repo, extra, protect_file):
    """Every protected path with its source: the built-in list, the repository's own main
    checkout, the protect file and --protect."""
    out = [(p, "built in") for p in PROTECTED]
    if not any(real(repo) == real(p) for p, _ in out):
        out.append((repo, "the repository's main checkout"))
    out += read_protect_file(protect_file)
    out += [(os.path.normpath(os.path.abspath(os.path.expanduser(p))), "--protect") for p in extra]
    return out


def protected_by(path, protected):
    """The (path, source) that protects path: path lies under it, or it lies under path (a
    build folder holding a protected path is never removed); None if none does."""
    for p, src in protected:
        if inside(path, p) or inside(p, path):
            return p, src
    return None


def free_bytes(path="/"):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def git(args, cwd):
    r = subprocess.run(["git", "--no-optional-locks", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return r.returncode, r.stdout


def worktrees(repo):
    code, out = git(["worktree", "list", "--porcelain"], repo)
    if code:
        raise SystemExit(f"disk_clean: {repo} is not a git repository")
    wts, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                wts.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "")
        elif line == "detached":
            cur["branch"] = None
        elif line == "bare":
            cur["bare"] = True
    return [w for w in wts if not w.get("bare") and os.path.isdir(w["path"])]


def is_tag(path):
    try:
        with open(os.path.join(path, "CACHEDIR.TAG"), errors="replace") as f:
            head = f.read(400)
    except OSError:
        return False
    return head.startswith(CARGO_SIG) and "cargo" in head


def is_target(path):
    if is_tag(path):
        return True
    if not os.path.isfile(os.path.join(path, ".rustc_info.json")):
        return False
    try:
        kids = [e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return False
    return any(is_tag(k.path) or os.path.exists(os.path.join(k.path, ".cargo-lock")) for k in kids)


CARGO_ENTRIES = {"CACHEDIR.TAG", ".rustc_info.json", ".future-incompat-report.json", "debug", "release", "doc", "package", "tmp",
                 "cargo-timings", "build", "flycheck0", "rust-analyzer", "living-check", ".package-cache"}


def cargo_made(path, name):
    p = os.path.join(path, name)
    if name in CARGO_ENTRIES or name.startswith(".slop-reclaim-"):
        return True
    return os.path.isdir(p) and not os.path.islink(p) and (is_tag(p) or any(os.path.exists(os.path.join(p, f)) for f in (".cargo-lock", ".fingerprint", ".cargo-build-lock")))


def foreign_entries(path):
    """Entries of a target root that Cargo (or living-check's logs) did not make: a folder
    with any is kept, as someone may keep evidence there."""
    bad = []
    try:
        entries = list(os.scandir(path))
    except OSError as e:
        return [f"unreadable: {e}"]
    for e in entries:
        if e.name in CARGO_ENTRIES or e.name.startswith(".slop-reclaim-"):
            continue
        if e.is_dir(follow_symlinks=False) and (is_tag(e.path) or any(os.path.exists(os.path.join(e.path, f)) for f in (".cargo-lock", ".fingerprint", ".cargo-build-lock"))):
            continue  # a <triple> or custom-profile build directory
        bad.append(e.name)
    return bad


def find_targets(root, depth=6):
    """Outermost Cargo target folders under root, without following symlinks."""
    found, stack = [], [(root, 0)]
    while stack:
        d, n = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.name in SKIP_DIRS or not e.is_dir(follow_symlinks=False):
                continue
            if os.path.exists(os.path.join(e.path, ".git")):
                continue  # a nested repository or worktree: not this worktree's to clean
            if re.search(r"\.slop-reclaim-\d+$", e.name) or is_target(e.path):
                found.append(e.path)
            elif n + 1 < depth:
                stack.append((e.path, n + 1))
    return found


def scan(path):
    """(bytes on disk, newest mtime, files, crosses a mount) of a folder tree, without following
    symlinks; a file hard-linked several times counts once."""
    size, newest, files, stack, seen, mounts = 0, 0.0, 0, [path], set(), False
    try:
        dev = os.lstat(path).st_dev
    except OSError:
        return 0, 0.0, 0, False
    while stack:
        d = stack.pop()
        try:
            st = os.lstat(d)
            newest = max(newest, st.st_mtime)
            if st.st_dev != dev:
                mounts = True
                continue
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            if e.is_dir(follow_symlinks=False):
                stack.append(e.path)
            else:
                files += 1
                if st.st_nlink > 1:
                    if (st.st_dev, st.st_ino) in seen:
                        continue
                    seen.add((st.st_dev, st.st_ino))
                size += getattr(st, "st_blocks", 0) * 512 or st.st_size
    return size, newest, files, mounts


FIEMAP = 0xC020660B  # FS_IOC_FIEMAP
EXTENT_SHARED, EXTENT_LAST = 0x2000, 0x1


def exclusive_bytes(path):
    """Bytes a file holds alone on disk: its extents minus those shared with another file
    (XFS and btrfs reflink copies, `cp --reflink`). Removing the file frees at least this
    much. None where FIEMAP is unsupported (macOS, some filesystems)."""
    import struct
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    total, start = 0, 0
    try:
        while True:
            n = 256
            buf = bytearray(struct.pack("=QQIIII", start, 0xFFFFFFFFFFFFFFFF - start, 0, 0, n, 0) + b"\0" * (56 * n))
            try:
                fcntl.ioctl(fd, FIEMAP, buf)
            except OSError:
                return None
            mapped = struct.unpack_from("=I", buf, 20)[0]
            if mapped == 0:
                return total
            last = False
            for i in range(mapped):
                logical, _phys, length, _r1, _r2, flags = struct.unpack_from("=QQQQQI", buf, 32 + 56 * i)
                if not flags & EXTENT_SHARED:
                    total += length
                start = logical + length
                last = last or bool(flags & EXTENT_LAST)
            if last:
                return total
    finally:
        os.close(fd)


_APFS = None


def apfs_private_bytes(path):
    """Bytes of a file no clone shares (macOS: getattrlist ATTR_CMNEXT_PRIVATESIZE, which
    APFS keeps for every file, no root needed): what deleting it frees. None where the
    attribute is not returned (another filesystem, an older macOS)."""
    global _APFS
    import ctypes
    import ctypes.util
    if _APFS is None:
        try:
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

            class AttrList(ctypes.Structure):
                _fields_ = [("bitmapcount", ctypes.c_ushort), ("reserved", ctypes.c_uint16), ("commonattr", ctypes.c_uint32),
                            ("volattr", ctypes.c_uint32), ("dirattr", ctypes.c_uint32), ("fileattr", ctypes.c_uint32), ("forkattr", ctypes.c_uint32)]
            fn = libc.getattrlist
            fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(AttrList), ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint]
            fn.restype = ctypes.c_int
            # ATTR_BIT_MAP_COUNT, ATTR_CMN_RETURNED_ATTRS; with FSOPT_ATTR_CMN_EXTENDED the fork
            # group means the extended common attributes, ATTR_CMNEXT_PRIVATESIZE among them
            _APFS = (fn, AttrList(5, 0, 0x80000000, 0, 0, 0, 0x00000008))
        except (OSError, AttributeError):
            _APFS = False
    if not _APFS:
        return None
    fn, al = _APFS
    buf = ctypes.create_string_buffer(64)
    # FSOPT_NOFOLLOW | FSOPT_ATTR_CMN_EXTENDED
    if fn(os.fsencode(path), ctypes.byref(al), buf, len(buf), 0x1 | 0x20) != 0:
        return None
    import struct
    # u32 length; attribute_set_t returned (5 x u32); then the off_t private size
    length, = struct.unpack_from("=I", buf.raw, 0)
    returned_ext, = struct.unpack_from("=I", buf.raw, 4 + 16)
    if length < 32 or not returned_ext & 0x8:
        return None
    priv, = struct.unpack_from("=q", buf.raw, 24)
    return priv if priv >= 0 else None


def file_exclusive(path):
    return apfs_private_bytes(path) if platform.system() == "Darwin" else exclusive_bytes(path)


SIZE_METHOD = {"Linux": "FIEMAP", "Darwin": "getattrlist ATTR_CMNEXT_PRIVATESIZE"}


def real_size(path):
    """(exclusive bytes, shared bytes) of a folder tree, or None when the filesystem cannot
    say which blocks a clone or reflink copy shares (SIZE_METHOD names the way it asks)."""
    excl = shared = 0
    for d, dirs, files in os.walk(path):
        for f in files:
            full = os.path.join(d, f)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            e = file_exclusive(full)
            if e is None:
                return None
            excl += e
            shared += max(st.st_blocks * 512 - e, 0)
    return excl, shared


def users_linux():
    """Map of real path -> list of 'pid (comm) how' for every path a process holds."""
    held, me = [], str(os.getpid())
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == me:
            continue
        base = f"/proc/{pid}"
        try:
            comm = open(f"{base}/comm", errors="replace").read().strip()
        except OSError:
            continue
        try:
            held.extend(_proc_paths(base, pid, comm))
        except Exception as e:  # one odd process must not stop the scan; count it as unknown
            held.append(("*", f"{pid} ({comm}) could not be inspected: {e}"))
    return held


def _proc_paths(base, pid, comm):
    held = []
    for how in ("cwd", "exe", "root"):
        try:
            p = os.readlink(f"{base}/{how}")
            if how != "root" or p != "/":
                held.append((p.replace(" (deleted)", ""), f"{pid} ({comm}) {how}"))
        except OSError:
            pass
    try:
        for fd in os.listdir(f"{base}/fd"):
            try:
                p = os.readlink(f"{base}/fd/{fd}")
            except OSError:
                continue
            if p.startswith("/"):
                held.append((p.replace(" (deleted)", ""), f"{pid} ({comm}) open file"))
    except OSError:
        pass
    try:
        for line in open(f"{base}/maps", errors="surrogateescape"):
            parts = line.split(None, 5)
            if len(parts) == 6 and parts[5].startswith("/"):
                held.append((parts[5].strip().replace(" (deleted)", ""), f"{pid} ({comm}) mapped"))
    except OSError:
        pass
    return held


def users_lsof():
    held = []
    try:
        r = subprocess.run(["lsof", "-n", "-w", "-F", "pcn"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return [("*", "lsof did not answer: treating every folder as in use")]
    if r.returncode not in (0, 1) or not r.stdout:
        return [("*", f"lsof failed (exit {r.returncode}): treating every folder as in use")]
    pid = comm = None
    for line in r.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("c"):
            comm = line[1:]
        elif line.startswith("n/") and pid != str(os.getpid()):
            held.append((line[1:], f"{pid} ({comm}) open"))
    return held


def podman_without_machine(stderr):
    """True when podman fails only because it has no machine to talk to (macOS, Windows):
    then no podman container exists that could mount anything."""
    if platform.system() == "Linux":
        return False
    try:
        r = subprocess.run(["podman", "machine", "list", "--format", "{{.Name}}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and not r.stdout.strip()


def container_mounts(quiet=False):
    srcs, answered, down = [], [], []
    for tool in ("podman", "docker"):
        if not shutil.which(tool):
            continue
        try:
            # -a: a stopped container's bind mounts still belong to it
            ps = subprocess.run([tool, "ps", "-a", "-q"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if ps.returncode != 0 and not re.search(r"cannot connect|connection refused|no such file|is the docker daemon running|not running", ps.stderr or "", re.I):
                raise OSError(f"{tool} ps exit {ps.returncode}: {(ps.stderr or '').strip()[:120]}")
            if ps.returncode != 0:
                # no daemon answering: nothing runs under it; what its stopped containers mount is unknown
                down.append((tool, ps.returncode, ps.stderr or ""))
                continue
            answered.append(tool)
            ids = ps.stdout.split()
            if ids:
                ins = subprocess.run([tool, "inspect", "--format", "{{range .Mounts}}{{.Source}}\n{{end}}", *ids], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, timeout=30)
                if ins.returncode != 0:
                    raise OSError(f"{tool} inspect exit {ins.returncode}")
                srcs += [(s.strip(), f"container mount ({tool})") for s in ins.stdout.splitlines() if s.strip().startswith("/")]
        except (subprocess.TimeoutExpired, OSError) as e:  # a hung daemon may still run containers
            srcs.append(("/", f"{tool} did not answer ({e}): treating every folder as mounted"))
    if not quiet:
        for tool, code, err in down:
            if tool == "podman" and podman_without_machine(err):
                NOTES.append(f"podman has no machine (ps exit {code}), so it has no containers")
            elif answered:
                NOTES.append(f"{tool} ps failed (exit {code}); {', '.join(answered)} answered, and no {tool} container is running")
            else:
                WARNINGS.append(f"{tool} ps failed (exit {code}); no container of it is running, its stopped containers' mounts are unknown")
    return srcs


def mount_points():
    """Mount points (Linux /proc/self/mountinfo; `mount` elsewhere): a folder with one at or
    under it is never removed, even on the same filesystem (a bind mount)."""
    pts = []
    try:
        for line in open("/proc/self/mountinfo", errors="surrogateescape"):
            f = line.split()
            if len(f) > 4:
                pts.append(f[4].replace("\\040", " "))
    except OSError:
        # macOS keeps `mount` in /sbin, which a minimal PATH (the self-test's, a launchd job's)
        # may leave out: try PATH, then the usual places.
        exe = shutil.which("mount") or next((p for p in ("/sbin/mount", "/usr/sbin/mount", "/bin/mount") if os.access(p, os.X_OK)), None)
        if exe is None:
            print("disk_clean: warning: no `mount` found, so bind mounts under build folders cannot be seen", file=sys.stderr)
            return pts
        try:
            r = subprocess.run([exe], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError as e:
            print(f"disk_clean: warning: `{exe}` failed ({e}), so bind mounts under build folders cannot be seen", file=sys.stderr)
            return pts
        pts = [m.group(1) for m in re.finditer(r" on (/.*?) \(", r.stdout)]
    return pts


def in_use(path, held, mounts):
    rp = real(path)
    for p, who in held:
        if p == "*" or p == rp or p.startswith(rp + "/"):
            return who
    for src, who in mounts:
        if inside(src, rp) or inside(rp, src):
            return f"{who} {src}"
    return None


def cargo_locks(path):
    locks = []
    for d, dirs, files in os.walk(path):
        if d.count(os.sep) - path.count(os.sep) >= 3:
            dirs[:] = []
        for f in files:
            if f in (".cargo-lock", ".cargo-build-lock", ".cargo-artifact-lock", ".package-cache"):
                locks.append(os.path.join(d, f))
        dirs[:] = [x for x in dirs if x not in ("deps", "build", ".fingerprint", "incremental", "examples")]
    return locks


def hold_locks(path):
    """Take every Cargo lock in the folder without waiting; None if any is held."""
    fds = []
    for p in cargo_locks(path):
        try:
            fd = os.open(p, os.O_RDWR)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            for x in fds:
                os.close(x)
            return None
        fds.append(fd)
    return fds


def git_idle(wt):
    """Newest mtime of the worktree's index and HEAD log (commits, checkouts, adds)."""
    code, gd = git(["rev-parse", "--absolute-git-dir"], wt)
    gd = gd.strip()
    t = 0.0
    for f in ("index", "logs/HEAD", "HEAD"):
        try:
            t = max(t, os.stat(os.path.join(gd, f)).st_mtime)
        except OSError:
            pass
    return t


def fmt_gb(b):
    return f"{b / GB:5.1f} GB"


def short(p):
    return p.replace(HOME, "~")


def current_users():
    return [(real(p) if p != "*" and os.path.exists(p) else p, w) for p, w in (users_linux() if os.path.isdir("/proc/self/fd") else users_lsof())]


def remove_row(r, now, mpoints):
    """Remove one folder, or only Cargo's entries in it, if nothing uses it now; returns the
    bytes freed and records the result in r."""
    mounts_now = container_mounts(quiet=True)
    user = in_use(r["path"], current_users(), mounts_now)
    if user:
        r.update(decision="keep", result="kept", why=f"in use by now: {user}")
        return 0
    if re.search(r"\.slop-reclaim-\d+$", os.path.basename(r["path"])):  # left by an earlier run
        before = free_bytes(r["worktree"])
        shutil.rmtree(r["path"], ignore_errors=True)
        r["freed"] = free_bytes(r["worktree"]) - before
        r["result"] = "removed" if not os.path.exists(r["path"]) else "partly removed"
        return max(r["freed"], 0)
    fds = hold_locks(r["path"])
    if fds is None:
        r.update(decision="keep", result="kept", why="a Cargo lock in it is held (a build started)")
        return 0
    moved = []
    try:
        # decide again under the locks: only entries Cargo made go, whatever appeared since the scan
        entries = os.listdir(r["path"])
        partial = any(not cargo_made(r["path"], e) for e in entries)
        if partial:
            aside = os.path.join(r["path"], f".slop-reclaim-{int(now)}")
            os.mkdir(aside)
            for e in entries:
                if e != os.path.basename(aside) and cargo_made(r["path"], e):
                    os.rename(os.path.join(r["path"], e), os.path.join(aside, e))
                    moved.append(e)
        else:
            aside = f"{r['path']}.slop-reclaim-{int(now)}"
            os.rename(r["path"], aside)
        again = in_use(aside, current_users(), container_mounts(quiet=True)) or (
            "a filesystem is mounted inside" if any(inside(m, aside) for m in mount_points()) else None)
        if again:
            if partial:
                for e in moved:
                    os.rename(os.path.join(aside, e), os.path.join(r["path"], e))
                os.rmdir(aside)
            else:
                os.rename(aside, r["path"])
            r.update(decision="keep", result="kept", why=f"in use after all: {again}")
            return 0
    finally:
        for fd in fds:
            os.close(fd)
    before = free_bytes(r["worktree"])
    shutil.rmtree(aside, ignore_errors=True)
    freed = free_bytes(r["worktree"]) - before
    r["result"] = ("removed" if not partial else f"removed Cargo's entries, kept {', '.join(sorted(set(entries) - set(moved)))[:80]}") \
        if not os.path.exists(aside) else "partly removed"
    r["freed"] = freed
    return max(freed, 0)


def main(argv):
    opts = {"apply": False, "repo": None, "floor": 40.0, "target": None, "idle": 24.0, "merged_idle": 2.0, "pressure_idle": 2.0, "json": False,
            "protect": [], "protect_file": PROTECT_FILE, "list": False}
    args = list(argv)
    try:
        while args:
            a = args.pop(0)
            if a == "--apply":
                opts["apply"] = True
            elif a == "--json":
                opts["json"] = True
            elif a == "--list-protected":
                opts["list"] = True
            elif a == "--protect":
                opts["protect"].append(args.pop(0))
            elif a == "--protect-file":
                opts["protect_file"] = os.path.expanduser(args.pop(0))
            elif a in ("--repo", "--floor-gb", "--target-gb", "--idle", "--merged-idle", "--pressure-idle"):
                v = args.pop(0)
                key = {"--repo": "repo", "--floor-gb": "floor", "--target-gb": "target", "--idle": "idle", "--merged-idle": "merged_idle", "--pressure-idle": "pressure_idle"}[a]
                opts[key] = v if key == "repo" else float(v)
            elif a in ("-h", "--help"):
                print(__doc__)
                return 0
            else:
                raise ValueError(a)
    except (ValueError, IndexError) as e:
        print(f"disk_clean: bad argument {e}\n{__doc__}", file=sys.stderr)
        return 2
    if opts["target"] is None:
        opts["target"] = opts["floor"] + 30
    repo = opts["repo"] or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code, common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)
    if code:
        print(f"disk_clean: {repo} is not in a git repository", file=sys.stderr)
        return 2
    repo = os.path.dirname(common.strip())
    try:  # the built-in list, the main checkout of the repository wherever it is, the machine's file
        protected = protected_paths(repo, opts["protect"], opts["protect_file"])
    except ValueError as e:
        print(f"disk_clean: {e}; nothing removed", file=sys.stderr)
        return 2
    plist = [f"  {short(p)}  ({src}{'' if os.path.lexists(p) else '; does not exist now'})" for p, src in protected] + \
            [f"  {short(n)}  (built in: container storage)" for n in NEVER]
    if opts["list"]:
        print("protected (never removed, nor anything under them, nor a build folder holding them):")
        print("\n".join(plist))
        return 0
    os.makedirs(os.path.join(STATE, "reports"), exist_ok=True)
    lockf = open(os.path.join(STATE, "clean.lock"), "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("disk_clean: another run is in progress")
        return 0
    now = time.time()
    free0 = free_bytes(repo)
    code, main_sha = git(["rev-parse", "-q", "--verify", "refs/remotes/origin/main"], repo)
    main_sha = main_sha.strip() if code == 0 else None
    # main's own line (first parents): a worktree sitting on it has no finished branch of its
    # own (a fresh worktree, or a coordinator whose merges are main), so the merged rule
    # does not apply to it
    first_parent = set(git(["rev-list", "--first-parent", main_sha], repo)[1].split()) if main_sha else set()
    # and every commit origin/main has pointed to here, in case main's line was rewired
    first_parent |= set(git(["reflog", "show", "--format=%H", "refs/remotes/origin/main"], repo)[1].split())
    mpoints = mount_points()
    held = users_linux() if os.path.isdir("/proc/self/fd") else users_lsof()
    held = [(real(p) if os.path.exists(p) else p, who) for p, who in held]
    mounts = container_mounts()
    rows = []
    for wt in worktrees(repo):
        path = wt["path"]
        guard = next(((p, src) for p, src in protected if inside(path, p)), None)
        if guard:
            for t in find_targets(path):
                size, newest, _, _ = scan(t)
                rows.append({"path": t, "worktree": path, "branch": wt.get("branch"), "size": size, "idle_h": max(now - newest, 0) / 3600,
                             "decision": "never", "why": f"protected: {short(guard[0])} ({guard[1]})"})
            continue
        merged = False
        clean = False
        if main_sha:
            head = git(["rev-parse", "HEAD"], path)[1].strip()
            merged = head not in first_parent and git(["merge-base", "--is-ancestor", "HEAD", main_sha], path)[0] == 0
            # uncommitted or untracked work; .local/ is every worker's scratch space, not work
            st_code, st = git(["status", "--porcelain", "--untracked-files=normal", "--", ".", ":(exclude).local"], path)
            clean = st_code == 0 and not st.strip()
        gtime = git_idle(path)
        for t in find_targets(path):
            if os.path.islink(t) or not inside(t, path) or real(t) == real(path) or any(inside(t, n) or inside(n, t) for n in NEVER):
                continue
            guard = protected_by(t, protected)
            if guard:
                size, newest, _, _ = scan(t)
                rows.append({"path": t, "worktree": path, "branch": wt.get("branch"), "size": size, "idle_h": max(now - newest, 0) / 3600,
                             "decision": "never", "why": f"protected: {short(guard[0])} ({guard[1]})"})
                continue
            try:
                size, newest, files, crosses = scan(t)
            except OSError as e:
                WARNINGS.append(f"skipped {short(t)}: {e}")
                continue
            crosses = crosses or any(inside(m, t) for m in mpoints)
            # a file written during the scan is newer than `now`: idle 0, not negative
            idle_h = max(now - newest, 0) / 3600
            wt_idle_h = max(now - max(newest, gtime), 0) / 3600
            row = {"path": t, "worktree": path, "branch": wt.get("branch"), "size": size, "files": files, "idle_h": idle_h,
                   "wt_idle_h": wt_idle_h, "merged": merged, "clean": clean}
            user = in_use(t, held, mounts)
            foreign = [] if ".slop-reclaim-" in os.path.basename(t) else foreign_entries(t)
            if user:
                row.update(decision="keep", why=f"in use: {user}")
            elif crosses:
                row.update(decision="keep", why="another filesystem is mounted inside it")
            elif ".slop-reclaim-" in os.path.basename(t):
                row.update(decision="remove", why="left over from an earlier removal")
            elif merged and clean and idle_h >= opts["merged_idle"]:
                row.update(decision="remove", why=f"merged ({wt.get('branch') or 'detached'} is in origin/main), idle {idle_h:.1f} h")
            elif wt_idle_h >= opts["idle"]:
                row.update(decision="remove", why=f"idle {wt_idle_h:.1f} h")
            elif idle_h >= opts["pressure_idle"]:
                row.update(decision="pressure", why=f"idle {idle_h:.1f} h; removed only under pressure")
            else:
                row.update(decision="keep", why=f"active (idle {idle_h:.1f} h)")
            if foreign and row["decision"] in ("remove", "pressure"):
                # keep the folder and whatever someone put there; only Cargo's own entries go
                row["keep_entries"] = sorted(foreign)
                row["why"] += "; keeping its other files (" + ", ".join(sorted(foreign)[:4]) + ("…" if len(foreign) > 4 else "") + ")"
                try:
                    row["size"] -= sum(scan(os.path.join(t, f))[0] if os.path.isdir(os.path.join(t, f)) else os.lstat(os.path.join(t, f)).st_size for f in foreign)
                except OSError:
                    pass
            rows.append(row)
    # what removing a folder really frees: reflink copies share extents, which du (and the
    # block count above) counts in every copy
    sized = {"exclusive": 0, "blocks": 0}
    for r in rows:
        if r["decision"] in ("remove", "pressure"):
            rs = real_size(r["path"])
            if rs is not None:
                r["shared"] = rs[1]
                r["size"] = rs[0] if not r.get("keep_entries") else min(r["size"], rs[0])
                sized["exclusive"] += 1
            else:
                r["sized_by"] = "blocks"
                sized["blocks"] += 1
    # pressure: oldest idle first. The dry run projects free space from the sizes above; an
    # applied run measures free space before each pressure removal and stops at the target,
    # so a size that over-counts (clone blocks counted in full) never removes too little,
    # and one that under-counts never removes too much
    projected = free0 + sum(r["size"] for r in rows if r["decision"] == "remove")
    pressure = sorted((r for r in rows if r["decision"] == "pressure"), key=lambda r: -r["idle_h"])
    for r in pressure:
        if opts["apply"]:
            continue  # decided below, one at a time against measured free space
        if projected >= opts["target"] * GB:
            r.update(decision="keep", why=r["why"].replace("removed only under pressure", f"free space at or over {opts['target']:.0f} GB"))
            continue
        r.update(decision="remove", why=r["why"].replace("; removed only under pressure", f"; under pressure (free under {opts['target']:.0f} GB)"))
        projected += r["size"]
    removed_bytes = 0

    def remove(r):
        nonlocal removed_bytes
        try:
            removed_bytes += remove_row(r, now, mpoints)
        except Exception as e:  # never stop half way without a report
            r.update(decision="keep", result="error", why=f"{r['why']}; stopped: {type(e).__name__}: {e}")

    for r in rows:
        if r["decision"] != "remove":
            continue
        if not opts["apply"]:
            r["result"] = "would remove"
            continue
        remove(r)
    for r in pressure if opts["apply"] else []:
        free_now = free_bytes(repo)
        if free_now >= opts["target"] * GB:
            r.update(decision="keep", why=r["why"].replace("removed only under pressure", f"free space measured at {free_now / GB:.1f} GB, at or over {opts['target']:.0f} GB"))
            continue
        r.update(decision="remove", why=r["why"].replace("; removed only under pressure", f"; under pressure (free measured at {free_now / GB:.1f} GB, under {opts['target']:.0f} GB)"))
        remove(r)
    free1 = free_bytes(repo)
    host = platform.node()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    lines = [f"slop disk clean on {host} at {stamp} ({'applied' if opts['apply'] else 'dry run, nothing removed'})",
             f"policy: floor {opts['floor']:.0f} GB, target {opts['target']:.0f} GB; merged+clean idle >= {opts['merged_idle']:g} h; "
             f"idle >= {opts['idle']:g} h; under pressure idle >= {opts['pressure_idle']:g} h; repo {short(repo)}",
             f"free before: {free0 / GB:.1f} GB; 'freed' is the measured change in free space",
             "sizes: blocks on disk; for the folders it would remove, " + (
                 f"only the blocks no clone or reflink copy shares (asked with {SIZE_METHOD.get(platform.system(), 'FIEMAP')}" + (
                     f"; {sized['blocks']} folders on a filesystem that cannot say, counted in full)" if sized["blocks"] else ")")
                 if sized["exclusive"] or not sized["blocks"] else
                 f"all blocks: this filesystem cannot say which blocks clones share ({SIZE_METHOD.get(platform.system(), 'FIEMAP')} unavailable), so clones count in full"),
             "pressure: " + ("removals one at a time, oldest first, each only while measured free space is under the target"
                             if opts["apply"] else "projected from the sizes; an applied run measures free space before each removal instead"),
             "protected (never removed, nor anything under them, nor a build folder holding them):"] + plist + \
        [f"note: {n}" for n in NOTES] + [f"warning: {w}" for w in WARNINGS] + [""]
    order = {"remove": 0, "keep": 1, "pressure": 1, "never": 2}
    for r in sorted(rows, key=lambda r: (order[r["decision"]], -r["size"])):
        tag = {"remove": "REMOVE", "keep": "keep", "pressure": "keep", "never": "never"}[r["decision"]]
        res = f" [{r['result']}{', freed ' + fmt_gb(r['freed']).strip() if r.get('freed') is not None else ''}]" if r.get("result") else ""
        note = f" (+{r['shared'] / GB:.1f} GB shared with reflink copies, freed only with them)" if r.get("shared", 0) >= GB / 10 else ""
        note += " (all blocks counted: clones unknown)" if r.get("sized_by") == "blocks" else ""
        lines.append(f"  {tag:6} {fmt_gb(r['size'])}  {short(r['path'])}  ({r.get('branch') or 'detached'}): {r['why']}{note}{res}")
    if not rows:
        lines.append("  no build folders found")
    would = sum(r["size"] for r in rows if r["decision"] == "remove")
    lines.append("")
    if opts["apply"]:
        lines.append(f"removed {sum(1 for r in rows if r.get('result') in ('removed', 'partly removed'))} folders, freed {removed_bytes / GB:.1f} GB; free after: {free1 / GB:.1f} GB")
    else:
        lines.append(f"would remove {sum(1 for r in rows if r['decision'] == 'remove')} folders, {would / GB:.1f} GB; free would be about {(free0 + would) / GB:.1f} GB")
    low = (free1 if opts["apply"] else free0 + would) < opts["floor"] * GB
    if low:
        lines.append(f"BELOW THE FLOOR ({opts['floor']:.0f} GB): the rest is in use, active or protected; see the list above")
    report = "\n".join(lines)
    print(report)
    name = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + ("-apply" if opts["apply"] else "-dry") + ".txt"
    with open(os.path.join(STATE, "reports", name), "w") as f:
        f.write(report + "\n")
    with open(os.path.join(STATE, "log.jsonl"), "a") as f:
        f.write(json.dumps({"at": stamp, "host": host, "apply": opts["apply"], "free0": free0, "free1": free1, "removed": removed_bytes,
                            "protected": [[p, src] for p, src in protected], "sized": sized, "notes": NOTES, "warnings": WARNINGS,
                            "rows": [{k: r.get(k) for k in ("path", "size", "decision", "why", "result", "freed")} for r in rows]}) + "\n")
    reports = sorted(os.listdir(os.path.join(STATE, "reports")))
    for old in reports[:-300]:
        os.remove(os.path.join(STATE, "reports", old))
    if opts["json"]:
        print(json.dumps(rows, default=str))
    return 3 if low else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
