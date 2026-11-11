# Tooling: the check, merges and disk

Status: **current** (Tool 7, 2026-11-11, branch `tool-7`). Three machines (the laptop, the dev-box and the Spark) merge branches into `main`. Each merge runs `just living-check`, and each machine has several worktrees with their own Cargo target folders. Before Tool 7, every re-run of the check after `main` moved was a full rebuild, and build folders filled the disks three times in one day. Tool 7 has three parts, each built on our own scripts:

| Part | Command | Script |
| --- | --- | --- |
| The check | `just living-check` (`just living-check-full`) | [`living/tools/check.py`](../living/tools/check.py), [`sccache-rustc`](../living/tools/sccache-rustc), [`install_sccache.sh`](../living/tools/install_sccache.sh) |
| Merging | `just living-merge <branch> -m "Merge <branch>: …"` | [`living/tools/merge.py`](../living/tools/merge.py), self-test [`merge_selftest.py`](../living/tools/merge_selftest.py) |
| Disk | `just living-disk-clean [--apply]`, on a timer | [`living/tools/disk_clean.py`](../living/tools/disk_clean.py), [`disk_clean_install.sh`](../living/tools/disk_clean_install.sh) |

[`check_timings.py`](../living/tools/check_timings.py) reads a cargo `--timings` report and splits the time between workspace crates, dependencies and build scripts.

## The check

`just living-check` runs the same five cargo commands as before, in [`check.py`](../living/tools/check.py):

| Step | Command | Lane |
| --- | --- | --- |
| `authority` | `cargo build -p living-authority --target wasm32-unknown-unknown --release` | release |
| `mind+viewer` | `cargo build -p living-mind -p living-viewer` | debug |
| `game` | `cargo build --release -p living-game` | release |
| `viewer-wasm` | `cargo build --manifest-path living/viewer/Cargo.toml --target wasm32-unknown-unknown --profile wasm-dev --bin living-viewer` | wasm-dev |
| `rules-tests` | `cargo test -p living-rules` | debug |

Three things are new:

