# Tooling: the check, merges and disk

Status: **current** (Tool 7, 2026-11-11, branch `tool-7`; the laptop's follow-ups in `tool-7b`, the same day). Three machines (the laptop, the dev-box and the Spark) merge branches into `main`. Each merge runs `just living-check`, and each machine has several worktrees with their own Cargo target folders. Before Tool 7, every re-run of the check after `main` moved was a full rebuild, and build folders filled the disks three times in one day. Tool 7 has three parts, each built on our own scripts:

| Part | Command | Script |
| --- | --- | --- |
| The check | `just living-check` (`just living-check-full`) | [`living/tools/check.py`](../living/tools/check.py), [`sccache-rustc`](../living/tools/sccache-rustc), [`install_sccache.sh`](../living/tools/install_sccache.sh), self-test [`check_selftest.py`](../living/tools/check_selftest.py) |
| Merging | `just living-merge <branch> -m "Merge <branch>: …"` | [`living/tools/merge.py`](../living/tools/merge.py), self-test [`merge_selftest.py`](../living/tools/merge_selftest.py) |
| Disk | `just living-disk-clean [--apply]`, on a timer | [`living/tools/disk_clean.py`](../living/tools/disk_clean.py), [`disk_clean_install.sh`](../living/tools/disk_clean_install.sh), self-test [`disk_clean_selftest.py`](../living/tools/disk_clean_selftest.py) |

[`check_timings.py`](../living/tools/check_timings.py) reads a cargo `--timings` report and splits the time between workspace crates, dependencies and build scripts.

## The check

`just living-check` runs the five cargo commands of before and, since `tool-8`, the script fuel gate, since `fix-laws` the seed-laws test, and since `check-game-tests` the game client's unit tests, in [`check.py`](../living/tools/check.py):

| Step | Command | Lane |
| --- | --- | --- |
| `authority` | `cargo build -p living-authority --target wasm32-unknown-unknown --release` | release |
| `mind+viewer` | `cargo build -p living-mind -p living-viewer` | debug |
| `game` | `cargo build --release -p living-game` | release |
| `game-tests` | `cargo test --release -p living-game`: the client's unit tests on the game step's release tree, headless (no display, GPU or generated assets); names in `GAME_TEST_SKIPS` are skipped here by name (`--exact --skip`) and run by hand: none needs a display, and none is skipped now (fix-make-offer fixed the one known red test). The client reads the rules (`offered()`, the checks), and a rules change turned `verbs::tests::make_is_offered_at_a_furnace_only_while_it_burns_with_fuel` red on main (f0061a07) while the check only built the game (its fixture held no crucible, which goods-3's glass needs). Its stamp covers the game's closure, the rules included. Spark, 2026-11-12: 15 s on top of a built game tree, 0 s stamped | release |
| `viewer-wasm` | `cargo build --manifest-path living/viewer/Cargo.toml --target wasm32-unknown-unknown --profile wasm-dev --bin living-viewer` | wasm-dev |
| `rules-tests` | `cargo test -p living-rules` | debug |
| `seed-laws` | `cargo test -p living-authority --lib seed::tests::a_seeds_laws_are_in_force_after_init`: every seed with its own laws has them in force after `init` | debug |
| `script-gate` | `cargo build --manifest-path living/tools/script_bench/Cargo.toml -p sb-module --target wasm32-unknown-unknown --release --features rhai`, then `-p sb-host --bin sb-host --release --no-default-features`, then [`gate.py`](../living/tools/script_bench/gate.py) ([below](#the-script-fuel-gate)) | script-bench |

Three things are new:

- **Lanes at once.** Cargo locks each build directory (`target/debug`, `target/release` and the wasm ones), so steps that use different directories can run together. The four lanes run in parallel, each lane's steps in the order above. The script bench is a cargo workspace of its own, built into `<target>/script-bench`, so its lane locks nothing the others use. One make-style jobserver (a fifo that every cargo joins) caps the lanes together at `CARGO_BUILD_JOBS` jobs (default: all cores). Each step's output goes to `<target>/living-check/<step>.log`, and a failing step's log is printed. After a failure no new step starts. `LIVING_CHECK_SERIAL=1` (or `--serial`) runs the steps one by one, with cargo's output on the terminal.
- **Step stamps.** A step's inputs are:
  - the files of the packages it builds and their path dependencies (from `cargo metadata`); a path package that is no workspace member, such as a `[patch]` path, leaves the step unstampable until it is mapped;
  - the shared inputs: `living/Cargo.toml`, `Cargo.lock`, `living/seeds/`, `living/scripts/`, and toolchain and `.cargo` files. `check.py` is not an input: the digest holds each step's command and input list, and its `TOOL_VERSION` is raised whenever the keying or the audit changes;
  - the game's two `#[path]` modules from the viewer, and the script bench's `port.rs`;
  - a step's own inputs: for `script-gate`, the bench's `Cargo.toml` and `Cargo.lock`, `budgets.json` and `gate.py`;
  - the toolchain (`rustc -vV`, `cargo -V`, the C compiler's version), the command, the OS and architecture, and every Cargo configuration file outside the repository that cargo would load (`.cargo/config.toml` in the parent folders and in `CARGO_HOME`);
  - the build environment (`RUSTFLAGS`, `CARGO_PROFILE_*`, `LIVING_*`, `CC`, and every variable a build script or crate was seen to depend on).

  Files are hashed from the working tree's raw bytes (tracked and untracked, not git-ignored), so uncommitted changes count and the index is not trusted. When a step passes, its digest is stamped in `~/.cache/slop-check/stamps/`, a store shared by every worktree on the machine. A later check with the same digest skips the step and prints where and when it passed.
- **Compile cache.** When `sccache` is installed (`living/tools/install_sccache.sh` puts v0.19.0, pinned by checksum, in `~/.local/share/slop-tools/bin`, off `PATH`), rustc runs through `living/tools/sccache-rustc`. The check uses only that pinned copy (or `SLOP_SCCACHE`, when set), never an sccache on `PATH` such as Homebrew's; without the pinned copy it compiles without a cache and says so. The wrapper itself, run outside the check, takes `SLOP_SCCACHE`, then the pinned copy, then `PATH`. The cache lives in `~/.cache/slop-sccache`, capped at 10 GB (`SLOP_SCCACHE_SIZE`; 20 GB until 2026-11-13, lowered after dev-box ran short of disk), behind a server on port 4237 of its own. sccache puts every `CARGO_*` variable and the working directory in a Rust cache key, so the wrapper removes the ones rustc never reads (`CARGO_TARGET_DIR`, terminal settings). Registry crates then hit across worktrees. Workspace crates hit only within their own worktree, and cargo does not cache incremental (debug) builds of them at all. A cache failure compiles locally. The check prints a `compile cache:` line saying which sccache it uses and through which wrapper, or why there is none.

**A `RUSTC_WRAPPER` that is already set** (the laptop's `build-slot`, say) is handled by what it resolves to:

| Pre-set `RUSTC_WRAPPER` | What the check does |
| --- | --- |
| `sccache-rustc`: this worktree's, a symlink to it, a copy of it under any name or in another worktree, or the bare name on `PATH` (recognized by its header line) | Keeps the caller's wrapper and adds the cache settings: the pinned sccache, and `SCCACHE_DIR`, `SCCACHE_SERVER_PORT` and `SCCACHE_CACHE_SIZE` unless the caller set them (the caller's values win, so the stats ask the server it compiles through). Prints the `compile cache:` line and records the sccache stats in `runs.jsonl`. Not part of the step digest. |
| a plain `sccache` | Left as it is, with its own settings; no cache line or stats. Not part of the digest, as sccache does not change outputs. |
| anything else | Left as it is: cargo runs it, without this check's cache settings or stats. It enters every step's digest, so stamps made with it apply only with it. (This was the behaviour for every pre-set wrapper before `tool-7b`.) |

**Failed compiles in the sccache stats.** A passing check whose build scripts ran shows a few "compilation failures" (`failed` in the stats). They are build scripts' feature probes, compiled through `RUSTC_WRAPPER` and meant to fail on stable Rust. On 2026-11-11 the four were `anyhow` (`src/nightly.rs`, `error_generic_member_access`), `thiserror` 1.0.69 and 2.0.21 (`build/probe.rs`, `error_generic_member_access`) and `proc-macro2` (`src/probe/proc_macro_span.rs`, `proc_macro_span`). Each fails with E0554, "`#![feature]` may not be used on the stable release channel", so the crate uses its stable code. They were found by building those crates through a private sccache server with debug logging. sccache does not cache failures, so each build that re-runs those build scripts counts them again. A warm build that does not re-run them counts none. They are not ours to fix, and fixing them would change nothing.

**Stopping its children.** Each cargo runs in a process group of its own, so an interrupted check stops rustc, build scripts and test binaries with it. A SIGINT or SIGTERM stops them directly. For a check that is killed outright, the check also starts a small watchdog process in a session of its own. The watchdog reads a pipe that only the check holds open, and the check registers each cargo's process group on it, along with its jobserver folder. When the check exits in any way, a SIGKILL included, the kernel closes the pipe. The watchdog then sends each group still registered SIGTERM, then SIGKILL after 10 s, and removes the folder. This relies only on POSIX pipes and process groups, so it works the same on macOS, where `PR_SET_PDEATHSIG` does not exist. On Linux, `PR_SET_PDEATHSIG` stays as a second guard. Tested on the dev-box: a `check.py --full` was SIGKILLed mid-build (3 cargos, 10–11 rustc), once with `PR_SET_PDEATHSIG` on and once with it off. Within 1 s no cargo, rustc or build script of the check was left, including the rustc processes the shared sccache server had started for it. `check_selftest.py` does the same with a stand-in group. One gap is left: a SIGKILL between starting a cargo and registering it (microseconds) is covered only by `PR_SET_PDEATHSIG`, so on macOS that cargo would be left running.

A failure of the check itself (a full disk while writing a log, say) fails the step. Every planned step must end skipped, passed or failed, so a crash is never reported as a pass. With `CARGO_BUILD_JOBS` at or under the number of lanes, the steps run one by one. The jobserver caps compile jobs, not the threads of the rules tests while they run (libtest uses all cores).

`just living-check-full` (or `LIVING_CHECK_FULL=1`) runs every step and ignores stamps; it still writes them. `python3 living/tools/check.py --plan` prints what would run or be skipped, and why. `--steps a,b` runs some steps. Every run is appended to `~/.cache/slop-check/runs.jsonl` with each step's time, the load average, the wrapper used and the cache stats. `python3 living/tools/check_selftest.py` checks the wrapper choice, the watchdog and the gate step's keying and judging (22 checks, about 2 s), building nothing. `--gate` adds four checks that build and run the gate step in a clone (below). `--plan --json PATH` writes each step's digest, inputs and whether its stamp applies.

### The script fuel gate

The `script-gate` step fails the check when a hot Rhai law takes more fuel (WASM instructions) per call than [budgets.json](../living/tools/script_bench/budgets.json) allows. The laws and the budgets' history are in the [living core](LIVING_CORE.md) ("Fuel budgets"). It builds the bench module (living-rules' `Scripts` over `living/scripts/skills.rhai`, as the authority calls it) and `sb-host`: wasmtime 39.0.1, configured as SpacetimeDB 2.14.1 runs reducers. `gate.py` then runs the host with fixed counts (`--calls 64`) under eight fixed sets of Rhai hashing keys (`--seeds 8`). That makes the fuel a function of the code and the fixtures only, the same on every run and every machine. Since `det-1`, `gate.py` judges each law's fuel under key set 0, which is the seed the rules fix for every engine of the game (`living_rules::script::HASHING_SEED`, [living core](LIVING_CORE.md#one-hashing-seed)): the cost the game pays. The mean and range over the eight sets are printed as a diagnostic of how much of a law's fuel is where its entries land. Before `det-1` it judged the mean.

- **Inputs** (the step's digest; the audit checks the dep-info against them as for the other steps): the shipped script and seeds (`living/scripts`, `living/seeds`, shared); the rules crate; the bench crates (`bench`, with its fixtures and `port.rs`, `module`, and `host`, whose `main.rs` holds wasmtime's configuration); the bench's `Cargo.toml` and `Cargo.lock` (wasmtime's `=39.0.1` pin and every crate's locked version, Rhai's included); `budgets.json` and `gate.py`; and the toolchain and build environment, as for every step. The bench's README, `run.sh`, its other engines' scripts and its results are not inputs. On its first run the audit found `port.rs`, which `bench/src/native.rs` includes.
- **A failure** prints `script-gate: FAILED`, then one line per law over budget: `perceived takes 73,068 fuel a call, over its budget of 70,000 (living/tools/script_bench/budgets.json)`. The step's log holds gate.py's table: every law's fuel under the game's keys, its budget, the eight key sets' mean and range and the time per call on this machine. The raw lines are in `<target>/script-bench/living-check-gate/`. A failing step writes no stamp.
- **By hand:** `just living-script-gate` runs the step alone, whatever its stamp says (`check.py --steps script-gate --full`). [gate.sh](../living/tools/script_bench/gate.sh) runs the same builds and `gate.py` with any `CARGO_TARGET_DIR` and keeps the module and the raw lines in `OUT`, for evidence.
- **Cost** (dev-box, `CARGO_BUILD_JOBS=12`, 2026-11-11, the step alone, `--json` records in the run): cold, a new target folder with the shared compile cache warm from other worktrees, **204 s** at load average 59–64 from other workers (89 cache hits, 177 misses, 111 not cacheable). The gate run itself is about 2 s: eight instances, 4 batches of 64 calls per law. Warm, nothing to rebuild and no stamp, **3 s**. Stamped, **0.18 s** (skipped). Its target folder takes 0.9 GB. In a whole check it runs in its own lane, beside the other three.
- **Self-test:** `check_selftest.py` checks it in a clone of the worktree, with its uncommitted files. An empty stamp store runs the step; a stamp at its digest skips it. An edited script, `budgets.json` or `host/src/main.rs` runs it again; an edited README does not. Over a stand-in bench, `gate.py` passes laws within budget, and fails a law over budget (naming the law, its fuel and its budget) or a budgeted law not measured. `check_selftest.py --gate` also runs the real step there (`CHECK_SELFTEST_TARGET` sets its target folder). It passes and is stamped, is skipped on a second run, fails the check with that message under a budget of 1,000 for `rates-law`, and runs and passes again after an edit to the script: 57 s with a warm target folder.

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
4a. **Checks that the bindings were regenerated.** This runs when the merge touches the module's shape: `living/authority`, `living/rules`, `living/bindings`, or the workspace's `Cargo.toml` or `Cargo.lock`.
    - **What it does:** runs `just living-generate` on the checked tree and fails the merge when `git status --porcelain living/bindings` then shows a change. The check already built the module, so cargo rebuilds nothing when it is current.
    - **On a diff:** the summary names the files ("bindings not regenerated: living/bindings/src/generated/fight_seen.rs, …"). The worktree and HEAD are restored and nothing is pushed (exit 11).
    - **On a generator failure** (its container down, say): "bindings check could not run", also exit 11, never a silent pass.
    - **Skipped:** docs, client and tool merges skip it. `LIVING_MERGE_BINDINGS=always` forces it, and `=off` skips it.
    - **Why:** battle-fold added the private table `fight_seen` and merged without regenerating. dev-box's cullet-sweep added it later. **This replaces the laptop's manual "regenerate and see no diff" check before a merge.**
    - **The generator** is `LIVING_GENERATE_CMD`, as in `generate_bindings.sh`. When it is unset and a container named `LIVING_GENERATE_CONTAINER` (default `slop-trials-stdb`, the Spark's) is running, the module is generated in that container ([`generate_in_container.sh`](../living/tools/generate_in_container.sh): copy the module in, `spacetime generate`, a tar stream out). Otherwise the Justfile's compose run is used.
5. Pushes the checked merge commit as a compare-and-swap: `git push --force-with-lease=refs/heads/main:<base> origin <merge>:refs/heads/main`. It lands only while `main` is still exactly the commit that was merged onto and checked, so it never lands on a `main` that moved or was rewound meanwhile. When the push is refused and the remote `main` is no longer the base, the tool re-fetches, merges the same branch commit onto the new `main` and checks again; stamps skip the steps whose inputs the new `main` did not change. It tries up to `--retries` times (5; exit 7 after). If the branch was merged by someone else meanwhile, it stops with nothing to push (exit 0). Any other push failure stops (exit 8) with the checked merge left in HEAD, and any other git failure stops with the summary (exit 9).
6. Prints every git command it ran and a summary. The check's output is also kept in `~/.local/state/slop-merge/<time>-<branch>.log`.

`--no-push` stops after a passing check. `python3 living/tools/merge_selftest.py` drives all of this against a throwaway remote (24 checks):
- the dirty-worktree, local-commit, conflict, failing-check and dirtying-check refusals;
- a failing and a passing scene gate (a stand-in command);
- a `main` that moves during the check, and one rewound during the check;
- a branch merged by someone else meanwhile, an unknown branch, and a clean merge;
- the bindings check with a stand-in generator: bindings that change fail and are named, a failing generator fails, unchanged bindings pass, and a docs-only merge skips it.

### The scene gate

`just living-merge <branch> --scenes` (or `LIVING_MERGE_SCENES=1`) runs the scene gate, [`scene_gate.py`](../living/tools/scene_gate.py), after a passing check and before the push. `just living-check` builds and runs cargo tests only; no scene runs against a live authority, so `fix-place-free` (e3f0527f) merged green while verify-minds `dealings` and verify-player's combat staging went red on main. When the merge's diff against `main` touches behaviour (`living/authority`, `rules`, `scripts`, `mind`, `seeds`, `configs`, `bindings`, the workspace manifest or lock, or the drivers the gate runs), the gate runs real scenes with the fake model on scratch `verify-gate-*` databases: verify-core `tick`, `sight`, `senses`, `refusal` (one default-seed world) and `skirmish` (island), verify-minds `roundtrip`, `acts`, `dealings`, `conversation` (each its own world, the real `living-mind`), verify-player `combat` (`--scene all`, island), and `mind-unit`, living-mind's cargo tests (the check builds the mind but tests only `living-rules`). The four worlds and the tests run at once. Client, viewer, docs, other tools and verify-ui changes skip it in under a second. A failing case runs again once, alone, on a fresh world; the gate fails only on a case that fails twice and passes on `main` (the merge's first parent, run in its own checkout, `~/.local/state/slop-merge/scene-gate/main`, built in `main-target` beside it). A case that also fails on `main` is reported as red on main too, does not block, and stays on the red-on-main list until it passes on main. The list is in git, so every machine's gate shares it: the branch `red-on-main` (one file, `red-on-main.json`; never merged into main) is fetched before every gate command and written by commits pushed without force, fetched and retried when another writer got there first; the local file (`LIVING_GATE_REDS`, `~/slop-mq/red-on-main.json` on the Spark) is a cache, read only when the fetch fails, which the gate says ([`scene_gate_selftest.py`](../living/tools/scene_gate_selftest.py): an add on one clone seen on another and back, eight racing writers on two clones, the fallback); every gate run prints the list and `just living-scene-gate reds` prints it alone (the daily digest). `reds --add CASE --skill S --who OWNER --reason WHY` lists a known red by hand, `reds --drop CASE` removes one, and `recheck` runs every listed case it can (the gate's own and any verify-minds case) on `origin/main`, dropping the green ones. A listed part of a case, a mind test `living-mind::<test>` or a combat scene `combat:<scene>`, is reported when it fails but does not fail its case; such parts are dropped by hand. A failed gate restores HEAD and pushes nothing (exit 10). When `main` moved and the merge is redone, the gate runs again only if the new `main` commits touch behaviour. It uses the Spark's trial server by default (`slop-trials-stdb`, `http://127.0.0.1:3320`; `LIVING_GATE_STDB_CONTAINER`, `LIVING_GATE_STDB_URL`), never Neo4j, and deletes its databases in every case. See the verify skill's "Scene gate" for the case list, flakes and evidence.

Measured on the Spark on 2026-11-12, load average 75–105 on 20 cores, private `CARGO_TARGET_DIR`: the scenes' first pass takes 199–284 s, with the four worlds at once. A case failing once adds its retry (45–85 s). A case failing twice also adds main's run of it: 21–302 s, the most when main's checkout builds cold. Whole gates: 265 s when `sight` was broken, and 753 s on a main where `dealings` was red (a cold main build). A real `living-merge --scenes --no-push` of a behavioural branch took 1263 s: the check 993 s, the scenes 265 s, git about 5 s. A push adds seconds. A docs-only merge skips the gate in 0.1 s.

## Disk

[`disk_clean.py`](../living/tools/disk_clean.py) carries out this policy. Without `--apply` it is a dry run that prints the same report. The timer runs it every 30 minutes with `--apply`.

**May be removed:** Cargo target folders inside the git worktrees of this repository. A Cargo target folder is one Cargo tagged with `CACHEDIR.TAG`, or one holding Cargo's `.rustc_info.json` beside tagged or locked build directories. Cargo leaves the root of a `CARGO_TARGET_DIR` untagged when the folder already existed. Nothing else may be removed. A folder goes when all of these hold:

- **Nothing uses it.** No process has its working directory, executable, open files or mapped files inside it (`/proc` on Linux, `lsof` on macOS; if `lsof` fails, every folder counts as in use). No Podman or Docker container mounts it, its worktree, or anything inside; stopped containers count too. A container tool that does not answer makes every folder count as mounted. One that answers with an error (no daemon running) is reported as a warning: nothing of it runs, but its stopped containers' mounts are unknown. It is only a note when the other tool answered, or when podman fails because it has no machine (macOS: `podman machine list` is empty), so it has no containers. No Cargo lock in it is held. It holds no other mounted filesystem.
- **One of three rules fits:**
  - **merged:** the worktree's HEAD is in `origin/main` but not on `main`'s own first-parent line, the worktree has no uncommitted or untracked changes outside `.local/`, and the folder has been idle 2 hours. The first-parent condition means the worktree had a branch of its own that was merged. A fresh worktree started from `main`, or a coordinator whose merges are `main`, stays under the 24-hour rule, so a coordinator keeps its warm merge build;
  - **idle:** the folder and the worktree's git state (index, HEAD log) have been idle 24 hours;
  - **pressure:** free space is under the floor plus 30 GB and the folder has been idle 2 hours. These go oldest first, and only until free space reaches the floor plus 30 GB.

**Free-space floor:**

| Machine | Floor | Target (floor + 30 GB, about one cold check build) |
| --- | --- | --- |
| dev-box | 40 GB | 70 GB |
| Spark | 60 GB proposed (`--floor-gb 60`): its paid trial servers write to the same disk, and several agents build cold at once | 90 GB |
| laptop | 40 GB (the default; set `--floor-gb` when installing) | 70 GB |

When the folders that may go are gone and free space is still under the floor, the report says so (exit 3), and the list shows what holds the rest.

**Never touched:**

- the owner's checkouts `~/dev/slop-art-online`, `~/dev/slop-game`, `~/dev/slop-floors`, `~/dev/slop-ab-arm1` and `~/dev/slop-ab-arm2`, and everything under them (their build folders are listed as `never`);
- `~/archive`;
- container storage, Docker and Podman volumes (never pruned) and the databases in them. `living/tools/reclaim_disk.sh`, which deletes idle SpacetimeDB replicas, stays a manual tool: the paused reference worlds are idle replicas;
- containers: none is restarted, stopped, signalled or pruned by the timer. The only container actions are Docker Desktop's VM trim and the restart an operator names with `--restart-stdb` (below);
- `.local` evidence that is not a build folder;
- worktree roots, symlinks, and anything outside this repository's worktrees, except the outside target folders a machine names (below);
- each machine's own protected paths (below).

**The machine's protected paths.** Each machine lists its own in `~/.config/slop-disk/protect.txt`: one path per line, `~` expanded, `#` starting a comment (a whole line, or after a space). A path protects everything under it, and a build folder that holds it is not removed either. `--protect PATH` (repeatable) adds more for one run. These add to the built-in list above; nothing can remove a built-in path. Every run reads the file, the timer's included, so an edit applies from the next run. A missing file adds nothing. A file that cannot be read, or a line that is not an absolute path, stops the run with exit 2, and nothing is removed. Every report, and `--list-protected`, lists each protected path with its source: `built in`, `the repository's main checkout`, the file and line, or `--protect`. A protected worktree's build folders are listed as `never` with the path that protects them. Example (the laptop):

```text
# never touch these on this machine
~/dev/slop-trials     # 14 GB, the trials
~/dev/slop-play       # 2.5 GB, the play-tests
```

A line with `*`, `?` or `[` is a glob, expanded on every run and listed once per match with its line (`~/.t3/worktrees/*/*/.local/living`, say, where verify runs build inside their evidence). A glob that matches nothing protects nothing.

**Target folders outside the worktrees.** A machine whose agents build in private `CARGO_TARGET_DIR`s outside the worktrees (the Spark's `~/slop-<name>-target`, 16–24 GB each) names them in `~/.config/slop-disk/targets.txt` (`--targets-file`), in the same format. Without the file, no folder outside the worktrees is a candidate. A named folder must be a Cargo target. No worktree goes with it, so the in-use checks and the idle (24 hours) and pressure rules apply, never the merged rule, and the protected paths still win. Reports list them as `(outside the worktrees)`, and `--list-protected` prints them after the protected paths.

**A target folder that holds other files** (a worker's `build.log` in its target root, say) keeps them. Only Cargo's own entries are removed (`debug`, `release`, the target-triple and profile folders, `.rustc_info.json`, `CACHEDIR.TAG`, `cargo-timings`), and the folder and the other files stay. A nested repository (a folder with its own `.git`) is not entered.

**Sizes and reflinks.** `du` and plain block counts count a reflink copy's shared blocks in every copy (`cp --reflink` on the dev-box's XFS, clones on APFS). Two copies of one 14 GB target therefore show as 28 GB, and deleting one of them frees almost nothing. For the folders it would remove, the report counts only the blocks no other file shares, and notes the shared part:

- **Linux:** `FIEMAP`, counting the extents not marked `FIEMAP_EXTENT_SHARED`.
- **macOS:** `getattrlist` with `ATTR_CMNEXT_PRIVATESIZE`. APFS keeps this for every file, and no root is needed: it is the bytes no clone shares, which is what deleting the file frees. `fcntl F_LOG2PHYS_EXT` was not used, because it maps one file's blocks. Telling whether another file shares them would mean mapping every file on the volume.
- **Neither works** (another filesystem, an older macOS, tmpfs): the folder's blocks are counted in full, and the row says "all blocks counted: clones unknown".

The report's `sizes:` line says which method was used. Whatever the method, the pressure tier no longer trusts the sizes when it is applied. The dry run projects free space from them. An applied run measures free space before each pressure removal, oldest first, and stops once it reaches the target, so a size that over-counts never leaves free space short and one that under-counts never removes extra folders. "Freed" is always the measured change in free space. On macOS, a local Time Machine snapshot holds deleted blocks until it is thinned, so a removal can free less than its size. The pressure tier then keeps going down the list, as the policy says.

**Known limit on macOS.** Without Full Disk Access, `lsof` cannot see the open files of root's processes and of system processes (Spotlight's `mds`, say). A build is still seen, because cargo, rustc and the game run as the user. A system process holding a file inside a build folder could be missed. The removal would then delete the file under it, which harms neither the process nor the build. The laptop does not grant Full Disk Access, and this limit stands.

**SpacetimeDB servers: deleted files held open and deleted databases' directories (every machine).** SpacetimeDB 2.14.1 never removes a deleted database's replica directory. `on_delete_replica` in `crates/standalone/src/lib.rs` (tag `v2.14.1`) says it "will just drop them from memory, but will not remove them from disk"; [TRIAL_DISK.md](TRIAL_DISK.md) records the source and documentation check. The Spark tested a scratch 2.14.1 server on 2026-11-13 (evidence: `~/slop-evidence/stdb-delete-fds-20261113.tar.zst` on the Spark):
- `spacetime delete` closes the database's `db.lock` and module log, but its commitlog segment (`clog/….stdb.log`) stays open.
- Pausing first, publishing another database, waiting and SIGHUP do not release it. Only a process restart does.
- A directory removed while the server runs frees nothing until the restart. That is how the laptop held 99 deleted files (19 GB) on 2026-11-13.

The dev-box shows the same: on 2026-11-13, `sex1-stdb` held 26 replica directories' segments open, and only one also had its `db.lock` and module log open. Every report has a `containers` section that reads each running SpacetimeDB server (a `spacetimedb-standalone`, or the `spacetime start` that runs it) and names its container and pid:
- **Deleted files it holds open:** their count, their allocated size, and the three biggest paths. Memfds (the wasm memory images) and files that still exist are left out.
- **Live databases:** the replica directories whose `db.lock` or module log it holds open.
- **Deleted databases' directories still on disk:** every other replica directory not written in the last 15 minutes, with their size. A directory written in the last 15 minutes counts as live, since a world may be starting.
- **Clients connected:** established TCP connections to its listening port.

How it reads them:
- **Linux** reads the host's `/proc`, and a server outside any container is reported as "on the host". Rootless podman runs the server as a sub-uid whose `fd` folder the user cannot list. Those servers are probed again under `podman unshare`, which runs as the root of the user's namespace and joins no container.
- **Docker** run as root on Linux cannot be read without root, and the report says so. This was not tried on the Spark, whose trial server runs under Docker: its first dry run will show which.
- **macOS** runs this script's own probe inside Docker Desktop's VM: `docker run --rm --privileged --pid=host -i python:3.12-alpine python3 - --probe /proc --vm`, with the script on stdin. It reads the VM's `/proc` and the VM's `/var/lib` (`statvfs` of pid 1's root).

The report needs only `ps`, `inspect` and that probe. A line such as "spacetimedb in sex1-stdb (podman, pid 959577): 2 live databases, 1 client connected / 17 directories of deleted databases still on disk (968 MB)" ends with the command that would free them. For a server this tool never restarts (below), the line says so instead and names the manual route: a stop, the removal and a start at a quiet moment, with the owner's approval. On the laptop that server, `sao-living_spacetimedb_1`, holds the play and reference worlds and every scratch world, so its deleted databases' directories are freed only that way.

**The quiet restart (`--apply --restart-stdb NAME`).** It is never automatic: the timer never passes it. It restarts only the named container: SIGINT (`kill -s INT`, as we stop servers by hand), then it waits up to 180 s for the container to stop. It removes the deleted databases' directories with the server stopped (`run --rm -v <its data volume>:/data alpine rm -rf -- /data/…/replicas/<id>`, each directory named), starts the container, and checks the kept databases. It pauses no world and never uses `--force` or any other signal. It refuses, before stopping anything, when any of these holds, and says which:
- the name is the reference worlds' server (`sao-living_spacetimedb_1`, `sao-living-spacetimedb-1`), is in `~/.config/slop-disk/never-restart.txt`, or the container mounts a protected path;
- the container is not running, or no SpacetimeDB server runs in it;
- a merge or the scene gate holds a lock: `~/.local/state/slop-build/gate.lock` or any `~/.local/state/slop-merge/*.lock`, each tested with a non-blocking `flock`. An unreadable lock counts as held;
- **a client is connected**: an established TCP connection to the server's listening port inside its network namespace. That covers a play session, a game client, a mind service, an observer and a trial runner mid-call. If its connections cannot be read, it refuses;
- **a host process names the published port** (`:3341` or `--port 3341`) in its command line or, for this user's processes, its environment: a mind service or trial runner between connections. Port forwarders (pasta, rootlessport, conmon, Docker's proxies) are not counted. On macOS, `ps` and `lsof -iTCP:<port> -sTCP:ESTABLISHED` are used instead;
- `spacetime list` (the container CLI's identity) fails or lists a reference world (`aske-coast*`, `stage*`);
- the server hosts more databases (open `db.lock`s) than are known by name. Databases the verify harness publishes under its own identity are not listed; name each with `--stdb-db NAME` (repeatable), so it can be checked afterwards;
- a known database does not answer `SELECT paused FROM world` before the restart, so it could not be confirmed after;
- **its deleted databases' directories are run evidence:** `slop-trials-stdb` (built in, [TRIAL_DISK.md](TRIAL_DISK.md): paid and no-model commitlogs are archived before any removal; runs up to 2026-11-12 are archived on the Spark in `~/slop-evidence/commitlogs-20261112/`, later ones are not yet, so the exception stays) or a name in `~/.config/slop-disk/stdb-keep-dirs.txt`. `--keep-dirs` then restarts without removing any directory, which still frees the deleted files held open;
- the data directory is on no volume or bind mount, so its directories cannot be removed while the container is stopped.

After the start, it asks every known database `SELECT paused FROM world` for up to 600 s, and reports any that does not answer or whose paused state changed (exit 4). It also reports free space before and after. On macOS, Docker Desktop's VM is trimmed right after, whatever the free space and the back-off. If the container does not stop within 180 s, it is not forced: nothing is removed, it is not started, and the report says to look at it. If a removal fails, the container is started again. Without `--apply`, it runs every check and prints what it would do. With `--containers-only`, it prints only the container section and changes nothing, and the same holds for a restart named there.

Removing a deleted database's directory is irreversible: its commitlog is that world's whole record ([TRIAL_DISK.md](TRIAL_DISK.md)). Run the restart on servers that hold scratch databases, at a quiet moment, and keep the trial server's procedure for evidence.

**Docker Desktop's VM disk (macOS only).** Docker Desktop keeps its containers in a VM whose disk is one sparse file, `Docker.raw`. Space freed inside the VM (a removed replica directory, a deleted image) goes back to macOS only when the VM's filesystem is trimmed. On 2026-11-13 the laptop lost 170 GB in two hours this way (204 → 34 GB, `Docker.raw` at 62 GB allocated). At 02:36 the VM disk filled and went read-only, and SpacetimeDB stopped. On macOS the report shows:
- **`Docker.raw`'s allocated size** (its blocks on disk, as `du -k` counts them, not its apparent size). It is found at `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`, another `vms/*`, a custom location in Docker Desktop's settings, or `--docker-raw PATH`;
- **the VM's `/var/lib`:** used, size and free.

With `--apply`, when free space on the volume holding `Docker.raw` (the startup disk's APFS container, so the same as `/`) is under the floor plus `--trim-margin-gb` (10 GB; 50 GB on the laptop's floor of 40), and Docker Desktop is running, it runs `docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -u -i -n fstrim /var/lib`. That is safe online. It trims at most once a run and waits 5 s, then measures free space and `Docker.raw` again. Each trim is recorded in `~/.local/state/slop-disk/vm-trim.json`. A trim that failed, or freed under 1 GB, blocks the next for an hour. A dry run says it would trim. A failing trim is reported, and the report goes on. `~/Library/Containers` stays on the never-delete list: only its size is read. On Linux the report says the VM part is skipped: containers write to the host's disk directly.

**The macOS part was tested only with fakes.** No macOS run exists: the Docker Desktop probe, `Docker.raw` detection, the trim and the restart through Docker were all exercised against fake `docker`, `ps` and `lsof` and a fake `/proc` on Linux. The laptop must run a dry run on real hardware first (Adoption, below).

**How a removal happens.** Just before each removal the script looks again at the processes and containers. It takes every Cargo lock in the folder without waiting, renames the folder aside (`<folder>.slop-reclaim-<time>`), checks again that no process uses it, and deletes it. If a check fails, it renames the folder back. An aside folder left by an interrupted run is removed on a later run. `python3 living/tools/disk_clean_selftest.py` runs the policy in a throwaway home with aged fake targets (78 checks). It covers a merged worktree, a busy one, a fresh one, an old one holding a log, protected checkouts, untagged evidence, a foreign tag, a symlink and a nested repository. It also covers worktrees protected by the protect file and by `--protect`, a target holding a protected path, an invalid protect file, a file newer than the scan (idle 0.0 h, never negative), the measured pressure tier, the container notes (podman with no machine; docker answering), a protect-file glob, and outside target folders (idle, protected by a glob, active, busy, not Cargo's, and no `targets.txt`). The container part runs against a fake `/proc` and fake `podman`, `docker`, `ps` and `lsof`:
- **the report:** deleted files held open (deduplicated; memfds, live files and other programs left out), a server under its container's init, an unreadable `fd` folder read through `podman unshare`, without podman said and not guessed, a host server, a failing podman, deleted databases' directories apart from the live one and one written in the last 15 minutes;
- **the VM:** `Docker.raw`'s allocated size, the VM's `/var/lib`, the probe run as the VM would run it, the trim (dry run, applied once with free space before and after, back-off after a small or failed trim, failure reported, not needed, Docker not running), a missing `--docker-raw`, and Linux skipping it;
- **the restart, every refusal:** the reference worlds' server, `never-restart.txt`, a container not running, a held `gate.lock` and a held merge lock, a connected client, unreadable connections, a host process naming the port in its command line and in its environment, an `lsof` connection on macOS, a failing `spacetime list`, a reference world, an unnamed hosted database, a database not answering SQL, an evidence server without `--keep-dirs`;
- **the restart, its runs:** the dry run, `--keep-dirs`, a stop that hangs (not forced, nothing removed, not started), a failing removal (started anyway), a paused state that changed, the full restart (exactly the deleted databases' directories removed), and the restart on macOS followed by a trim;
- **the calls:** the fakes log every call. The report asks only `ps`, `inspect`, `info` and the probe, and the restart adds only `kill -s INT`, `exec … spacetime list|sql`, the `rm` of the listed directories and `start`. There is never `--force`, `stop`, `restart`, `prune` or another signal. Reports go to `~/.local/state/slop-disk/reports/` and `log.jsonl`, and on Linux also to the journal (`journalctl --user -u slop-disk-clean.service`).

**Install** (re-run after `disk_clean.py` changes; it copies the script to `~/.local/share/slop-tools/`, so removing a worktree never breaks the timer). The installer reads `~/.config/slop-disk/protect.txt` the way the timer will and prints every protected path. If the file is invalid, it stops before installing. When there is no file, it writes a template that holds only comments.

```bash
living/tools/disk_clean_install.sh --floor-gb 40          # Linux: systemd user timer slop-disk-clean.timer
living/tools/disk_clean_install.sh --floor-gb 40 --trim-margin-gb 10   # macOS; --docker-raw PATH if it is not found
living/tools/disk_clean_install.sh --uninstall
```

On Linux the timer runs without a login when lingering is on (`loginctl enable-linger`). The Linux timer runs on a calendar schedule (`OnCalendar=*:0/30` for the default 30 minutes) and the installer warns when the timer has no next trigger. The earlier `OnUnitActiveSec` form counted from the service's last run, so a timer stopped and restarted after that moment had passed showed `elapsed` and never fired again (seen on the Spark, 2026-11-12). An interval that does not divide an hour keeps that form, with `OnActiveSec=1min` so a restart always schedules a first run. On macOS the same command writes and loads the launchd agent `~/Library/LaunchAgents/dev.slop.disk-clean.plist` (every 30 minutes, log in `~/.local/state/slop-disk/launchd.log`). Full Disk Access is optional; see the known limit above.

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

## Measurements (Spark, 2026-11-11)

The DGX Spark: aarch64, 20 cores, `CARGO_BUILD_JOBS` unset (20), with paid trial batches and other agents building throughout. Every run was `check.py` on the same commit (`e56c203`, tool-7) in one fresh worktree, each with a fresh target folder and its own stamp store. The cache had its own folder and port. The raw records (`check.py --json`, logs) are in `~/slop-mq/sccache-bench-20261111/` on the Spark.

| Case | Wall | Load at start → end (peak) | Steps: authority, mind+viewer, game, viewer-wasm, rules tests | sccache |
| --- | --- | --- | --- | --- |
| a: cold, no cache | 509 s | 11 → 25 | 156, 285, 280, 312, 219 | none |
| b: cold, empty cache | 436 s | 15 → 34 | 71, 218, 282, 168, 215 | 2 hits, 1,480 misses, 393 not cacheable |
| c: cold target, warm cache | 638 s | 34 → 40 (49) | 112, 334, 487, 324, 299 | 1,068 hits, 414 misses, 393 not cacheable |
| c2: the same again | 582 s | 33 → 37 (49) | 147, 324, 358, 246, 254 | 1,068 hits, 414 misses, 392 not cacheable |
| d: c rerun unchanged | 0.6 s | 40 | all five skipped by stamps | – |

On aarch64, sccache behaved as it did on the dev-box: the pinned musl build ran, and with a warm cache it served the same 56% of compile requests (1,068 of 1,909). It showed no gain in wall time here. The warm-cache runs ran under about twice the uncached run's load. The steps it cannot serve also set the length of each lane: the game crate and its link, the debug workspace crates, and the rules test run, 200–300 s under this load. A second uncached run, to interleave the arms, was not started: free space had fallen to 47 GB. The cache held 3.8 GB afterwards. Stamps made the unchanged rerun take under a second, and a docs-only merge through `living-merge` too, because the coordinator's merge of `main` had already stamped every step.

## Adoption

Every part arrives with `main` once `tool-7` is merged; `just living-check` keeps its name and its five steps. Each machine then does the following.

**All three machines.**
- Merge with `just living-merge <branch> -m "Merge <branch>: …"` from the coordinator worktree instead of the four hand steps. It runs the check, pushes, and on a moved `main` merges and checks again by itself.
- Stamps are per machine. A merge skips the steps that a worker on the same machine checked on identical inputs with the new check. A branch checked on another machine runs in full, as before.
- Keep 40 GB free before a cold check (about 15 GB of target and up to 10 GB of compile cache over time).

**dev-box** (done on 2026-11-11): `install_sccache.sh` ran (v0.19.0), the timer is installed (`disk_clean_install.sh --floor-gb 40`), and lingering is on.

**Spark** (aarch64 Linux, its coordinator):
1. `living/tools/install_sccache.sh` (the pinned aarch64 musl build) works on the Spark. It puts sccache where every check on the machine finds it, so installing it turns on the cache for every agent's check at once. That is the coordinator's call; see "Measurements (Spark)". A bench passes `SLOP_SCCACHE=<private copy>` instead.
2. `living/tools/disk_clean_install.sh --floor-gb 60`, after a dry run `just living-disk-clean`. The Spark's `protect.txt` (evidence globs, labs, run checkouts and the running batches' targets) and `targets.txt` (`~/slop-*-target`) were written on 2026-11-11; check the dry run's list against them.
3. `loginctl show-user $USER -p Linger`; if it is `no`, run `loginctl enable-linger $USER` so the timer runs without a login.

**Laptop** (macOS, Apple silicon), after `tool-7b` is merged:
1. `living/tools/install_sccache.sh` (the pinned `aarch64-apple-darwin` build). Homebrew's sccache can stay on `PATH`: the check never uses it.
2. `just living-check` needs `python3` (Xcode command-line tools). The lanes use a fifo jobserver. Under `build-slot`, which pre-sets `RUSTC_WRAPPER` to `sccache-rustc`, the check now prints `compile cache: … through the pre-set RUSTC_WRAPPER=…` and records the stats. If it says "is not living/tools/sccache-rustc" instead, `build-slot` points at something else; report what it is. Run `python3 living/tools/check_selftest.py` once: it checks the wrapper choice and the watchdog on macOS (11 checks).
3. Disk, before installing anything:
   1. Write `~/.config/slop-disk/protect.txt` with the never-touch list, at least `~/dev/slop-trials` and `~/dev/slop-play`.
   2. Run `python3 living/tools/disk_clean_selftest.py`, which covers the getattrlist size path and the podman note on macOS.
   3. Run the dry run, `just living-disk-clean`. Check four things:
      - the `protected` list shows both paths with `protect.txt, line N`;
      - `slop-trials` and `slop-play` are listed as `never`;
      - the `sizes:` line says `asked with getattrlist ATTR_CMNEXT_PRIVATESIZE`. If it says `all blocks`, the attribute is not available: report it. Pressure removals are still measured one by one;
      - podman without a machine shows as a `note:`, not a `warning:`.
   4. Run `living/tools/disk_clean_install.sh --floor-gb <N>`. It prints the protected list again, then writes and loads the launchd agent. Later edits to `protect.txt` apply from the next run, with no reinstall.
   5. In-use detection uses `lsof`, without Full Disk Access (the known limit above). If `lsof` fails, nothing is removed.

   None of the macOS paths in `tool-7b` were run on macOS: the getattrlist sizes, the podman machine probe and the watchdog. They are reasoned from the documented interfaces, and the Linux runs cover the shared logic.
4. **Docker Desktop's VM and SpacetimeDB's held files (`disk-vm`).** All of the macOS part was tested only with fakes on Linux. Before relying on the timer:
   1. `python3 living/tools/disk_clean_selftest.py`: all 78 checks pass.
   2. `just living-disk-clean --containers-only`. It is read-only, and its first run pulls `python:3.12-alpine`. Check:
      - `Docker.raw` is found and shows its allocated size, about 62 GB now, not its apparent size. If it says "no Docker.raw found", find the file (Docker Desktop, Settings, Resources, Advanced, "Disk image location") and pass `--docker-raw PATH`;
      - the VM's `/var/lib` line shows a size and free space, not "unknown". If the probe fails, report its message;
      - each SpacetimeDB container is named with its live databases, clients and directories of deleted databases. The local server should show the overnight scratch databases' directories.
   3. `just living-disk-clean` (dry run): near the floor, it says "would trim /var/lib (dry run)" with the free space measured.
   4. Run the trim once by hand under watch: `python3 living/tools/disk_clean.py --apply --floor-gb 40 --trim-margin-gb 1000`, which forces the margin. Note free space before and after, and `Docker.raw`'s allocated size.
   5. Reinstall: `living/tools/disk_clean_install.sh --floor-gb 40` (the installed copy in `~/.local/share/slop-tools/` predates `disk-vm`). The launchd agent then trims near the floor on its own.
   6. The restart, at a quiet moment only: first a dry run, `python3 living/tools/disk_clean.py --containers-only --restart-stdb <container> [--stdb-db NAME]...`. Read every refusal and the plan. Then the same with `--apply` instead of `--containers-only`, and check its "started; N of N databases answer SQL" line and the trim after it. Never name the `sao-living` server; the tool refuses it anyway.
