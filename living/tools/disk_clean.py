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
or with --protect PATH; these add to the built-in list and never shorten it. A line with
`*`, `?` or `[` is a glob, expanded on every run (one that matches nothing protects nothing).

Target folders outside the worktrees (private CARGO_TARGET_DIRs such as the Spark's
~/slop-<name>-target) are candidates only when ~/.config/slop-disk/targets.txt names them
(same format: absolute paths or globs). No worktree goes with them, so only the in-use
checks and the idle and pressure rules apply, never the merged rule; protection applies.

A removal renames the folder aside while holding its Cargo locks, checks again that nothing
uses it, then deletes it. Prints a report and keeps it in ~/.local/state/slop-disk/.

Containers (docs/TOOLING.md, "Disk": SpacetimeDB servers, the quiet restart, Docker's VM disk):
  - every machine: each running SpacetimeDB server's deleted files still held open, its live
    databases (db.lock or module log open), the directories of deleted databases left on disk
    (SpacetimeDB 2.14.1 never removes them) and its connected clients, by container and pid.
    Linux reads /proc (rootless podman's through `podman unshare`); macOS runs this file's probe
    inside Docker Desktop's VM. Report only: the timer never restarts, stops or signals anything.
  - --apply --restart-stdb NAME (never automatic): SIGINT to that container, removal of its
    deleted databases' directories while it is stopped, start, then every known database must
    answer SQL with the same paused state. Refused, before anything is stopped, for the
    reference worlds' server, a held gate or merge lock, a connected client, a host process
    naming its port, an unlisted or unanswering database, an evidence server without
    --keep-dirs, or anything it cannot read.
  - macOS Docker Desktop only: Docker.raw's allocated size and the VM's /var/lib; with --apply,
    one `fstrim /var/lib` in the VM when free space is under floor + --trim-margin-gb (10) and
    Docker Desktop runs, or after a restart; none for an hour after a trim that freed under
    1 GB (state in vm-trim.json beside the reports).

Usage: disk_clean.py [--apply] [--repo PATH] [--floor-gb 40] [--target-gb N] [--idle 24]
                     [--merged-idle 2] [--pressure-idle 2] [--protect PATH]...
                     [--protect-file PATH] [--targets-file PATH] [--list-protected] [--json]
                     [--docker-raw PATH] [--trim-margin-gb 10] [--containers-only]
                     [--restart-stdb NAME [--stdb-db DB]... [--keep-dirs]]
  Without --apply it is a dry run: the same report, nothing removed, no trim.
  --docker-raw PATH  Docker Desktop's VM disk, when it is not found by itself
  --containers-only  print only the container section (read-only: no trim, no restart), then stop
  --restart-stdb N   with --apply, the quiet restart of container N (without it, its checks and plan)
  --stdb-db DB       a database N hosts that its CLI identity does not list (repeatable)
  --keep-dirs        restart without removing the deleted databases' directories
  --protect PATH     protect PATH and everything under it (repeatable), besides the file
  --protect-file P   read the machine's protected paths from P (~/.config/slop-disk/protect.txt)
  --targets-file P   read the outside target folders from P (~/.config/slop-disk/targets.txt)
  --list-protected   print every protected path and where it comes from, then stop
Exit status: 0, 2 for a bad argument or an unreadable or invalid protect or targets file (nothing is
removed), 3 when free space is still under the floor afterwards, or 4 when --restart-stdb was
refused or did not complete.
"""
import fcntl
import glob
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
# Cargo target folders outside the worktrees that may be cleaned (globs; none by default).
TARGETS_FILE = os.path.join(HOME, ".config", "slop-disk", "targets.txt")
CARGO_SIG = "Signature: 8a477f597d28d172789f06886806bc55"
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state"), "slop-disk")


# System tools live outside a minimal PATH on some systems (macOS: /usr/sbin/lsof, /sbin/mount),
# and the self-test and launchd jobs run with one. Look on PATH first, then the system's own
# directories. Container tools (podman, docker) are only looked for on PATH, so a test's fake
# PATH stays hermetic; the timer's PATH includes Homebrew's (disk_clean_install.sh).
SYSTEM_DIRS = ("/usr/sbin", "/usr/bin", "/sbin", "/bin")


def system_tool(name):
    return shutil.which(name) or next((os.path.join(d, name) for d in SYSTEM_DIRS if os.access(os.path.join(d, name), os.X_OK)), None) or name
SKIP_DIRS = {".git", "node_modules", "__pycache__"}
GB = 1024 ** 3
WARNINGS = []
NOTES = []  # things worth knowing that limit nothing (a container tool with nothing to run)


def real(p):
    return os.path.realpath(p)


def inside(path, base):
    path, base = real(path), real(base)
    return path == base or path.startswith(base.rstrip("/") + "/")


def read_path_file(path, kind="protect"):
    """[(path, source)] from a protect or targets file: one path per line, `#` starts a
    comment (a whole line, or after a space), `~` is expanded, and a line with `*`, `?` or `[`
    is a glob expanded now. A missing file adds nothing. Raises ValueError for an unreadable
    file or a line that is not an absolute path, so a broken file stops the run instead of
    protecting less than it says."""
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"cannot read the {kind} file {path}: {e}")
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not line:
            continue
        p = os.path.expanduser(line)
        if not os.path.isabs(p):
            raise ValueError(f"{path} line {n}: {line!r} is not an absolute path (start it with / or ~)")
        if glob.has_magic(p):
            out += [(os.path.normpath(m), f"{short(path)}, line {n}: {line}") for m in sorted(glob.glob(p))]
        else:
            out.append((os.path.normpath(p), f"{short(path)}, line {n}"))
    return out


def read_protect_file(path):
    return read_path_file(path, "protect")


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
    r = subprocess.run([system_tool("git"), "--no-optional-locks", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
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
        r = subprocess.run([system_tool("lsof"), "-n", "-w", "-F", "pcn"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=120)
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
        exe = system_tool("mount")
        if not os.path.isabs(exe):
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
    real_home = os.path.realpath(HOME)
    if real_home != HOME and p.startswith(real_home):
        p = HOME + p[len(real_home):]
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


# ---- Containers: SpacetimeDB servers (every machine) and Docker Desktop's VM disk (macOS) ----
# Report only by default. Two actions, each only with --apply: the VM trim (macOS, near the
# floor or after a restart) and the quiet restart of one SpacetimeDB container named with
# --restart-stdb, which refuses whenever the server may be in use. No container is otherwise
# restarted, stopped, signalled, pruned or exec'd into: that would cut live worlds.

PROC = "/proc"  # the self-test points this at a fake tree
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state")
DOCKER_RAW = os.path.join(HOME, "Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw")
DOCKER_SETTINGS = [os.path.join(HOME, "Library/Group Containers/group.com.docker", f) for f in ("settings-store.json", "settings.json")]
# A privileged throwaway container in the VM's pid namespace: it reads the VM's /proc, and
# nsenter into pid 1's namespaces reaches the VM's own filesystem.
VM_RUN = ["run", "--rm", "--privileged", "--pid=host"]
ALPINE = "alpine"
PROBE_IMAGE = "python:3.12-alpine"  # runs this file's probe inside Docker Desktop's VM
TRIM = VM_RUN + [ALPINE, "nsenter", "-t", "1", "-m", "-u", "-i", "-n", "fstrim", "/var/lib"]
TRIM_MARGIN_GB = 10.0      # trim when free space is under floor + this
TRIM_BACKOFF_S = 3600      # a trim within this long that freed under TRIM_BACKOFF_MIN blocks the next
TRIM_BACKOFF_MIN = GB
TRIM_SETTLE_S = 5          # wait after fstrim before measuring (the VM returns blocks to the host file)
TRIM_STATE = os.path.join(STATE, "vm-trim.json")
DEFAULT_DATA_DIR = "/home/spacetime/.local/share/spacetime/data"
RECENT_S = 15 * 60         # a replica directory written this recently counts as live (a world starting)
# Never restarted: the reference worlds' server (both compose spellings), and the machine's list.
NEVER_RESTART = ("sao-living_spacetimedb_1", "sao-living-spacetimedb-1")
NEVER_RESTART_FILE = os.path.join(HOME, ".config", "slop-disk", "never-restart.txt")
# Restarted only with --keep-dirs: deleted databases' directories there hold run evidence
# (the trial server's paid and no-model commitlogs; docs/TRIAL_DISK.md).
KEEP_DIRS = ("slop-trials-stdb",)
KEEP_DIRS_FILE = os.path.join(HOME, ".config", "slop-disk", "stdb-keep-dirs.txt")
REFERENCE_WORLDS = re.compile(r"^(aske-coast|stage)")
GATE_LOCK = os.path.join(STATE_HOME, "slop-build", "gate.lock")
MERGE_LOCKS = os.path.join(STATE_HOME, "slop-merge", "*.lock")
# Port forwarders and container plumbing name the published port without using the server.
FORWARDERS = ("pasta", "pasta.avx2", "rootlessport", "rootlessport-child", "slirp4netns", "conmon", "docker-proxy", "vpnkit",
              "gvproxy", "com.docker.backend", "com.docker.vpnkit", "com.docker.build", "podman")
STOP_WAIT_S = 180
SQL_WAIT_S = 600
POLL_S = 5


def human(b):
    return f"{b / GB:.1f} GB" if abs(b) >= GB else f"{b / 1024 ** 2:.0f} MB"


def run_tool(cmd, timeout=60, input=None):
    """(exit code, stdout, stderr); exit -1 with the reason when it could not run or timed out."""
    try:
        r = subprocess.run(cmd, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return -1, "", f"no answer in {timeout} s"
    except OSError as e:
        return -1, "", str(e)


def first_line(s):
    return (s or "").strip().splitlines()[0][:160] if (s or "").strip() else ""


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else many or word + 's'}"


def is_server(argv):
    """A SpacetimeDB server: spacetimedb-standalone, or the `spacetime start` that runs it."""
    if not argv:
        return False
    base = os.path.basename(argv[0])
    return base.startswith("spacetimedb-standalone") or (base == "spacetime" and "start" in argv[1:])


def proc_table(root):
    """{pid: (ppid, argv)} of every process under a /proc tree (stat and cmdline, readable by all)."""
    t = {}
    try:
        names = os.listdir(root)
    except OSError:
        return t
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(root, name, "stat"), errors="replace") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            with open(os.path.join(root, name, "cmdline"), "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except (OSError, ValueError, IndexError):
            continue
        t[int(name)] = (ppid, argv)
    return t


def tcp_peer(hexaddr):
    ip, port = hexaddr.rsplit(":", 1)
    if len(ip) == 8:
        ip = ".".join(str(int(ip[i:i + 2], 16)) for i in (6, 4, 2, 0))
    return f"{ip}:{int(port, 16)}"


def sockets(root, pid, inodes):
    """(listening ports, established peers) of the process's own TCP sockets: the rows of its
    network namespace's tcp and tcp6 tables whose inode is one of its fds. OSError if unreadable."""
    rows, seen = [], 0
    for name in ("tcp", "tcp6"):
        try:
            with open(os.path.join(root, str(pid), "net", name)) as f:
                rows += [r.split() for r in f.read().splitlines()[1:]]
            seen += 1
        except FileNotFoundError:
            continue
    if not seen:
        raise OSError(f"no {root}/{pid}/net/tcp")
    mine = [r for r in rows if len(r) > 9 and r[9] in inodes]
    listen = {int(r[1].rsplit(":", 1)[1], 16) for r in mine if r[3] == "0A"}
    peers = [tcp_peer(r[2]) for r in mine if r[3] == "01" and int(r[1].rsplit(":", 1)[1], 16) in listen]
    return sorted(listen), peers


def server_info(root, pid, argv):
    """One SpacetimeDB server process: its deleted files held open, its replica directories
    (live: it holds their db.lock or module log open; the others are deleted databases'), and
    its clients. Raises PermissionError when its fd folder cannot be read."""
    import stat as st_
    d = os.path.join(root, str(pid), "fd")
    deleted, paths, inodes = [], [], set()
    for fd in os.listdir(d):
        try:
            link = os.readlink(os.path.join(d, fd))
        except OSError:
            continue
        if link.startswith("socket:["):
            inodes.add(link[8:-1])
        elif not link.startswith("/") or link.startswith("/memfd:"):
            continue
        elif link.endswith(" (deleted)"):
            try:
                s = os.stat(os.path.join(d, fd))
            except OSError:
                continue
            if st_.S_ISREG(s.st_mode):
                deleted.append((link[:-len(" (deleted)")], s.st_blocks * 512, f"{s.st_dev}:{s.st_ino}"))
        else:
            paths.append(link)
    data = next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--data-dir"), None) or \
        next((a.split("=", 1)[1] for a in argv if a.startswith("--data-dir=")), None) or DEFAULT_DATA_DIR
    reps = data.rstrip("/") + "/replicas/"
    live = sorted({p[len(reps):].split("/")[0] for p in paths if p.startswith(reps) and (p.endswith("/db.lock") or "/module_logs/" in p)})
    segments = sorted({p[len(reps):].split("/")[0] for p in paths if p.startswith(reps) and "/clog/" in p})
    info = {"data_dir": data, "deleted": deleted, "live": live, "segments_open": segments, "replicas": {}}
    try:
        for e in os.scandir(os.path.join(root, str(pid), "root") + reps.rstrip("/")):
            if e.is_dir(follow_symlinks=False):
                size, newest, _, _ = scan(e.path)
                info["replicas"][e.name] = [size, newest]
    except OSError as e:
        info["replicas_error"] = f"{type(e).__name__}: {e.strerror or e}"
    try:
        info["listen"], info["clients"] = sockets(root, pid, inodes)
    except OSError as e:
        info["sockets_error"] = f"{type(e).__name__}: {e.strerror or e}"
    return info


def probe(root, pids=None, vm=False):
    """--probe: every SpacetimeDB server under a /proc tree (or the given pids) as JSON-ready data;
    run in this process, under `podman unshare`, or inside Docker Desktop's VM."""
    procs = proc_table(root)
    out = {"servers": {}}
    if pids is None:
        out["procs"] = {str(p): v for p, v in procs.items()}
        pids = [p for p, (_, a) in procs.items() if is_server(a)]
    for p in pids:
        try:
            out["servers"][str(p)] = server_info(root, p, procs.get(p, (0, []))[1])
        except PermissionError as e:
            out["servers"][str(p)] = {"denied": f"permission denied ({e.strerror or e})"}
        except OSError as e:
            out["servers"][str(p)] = {"error": f"{type(e).__name__}: {e.strerror or e}"}
    if vm:
        try:
            s = os.statvfs(os.path.join(root, "1", "root", "var", "lib"))
            out["vm_df"] = {"total": s.f_blocks * s.f_frsize, "free": s.f_bavail * s.f_frsize, "used": (s.f_blocks - s.f_bfree) * s.f_frsize}
        except OSError as e:
            out["vm_df"] = {"error": str(e)}
    return out


def running_containers(tools=("podman", "docker")):
    """([(tool, name, pid)] of running containers, [problems]). A tool that is a link to
    another (docker -> podman) is asked once. Read-only: ps and inspect."""
    out, problems, seen_tools, seen_pids = [], [], set(), set()
    for tool in tools:
        exe = shutil.which(tool)
        if not exe or real(exe) in seen_tools:
            continue
        seen_tools.add(real(exe))
        code, so, se = run_tool([tool, "ps", "-q"], 30)
        if code:
            problems.append(f"{tool} ps failed (exit {code}): {first_line(se) or 'no message'}")
            continue
        ids = so.split()
        if not ids:
            continue
        code, so, se = run_tool([tool, "inspect", "--format", "{{.Name}}\t{{.State.Pid}}", *ids], 30)
        if code:
            problems.append(f"{tool} inspect failed (exit {code}): {first_line(se) or 'no message'}")
            continue
        for line in so.splitlines():
            name, _, pid = line.strip().partition("\t")
            if pid.strip().isdigit() and int(pid) > 0 and int(pid) not in seen_pids:
                seen_pids.add(int(pid))
                out.append((tool, name.lstrip("/"), int(pid)))
    return out, problems


def collect():
    """{containers, problems, procs, servers, vm_df?} for this machine's SpacetimeDB servers.
    Linux reads the host's /proc; a rootless container's server runs as a sub-uid whose fd
    folder the user cannot list, so those are probed again under `podman unshare` (the user
    namespace's root; it joins no container). macOS probes inside Docker Desktop's VM."""
    if platform.system() == "Darwin":
        containers, problems = running_containers(("docker",))
        code, so, se = run_tool(["docker", *VM_RUN, "-i", PROBE_IMAGE, "python3", "-", "--probe", PROC, "--vm"], 300,
                                input=open(os.path.abspath(__file__)).read())
        try:
            got = json.loads(so.strip().splitlines()[-1]) if code == 0 else None
        except (ValueError, IndexError):
            got = None
        if got is None:
            return {"containers": containers, "problems": problems, "procs": {}, "servers": {},
                    "error": f"the probe inside Docker Desktop's VM failed (exit {code}): {first_line(se) or first_line(so) or 'no output'}"}
        return {"containers": containers, "problems": problems, "procs": {int(k): tuple(v) for k, v in got["procs"].items()},
                "servers": {int(k): v for k, v in got["servers"].items()}, "vm_df": got.get("vm_df")}
    containers, problems = running_containers()
    got = probe(PROC)
    procs = {int(k): tuple(v) for k, v in got["procs"].items()}
    servers = {int(k): v for k, v in got["servers"].items()}
    denied = [p for p, v in servers.items() if "denied" in v]
    if denied and shutil.which("podman"):
        code, so, se = run_tool(["podman", "unshare", sys.executable, "-I", os.path.abspath(__file__), "--probe", PROC, *map(str, denied)], 300)
        try:
            again = json.loads(so.strip().splitlines()[-1])["servers"] if code == 0 else None
        except (ValueError, IndexError, KeyError):
            again = None
        for p in denied:
            v = (again or {}).get(str(p))
            servers[p] = v if v else {"denied": f"permission denied, and podman unshare failed (exit {code}): {first_line(se) or first_line(so) or 'no output'}"}
    for p in denied:
        if "denied" in servers[p] and not shutil.which("podman"):
            servers[p]["denied"] += "; run the report as root to see it"
    return {"containers": containers, "problems": problems, "procs": procs, "servers": servers}


def group_servers(procs, containers):
    """{(tool, name, container pid) or ('host', None, pid): [server pids]}: each SpacetimeDB
    server process under the container whose init it descends from."""
    by_pid = {pid: (tool, name, pid) for tool, name, pid in containers}
    groups = {}
    for pid, (_, argv) in sorted(procs.items()):
        if not is_server(argv):
            continue
        p, owner = pid, None
        for _ in range(64):
            if p in by_pid:
                owner = by_pid[p]
                break
            if p not in procs or procs[p][0] in (0, p):
                break
            p = procs[p][0]
        groups.setdefault(owner or ("host", None, pid), []).append(pid)
    return groups


def summarize(key, pids, servers, now):
    """One server group's view: deleted files held open, live and deleted databases' replica
    directories, clients, and what could not be read."""
    tool, name, cpid = key
    s = {"server": f"spacetimedb in {name} ({tool}, pid {cpid})" if tool != "host" else f"spacetimedb on the host (pid {cpid})",
         "tool": tool, "container": name, "pid": cpid, "pids": pids, "errors": []}
    files, live, reps, clients, listen, data = {}, set(), {}, [], set(), None
    for p in pids:
        v = servers.get(p, {"error": "not probed"})
        if "denied" in v or "error" in v:
            s["errors"].append(v.get("denied") or v.get("error"))
            continue
        for path, size, k in v.get("deleted", []):
            files[k] = (path, size)
        live |= set(v.get("live", []))
        reps.update(v.get("replicas", {}))
        clients += v.get("clients", [])
        listen |= set(v.get("listen", []))
        data = data or (v["data_dir"] if v.get("replicas") or v.get("live") else None)
        for e in ("replicas_error", "sockets_error"):
            if v.get(e) and (e != "replicas_error" or v.get("live")):
                s["errors"].append(f"{e.split('_')[0]}: {v[e]}")
    dead = {r: sz for r, (sz, newest) in reps.items() if r not in live and now - newest >= RECENT_S}
    s.update(files=len(files), bytes=sum(x for _, x in files.values()), top=sorted(files.values(), key=lambda f: -f[1])[:3],
             replicas_of_files=len({m.group(1) for p, _ in files.values() for m in [re.search(r"/replicas/([^/]+)/", p)] if m}),
             live=sorted(live), dead=sorted(dead), dead_bytes=sum(dead.values()),
             recent=sorted(r for r, (sz, newest) in reps.items() if r not in live and r not in dead),
             clients=clients, listen=sorted(listen), data_dir=data)
    return s


def held_lines(summaries):
    lines, quiet = [], []
    for s in summaries:
        if s["errors"] and not (s["files"] or s["live"] or s["dead"]):
            lines.append(f"  {s['server']}: cannot see its files ({s['errors'][0]})")
            continue
        if not (s["files"] or s["dead"]):
            quiet.append(s["container"] or f"host pid {s['pid']}")
            continue
        lines.append(f"  {s['server']}: {plural(len(s['live']), 'live database')}, {plural(len(s['clients']), 'client')} connected"
                     + (f"; unreadable: {s['errors'][0]}" if s["errors"] else ""))
        if s["files"]:
            lines.append(f"    holds {plural(s['files'], 'deleted file')} ({human(s['bytes'])})"
                         + (f" of {plural(s['replicas_of_files'], 'replica')}" if s["replicas_of_files"] else "")
                         + "; a restart at a quiet moment frees them")
            lines += [f"      {human(size):>8}  {path}" for path, size in s["top"]]
        if s["dead"]:
            lines.append(f"    {plural(len(s['dead']), 'directory', 'directories')} of deleted databases still on disk ({human(s['dead_bytes'])}); "
                         "only a stop, their removal and a start frees them")
        if s["tool"] != "host":
            lines.append(f"    to free: disk_clean.py --apply --restart-stdb {s['container']} (refused while in use; docs/TOOLING.md)")
    if quiet:
        lines.append(f"  no deleted files or deleted databases' directories: {', '.join(quiet)}")
    if not summaries:
        lines.append("  no SpacetimeDB server running")
    return lines


def find_docker_raw(given=None):
    """Docker Desktop's VM disk: --docker-raw, the usual place, another VM number, or a custom
    disk image location named in Docker Desktop's settings. None when there is none."""
    if given:
        return given if os.path.isfile(given) else None
    cands = [DOCKER_RAW] + sorted(glob.glob(os.path.join(HOME, "Library/Containers/com.docker.docker/Data/vms/*/data/Docker.raw")))
    for s in DOCKER_SETTINGS:
        try:
            settings = json.load(open(s))
        except (OSError, ValueError):
            continue
        for k, v in (settings.items() if isinstance(settings, dict) else []):
            if isinstance(v, str) and v.startswith("/") and re.search(r"data.?folder|disk.?image", k, re.I):
                cands += [v] if v.endswith(".raw") else sorted(glob.glob(os.path.join(v, "Docker.raw")) + glob.glob(os.path.join(v, "vms/*/data/Docker.raw")))
    return next((c for c in cands if os.path.isfile(c)), None)


def allocated(path):
    """(bytes allocated on disk, as du -k counts them; apparent size)."""
    s = os.stat(path)
    return s.st_blocks * 512, s.st_size


def trim_state():
    try:
        v = json.load(open(TRIM_STATE))
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def docker_running():
    code, so, se = run_tool(["docker", "info", "--format", "{{.OperatingSystem}}"], 30)
    return code == 0 and "Docker Desktop" in so, first_line(se) or first_line(so) or f"docker info exit {code}"


def docker_vm(opts, now, col, force_trim=False):
    """macOS Docker Desktop: report Docker.raw and the VM's /var/lib, and trim /var/lib when free
    space is near the floor (only with --apply, at most once a run, backing off after a trim
    that freed little), or after a restart of a SpacetimeDB container (force_trim)."""
    lines, data = [], {"platform": "Darwin"}
    raw = find_docker_raw(opts.get("docker_raw"))
    running, why = docker_running()
    data["running"] = running
    if not raw:
        lines.append(f"  docker desktop vm: no Docker.raw found ({short(opts.get('docker_raw') or DOCKER_RAW)} and Docker Desktop's settings); "
                     "give --docker-raw PATH. Nothing to trim")
        return lines, data
    alloc, apparent = allocated(raw)
    data.update(raw=raw, raw_allocated=alloc, raw_apparent=apparent)
    lines.append(f"  docker desktop vm: {short(raw)} allocated {human(alloc)} (apparent size {human(apparent)})")
    if not running:
        lines.append(f"  docker desktop vm: Docker Desktop is not running ({why}); no trim, no look inside the VM")
    elif col is not None:
        df = col.get("vm_df") or {}
        data["vm_df"] = df
        lines.append(f"  docker desktop vm: /var/lib in the VM: " + (f"{human(df['used'])} used of {human(df['total'])}, {human(df['free'])} free"
                                                                     if "total" in df else f"unknown ({df.get('error') or col.get('error')})"))
    free_now = free_bytes(os.path.dirname(raw))
    limit = (opts["floor"] + opts["trim_margin"]) * GB
    where = f"free {human(free_now)} on the volume holding Docker.raw"
    recent = [t for t in trim_state() if now - t.get("at", 0) < TRIM_BACKOFF_S]
    weak = recent and recent[-1].get("freed", 0) < TRIM_BACKOFF_MIN
    if not running:
        data["trim"] = "docker not running"
    elif free_now >= limit and not force_trim:
        data["trim"] = "not needed"
        lines.append(f"  docker desktop vm: no trim: {where}, at or over floor + margin ({opts['floor']:g} + {opts['trim_margin']:g} GB)")
    elif weak and not force_trim:
        t = recent[-1]
        data["trim"] = "backing off"
        lines.append(f"  docker desktop vm: no trim, backing off: the trim at {time.strftime('%H:%M', time.localtime(t['at']))} "
                     f"{'failed' if not t.get('ok') else 'freed ' + human(t.get('freed', 0))} (under {human(TRIM_BACKOFF_MIN)}); "
                     f"next try after {time.strftime('%H:%M', time.localtime(t['at'] + TRIM_BACKOFF_S))}; {where}")
    elif not opts["apply"]:
        data["trim"] = "would trim"
        lines.append(f"  docker desktop vm: would trim /var/lib (dry run): {where}, under floor + margin "
                     f"({opts['floor']:g} + {opts['trim_margin']:g} GB): docker {' '.join(TRIM)}")
    else:
        raw0 = allocated(raw)[0]
        code, so, se = run_tool(["docker", *TRIM], 900)
        if TRIM_SETTLE_S:
            time.sleep(TRIM_SETTLE_S)
        free1 = free_bytes(os.path.dirname(raw))
        raw1 = allocated(raw)[0] if os.path.isfile(raw) else 0
        rec = {"at": now, "ok": code == 0, "freed": free1 - free_now, "free_before": free_now, "free_after": free1, "after_restart": force_trim,
               "raw_before": raw0, "raw_after": raw1, "output": first_line(so) if code == 0 else first_line(se) or first_line(so)}
        try:
            with open(TRIM_STATE, "w") as f:
                json.dump((trim_state() + [rec])[-50:], f)
        except OSError as e:
            WARNINGS.append(f"could not record the trim in {short(TRIM_STATE)}: {e}")
        data["trim"] = rec
        why = "after the restart" if force_trim else f"{where}, under floor + margin"
        if code:
            lines.append(f"  docker desktop vm: TRIM FAILED (exit {code}, {why}): {rec['output'] or 'no message'}; no retry for {TRIM_BACKOFF_S // 60} min")
        else:
            lines.append(f"  docker desktop vm: trimmed /var/lib ({why}; {rec['output'] or 'fstrim said nothing'}): free {human(free_now)} -> {human(free1)} "
                         f"({'+' if free1 >= free_now else ''}{human(free1 - free_now)}), Docker.raw {human(raw0)} -> {human(raw1)}")
    return lines, data


def container_section(opts, now, restarted=False):
    """The report's container lines and data: the SpacetimeDB servers (every machine) and the
    Docker Desktop VM (macOS)."""
    lines, data = ["containers (report only, except a trim or a named restart with --apply):"], {}
    try:
        darwin = platform.system() == "Darwin"
        col = None
        if not darwin or docker_running()[0]:
            col = collect()
        if darwin:
            vm_lines, data["vm"] = docker_vm(opts, now, col, force_trim=restarted)
            lines += vm_lines
        else:
            lines.append(f"  docker desktop vm: skipped ({platform.system()}, not macOS: there is no VM disk between the containers and this disk)")
        if col is None:
            lines.append("  spacetimedb servers: not looked at (Docker Desktop is not running)")
        elif col.get("error"):
            lines.append(f"  spacetimedb servers: not looked at ({col['error']})")
        else:
            sums = [summarize(k, p, col["servers"], now) for k, p in sorted(group_servers(col["procs"], col["containers"]).items(),
                                                                           key=lambda g: (g[0][0] == "host", g[0][1] or "", g[0][2]))]
            data["held"] = [{k: v for k, v in s.items() if k != "top"} | {"top": [list(t) for t in s["top"]]} for s in sums]
            lines += [f"  note: {p}" for p in col["problems"]] + held_lines(sums)
    except Exception as e:  # the report and the build-folder cleanup must not depend on this
        lines.append(f"  stopped: {type(e).__name__}: {e}")
        data["error"] = f"{type(e).__name__}: {e}"
    return lines, data


# ---- The quiet restart of one SpacetimeDB container (--apply --restart-stdb NAME) ----

def name_file(path):
    try:
        return [l.split("#")[0].strip() for l in open(path) if l.split("#")[0].strip()]
    except OSError:
        return []


def locks_held():
    """Held locks of the merge queue and the scene gate (a non-blocking flock on each)."""
    held = []
    for p in [GATE_LOCK] + sorted(glob.glob(MERGE_LOCKS)):
        if not os.path.exists(p):
            continue
        try:
            fd = os.open(p, os.O_RDONLY)
        except OSError as e:
            held.append(f"{short(p)} (unreadable: {e.strerror}; counted as held)")
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            held.append(short(p))
        finally:
            os.close(fd)
    return held


def port_users(ports, procs, skip):
    """Processes outside the container that name one of its published host ports (a mind
    service, a trial runner, a play session, an observer: in their command line or, for this
    user's processes, their environment), and on macOS those with a connection to it."""
    if not ports:
        return []
    pat = re.compile(r"(?::|--port[= ])(?:%s)(?!\d)" % "|".join(map(str, ports)))
    found = []
    if platform.system() == "Darwin":
        code, so, _ = run_tool([system_tool("ps"), "-axww", "-o", "pid=,command="], 30)
        if code:
            return [f"ps failed (exit {code}): the port's users are unknown"]
        rows = [(int(l.split(None, 1)[0]), l.split(None, 1)[1] if len(l.split(None, 1)) > 1 else "") for l in so.splitlines() if l.strip()]
        for pid, cmd in rows:
            base = os.path.basename(cmd.split()[0]) if cmd.split() else ""
            if pid not in skip and base not in FORWARDERS and pat.search(cmd):
                found.append(f"pid {pid} ({cmd[:80]})")
        for port in ports:
            code, so, _ = run_tool([system_tool("lsof"), "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-Fpc"], 30)
            if code not in (0, 1):
                return found + [f"lsof failed (exit {code}): connections to port {port} are unknown"]
            pid = None
            for l in so.splitlines():
                if l.startswith("p"):
                    pid = int(l[1:])
                elif l.startswith("c") and pid not in skip and l[1:] not in FORWARDERS:
                    found.append(f"pid {pid} ({l[1:]}) is connected to port {port}")
        return found
    for pid, (_, argv) in procs.items():
        if pid in skip or not argv or os.path.basename(argv[0]) in FORWARDERS:
            continue
        cmd = " ".join(argv)
        hit = pat.search(cmd)
        if not hit:
            try:
                with open(os.path.join(PROC, str(pid), "environ"), "rb") as f:
                    hit = pat.search(f.read().decode(errors="replace").replace("\0", " "))
            except OSError:
                pass
        if hit:
            found.append(f"pid {pid} ({cmd[:80]})")
    return found


def list_databases(tool, name):
    """Database names the container's CLI identity lists, or raise RuntimeError (an empty or
    failed list is never taken as "none": SpacetimeDB 2.14.1 fails it on a 64-character name)."""
    code, so, se = run_tool([tool, "exec", name, "spacetime", "list"], 60)
    if code or "error" in (so + se).lower():
        raise RuntimeError(f"spacetime list failed (exit {code}): {first_line(se) or first_line(so)}")
    out = []
    for l in so.splitlines():
        if "|" not in l:
            continue
        n = l.split("|")[0].strip()
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", n) and n not in ("name", "database", "db_name", "identity") and not re.fullmatch(r"(0x)?[0-9a-f]{64}", n):
            out.append(n)
    return out


def sql_paused(tool, name, db):
    code, so, se = run_tool([tool, "exec", name, "spacetime", "sql", "-s", "local", db, "SELECT paused FROM world"], 60)
    if code or "error" in (so + se).lower():
        return {"ok": False, "error": first_line(se) or first_line(so) or f"exit {code}"}
    vals = re.findall(r"\b(true|false)\b", so)
    return {"ok": True, "paused": (vals[0] == "true") if vals else None}


def descendants(procs, root_pid):
    kids = {}
    for p, (pp, _) in procs.items():
        kids.setdefault(pp, []).append(p)
    out, stack = set(), [root_pid]
    while stack:
        p = stack.pop()
        if p not in out:
            out.add(p)
            stack += kids.get(p, [])
    return out


def restart_stdb(opts, now):
    """Stop one SpacetimeDB container with SIGINT, remove its deleted databases' directories,
    start it, and confirm every kept database. Refuses when it may be in use or when anything
    cannot be checked. Returns (lines, data); data["restarted"] when it was stopped and started."""
    name = opts["restart_stdb"]
    lines, data = [f"restart of {name} (--restart-stdb{'' if opts['apply'] else ', dry run'}):"], {"container": name, "restarted": False}

    def refuse(why):
        lines.append(f"  REFUSED: {why}. Nothing was stopped or removed")
        data["refused"] = why
        return lines, data

    never = [n for n in NEVER_RESTART + tuple(name_file(NEVER_RESTART_FILE)) if n == name]
    if never:
        return refuse(f"{name} is never restarted (built in, or {short(NEVER_RESTART_FILE)})")
    darwin = platform.system() == "Darwin"
    if darwin and not docker_running()[0]:
        return refuse("Docker Desktop is not running")
    col = collect()
    if col.get("error"):
        return refuse(col["error"])
    match = [c for c in col["containers"] if c[1] == name]
    if not match:
        return refuse(f"no running container is named {name}" + (f" ({'; '.join(col['problems'])})" if col["problems"] else ""))
    tool, _, cpid = match[0]
    code, so, se = run_tool([tool, "inspect", "--format", "{{json .Mounts}}\t{{json .HostConfig.PortBindings}}", name], 30)
    try:
        mounts_j, ports_j = so.strip().split("\t", 1)
        mounts, bindings = json.loads(mounts_j) or [], json.loads(ports_j) or {}
    except ValueError:
        return refuse(f"{tool} inspect failed (exit {code}): {first_line(se) or first_line(so)}")
    for m in mounts:
        guard = protected_by(m.get("Source") or "/nonexistent-source", opts.get("protected", []))
        if guard:
            return refuse(f"it mounts {short(m['Source'])}, protected by {short(guard[0])} ({guard[1]})")
    held = locks_held()
    if held:
        return refuse(f"a merge or the scene gate holds {', '.join(held)}")
    groups = group_servers(col["procs"], col["containers"])
    key = next((k for k in groups if k[:2] == (tool, name)), None)
    if not key:
        return refuse("no SpacetimeDB server runs in it")
    s = summarize(key, groups[key], col["servers"], now)
    data["before"] = {k: s[k] for k in ("files", "bytes", "live", "dead", "dead_bytes", "recent", "clients")}
    if s["errors"]:
        return refuse(f"its files or connections cannot be read ({s['errors'][0]})")
    if not s["listen"]:
        return refuse("it listens on no port it could be seen on, so its clients are unknown")
    if s["clients"]:
        return refuse(f"{plural(len(s['clients']), 'client')} connected to it ({', '.join(s['clients'][:3])})")
    host_ports = sorted({int(b["HostPort"]) for v in bindings.values() for b in (v or []) if str(b.get("HostPort", "")).isdigit()})
    me, skip = os.getpid(), descendants(col["procs"], cpid) if not darwin else set()
    p = me
    while p and p not in skip:  # this run and the shell that started it
        skip.add(p)
        p = col["procs"].get(p, (0, []))[0] if not darwin else 0
    skip.add(os.getppid())
    users = port_users(host_ports, col["procs"] if not darwin else {}, skip)
    if users:
        return refuse(f"in use through port {', '.join(map(str, host_ports))}: {'; '.join(users[:3])}")
    try:
        listed = list_databases(tool, name)
    except RuntimeError as e:
        return refuse(f"{e}, so its databases cannot be checked")
    refs = [n for n in listed if REFERENCE_WORLDS.match(n)]
    if refs:
        return refuse(f"it hosts reference worlds ({', '.join(refs)})")
    names = sorted(set(listed) | set(opts.get("stdb_db", [])))
    if len(names) < len(s["live"]):
        return refuse(f"it hosts {plural(len(s['live']), 'database')} but {len(names)} are known by name (its CLI identity lists {len(listed)}); "
                      "name the others with --stdb-db NAME so each can be checked after the restart")
    before = {n: sql_paused(tool, name, n) for n in names}
    bad = [n for n, v in before.items() if not v["ok"]]
    if bad:
        return refuse(f"{bad[0]} does not answer SQL before the restart ({before[bad[0]]['error']}), so it could not be confirmed after")
    data["databases"] = before
    dirs = [] if opts.get("keep_dirs") else s["dead"]
    if dirs and (name in KEEP_DIRS or name in name_file(KEEP_DIRS_FILE)):
        return refuse(f"its deleted databases' directories hold run evidence (docs/TRIAL_DISK.md: archive the commitlogs first); "
                      "restart without removing them with --keep-dirs")
    if any(not re.fullmatch(r"[0-9A-Za-z_-]+", r) for r in dirs):
        return refuse("a replica directory has an unexpected name")
    mount = None
    if dirs:
        cands = [m for m in mounts if s["data_dir"] == m.get("Destination") or s["data_dir"].startswith(m.get("Destination", "").rstrip("/") + "/")]
        mount = max(cands, key=lambda m: len(m["Destination"]), default=None)
        if not mount:
            return refuse(f"its data directory {s['data_dir']} is on no volume or bind mount, so its directories cannot be removed while it is stopped")
    plan = (f"stop ({tool} kill -s INT), remove {plural(len(dirs), 'directory', 'directories')} of deleted databases ({human(s['dead_bytes'] if dirs else 0)}), start; "
            f"frees {plural(s['files'], 'deleted file')} held open ({human(s['bytes'])}); keeps {plural(len(s['live']), 'live database')}"
            + (f" and {plural(len(s['recent']), 'directory', 'directories')} written in the last {RECENT_S // 60} min" if s["recent"] else "")
            + (f"; {plural(len(s['dead']), 'directory', 'directories')} kept (--keep-dirs)" if opts.get("keep_dirs") and s["dead"] else ""))
    if not opts["apply"]:
        lines.append(f"  would: {plan}")
        data["would"] = plan
        return lines, data
    lines.append(f"  plan: {plan}")
    free0 = free_bytes(HOME)
    code, so, se = run_tool([tool, "kill", "-s", "INT", name], 60)
    if code:
        return refuse(f"{tool} kill -s INT failed (exit {code}): {first_line(se)}")
    t0, stopped = time.time(), False
    while time.time() - t0 < STOP_WAIT_S:
        code, so, _ = run_tool([tool, "inspect", "--format", "{{.State.Running}}", name], 30)
        if code == 0 and so.strip() == "false":
            stopped = True
            break
        time.sleep(POLL_S)
    if not stopped:
        lines.append(f"  NOT STOPPED {STOP_WAIT_S} s after SIGINT; not forced, nothing removed, not started: look at {name} now")
        data["error"] = "did not stop"
        return lines, data
    lines.append(f"  stopped after {time.time() - t0:.0f} s")
    if dirs:
        dest = mount["Destination"].rstrip("/")
        rel = s["data_dir"][len(dest):].strip("/")
        src = mount["Name"] if mount.get("Type") == "volume" and mount.get("Name") else mount["Source"]
        paths = [os.path.join("/data", rel, "replicas", r) for r in dirs]
        removed = 0
        for i in range(0, len(paths), 200):
            code, so, se = run_tool([tool, "run", "--rm", "-v", f"{src}:/data", ALPINE, "rm", "-rf", "--", *paths[i:i + 200]], 1800)
            if code:
                lines.append(f"  REMOVAL FAILED (exit {code}): {first_line(se) or first_line(so)}; starting it again anyway")
                data["error"] = "removal failed"
                break
            removed += len(paths[i:i + 200])
        lines.append(f"  removed {removed} of {plural(len(dirs), 'directory', 'directories')} of deleted databases")
        data["removed"] = dirs[:removed]
    code, so, se = run_tool([tool, "start", name], 120)
    if code:
        lines.append(f"  START FAILED (exit {code}): {first_line(se) or first_line(so)}; {name} is stopped: start it by hand")
        data["error"] = "start failed"
        return lines, data
    data["restarted"] = True
    after, t0 = {}, time.time()
    for n in names:
        while True:
            after[n] = sql_paused(tool, name, n)
            if after[n]["ok"] or time.time() - t0 > SQL_WAIT_S:
                break
            time.sleep(POLL_S)
    data["after"] = after
    wrong = [n for n in names if not after[n]["ok"] or after[n]["paused"] != before[n]["paused"]]
    free1 = free_bytes(HOME)
    lines.append(f"  started; {len(names) - len(wrong)} of {plural(len(names), 'database')} answer SQL with the same paused state"
                 + (f"; paused: {', '.join(n for n in names if after[n].get('paused'))}" if any(after[n].get("paused") for n in names) else ""))
    if wrong:
        lines.append(f"  CHECK THESE: " + "; ".join(f"{n}: before {before[n]}, after {after[n]}" for n in wrong))
        data["error"] = "databases differ after the restart"
    lines.append(f"  free space {human(free0)} -> {human(free1)} ({'+' if free1 >= free0 else ''}{human(free1 - free0)})"
                 + ("; Docker Desktop's VM is trimmed next" if darwin else ""))
    return lines, data


def main(argv):
    if argv[:1] == ["--probe"]:  # internal: run under `podman unshare` or inside Docker Desktop's VM
        rest = [a for a in argv[2:] if a != "--vm"]
        print(json.dumps(probe(argv[1], [int(p) for p in rest] or None, vm="--vm" in argv)))
        return 0
    opts = {"apply": False, "repo": None, "floor": 40.0, "target": None, "idle": 24.0, "merged_idle": 2.0, "pressure_idle": 2.0, "json": False,
            "protect": [], "protect_file": PROTECT_FILE, "targets_file": TARGETS_FILE, "list": False,
            "docker_raw": None, "trim_margin": TRIM_MARGIN_GB, "containers_only": False, "restart_stdb": None, "stdb_db": [], "keep_dirs": False}
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
            elif a == "--targets-file":
                opts["targets_file"] = os.path.expanduser(args.pop(0))
            elif a == "--docker-raw":
                opts["docker_raw"] = os.path.expanduser(args.pop(0))
            elif a == "--trim-margin-gb":
                opts["trim_margin"] = float(args.pop(0))
            elif a == "--containers-only":
                opts["containers_only"] = True
            elif a == "--restart-stdb":
                opts["restart_stdb"] = args.pop(0)
            elif a == "--stdb-db":
                opts["stdb_db"].append(args.pop(0))
            elif a == "--keep-dirs":
                opts["keep_dirs"] = True
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
        outside = read_path_file(opts["targets_file"], "targets")
    except ValueError as e:
        print(f"disk_clean: {e}; nothing removed", file=sys.stderr)
        return 2
    plist = [f"  {short(p)}  ({src}{'' if os.path.lexists(p) else '; does not exist now'})" for p, src in protected] + \
            [f"  {short(n)}  (built in: container storage)" for n in NEVER]
    opts["protected"] = protected
    if opts["containers_only"]:  # read-only: never trims, restarts or removes anything, takes no lock
        ro = {**opts, "apply": False}
        lines = restart_stdb(ro, time.time())[0] + [""] if opts["restart_stdb"] else []
        print("\n".join(lines + container_section(ro, time.time())[0]))
        return 0
    if opts["list"]:
        print("protected (never removed, nor anything under them, nor a build folder holding them):")
        print("\n".join(plist))
        if outside:
            print("target folders outside the worktrees that may be cleaned:")
            print("\n".join(f"  {short(p)}  ({src})" for p, src in outside))
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
    # Cargo target folders outside the worktrees that targets.txt names (private CARGO_TARGET_DIRs)
    seen = {real(r["path"]) for r in rows}
    cands = sorted({p for p, _ in outside} | {m for p, _ in outside for m in glob.glob(glob.escape(p) + ".slop-reclaim-*")})
    for t in cands:
        if real(t) in seen or os.path.islink(t) or not os.path.isdir(t) or any(inside(t, n) or inside(n, t) for n in NEVER):
            continue
        seen.add(real(t))
        leftover = re.search(r"\.slop-reclaim-\d+$", t)
        if not leftover and not is_target(t):
            continue
        try:
            size, newest, files, crosses = scan(t)
        except OSError as e:
            WARNINGS.append(f"skipped {short(t)}: {e}")
            continue
        idle_h = max(now - newest, 0) / 3600
        row = {"path": t, "worktree": os.path.dirname(t), "branch": "outside the worktrees", "size": size, "files": files, "idle_h": idle_h}
        guard = protected_by(t, protected)
        user = None if guard else in_use(t, held, mounts)
        if guard:
            row.update(decision="never", why=f"protected: {short(guard[0])} ({guard[1]})")
        elif user:
            row.update(decision="keep", why=f"in use: {user}")
        elif crosses or any(inside(m, t) for m in mpoints):
            row.update(decision="keep", why="another filesystem is mounted inside it")
        elif leftover:
            row.update(decision="remove", why="left over from an earlier removal")
        elif idle_h >= opts["idle"]:
            row.update(decision="remove", why=f"idle {idle_h:.1f} h")
        elif idle_h >= opts["pressure_idle"]:
            row.update(decision="pressure", why=f"idle {idle_h:.1f} h; removed only under pressure")
        else:
            row.update(decision="keep", why=f"active (idle {idle_h:.1f} h)")
        foreign = [] if leftover else foreign_entries(t)
        if foreign and row["decision"] in ("remove", "pressure"):
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
    restart_lines, restart = restart_stdb(opts, now) if opts["restart_stdb"] else ([], {})
    cont_lines, cont = container_section(opts, now, restarted=restart.get("restarted", False))
    if restart:
        cont["restart"] = restart
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
    lines += [""] + restart_lines + ([""] if restart_lines else []) + cont_lines
    low = (free1 if opts["apply"] else free0 + would) < opts["floor"] * GB
    if low:
        held = sum(r.get("bytes", 0) for r in cont.get("held", []))
        lines.append(f"BELOW THE FLOOR ({opts['floor']:.0f} GB): the rest is in use, active or protected; see the list above"
                     + (f"; SpacetimeDB holds {human(held)} of deleted files open (above)" if held >= GB else ""))
    report = "\n".join(lines)
    print(report)
    name = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + ("-apply" if opts["apply"] else "-dry") + ".txt"
    with open(os.path.join(STATE, "reports", name), "w") as f:
        f.write(report + "\n")
    with open(os.path.join(STATE, "log.jsonl"), "a") as f:
        f.write(json.dumps({"at": stamp, "host": host, "apply": opts["apply"], "free0": free0, "free1": free1, "removed": removed_bytes,
                            "protected": [[p, src] for p, src in protected], "sized": sized, "notes": NOTES, "warnings": WARNINGS, "containers": cont,
                            "rows": [{k: r.get(k) for k in ("path", "size", "decision", "why", "result", "freed")} for r in rows]}) + "\n")
    reports = sorted(os.listdir(os.path.join(STATE, "reports")))
    for old in reports[:-300]:
        os.remove(os.path.join(STATE, "reports", old))
    if opts["json"]:
        print(json.dumps(rows, default=str))
    if restart and (restart.get("refused") or restart.get("error")):
        return 4
    return 3 if low else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