- **Lanes at once.** Cargo locks each build directory (`target/debug`, `target/release` and the wasm ones), so steps that use different directories can run together. The three lanes run in parallel, each lane's steps in the order above. One make-style jobserver (a fifo that every cargo joins) caps the lanes together at `CARGO_BUILD_JOBS` jobs (default: all cores). Each step's output goes to `<target>/living-check/<step>.log`, and a failing step's log is printed. After a failure no new step starts. `LIVING_CHECK_SERIAL=1` (or `--serial`) runs the steps one by one, with cargo's output on the terminal.
- **Step stamps.** A step's inputs are:
  - the files of the packages it builds and their path dependencies (from `cargo metadata`); a path package that is no workspace member, such as a `[patch]` path, leaves the step unstampable until it is mapped;
  - the shared inputs: `living/Cargo.toml`, `Cargo.lock`, `living/seeds/`, `living/scripts/`, and toolchain and `.cargo` files. `check.py` is not an input: the digest holds each step's command and input list, and its `TOOL_VERSION` is raised whenever the keying or the audit changes;
  - the game's two `#[path]` modules from the viewer;
  - the toolchain (`rustc -vV`, `cargo -V`, the C compiler's version), the command, the OS and architecture, and every Cargo configuration file outside the repository that cargo would load (`.cargo/config.toml` in the parent folders and in `CARGO_HOME`);
  - the build environment (`RUSTFLAGS`, `CARGO_PROFILE_*`, `LIVING_*`, `CC`, and every variable a build script or crate was seen to depend on).

  Files are hashed from the working tree's raw bytes (tracked and untracked, not git-ignored), so uncommitted changes count and the index is not trusted. When a step passes, its digest is stamped in `~/.cache/slop-check/stamps/`, a store shared by every worktree on the machine. A later check with the same digest skips the step and prints where and when it passed.
- **Compile cache.** When `sccache` is installed (`living/tools/install_sccache.sh` puts v0.19.0, pinned by checksum, in `~/.local/share/slop-tools/bin`, off `PATH`), rustc runs through `living/tools/sccache-rustc`. The cache lives in `~/.cache/slop-sccache`, capped at 20 GB (`SLOP_SCCACHE_SIZE`), behind a server on port 4237 of its own. sccache puts every `CARGO_*` variable and the working directory in a Rust cache key, so the wrapper removes the ones rustc never reads (`CARGO_TARGET_DIR`, terminal settings). Registry crates then hit across worktrees. Workspace crates hit only within their own worktree, and cargo does not cache incremental (debug) builds of them at all. A cache failure compiles locally.

A failure of the check itself (a full disk while writing a log, say) fails the step. Every planned step must end skipped, passed or failed, so a crash is never reported as a pass. With `CARGO_BUILD_JOBS` at or under the number of lanes, the steps run one by one. The jobserver caps compile jobs, not the threads of the rules tests while they run (libtest uses all cores).

`just living-check-full` (or `LIVING_CHECK_FULL=1`) runs every step and ignores stamps; it still writes them. `python3 living/tools/check.py --plan` prints what would run or be skipped, and why. `--steps a,b` runs some steps. Every run is appended to `~/.cache/slop-check/runs.jsonl` with each step's time, the load average and the cache hits.

### What a passing check still guarantees

A merge checked this way guarantees what it did before: every step of `living-check` has passed **on this machine**, with this toolchain and build environment, on inputs byte-identical to the merged tree's inputs for that step. A skipped step's result is the one it had when it ran; nothing is assumed from another machine.

Two things keep the input map honest:

- **The audit.** After each passing step, the compiler's dep-info and the build scripts' `rerun-if-changed` lines are checked. Every file a workspace crate read must lie inside that package's declared inputs and must not be git-ignored. A step that fails the audit passed, but writes no stamp, so an out-of-date map costs time, never a false skip. On its first run the audit found the game's `#[path]` modules.
- **Environment learning.** Environment names that build scripts declare (`rerun-if-env-changed`) and that crates read (`env!`) are kept per step in `~/.cache/slop-check/envdeps.json` and enter that step's digest.

What it does not add: a skipped test step is not re-run, so a flaky test that once passed stays passed until its inputs change. Outputs are not compared, only inputs, so the guarantee is cargo's own freshness rule applied across worktrees. A test that reads files outside its inputs at run time would not be seen; the rules tests read none (all their fixtures are `include_str!`, which the audit sees).

## Merging

From a clean coordinator worktree (on its own branch, such as `coord-devbox`, or detached; never `main` and never `~/dev/slop-art-online`):

```bash
set -o pipefail; just living-merge plan-3 -m "Merge plan-3: what it brings"
```

[`merge.py`](../living/tools/merge.py):

1. Refuses a dirty worktree (untracked files included), an unfinished merge or rebase, `main` checked out here, the owner's checkout, and commits that `origin/main` lacks.
2. Fetches `main` and the branch, and pins the branch to the commit it has now. It prefers `origin/<branch>` and otherwise takes a local branch, saying so.
3. Moves HEAD to `origin/main` (`git reset --keep`) and runs `git merge --no-ff`. On a conflict it aborts the merge, restores HEAD and stops (exit 4).
4. Runs the check (`check.py`). If the check fails, HEAD is restored and nothing is pushed (exit 5). If the check changes the worktree (a rewritten `Cargo.lock`, say), it stops (exit 6).
5. Pushes the checked merge commit as a compare-and-swap: `git push --force-with-lease=refs/heads/main:<base> origin <merge>:refs/heads/main`. It lands only while `main` is still exactly the commit that was merged onto and checked, so it never lands on a `main` that moved or was rewound meanwhile. When the push is refused and the remote `main` is no longer the base, the tool re-fetches, merges the same branch commit onto the new `main` and checks again; stamps skip the steps whose inputs the new `main` did not change. It tries up to `--retries` times (5; exit 7 after). If the branch was merged by someone else meanwhile, it stops with nothing to push (exit 0). Any other push failure stops (exit 8) with the checked merge left in HEAD, and any other git failure stops with the summary (exit 9).
6. Prints every git command it ran and a summary. The check's output is also kept in `~/.local/state/slop-merge/<time>-<branch>.log`.

`--no-push` stops after a passing check. `python3 living/tools/merge_selftest.py` drives all of this against a throwaway remote (18 checks): the dirty-worktree, local-commit, conflict, failing-check and dirtying-check refusals, a `main` that moves during the check, a `main` that is rewound during the check, a branch merged by someone else meanwhile, an unknown branch, and a clean merge.

## Disk

[`disk_clean.py`](../living/tools/disk_clean.py) carries out this policy. Without `--apply` it is a dry run that prints the same report. The timer runs it every 30 minutes with `--apply`.

**May be removed:** Cargo target folders inside the git worktrees of this repository. A Cargo target folder is one Cargo tagged with `CACHEDIR.TAG`, or one holding Cargo's `.rustc_info.json` beside tagged or locked build directories. Cargo leaves the root of a `CARGO_TARGET_DIR` untagged when the folder already existed. Nothing else may be removed. A folder goes when all of these hold:

- **Nothing uses it.** No process has its working directory, executable, open files or mapped files inside it (`/proc` on Linux, `lsof` on macOS; if `lsof` fails, every folder counts as in use). No Podman or Docker container mounts it, its worktree, or anything inside; stopped containers count too. A container tool that does not answer makes every folder count as mounted. One that answers with an error (no daemon running) is reported as a warning, since nothing of it runs. No Cargo lock in it is held. It holds no other mounted filesystem.
- **One of three rules fits:**
  - **merged:** the worktree's HEAD is in `origin/main` but not on `main`'s own first-parent line, the worktree has no uncommitted or untracked changes outside `.local/`, and the folder has been idle 2 hours. The first-parent condition means the worktree had a branch of its own that was merged. A fresh worktree started from `main`, or a coordinator whose merges are `main`, stays under the 24-hour rule, so a coordinator keeps its warm merge build;
  - **idle:** the folder and the worktree's git state (index, HEAD log) have been idle 24 hours;
  - **pressure:** free space is under the floor plus 30 GB and the folder has been idle 2 hours. These go oldest first, and only until free space reaches the floor plus 30 GB.

**Free-space floor:**

| Machine | Floor | Target (floor + 30 GB, about one cold check build) |
| --- | --- | --- |
| dev-box | 40 GB | 70 GB |
| Spark | 40 GB (the default; set `--floor-gb` when installing) | 70 GB |
| laptop | 40 GB (the default; set `--floor-gb` when installing) | 70 GB |

When the folders that may go are gone and free space is still under the floor, the report says so (exit 3), and the list shows what holds the rest.

**Never touched:**

- the owner's checkouts `~/dev/slop-art-online`, `~/dev/slop-game`, `~/dev/slop-floors`, `~/dev/slop-ab-arm1` and `~/dev/slop-ab-arm2`, and everything under them (their build folders are listed as `never`);
- `~/archive`;
- container storage, Docker and Podman volumes (never pruned) and the databases in them. `living/tools/reclaim_disk.sh`, which deletes idle SpacetimeDB replicas, stays a manual tool: the paused reference worlds are idle replicas;
- `.local` evidence that is not a build folder;
- worktree roots, symlinks, and anything outside this repository's worktrees.

**A target folder that holds other files** (a worker's `build.log` in its target root, say) keeps them. Only Cargo's own entries are removed (`debug`, `release`, the target-triple and profile folders, `.rustc_info.json`, `CACHEDIR.TAG`, `cargo-timings`), and the folder and the other files stay. A nested repository (a folder with its own `.git`) is not entered.

**Sizes and reflinks.** `du` and plain block counts count a reflink copy's shared blocks in every copy (`cp --reflink` on the dev-box's XFS, clones on APFS). Two copies of one 14 GB target therefore show as 28 GB, and deleting one of them frees almost nothing. For the folders it would remove, the report counts only the blocks no other file shares (Linux `FIEMAP`, `FIEMAP_EXTENT_SHARED`), notes the shared part, and plans the pressure tier with these real sizes. "Freed" is always the measured change in free space.

**How a removal happens.** Just before each removal the script looks again at the processes and containers. It takes every Cargo lock in the folder without waiting, renames the folder aside (`<folder>.slop-reclaim-<time>`), checks again that no process uses it, and deletes it. If a check fails, it renames the folder back. An aside folder left by an interrupted run is removed on a later run. `python3 living/tools/disk_clean_selftest.py` runs the policy in a throwaway home with aged fake targets: a merged worktree, a busy one, a fresh one, an old one holding a log, protected checkouts, untagged evidence, a foreign tag, a symlink and a nested repository. Reports go to `~/.local/state/slop-disk/reports/` and `log.jsonl`, and on Linux also to the journal (`journalctl --user -u slop-disk-clean.service`).

**Install** (re-run after `disk_clean.py` changes; it copies the script to `~/.local/share/slop-tools/`, so removing a worktree never breaks the timer):

```bash
living/tools/disk_clean_install.sh --floor-gb 40          # Linux: systemd user timer slop-disk-clean.timer
living/tools/disk_clean_install.sh --uninstall
```

On Linux the timer runs without a login when lingering is on (`loginctl enable-linger`). On macOS the same command writes and loads the launchd agent `~/Library/LaunchAgents/dev.slop.disk-clean.plist` (every 30 minutes, log in `~/.local/state/slop-disk/launchd.log`). Give `python3` Full Disk Access if the report shows folders it cannot read.

[`disk_report.sh`](../living/tools/disk_report.sh) still reports free space and big folders across the machines; it deletes nothing.

## Measurements (dev-box, 2026-11-11)

All runs used `CARGO_BUILD_JOBS=12` on the 32-core dev-box while other workers were building. The load average at each run's start (and the range during it) is given because it moved the numbers more than anything else. Before/after arms on the same change are interleaved A B B A. The runs used a scratch clone of the repository and private target folders; reflink snapshots gave each warm arm the same starting state. The raw records are in each run's JSON (`check.py --json`) and the step logs.

**Where the time goes (cold, plain `living-check`, load 27–43, 625 s).**

| Step | Wall | Unit time by kind (cargo `--timings`) |
| --- | --- | --- |
| authority (wasm, release) | 54 s | dependencies 103 s, workspace 30 s (`living-authority` 18 s, `living-rules` 12 s) |
| mind+viewer (debug) | 69 s | dependencies 518 s, build scripts 61 s (`aws-lc-sys` 39 s), workspace 30 s |
| game (release) | 229 s | dependencies 1,953 s (`bevy_pbr` 103 s, `bevy_render` 89 s, `bevy_ui` 84 s), workspace 125 s (`living-bindings` 51 s) |
| viewer-wasm (wasm-dev) | 171 s | dependencies 1,702 s, workspace 66 s |
| rules tests: build / run | 19 s / 83 s | 139 tests; the run is single-binary libtest on all cores |

A cold check is almost all dependency compiles, which a shared cache can serve. A warm check is the opposite: the workspace crates (rules built five ways, the game crate and its link) and the rules test run.

**Warm: a merge in a coordinator's worktree, the same change (`6a905c31`, rules-1: authority, game, mind, rules, seeds and viewer changed; warm on its first parent).**

| Arm | Wall | Load at start (range) |
| --- | --- | --- |
| A1 plain | 202 s (authority 19, mind+viewer 18, game 49, viewer-wasm 9, rules build 9, rules run 98) | 15 (13–27) |
| B1 lanes (+ cache, no stamps apply) | 173 s (lanes: 30 + 87 / 28 + 143 / 8) | 25 (24–53) |
| B2 lanes | 130 s | 38 (26–38) |
| A2 plain | 209 s (rules run 106) | 26 (19–39) |

Average A 205 s, B 151 s (−26%), with B under the higher load. The lanes overlap the test run with the game build. The floor is the debug lane: mind+viewer, then the rules tests, about 100 s of which is the test run itself. No stamp applied, because the merge changed `living/rules`, which every step reads.

**How much of a merge's wait was work another worktree had already done.** In the warm merge above, about 105 s of the 205 s rebuilt workspace crates. The branch's own worktree had built exactly those crates before asking for the merge, but at another path, so neither cargo nor sccache could reuse them (both key workspace crates by path). The other 100 s re-ran tests that had already passed there. Across the last 59 merges into `main`, the merged tree's inputs equalled the branch tip's for every step in 27 merges, and for 34–42 merges per step. Counting the previous `main`'s stamps as well, **35 of 59 merges needed no step at all, and on average 0.93 of the 5 steps had to run.** A plain warm check rebuilt about 3 steps and always ran the tests. Stamps reach this only for branches checked on the same machine with the new check.

**Stamps on a real merge shape (`755dafe7`, sight-2: only the game changed against main and against the branch tip).** A plain warm check took 131 s (game 43 s, the rest nothing to do but the 85 s test run). With the lanes and only the viewer-wasm stamp available, it took 106 s and 101 s. The branch-tip check that should have supplied the other stamps was invalid in this setup: I had seeded its target with a reflink copy built in the other clone, so cargo saw older source mtimes and judged every crate fresh. The audit caught it (the dep-info pointed outside the repository) and wrote no stamp. That is the false skip it is there to stop.

**First real use (this branch, merged with `main` at `e3f27e7b`, 17:48).** `just living-check` in a fresh worktree target, with the cache shared from the earlier runs, took 684 s under load 65–83: authority 78 s, mind+viewer 342 s, game 575 s, viewer-wasm 426 s and the rules tests 339 s, in three lanes. The cache served 1,070 compiles, missed 414, and 393 were not cacheable. All five steps passed the audit and were stamped. Run again on the same tree, the check skipped all five steps in 0.25 s.

**Cold: an empty target folder, the same commit (`bcbde99d`).**

| Arm | Wall | Load at start (range) | sccache |
| --- | --- | --- | --- |
| A plain (first baseline) | 625 s | 31 (27–43) | none |
| populate: lanes, empty cache, another worktree path | 424 s | 21 (21–52) | 2 hits, 1,482 misses, 391 not cacheable |
| A1 plain | 1,436 s (game 644 s) | 50 (50–75) | none |
| B1 lanes + cache warmed from the other worktree | 428 s | 59 (43–81) | 1,070 hits, 414 misses, 391 not cacheable |

B2 and A2 were not run: each cold arm needs about 15 GB, and free space kept falling to the 40 GB floor while other workers built. Under similar load, A1 against B1 is 1,436 s against 428 s, a 70% cut. Across all four runs, the plain check took 625–1,436 s and the new one about 425 s. 56% of the compile requests were served from the cache across worktrees. The 391 not-cacheable requests are binaries, proc-macros, cdylibs and incremental builds, which sccache cannot serve. The cache held 2.8 GB after these runs and 3.8 GB after the first real use (20 GB cap); 1,070 of the 1,909 requests in each cold run with a warm cache were served from it.

**Disk.** A cold check's target folder is 14–17 GB (debug 9 GB, release 3 GB, wasm 2 GB). On 2026-11-11 the cleanup's first runs on the dev-box found 24 build folders. All but one were in use or active (idle under 2 hours), so it removed 1 (0.9 GB). By then the folders of most finished worktrees had already been removed by hand.

## Adoption

Every part arrives with `main` once `tool-7` is merged; `just living-check` keeps its name and its five steps. Each machine then does the following.

**All three machines.**
- Merge with `just living-merge <branch> -m "Merge <branch>: …"` from the coordinator worktree instead of the four hand steps. It runs the check, pushes, and on a moved `main` merges and checks again by itself.
- Stamps are per machine. A merge skips the steps that a worker on the same machine checked on identical inputs with the new check. A branch checked on another machine runs in full, as before.
- Keep 40 GB free before a cold check (about 15 GB of target and up to 20 GB of compile cache over time).

**dev-box** (done on 2026-11-11): `install_sccache.sh` ran (v0.19.0), the timer is installed (`disk_clean_install.sh --floor-gb 40`), and lingering is on.

**Spark** (aarch64 Linux, its coordinator):
1. `living/tools/install_sccache.sh` (the pinned aarch64 musl build).
2. `living/tools/disk_clean_install.sh --floor-gb 40`, after a dry run `just living-disk-clean`. Check the dry run's list against the Spark's own rules: `~/kimodo-test` and the Hugging Face cache are not worktrees of this repository, so they are never candidates. If the Spark has protected checkouts other than the five listed, add them to `PROTECTED` in `disk_clean.py` first.
3. `loginctl show-user $USER -p Linger`; if it is `no`, run `loginctl enable-linger $USER` so the timer runs without a login.

**Laptop** (macOS, Apple silicon):
1. `living/tools/install_sccache.sh` (the pinned `aarch64-apple-darwin` build).
2. `just living-check` needs `python3` (Xcode command-line tools). The lanes use a fifo jobserver. On macOS this is not verified yet; if cargo reports a jobserver error, run with `LIVING_CHECK_SERIAL=1` and report it.
3. Disk: run the dry run, then `living/tools/disk_clean_install.sh --floor-gb <N>`, which writes and loads a launchd agent. In-use detection uses `lsof`; give `python3` Full Disk Access (System Settings, Privacy & Security) so it can see every process's files. If `lsof` fails, nothing is removed. The protected list includes the repository's own main checkout wherever it is. The script and installer were not run on macOS in this change.
