# Tooling: the check, merges and disk

Status: **current** (Tool 7, 2026-11-11, branch `tool-7`; the laptop's follow-ups in `tool-7b`, the same day). Three machines (the laptop, the dev-box and the Spark) merge branches into `main`. Each merge runs `just living-check`, and each machine has several worktrees with their own Cargo target folders. Before Tool 7, every re-run of the check after `main` moved was a full rebuild, and build folders filled the disks three times in one day. Tool 7 has three parts, each built on our own scripts:

| Part | Command | Script |
| --- | --- | --- |
| The check | `just living-check` (`just living-check-full`) | [`living/tools/check.py`](../living/tools/check.py), [`sccache-rustc`](../living/tools/sccache-rustc), [`host_paths.py`](../living/tools/host_paths.py), [`install_sccache.sh`](../living/tools/install_sccache.sh), self-test [`check_selftest.py`](../living/tools/check_selftest.py) |
| Merging | `just living-merge <branch> -m "Merge <branch>: …"` | [`living/tools/merge.py`](../living/tools/merge.py), self-test [`merge_selftest.py`](../living/tools/merge_selftest.py) |
| Disk | `just living-disk-clean [--apply]`, on a timer | [`living/tools/disk_clean.py`](../living/tools/disk_clean.py), [`disk_clean_install.sh`](../living/tools/disk_clean_install.sh), self-test [`disk_clean_selftest.py`](../living/tools/disk_clean_selftest.py) |

[`check_timings.py`](../living/tools/check_timings.py) reads a cargo `--timings` report and splits the time between workspace crates, dependencies and build scripts.

### Known red self-tests

Tool self-tests that fail on `main`, each with its owner, the date and the reason. A self-test leaves this list in the change that makes it pass.

| Self-test | Owner | Since | Reason |
| --- | --- | --- | --- |

None since 2026-11-21. Branch `trials-laws-selftest` fixed the first entry, [`trials_laws_selftest.py`](../living/tools/trials_laws_selftest.py) (Spark, from 2026-11-21: 3 failures and 2 errors in `Publish`, because its `FakeDb` did not answer `genesis_wait` and the call reached the trial server's real port with a dummy token). Its fake now answers the `genesis` row. While `Publish` runs, every socket connect is refused and recorded, so a call that escapes the fake fails the test by name and never reaches a running service.

## The check

`just living-check` runs the five cargo commands of before and, since `tool-8`, the script fuel gate, since `check-game-tests` the game client's unit tests, and since `check-authority-tests` the authority's native unit tests (they replaced the seed-laws test of `fix-laws` and frame-views' frame tests), in [`check.py`](../living/tools/check.py):

| Step | Command | Lane |
| --- | --- | --- |
| `authority` | `cargo build -p living-authority --target wasm32-unknown-unknown --release` | release |
| `mind+viewer` | `cargo build -p living-mind -p living-viewer` | debug |
| `game` | `cargo build --release -p living-game` | release |
| `game-tests` | `cargo test --release -p living-game`: the client's unit tests on the game step's release tree, headless (no display, GPU or generated assets); names in `GAME_TEST_SKIPS` are skipped here by name (`--exact --skip`) and run by hand: none needs a display, and none is skipped now (fix-make-offer fixed the one known red test). The client reads the rules (`offered()`, the checks), and a rules change turned `verbs::tests::make_is_offered_at_a_furnace_only_while_it_burns_with_fuel` red on main (f0061a07) while the check only built the game (its fixture held no crucible, which goods-3's glass needs). Its stamp covers the game's closure, the rules included. Spark, 2026-11-12: 15 s on top of a built game tree, 0 s stamped | release |
| `authority-tests` | `cargo test --release -p living-authority --lib`: the authority's whole native lib suite ([below](#the-authoritys-tests)), on the release tree after the game; the names in `AUTHORITY_TEST_XFAIL` are known red, skipped in the suite and run alone, where each must still fail | release |
| `viewer-wasm` | `cargo build --manifest-path living/viewer/Cargo.toml --target wasm32-unknown-unknown --profile wasm-dev --bin living-viewer` | wasm-dev |
| `rules-tests` | `cargo test -p living-rules` | debug |
| `script-gate` | `cargo build --manifest-path living/tools/script_bench/Cargo.toml -p sb-module --target wasm32-unknown-unknown --release --features rhai`, then `-p sb-host --bin sb-host --release --no-default-features`, then [`gate.py`](../living/tools/script_bench/gate.py) ([below](#the-script-fuel-gate)) | script-bench |

Three things are new:

- **Disk space before building.** When any step needs to run, the check looks at free space on the filesystem holding Cargo's target directory (`CARGO_TARGET_DIR` or Cargo's configured target, normally `living/target`). Required free space is `SLOP_DISK_FLOOR_GB` (default 45) plus the charge of the steps that will run ([The disk charge](#the-disk-charge)): their measured cost, never more than the full charge, the greater of 2 GiB and the remaining cost (`SLOP_CHECK_COST_GB`, default 18, minus the space already occupied by the target tree). A fresh tree running every step needs 63 GiB by default; a check that runs only the script bench needs 46. `SLOP_CHECK_START_GB` overrides the total and `0` disables the guard. All three settings are whole GiB. Below the threshold, the check reports free space and how it calculated the threshold, lists up to six of the largest build trees under `~/.t3/worktrees/*/*/living/target` and `~/.t3/worktrees/*/*/.local/*/target`, then polls free space every 60 seconds. Waiting never deletes files. Plans and runs fully served by stamps skip the disk check.
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
| a copy of `sccache-rustc` whose bytes differ from this checkout's (an older copy a `build-slot` pre-sets, say) | Runs this checkout's `living/tools/sccache-rustc` in its place, with the caller's cache settings, and says so in the `compile cache:` line (refresh the copy). A copy from before `wasm-remap-sccache` loses wasm compiles' path remapping ([Byte-identical wasm](#byte-identical-wasm)). |
| a plain `sccache` | Left as it is, with its own settings; no cache line or stats. Not part of the digest, as sccache does not change outputs. |
| anything else | Left as it is: cargo runs it, without this check's cache settings or stats. It enters every step's digest, so stamps made with it apply only with it. (This was the behaviour for every pre-set wrapper before `tool-7b`.) |

**Failed compiles in the sccache stats.** A passing check whose build scripts ran shows a few "compilation failures" (`failed` in the stats). They are build scripts' feature probes, compiled through `RUSTC_WRAPPER` and meant to fail on stable Rust. On 2026-11-11 the four were `anyhow` (`src/nightly.rs`, `error_generic_member_access`), `thiserror` 1.0.69 and 2.0.21 (`build/probe.rs`, `error_generic_member_access`) and `proc-macro2` (`src/probe/proc_macro_span.rs`, `proc_macro_span`). Each fails with E0554, "`#![feature]` may not be used on the stable release channel", so the crate uses its stable code. They were found by building those crates through a private sccache server with debug logging. sccache does not cache failures, so each build that re-runs those build scripts counts them again. A warm build that does not re-run them counts none. They are not ours to fix, and fixing them would change nothing.

**Stopping its children.** Each cargo runs in a process group of its own, so an interrupted check stops rustc, build scripts and test binaries with it. A SIGINT or SIGTERM stops them directly. For a check that is killed outright, the check also starts a small watchdog process in a session of its own. The watchdog reads a pipe that only the check holds open, and the check registers each cargo's process group on it, along with its jobserver folder. When the check exits in any way, a SIGKILL included, the kernel closes the pipe. The watchdog then sends each group still registered SIGTERM, then SIGKILL after 10 s, and removes the folder. This relies only on POSIX pipes and process groups, so it works the same on macOS, where `PR_SET_PDEATHSIG` does not exist. On Linux, `PR_SET_PDEATHSIG` stays as a second guard. Tested on the dev-box: a `check.py --full` was SIGKILLed mid-build (3 cargos, 10–11 rustc), once with `PR_SET_PDEATHSIG` on and once with it off. Within 1 s no cargo, rustc or build script of the check was left, including the rustc processes the shared sccache server had started for it. `check_selftest.py` does the same with a stand-in group. One gap is left: a SIGKILL between starting a cargo and registering it (microseconds) is covered only by `PR_SET_PDEATHSIG`, so on macOS that cargo would be left running.

A failure of the check itself (a full disk while writing a log, say) fails the step. Every planned step must end skipped, passed or failed, so a crash is never reported as a pass. With `CARGO_BUILD_JOBS` at or under the number of lanes, the steps run one by one. The jobserver caps compile jobs, not the threads of the rules tests while they run (libtest uses all cores).

`just living-check-full` (or `LIVING_CHECK_FULL=1`) runs every step and ignores stamps; it still writes them. `python3 living/tools/check.py --plan` prints what would run or be skipped, and why. `--steps a,b` runs some steps. Every run is appended to `~/.cache/slop-check/runs.jsonl` with each step's time, the load average, the wrapper used and the cache stats. `python3 living/tools/check_selftest.py` checks the disk guard, wrapper choice, watchdog, the gate step's keying and judging, and the authority tests' step and its expected failures without building. `--gate` adds four checks that build and run the gate step in a clone (below). `--plan --json PATH` writes each step's digest, inputs and whether its stamp applies.

### The script fuel gate

The `script-gate` step fails the check when a hot Rhai law takes more fuel (WASM instructions) per call than [budgets.json](../living/tools/script_bench/budgets.json) allows. The laws and the budgets' history are in the [living core](LIVING_CORE.md) ("Fuel budgets"). It builds the bench module (living-rules' `Scripts` over `living/scripts/skills.rhai`, as the authority calls it) and `sb-host`: wasmtime 39.0.1, configured as SpacetimeDB 2.14.1 runs reducers. `gate.py` then runs the host with fixed counts (`--calls 64`) under eight fixed sets of Rhai hashing keys (`--seeds 8`). That makes the fuel a function of the code and the fixtures only, the same on every run and every machine. Since `det-1`, `gate.py` judges each law's fuel under key set 0, which is the seed the rules fix for every engine of the game (`living_rules::script::HASHING_SEED`, [living core](LIVING_CORE.md#one-hashing-seed)): the cost the game pays. The mean and range over the eight sets are printed as a diagnostic of how much of a law's fuel is where its entries land. Before `det-1` it judged the mean.

- **Inputs** (the step's digest; the audit checks the dep-info against them as for the other steps): the shipped script and seeds (`living/scripts`, `living/seeds`, shared); the rules crate; the bench crates (`bench`, with its fixtures and `port.rs`, `module`, and `host`, whose `main.rs` holds wasmtime's configuration); the bench's `Cargo.toml` and `Cargo.lock` (wasmtime's `=39.0.1` pin and every crate's locked version, Rhai's included); `budgets.json` and `gate.py`; and the toolchain and build environment, as for every step. The bench's README, `run.sh`, its other engines' scripts and its results are not inputs. On its first run the audit found `port.rs`, which `bench/src/native.rs` includes.
- **A failure** prints `script-gate: FAILED`, then one line per law over budget: `perceived takes 73,068 fuel a call, over its budget of 70,000 (living/tools/script_bench/budgets.json)`. The step's log holds gate.py's table: every law's fuel under the game's keys, its budget, the eight key sets' mean and range and the time per call on this machine. The raw lines are in `<target>/script-bench/living-check-gate/`. A failing step writes no stamp.
- **By hand:** `just living-script-gate` runs the step alone, whatever its stamp says (`check.py --steps script-gate --full`). [gate.sh](../living/tools/script_bench/gate.sh) runs the same builds and `gate.py` with any `CARGO_TARGET_DIR` and keeps the module and the raw lines in `OUT`, for evidence.
- **Cost** (dev-box, `CARGO_BUILD_JOBS=12`, 2026-11-11, the step alone, `--json` records in the run): cold, a new target folder with the shared compile cache warm from other worktrees, **204 s** at load average 59–64 from other workers (89 cache hits, 177 misses, 111 not cacheable). The gate run itself is about 2 s: eight instances, 4 batches of 64 calls per law. Warm, nothing to rebuild and no stamp, **3 s**. Stamped, **0.18 s** (skipped). Its target folder takes 0.9 GB. In a whole check it runs in its own lane, beside the other three.
- **Self-test:** `check_selftest.py` checks it in a clone of the worktree, with its uncommitted files. An empty stamp store runs the step; a stamp at its digest skips it. An edited script, `budgets.json` or `host/src/main.rs` runs it again; an edited README does not. Over a stand-in bench, `gate.py` passes laws within budget, and fails a law over budget (naming the law, its fuel and its budget) or a budgeted law not measured. `check_selftest.py --gate` also runs the real step there (`CHECK_SELFTEST_TARGET` sets its target folder). It passes and is stamped, is skipped on a second run, fails the check with that message under a budget of 1,000 for `rates-law`, and runs and passes again after an edit to the script: 57 s with a warm target folder.

### The authority's tests

The `authority-tests` step runs every unit test of `living-authority` natively (`--lib`: the crate is a WASM `cdylib` with no other targets), 44 on 2026-11-20. Before `check-authority-tests` the check ran two of them, as `seed-laws` (`seed::tests::a_seeds_laws_are_in_force_after_init`, fix-laws) and `frame-tests` (`frame::tests`, frame-views), and `look::tests::the_island_wears_the_pool` went red on main (07f37b927) without the check seeing it. Both old steps are folded into this one; their tests are in the suite.

- **Release, on the release lane.** On the Spark (2026-11-20, no compile cache, load 5) the suite builds in 27 s and runs in 72 s in debug, where `seed::tests::a_plan_naming_kinds_the_world_lacks_is_refused` composes Cullet's world six times; in release it builds in 32 s and runs in 10.5 s. The debug lane (`mind+viewer`, `rules-tests`) is the check's longest, so the step runs in release after `game` and `game-tests`, on their tree. Like `game-tests`, release runs without debug assertions or overflow checks; the authority has no `debug_assert` and no `should_panic` test. No test needs a server or is slow enough to leave out.
- **Inputs.** The authority's closure (the rules crate included) and the shared inputs. The tests read their fixtures with `include_str!`, which the audit sees, and one reads `living/seeds` at run time (`a_seeds_laws_are_in_force_after_init`), a shared input. The build script picks the compiled-in seed from `LIVING_SEED` (default `world`); the check leaves it as the caller set it, and it is in the digest.
- **Known red tests.** `AUTHORITY_TEST_XFAIL` in [`check.py`](../living/tools/check.py) lists tests known red on main whose fix is owned elsewhere, each with its owner, the date and the reason, so a data issue another machine owns does not block every merge. Each is skipped in the suite (`--exact --skip NAME`, so the list is in the step's digest) and then run alone (`--exact NAME`). The step passes only when it still fails. One that passes fails the step with `now PASSES: take it out of AUTHORITY_TEST_XFAIL` (the fix takes the entry out in the same change), and a name that matches no test fails it too. Every check prints each entry (`authority-tests: KNOWN RED, expected to fail: …`, with owner, date and reason) whether the step runs or is skipped, and its last line ends with `KNOWN RED (expected failure, owner …)`. The entry is also on the scene gate's red-on-main list. The list is empty since 2026-11-21. From 2026-11-20 it held `look::tests::the_island_wears_the_pool`: the island's look data was generation `c4-e61b01c0` while Cullet's `looks.json` was `c4-cbcc40bf`. Branch `island-looks` regenerated the island's pool from Cullet's data (`living/tools/pool_looks.py island --into island`), and the test passes.
- **Cost** (Spark, 2026-11-20, `CARGO_BUILD_JOBS=10` as the merge queue runs it, no compile cache on the Spark, through `~/slop-mq/build-slot`; the whole check with an empty target folder and stamp store, `--json` records). Cold, back to back at load 11–13: 587 s before (main 0c72eb39), 601 s with this step (+14 s). The step takes 43 s there, after the game; the release lane becomes the longest (authority 103 s, game 430 s, game-tests 21 s, authority-tests 43 s: 597 s), and the debug lane, without `seed-laws` (75 s), falls to 515 s. An earlier pair at uneven load read 588 s and 734 s (load 3–24 against 15–45; the game alone took 416 s and 544 s). Warm, one comment appended to `living/authority/src/geometry.rs`: 48 s before (`authority` 14 s beside `seed-laws` 47 s), 43 s with it (`authority` 16 s, then `authority-tests` 26 s, on the same lane). Stamped, 0 s. It adds 0.23 GB to the release tree and no longer builds the authority's debug test binary (74 units for `seed-laws`, 0.19 GB of test binaries).
- **Self-test:** `check_selftest.py` checks the step's shape: the whole suite in release on the release lane after the game, no test filter, every expected failure with an owner, a date and a reason, skipped exactly in the suite and run alone. It checks how a lone run is judged: still failing passes, passing, matching no test or never reaching the test fails. In a clone, the plan names every expected failure whether the step runs or is skipped, an edited authority source or seed runs the step again, and an edited doc does not.

### What a passing check still guarantees

A merge checked this way guarantees what it did before: every step of `living-check` has passed **on this machine**, with this toolchain and build environment, on inputs byte-identical to the merged tree's inputs for that step. A skipped step's result is the one it had when it ran; nothing is assumed from another machine.

Two things keep the input map honest:

- **The audit.** After each passing step, the compiler's dep-info and the build scripts' `rerun-if-changed` lines are checked. Every file a workspace crate read must lie inside that package's declared inputs and must not be git-ignored. A step that fails the audit passed, but writes no stamp, so an out-of-date map costs time, never a false skip. On its first run the audit found the game's `#[path]` modules.
- **Environment learning.** Environment names that build scripts declare (`rerun-if-env-changed`) and that crates read (`env!`) are kept per step in `~/.cache/slop-check/envdeps.json` and enter that step's digest.

What it does not add: a skipped test step is not re-run, so a flaky test that once passed stays passed until its inputs change. Outputs are not compared, only inputs, so the guarantee is cargo's own freshness rule applied across worktrees. A test that reads files outside its inputs at run time would not be seen; the rules tests read none (all their fixtures are `include_str!`, which the audit sees), and the authority's tests read only `living/seeds`, a shared input.

### Byte-identical wasm

Status: **current** (branches `wasm-remap` and `wasm-remap-sccache`, Spark, 2026-11-21). **Reproducible within one OS and architecture:** with the pinned rustc ([`rust-toolchain.toml`](../rust-toolchain.toml)), one commit gives the same authority wasm on every machine of one OS and architecture, for any user, checkout path and target directory, with or without the compile cache. **Different host triples (OS or architecture) give different modules, by design of cargo's crate hashing** (see below and [WASM_XARCH.md](WASM_XARCH.md)). Before, the same commit built different modules on dev-box and the Spark (island 16,269,709 B against 16,264,556 B). Two inputs varied even within one machine type:

- **Host paths.** Panic locations embed source paths. Registry and git crates are compiled from absolute paths under `CARGO_HOME` (`/home/<user>/.cargo/registry/src/…`). Cargo passes workspace crates' paths relative to the workspace, and the standard library's are already `/rustc/<commit>/…`. Cargo's `trim-paths` is unstable in cargo 1.99.1.
- **Random keys.** rhai turns on ahash's `compile-time-rng`, so `const-random-macro` drew new random constants into ahash at every compile of it: two target directories on one machine already gave different modules. The laws' own hashing does not use them; living-rules fixes Rhai's hashing seed ([`script.rs`](../living/rules/src/script.rs), `HASHING_SEED`).

The fix is one file, the repository's [`.cargo/config.toml`](../.cargo/config.toml), and the cache wrapper. Cargo finds the file from its working directory, not from `--manifest-path`, so every cargo run inside the checkout gets it: the Justfile, `check.py`, `verify.py`, the scene gate, `genesis_fuel.py`, `lab.py`, `trials.py`, the tool scripts, and SpacetimeDB 2.14.1's `spacetime build` (it runs `cargo build --target=wasm32-unknown-unknown --release` in the module's folder with the caller's environment, [`crates/cli/src/tasks/rust.rs`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/cli/src/tasks/rust.rs)). A new build site needs nothing, as long as cargo runs inside the checkout. `genesis_fuel.py` and `trials.py` pass the checkout as the working directory for that reason.

- `build.rustc` is [`living/tools/rustc-remap`](../living/tools/rustc-remap). For a `wasm32-unknown-unknown` compile it adds `--remap-path-prefix` for `CARGO_HOME` (`/cargo`), the checkout (`/src`, only when rustc runs inside the checkout, as it does for workspace crates) and the crate's `OUT_DIR` (`/out`, only when its build script wrote files there), each as given and as resolved through symlinks. Native compiles run rustc unchanged, so native caches stay valid. `rustc-remap --remap-flags ARGS…` prints the flags for a compile instead of running it: the one computation both paths use.
- **Under sccache** (`RUSTC_WRAPPER=living/tools/sccache-rustc`: `check.py`, the laptop's `build-slot`). sccache v0.19.0 never runs `rustc-remap`. Its name is not `rustc`, so sccache probes it: `rustc-remap -vV` answers as rustc, and `rustc-remap +stable` succeeds because the `rustc` it runs is rustup's proxy. sccache then takes the toolchain's own rustc from `rustup which rustc` and compiles with that ([`src/compiler/compiler.rs`](https://github.com/mozilla/sccache/blob/v0.19.0/src/compiler/compiler.rs), `detect_compiler` and `resolve_rust_compiler`; [`src/compiler/rust.rs`](https://github.com/mozilla/sccache/blob/v0.19.0/src/compiler/rust.rs), `RustupProxy::find_proxy_executable` and `resolve_proxied_executable`; [`src/server.rs`](https://github.com/mozilla/sccache/blob/v0.19.0/src/server.rs), `compiler_info`). The marker flag was in the argv, but the remap flags were not, so the island kept 83 `CARGO_HOME` paths (laptop, macOS; reproduced on the Spark, Linux). `sccache-rustc` now replaces `rustc-remap` with plain `rustc`, as the script itself runs it, and appends `rustc-remap --remap-flags` to the argv. sccache passes the flags to rustc and puts them in its key, which is correct. The two conditions above keep a checkout or target path out of registry crates' flags, so they still hit across checkouts and target directories. A native compile's argv is unchanged, so its key is too. A `rustc-remap` without `--remap-flags` (an older checkout) is passed through as before.
- **A stale copy of the wrapper** (`~/.local/share/slop-tools/bin/sccache-rustc` that a `build-slot` pre-sets) keeps the bug for plain cargo runs until it is copied again from `living/tools/sccache-rustc`. The new copy is safe with older checkouts (see the previous point). `check.py` runs its own checkout's wrapper in place of a copy that differs from it, and says so ([pre-set wrappers](#the-check)).
- **`RUSTC` in the environment** replaces `build.rustc` (cargo prefers it), so nothing remaps. The host-path check below fails such a module and names `RUSTC` as the likely cause.
- The wasm target's `rustflags` hold a no-op marker remap (`/slop-remap-v2`). Cargo cannot see the flags the script adds. The marker is in cargo's fingerprint and sccache's key, so wasm crates built before the current mapping are rebuilt. Bump it when the mapping changes. v2 (`wasm-remap-sccache`) rebuilds what v1 built through sccache with host paths. A `RUSTFLAGS` in the environment replaces the marker, but the remapping still happens.
- `[env]` sets `CONST_RANDOM_SEED`. `const-random-macro` reads it with `option_env!`, so cargo rebuilds that crate and its dependents once when the seed is introduced. A variable of the same name in the environment wins.
- `check.py` keys every step on `rustc-remap` as well as on `.cargo`.

**The host-path check** ([`living/tools/host_paths.py`](../living/tools/host_paths.py)). It fails a module that holds `/home/`, `/Users/`, this machine's `CARGO_HOME`, the checkout or `$HOME` (each as given and as resolved). It names the module, the number of hits and the first five distinct paths. It prints only the path strings, each cut at its `.rs` or its first non-path byte and at 160 characters. It runs on every module `verify.py launch` builds, which includes all of the scene gate's modules, before the publish (`refusing to publish …`). It also runs on `check.py`'s `authority` step module, which then fails. It costs a fraction of a second on a 17 MB module. `python3 living/tools/host_paths.py --selftest` plants host paths and checks that they are found and that nothing around them is printed (9 checks). `python3 living/tools/host_paths.py MODULE…` checks any module by hand.

**Evidence, same machine type** (Spark, rustc 1.99.1, Linux aarch64, `--locked`, island). `wasm-remap` alone: two checkouts at different paths (`~/.t3/worktrees/…` and `~/slop-remap-checkout2/some/deeper/sao`), the second with a copied `CARGO_HOME` (`~/slop-remap-cargohome`, offline) and its own target directory. They built the same bytes for all ten modules the scene gate builds: five seeds, each plain and stepping. No module holds `/home/`, the user name or either checkout's path. Before the `[env]` seed, paths alone left the island 54 bytes apart in ahash's constants and in the `.llvm.<hash>` suffixes of the code that inlines them. `wasm-remap-sccache`, each build in a fresh target directory, through `build-slot` on CPUs 0-4 and 10-14, sccache v0.19.0 pinned (scratch copy, scratch cache):

| Build | sha256 (island) | Size | Host paths | sccache hits / misses |
| --- | --- | --- | --- | --- |
| `wasm-remap` 65c3d834, plain cargo | `c9a6cbaf…f566` | 16,991,630 B | 0 | |
| `wasm-remap` 65c3d834, through `sccache-rustc` (the bug) | `244bb312…d3c5` | 16,992,886 B | 83 | cold 0 / 101; warm 83 / 18 |
| fix, plain cargo, two checkouts | `c9a6cbaf…f566` | 16,991,630 B | 0 | |
| fix, through `sccache-rustc`, cold cache | `c9a6cbaf…f566` | 16,991,630 B | 0 | 0 / 101 |
| fix, through `sccache-rustc`, warm, same checkout | `c9a6cbaf…f566` | 16,991,630 B | 0 | 85 / 16 |
| fix, through `sccache-rustc`, warm, a second checkout at another path | `c9a6cbaf…f566` | 16,991,630 B | 0 | 85 / 16 |
| fix, through `sccache-rustc`, on the pre-fix cache | `c9a6cbaf…f566` | 16,991,630 B | 0 | 26 / 75 (native hits; every wasm crate misses on the v2 marker) |
| fix, `check.py --steps authority` with the wrapper pre-set | `c9a6cbaf…f566` | 16,991,630 B | 0 | 85 / 16 |
| fix, `check.py` with a pre-fix copy of the wrapper pre-set | `c9a6cbaf…f566` | 16,991,630 B | 0 | 85 / 16 (its own wrapper ran instead) |
| fix, `check.py` with `RUSTC=rustc` | (the bug's module) | | 83 | step **failed** on the host-path check |

The fix's module is the same bytes as `wasm-remap`'s plain one, so the conditions on `/src` and `/out` change no output.

**Across OSes and architectures** (rustc 1.99.1, `--locked`): each machine is reproducible with itself and its modules hold no host path, but they differ from one another. dev-box's ten modules differ from the Spark's by 5.2–5.8 kB. Island at `wasm-remap` 299da4eb (the laptop's from its coordinator's report, plain cargo):

| Machine | OS, architecture | sha256 | Size |
| --- | --- | --- | --- |
| Spark | Linux aarch64 | `c9a6cbaf26e71af6bede0fc8e4ed9d94fb2827d0de4a53e798d66a768882f566` | 16,991,630 B |
| dev-box | Linux x86_64 | `4435992654c7ee081de8115f5a7756910c768042c20ed2ce335611eecad1712f` | 16,997,417 B |
| laptop | macOS aarch64 | `724dd073…` | 16,990,457 B |

**The cause is the build host's triple** ([WASM_XARCH.md](WASM_XARCH.md), branch `wasm-xarch`). Cargo mixes the `host:` line of `rustc -vV` into the `-C metadata` hash of build scripts and proc-macros, and every crate that depends on one inherits a host-dependent identity: 21 crates in the module, rhai, serde, spacetimedb and the living crates among them. On the Spark, a rustc wrapper that changed only that `host:` line reproduced the laptop's module and dev-box's module byte for byte. The logic is the same (genesis builds the same world), but names, data layout, rhai's TypeId-keyed lookup hashes and some inlining differ, and island `init` fuel moves by up to about 1% (macOS −0.97%, x86_64 −0.62% against the Spark). The same shift can happen on one host whenever a dependency's hash changes (a build-dependency bump, a feature change). The 10% headroom rule absorbs it. A rewrite of `-C metadata` for wasm32 that gives one module on every host was prototyped and not adopted (2026-11-22); it is kept in WASM_XARCH.md in case one hash everywhere is ever needed. So compare module hashes, and fuel exactly, only between builds of one host triple and one dependency set. To build the authority into a scratch target directory and print its sha256:

```bash
LIVING_SEED=island CARGO_TARGET_DIR=$(mktemp -d) sh -c 'cargo build -q --locked --manifest-path living/Cargo.toml -p living-authority --target wasm32-unknown-unknown --release && sha256sum "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm" && python3 living/tools/host_paths.py "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/living_authority.wasm"'
```

## Merging

From a clean coordinator worktree (on its own branch, such as `coord-devbox`, or detached; never `main` and never `~/dev/slop-art-online`):

```bash
set -o pipefail; just living-merge plan-3 -m "Merge plan-3: what it brings"
```

[`merge.py`](../living/tools/merge.py):

1. Refuses a dirty worktree (untracked files included), an unfinished merge or rebase, `main` checked out here, the owner's checkout, and commits that `origin/main` lacks. Before fetching, it checks free space on the worktree and Cargo target filesystems ([disk policy](#disk)). It checks again before retrying a merge. A disk refusal names the path, free space, required space, and how much allocated target space it subtracted (exit 12).
2. Fetches `main` and the branch, and pins the branch to the commit it has now. It prefers `origin/<branch>` and otherwise takes a local branch, saying so.
3. Moves HEAD to `origin/main` (`git reset --keep`) and runs `git merge --no-ff`. On a conflict it aborts the merge, restores HEAD and stops (exit 4).
3a. **Checks that the compiled seeds are fresh** ([seed freshness](#seed-freshness)) on every merge, with or without `--scenes`: `scene_gate.py seeds`, files only, a fraction of a second. A stale seed that the red-on-main list does not hold restores HEAD and stops before the check (exit 13), naming the seed, the block and the command that recompiles it. `LIVING_MERGE_SEEDS=off` skips it, saying so.
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

`--no-push` stops after a passing check. `python3 living/tools/merge_selftest.py` drives these cases against a throwaway remote.

- fake `df` and `du` for cold and warm targets, the 2 GB minimum, a retry at 48.8 GB free, separate target and trial filesystems, and the overrides; the floor alone before the fetch; the charge after the merge from the merged tree's own plan (a stand-in `check.py`: every step stamped reaches the check at the floor plus nothing, a 3 GB plan is refused 1 GB short), the full charge when the tree has no plan; the scene reserve only when the merge touches a behavioural path;
- the dirty-worktree, local-commit, conflict, failing-check and dirtying-check refusals;
- a failing and a passing scene gate (a stand-in command), and a failed gate's genesis fuel per seed in the summary;
- a stale seed stopping the merge before the check (a stand-in command);
- a `main` that moves during the check, and one rewound during the check;
- a branch merged by someone else meanwhile, an unknown branch, and a clean merge;
- the bindings check with a stand-in generator: bindings that change fail and are named, a failing generator fails, unchanged bindings pass, and a docs-only merge skips it.

### The scene gate

`just living-merge <branch> --scenes` (or `LIVING_MERGE_SCENES=1`) runs the scene gate, [`scene_gate.py`](../living/tools/scene_gate.py), after a passing check and before the push. `just living-check` builds and runs cargo tests only; no scene runs against a live authority, so `fix-place-free` (e3f0527f) merged green while verify-minds `dealings` and verify-player's combat staging went red on main. When the merge's diff against `main` touches behaviour (`living/authority`, `rules`, `scripts`, `mind`, `seeds`, `configs`, `bindings`, the workspace manifest or lock, or the drivers the gate runs), the gate runs real scenes with the fake model on scratch `verify-gate-*` databases: verify-core `tick`, `sight`, `senses`, `refusal` (one default-seed world) and `skirmish` (island), `sides_battle` (since sides-battle-fix, only when the merge touches `SIDES_BATTLE_PATHS`: the battle fixture in `lib.rs`, `records.rs`, `brain.rs`, `combat.rs`, `living/rules/src/records.rs`, `battle_viewers.py` or verify-core's `scenes.py`; a Cullet world, `spawn_battle_sides` 60 in 2 sides: fighters fall within 30 s, no use targets a resident or the fighter's own side, no resident dies in 60 s), the speech group (since gate-say-path, 2026-11-23: verify-core `say`, `heard_first` and `audience`, then verify-player's `speak` and `told` (a player's own lines and a failed command told), on a fresh default-seed world of their own, only when the merge touches `SPEECH_PATHS`, the speech files `speech.rs`, `earshot.rs`, `mind.rs` and the rules' `normalize.rs`, `saying.rs`, `ways.rs`, `graph.rs` and `script/speech.rs`, or a changed hunk, its lines and two of context, of `brain.rs`, `perceive.rs` or `skills.rhai` that names speech (`SPEECH_WORDS`: say, said, speak, speech, spoken, earshot, whisper, hear, heard, audience, overtaken, with identifiers read by their parts, so `said_to_recently` counts); say-once, 7f21e425e, changed `speech.rs` and `brain.rs`, broke `say`, and no gate case ran it for ten days; replayed over main's last 400 merges it selects 55 of the 184 behavioural ones; about 4 min in the original trial), the steering group (verify-core `flee_wall` and `pursue_last_seen` on another fresh default-seed world, only when the merge touches `STEERING_PATHS`: `motion.rs` and the rules' `steer.rs`, `steer_drive.rs` and `nav.rs`; 13 of those 184; about 4.5 min), the acting group (since step 1 of gate-say-path: verify-core `act_gaps`, `act_replace` and `truthful_refusals` on a fresh default-seed world, only when the merge touches `ACTS_PATHS`: the authority's `acts.rs` and `outcomes.rs` and the rules' `acts.rs` and `outcome.rs`), the fight group (verify-core `committed`, `dodge_told`, `health_seen` and `seize` on another, and `outcomes` on its own island world, only when the merge touches `COMBAT_PATHS`: the authority's `combat.rs` and `codes.rs` and the rules' `combat.rs`). verify-minds `roundtrip`, `acts`, `dealings`, `conversation` (each its own world, the real `living-mind`), verify-player `combat` (`--scene all`, island), verify-client `cues` (since frame-views: `cues.py`, row-level security keeps each player's cues to that player and the `cue_transport_on` law off writes none, and `near_tier.py`, the near tier engaged first) and `motion_tables` (since battle-views: `motion_tables.py`, the public copy tables reach only their viewer and each delivery law off empties its table at once), one default-seed world and the SDK probe, which the gate builds, `combat_feed` (since views step 2: `combat_feed.py`, a player's combat feed as event rows reaches only its viewer and equals `my_combat`), `copy_privacy` (since copy-privacy, only when the merge touches `frame.rs`, `perception.rs`, `tables.rs`, `combat.rs` or its drivers: `battle_viewers.py --privacy`, 16 viewers round a 60-fighter battle, every copy row each viewer receives its own), and `mind-unit`, living-mind's cargo tests (the check builds the mind but tests only `living-rules`). The existing groups run together first. The speech, steering, acting, fight and outcomes groups run in a second wave. `LIVING_GATE_GROUPS` caps each wave separately (default 10, 0 for all groups within a wave). A change to how the client draws (shaders, character drawing, the camera and sight drawing, the verify-ui drivers) runs the [render group](#the-render-group): verify-ui's `looks`, `hair`, `seat`, `camera-faces`, `camera-lod` and `far`, after the other groups, on the host with a pinned [render asset set](#render-asset-set) (dev-box), and elsewhere `render-smoke` and a refusal until dev-box records a pass. Other client paths, the viewer, docs, other tools and the rest of verify-ui skip it in under a second. A failing case runs again once, alone, on a fresh world. A passing rerun excuses the first failure only when every part that failed (a scene's check, a combat `scene:check`, a mind test, a minds case's error) matches the case's recorded flake (`CASES[c]["flaky"]["parts"]`, taken from the skill's validation records); that is `flaky-pass`. Any other first failure blocks as `fail-unrecorded-flake` even when the rerun passes, as does one whose failed parts could not be read: a flake is recorded before it is excused (general coordinator, 2026-11-22, after a combat `wolves` failure passed under combat's unrelated flake; combat now excuses nothing, since its recorded failures were staging bugs, fixed). Otherwise the gate fails on a case that fails twice and passes on `main` (the merge's first parent, run in its own checkout, `~/.local/state/slop-merge/scene-gate/main`, built in `main-target` beside it). A case that also fails on `main` is reported as red on main too, does not block, and stays on the red-on-main list until it passes on main. The list is in git, so every machine's gate shares it: the branch `red-on-main` (one file, `red-on-main.json`; never merged into main) is fetched before every gate command and written by commits pushed without force, fetched and retried when another writer got there first; the local file (`LIVING_GATE_REDS`, `~/slop-mq/red-on-main.json` on the Spark) is a cache, read only when the fetch fails, which the gate says ([`scene_gate_selftest.py`](../living/tools/scene_gate_selftest.py): an add on one clone seen on another and back, eight racing writers on two clones, the fallback); every gate run prints the list and `just living-scene-gate reds` prints it alone (the daily digest). `reds --add CASE --skill S --who OWNER --reason WHY` lists a known red by hand, `reds --drop CASE` removes one, and `recheck` runs every listed case it can (the gate's own and any verify-minds case) on `origin/main`, dropping the green ones. A listed part of a case, a mind test `living-mind::<test>` or a combat scene `combat:<scene>`, is reported when it fails but does not fail its case; such parts are dropped by hand. A failed gate restores HEAD and pushes nothing (exit 10). When `main` moved and the merge is redone, the gate runs again only if the new `main` commits touch behaviour. It uses the Spark's trial server by default (`slop-trials-stdb`, `http://127.0.0.1:3320`; `LIVING_GATE_STDB_CONTAINER`, `LIVING_GATE_STDB_URL`), never Neo4j, and deletes its databases in every case. See the verify skill's "Scene gate" for the case list, flakes and evidence.

Measured on the Spark on 2026-11-12, load average 75–105 on 20 cores, private `CARGO_TARGET_DIR`: the scenes' first pass takes 199–284 s, with the four worlds at once. A case failing once adds its retry (45–85 s). A case failing twice also adds main's run of it: 21–302 s, the most when main's checkout builds cold. Whole gates: 265 s when `sight` was broken, and 753 s on a main where `dealings` was red (a cold main build). A real `living-merge --scenes --no-push` of a behavioural branch took 1263 s: the check 993 s, the scenes 265 s, git about 5 s. A push adds seconds. A docs-only merge skips the gate in 0.1 s.

#### Genesis fuel

**Why.** SpacetimeDB 2.14.1 gives every reducer call, `init` included, [120 × 10⁹ Wasmtime fuel](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/client-api-messages/src/energy.rs#L126-L142) (`FunctionBudget::DEFAULT_BUDGET`, one fuel unit per wasm instruction). A call that runs out fails, and a failed `init` refuses the publish. The island's `init` was a few tenths of a percent short of it when status-parts' extra ~1 × 10⁹ stopped island worlds from publishing on dev-box (2026-11-19), and nothing caught it before the merge. The gate now measures every seed's genesis on every gated merge, pass or fail.

**What it publishes.** Before the scenes, the gate publishes a fresh scratch world `verify-gate-<stamp>-fuel-<seed>` for each seed in `GENESIS_SEEDS`: `island` (the skirmish, minds and player combat worlds), `cullet`, `cullet-laws` and `plan-test` (verify-player's fixtures), then `world` (the core, mechanics and client scenes reuse its build). Each world is deleted through `verify.py cleanup`, which pauses it, confirms the pause and deletes it with the shared `world_delete.py` rule. Keep `GENESIS_SEEDS` in step when a scene or player fixture adopts a new seed. `just living-scene-gate run --genesis-only` runs the same publishes without the scenes or the red-on-main list.

**How it reads fuel.** The gate reads the server's [`/v1/metrics`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/client-api/src/routes/mod.rs#L74) and takes, for the fresh database's identity (`db`) and `reducer="init"`, the counter [`reducer_wasmtime_fuel_used`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/datastore/src/db_metrics/mod.rs#L109-L112) and the call count `spacetime_reducer_plus_query_duration_sec_count` (the histogram [`spacetime_reducer_plus_query_duration_sec`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/worker_metrics/mod.rs#L711-L714)). Both are recorded for every reducer call, failed calls included ([`call_reducer_with_tx`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/wasm_common/module_host_actor.rs#L1223-L1231), [`VmMetrics::report`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/wasm_common/module_host_actor.rs#L2070-L2077)). `init_fuel` is the counter divided by the count. A fresh publish runs `init` twice: standalone first [checks the module on an in-memory database](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/standalone/src/lib.rs#L317-L321) ([`check_module_validity_with_environment`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/host_controller.rs#L561-L597), opened under the same database identity, [`try_init_in_memory_to_check`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/core/src/host/host_controller.rs#L1542-L1557)), then initializes the real replica. The gate requires exactly two runs after a successful publish. The name is [registered before the check](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/client-api/src/routes/database.rs#L1541-L1564), so a refused publish still reports its fuel. A missing or duplicate series fails the seed, never passes it. The counters live as long as the server process, and each publish has a new identity, so parallel publishers and earlier worlds do not mix. The check adds no reducers, tables or subscriptions.

**Rules.** Per seed, on `init_fuel`:

- **The headroom rule:** fail when fuel is over 90% of the budget (108 × 10⁹), that is under 10% headroom (`SLOP_GATE_GENESIS_HEADROOM`, default 10). Warn above 50%.
- **The interim rule, "must not rise":** a seed that is already over 90% passes only when it has a baseline in [`genesis_fuel_baselines.json`](../living/tools/genesis_fuel_baselines.json) for the gate's rustc and its fuel is at most 0.1% above that baseline. An over-90% seed with no baseline for this rustc fails and says so.
- **Graduating:** a seed with a baseline uses the headroom rule as soon as its measured headroom reaches the required headroom, automatically, measurement by measurement. To make that permanent, or to put a seed back on the headroom rule at once, delete its entry from `genesis_fuel_baselines.json` (one line per toolchain).
- `SLOP_GATE_GENESIS_CHECK=0` skips the check with a warning in the output and `genesis_disabled: true` in the record.

Genesis failures stop the gate before the scenes (exit 1). They are not retried and the red-on-main list does not excuse them: the same module counts the same fuel. Three rounds on the same module gave identical `init_fuel` for four seeds, and `cullet-laws` varied by 38 fuel units.

**Baselines are per toolchain.** Fuel counts the instructions of the module that rustc produced, so another rustc gives other numbers for the same source: the island with status-parts measured 119.79 × 10⁹ on dev-box (rustc 1.97.1, x86_64) and 118.735 × 10⁹ on the Spark (rustc 1.99.1, aarch64). Since 2026-11-20 the repository pins rustc 1.99.1 ([`rust-toolchain.toml`](../rust-toolchain.toml)). Since `wasm-remap` a commit's module no longer depends on the build host's paths or on compile-time random keys ([Byte-identical wasm](#byte-identical-wasm)), but identity holds only within one host triple: another OS or architecture, or the same host after any dependency-hash change, can shift `init` fuel by up to about 1% ([WASM_XARCH.md](WASM_XARCH.md)). The file is empty and every seed is on the 10% headroom rule, which absorbs that. A baseline recorded later holds only for the host triple and dependency set it was measured on. **Never compare fuel or module hashes across hosts, or across a dependency change, without rebuilding both sides on the same host.** The file is keyed by seed and then by `rustc --version`, as the gate prints it. Each machine that runs the gate records its own baseline. A record that has one only for another rustc fails and names the toolchains it has. Record from a gate's evidence:

```bash
just living-scene-gate run --genesis-only          # on main, after the change the baseline is for
just living-scene-gate genesis-baseline .local/living/verify/gate-<stamp>/genesis.json island
```

`genesis-baseline` takes a clean two-run measurement only and records `init_fuel`, `commit` and the date for that record's rustc. Commit the file with the reason in the message.

**Output.** Each seed prints one line, forwarded by the Spark queue (it forwards `scene-gate:` lines), for example:

```text
scene-gate: genesis island: init 118.735e9 fuel per run (2 init runs), 98.95% of the 120e9 budget, 1.05% headroom; rule 10% minimum headroom, limit 108.000e9; init 118.735e9 is over its limit 108.000e9: under 10% headroom and no recorded baseline in genesis_fuel_baselines.json — FAIL
```

`living-merge` adds `genesis init fuel per run: island 118.735e9, 98.95% FAIL; …` to its summary on a pass and on a failure. The evidence folder's `genesis.json`, and `gate.json` (and `--json`) under `genesis`, hold one record per seed with dev-box's staged-genesis (`docs/STAGED_GENESIS.md` on the `staged-genesis` branch) field names: `seed`, `commit`, `init_fuel` (per run), `init_runs`, `steps` (`phase`, `label`, `fuel`, `reducer`), `largest_step_share` and `budget`. The gate adds `toolchain`, `headroom_pct`, `policy`, `limit_fuel`, `baseline_fuel`, `warnings`, `failures`, `passed`, the database and its identity, and the paths of the launch log and the two metric series (`genesis-<seed>.prom`).

**Staged genesis.** When `living/tools/genesis_fuel.py` exists in the tree under test, the gate runs `genesis_fuel.py --seed SEED` with the gate's server environment and reads one JSON object in that format from its stdout (stderr goes to the log). `--genesis-fuel-report FILE`, once per seed, reads reports already made for the commit under test. The gate checks the report's seed, commit, budget, two init runs and `largest_step_share`, then applies the rules to `init` and to **every step**, each against its own full budget (each scheduled step is its own reducer call). The interim baseline applies to `init` only.

Measured on the Spark (rustc 1.99.1, aarch64) on 2026-11-20, private `clockworklabs/spacetime:v2.14.1` server. Main `3ed22a74` (its module is battle-views' `a407be01`, with status-parts): three `--genesis-only` rounds of 193–210 s, five publishes in a row. Main `bfbbc079` (overlay-validate-once on top: a seed's laws overlay is validated once, about 24.8 × 10⁹ less on both Cullet seeds): one gate run with the generation cases, 182 s.

| Seed | `init_fuel` per run, `3ed22a74` | `bfbbc079` | Share of budget (`bfbbc079`) | Result under the default rules |
| --- | --- | --- | --- | --- |
| island | 118,734,992,179 | 118,734,992,179 | 98.95% (1.05% headroom) | fails: over 90%, no baseline |
| cullet | 91,829,020,112 | 66,994,189,556 | 55.83% | passes, warns |
| cullet-laws | 62,997,679,071–147 | 38,169,278,708 | 31.81% | passes |
| plan-test | 26,997,746,345 | 26,997,746,345 | 22.50% | passes |
| world | 17,614,179,252 | 17,614,179,252 | 14.68% | passes |

TODO (Spark): record the island's baseline for rustc 1.99.1 from a `--genesis-only` run on main once the status-parts revert is on main. Until then, every gated merge on the Spark fails on the island. Dev-box records its own for its rustc.

**Watch — script size.** The shipped script (`living/scripts/skills.rhai`) is about 236 KB, growing about 10 KB a week; the source cap (`MAX_SOURCE` in `living/rules/src/script.rs`) is 512 KiB (revisit comment-stripping around 400 KB composed, [script engines](SCRIPT_ENGINES.md#5-limits)); the genesis-fuel headroom rule above applies.

#### Generation smoke

The cases `generation-default` (`world`), `generation-island` (`island`) and `generation-cullet` (`cullet` and `cullet-laws`) run verify-generation's per-world checks (`generation.py --run RUN --smoke`): the world's day, **the seed's laws composed over the shipped script** (or the shipped script alone), dimensions and terrain chunks, settlements, residents and their sheets, bands, animals and resources, rhythms, land and plans, looks and body sex, and no sheet secret in a public table. The smoke pauses the world and reads its tables. It runs no native digest comparison, repeatability, floors or build: those stay in the full skill. In the first pass the smoke reads the genesis fuel worlds before they are deleted, so it publishes nothing of its own and adds seconds. A retry, or main's run of it, launches its own world. A passing world keeps `checks.json` and `smoke.json` (an island's table snapshots are about 60 MB). A failing one also keeps the snapshots.

A failing check is a part, `<case>:<seed>:<check>`, that the red-on-main list can hold like `combat:<scene>`. The case passes when every failing check is listed, and says which. `recheck` cannot run a part, so drop it by hand (`just living-scene-gate reds --drop '<key>'`) once it is green. Listed on 2026-11-20 against main `bfbbc079`: `generation-cullet:cullet-laws:the seed's laws are composed over the shipped script` (red on both cullet-laws seeds; fixed separately after status-parts-genesis), and Cullet's two look checks `generation-cullet:cullet:the cases are of the world's generation` and `generation-cullet:cullet:each band case's resident wears its entry, in its band, with its line, at its stage (11 cases)` (the stale compiled seed below; dev-box's `cullet-looks-seed`).

#### The render group

**Why.** The gate classed every client path as non-behavioural, so a shader or character-drawing change (char-port-2 S5's `toon.wesl` and `handmade.rs`) merged with no verify-ui case run. The render group runs verify-ui's drawing cases ([`check.py`](../.agents/skills/verify-ui/scripts/check.py)) when a merge changes how the client draws, and only then.

**What selects it** (`RENDER_CHARACTER`, `RENDER_CAMERA`, `RENDER_UI`, `RENDER_BOTH` in [`scene_gate.py`](../living/tools/scene_gate.py); `*` stays within a folder, `**` crosses folders):

| Class | Paths (under `living/game/src/` unless named) | Cases |
| --- | --- | --- |
| both (matched first) | every `*.wesl` (the shaders), `living/game/Cargo.toml`, `.agents/skills/verify-ui/scripts/**` | all seven |
| character | `characters/**` (`compose.rs` among them), `characters.rs`, `handmade.rs`, `compose.rs`, `lookdev.rs`, `looks.rs`, `style.rs`, `bodies.rs`, `anim.rs`, `gait.rs`, `ik.rs`, `twist.rs`, `mouth.rs`, `facing.rs`, `post.rs`, hair files (`**hair*.rs`) | `looks`, `hair`, `seat` (about 6 minutes on dev-box) |
| camera | `camera.rs`, `perf.rs`, `fade.rs`, `envs.rs`, `sightfield.rs`, `sightedge.rs` (the camera, LOD and sight) | `camera-faces`, `camera-lod`, `far` (about 5 minutes) |
| ui | `ui/**`, `.agents/skills/verify-ui/features/body-clock.md` (the HUD) | `body-clock` |

The split is automatic (render-autosplit, 2026-11-21; `ui` half added 2026-11-27): a merge runs the half or halves its paths select, and all halves when it touches a path of the first row. Every other client path keeps its classing: it selects nothing. A merge that touches drawing or UI paths and no behavioural path runs the render group alone: no genesis fuel, no authority scenes. `--render-split` and `LIVING_GATE_RENDER_SPLIT` are retired (the flag is accepted and ignored, with a note); `--render-only --force` runs all seven whatever the diff selects, for a manual full pass.

**How it runs.** After every other group has finished, never beside one (dev-box's `mechanics` already takes about 480 s under load), one case at a time: `looks` on a Cullet world, then `hair`, `seat`, `camera-faces`, `camera-lod`, `far` and `body-clock` on one island world (`gate-<stamp>-<tag>-cul`, `-isl`). The gate checks the set (`render_set.py check`), links it (`render_set.py link`), builds the release client into its `CARGO_TARGET_DIR` and runs `check.py --run <run> <case>` under `uv run --no-project --with pillow --with numpy` (the pixel checks), with `WGPU_VALIDATION`, a window, a theme, a forced shine or look book and `RUST_LOG` taken out of the environment: Vulkan validation layers log benign ERRORs. `check.py` and `drive.py` accept the gate's `gate-*` runs (`verify-gate-*` worlds). A failing case runs again once on a fresh world and is judged on main, as every case is; the red-on-main list holds render cases too.

**Verdicts.** A case passes when `check.py` exits 0 and the client logs of its drives (every `ui/<drive>/client.log` it wrote) hold none of:

- **shader/pipeline** (the code): ERROR lines from `wgpu`, `wgpu_core`, `wgpu_hal`, `naga`, `bevy_render`, `bevy_pbr` or `bevy_core_pipeline`, and any ERROR line with `Shader`, `pipeline` or `Validation Error`;
- **asset** (a load failure: the code or the set): ERROR lines from `bevy_asset` (an unapproved path, a load failure, a missing file);
- **panic**: a `panicked at` line.

WARN lines never fail (ShadowLodOrigin, bevy_egui's bindless, winit's Destroyed, the websocket's close and `offline` at teardown, `view`'s "no clip or view", `live`'s "no UI node"). The case's note names each verdict with its first line. A third verdict is the set's, not the case's: **asset set stale** when a drive logged that the book lacks a key or the world's generation (`is not in the look book`, `which the look book (…) does not hold`, `no look book at`), outside the drives that leave one out on purpose (`looks`, `looks-generation`, `camera-faces`). It ends the gate with exit 2 and no retry.

**Where it runs.** On the host with a pinned set ([below](#render-asset-set)): dev-box. Elsewhere (the Spark), the gate prints `render: not run here; needs a pinned asset set (dev-box)` and refuses the merge (exit 1, each render case `needs-render-host`) unless dev-box recorded a render pass for the same content covering every half the merge needs. That host runs `render-smoke` instead, which needs no set: the VRoid bases (fetched once into `~/.cache/slop-render-smoke`, pinned to the mirror's commit and their sha256), the look-dev island tour and one live drive (`ready`, Middle, Near and Far photographs) on an island world; it fails on a client that does not finish and on shader, pipeline and panic lines (missing kits, textures and the book are expected there). It never stands in for the render cases.

**Recorded render passes.** A render host that passes its render cases (`pass`, `flaky-pass` or `red-on-main`) records them on the branch `render-passes` (one file, `render-passes.json`; never merged; written like the red-on-main list, without force), keyed by the content: a hash of the trees of `living/`, `.agents/skills/verify/` and `.agents/skills/verify-ui/`. The same merge made on two machines (two merge commits) has one key, and a docs commit on main keeps it. A pass covers a (content, half) pair: a half counts only when every one of its cases passed for that content, so a character-half pass does not let a camera change through, and a merge that needs both halves needs both covered. Passes for one content merge into its entry (its `cases`, and `halves`, the halves they now cover), so a character pass and a later camera pass together cover both. An entry recorded before the split (`2ed2d93d65c7`, all six cases, no `halves`) covers both halves by its cases. A case recorded `red-on-main` covers its place in the half only while the shared red-on-main list still holds it (once dropped, main is green for it and dev-box must run it again: the refusal names it in `--cases`); it does not block, as no red-on-main case does, but the Spark's gate never reports it as passed: its status is `recorded-red-on-main`, a `WARNING render: <case> did not pass in dev-box's recorded pass` line names its owner and evidence, and the result reads `passed (red on main too: <case> (in dev-box's recorded pass, not passed))`. To let a refused merge through, dev-box makes the same tree (the gate prints how: merge the branch's head into the same main, and the content key to expect) and runs `just living-scene-gate run --render-only --base <main>` there; when the other half is already recorded the refusal adds `--cases` with only the missing half's cases. The next gate on the Spark reads the pass and reports each case `recorded-pass`, naming the halves it covered. `--render-only` runs only the cases of the halves the diff selects (all six with `--force`); `--cases` names cases exactly. `recheck` runs listed render cases only where a set checks ok against main.

**Host load.** The render cases are timing-sensitive (dev-box's `seat` failed 4 of 4 at a 1-minute load of 15 to 29, 2026-11-20, from a Blender batch that bypassed the gate pause and a mechanics container). The gate reads the host's 1-minute load average at the start and end of every render group and render-smoke run (after the client build, around the drives) and keeps them in `gate.json` (`load`); the results list them, and a value over 8 (`LIVING_GATE_LOAD_WARN`) prints `WARNING <group> (<tag>): <host>'s 1-minute load was over 8 …; a failure here may be load-made`. A recorded pass keeps its render group's load, and the Spark's gate prints it (and the warning) when it reads the pass.

**Cost.** On the Spark (GB10, Vulkan, no display; no set; 2026-11-20, CPUs 0-4 and 10-14, a private server), a rendering-only change (one line in `toon.wesl`), the whole `scene_gate.py run`: cold (an empty target folder) 360 s, of which the client's release build 311 s; warm (the client rebuilt for the change) 121 s, of which the build 71 s. In a merge the check has already built the release client into the same target folder, so the gate adds about 50 s there: the look-dev tour (about 40 s), an island world and one live drive, then refuses the merge until dev-box records a pass. A shader that does not compile (an unknown name in `toon.wesl`) failed `render-smoke` twice, 24 `bevy_render::render_resource::pipeline_cache: failed to process shader` lines, in 114 s and 43 s. dev-box's full group (the six cases, set 79072c65d37f, 2026-11-20): about 11 minutes, `looks` on Cullet about 196 s; hence the automatic split (a character change about 6 minutes, a camera change about 5).

#### Render asset set

The render group needs the game client's git-ignored assets. The gate does not generate them: it reads one pinned, read-only **asset set**, built on dev-box by [`render_set.py`](../living/tools/render_set.py) (its docstring is the format), and links it into its checkout. Sets are built on dev-box because the composed bundle's KTX2 pictures are byte-identical only on dev-box's kernel ([CHARACTERS.md § Pictures as KTX2](CHARACTERS.md#pictures-as-ktx2)).

- **Build:** `render_set.py build --bundle <KTX2 bundle> [--pin]` from a clean checkout of a main commit with its generated assets built, and the composed bundle of the same commit (`living/tools/characters/bundle.py --with-clips`). It writes `~/slop-assets/<id>/` (`<id>` the first 12 hex digits of the bundle's sha256), read-only: `assets/` laid out as `living/game/assets` (the VRoid and KayKit bases, the animated bases, the composed characters and `own-clips.glb`, `view/`, `textures/`, `envs/<name>/`, `characters/looks.json`), `bundle/` (the bundle as built, its `MANIFEST.txt`, the world look data), `SET-MANIFEST.txt` (every file under `assets/` with its sha256) and `set.json` (schema 2: `id`, `bundle` {file, sha256, commit, port, pictures}, `main_commit`, `generator_trees`, `generator_tree` (the generator hash, which leaves out the listed non-generating tools: [Building the render asset set](#building-the-render-asset-set)), `generator_exclude`, `looks` {book, generations, worlds}, `clips`, `files`, `bytes`, `built`, `build_seconds`). `--pin` (or `pin SET`) moves `~/slop-assets/current` to it atomically.
- **Where the gate looks:** `LIVING_GATE_RENDER_ASSETS`, default `~/slop-assets/current`. A host without it does not run the render group; a dangling `current` counts as a set, and a broken one.
- **Check** (`render_set.py check [SET] --repo <checkout>`, one JSON verdict), mapped by the gate, each a setup failure (exit 2) that does not blame the merge:
  - `corrupt` (exit 1, or a check that cannot run): a file's sha256 is not `SET-MANIFEST.txt`'s, or a file is missing or extra. The gate says `asset set corrupt`.
  - `stale` (exit 2): the checkout's generator tree (`git rev-parse HEAD:living/tools/{blender,characters,textures}`, hashed together) is not the set's, or a world's look generation (`living/seeds/worlds/<w>/looks.json`) is not in the set's book. The gate says `asset set stale`. A branch that changes a generator passes only with a set built from its own head, given with `LIVING_GATE_RENDER_ASSETS`; its worker builds that set, and after the merge dev-box pins it.
- **Link** (`render_set.py link SET --repo <checkout>`): `lookdev`, `view`, `textures`, `characters/looks.json` and each `envs/<name>` as symlinks into `living/game/assets`, refusing to replace anything that is not a link. The ignore patterns match the links as they matched folders, so a gate's checkout stays clean; the links stay until the next link replaces them.
- **What a set does not cover yet:** main's defaults only (no `SLOP_PORT` hair or ink pages until char-port-2's S8), so the KTX2 path is exercised through the bundle's other pictures, not a hair-mask page.

### The nightly suite

The scene gate runs only what a merge's paths select. [`nightly_suite.py`](../living/tools/nightly_suite.py) runs, once a night on the Spark, against the current `origin/main`, every verify-core scene and driver that no gate case reaches. Each entry runs on a fresh world of its own seed on a private server (`slop-nightly-<date>`, port 3690, CPUs 0-4 and 10-14). They include:
- the body and life (needs, alarms, sleeper, infant, lifecycle, family laws, sex);
- wildlife (wildlife, grazing, remains, flee, pack reflex on and off);
- laws and the clock (laws, decay, winter, law_override, look bands);
- perception and battle scale (the sweep scenes on Cullet, doing, cues, first sight, the notice and witness scenes);
- goods (goods, stock, making, workplace on the goods fixture);
- speech (`speech.py` regress, ways, channels, crowd);
- town (town.py, lives.py, rhythm.py), closed_gate, verify_steering and the rest.

The entries are `plan_entries()`. `nightly_suite.py plan` lists tonight's, without the gate's own cases.

- **Left out, with the reason in `EXCLUDED`:** the measurement drivers with no pass mark (`doing_cost`, `intents_cost`, `fights`, `chase`, `doing_deltas.py`); `arrival` (the wildlife rerun helper); `updates.py` (it needs chains of prebuilt modules); `cover.py` (its fixture is not in the skill); `speech.py diff` (it needs a baseline run).
- **Coverage is checked.** A scene that is neither an entry, a gate case nor excluded fails `nightly_suite.py selftest` and is named in the night's record. When adding a verify-core scene, register it in the nightly plan with its seed and area, register a scene-gate case that drives it, or add it to `EXCLUDED` with a reason. Run `python3 living/tools/nightly_suite.py plan --repo .` on the branch before pushing. This check needs only source files.
- **Guards.** It takes `battle.lock` first, exclusively, holding nothing else, and keeps it for the night. It runs each entry's launch and drive under the trial-activity lock, shared, and builds through `build-slot`. The world guard watches the nightly runner's PID, so long scenes using raw CLI or HTTP keep running while the runner lives. It starts no entry while the merge queue is at work (its `drain.lock` or `lock` is held, detected through `/proc/locks`, or `drain.sh`, `merge2.sh` or `scene_gate.py` runs) or while the 1-minute load is over 8. Branches waiting in `queue.txt` with nothing draining them do not hold it back: on 2026-11-23 the file kept a branch merged five hours before. They are noted in the record (`queue_at_start`). SIGINT or SIGTERM (systemd stops the service with SIGINT) starts nothing more, interrupts the running entries with SIGINT to their process groups (their cleanup runs), and stops the server. It starts nothing after `--until` (10:00); an entry not started by then is recorded "not run". The longest entries start first; 3 run at once (`--lanes`).
- **Its checkout.** A detached worktree of the repository at `origin/main` (`~/.local/state/slop-nightly/main`, made once), built in `~/.local/state/slop-nightly/target`.
- **Results** go to `~/.local/state/slop-nightly/<date>/`:
  - `record.json` and `record.md`: per entry its seed, run, exit codes, first failed checks, minutes and evidence;
  - `reds.txt`: one line per red for the owning machine's queue the next morning (owners from `~/.config/slop-nightly/owners.json`, by entry or area, else "unassigned");
  - `server.log`, the server's log; the server is stopped with SIGINT, and a forced stop is recorded as forced.
- **Reds on the list.** A red entry goes onto the red-on-main list as `nightly:<entry>` (`scene_gate.py reds --add`), and a listed entry that is green again is dropped (`--no-reds` writes nothing to that list). Set `SLOP_NIGHTLY_STATE` to a private directory for validation evidence and build targets while using the same queue guards.
- **Installing.** `living/tools/nightly_suite_install.sh` installs the systemd user timer `slop-nightly.timer` at 04:40. That is after the trial reclaim's 04:00 window, which needs `battle.lock` free. `--print` shows the units and changes nothing; `--uninstall` removes them. Before writing units, the installer tests the runner it will copy against the scene and gate registries from freshly fetched `origin/main`.

### Seed freshness

[`seed_fresh.py`](../living/tools/seed_fresh.py) compares every compiled seed with the sources it is compiled from, files only (no publish, no build, no model; about 0.5 s). Each `living/seeds/worlds/<world>/` compiles into `living/seeds/<into>.json` through `author_world.py <world> --compile-only` (`into` from `cast.json` or `world.json`, else the world's name). Cullet's land, plan, ways and town life come from `cullet_plan.py`. The compilers stamp nothing but the look data's own `generation`, so the check compares each block as its compiler copies it:

- `looks`: the seed's `looks.generation` against `looks.json`'s, then the whole block, then each resident's `look`;
- `ways`: `ways.json`'s `top`, `common` and `occupations` entries in the seed's `ways`, its `town_life`, and its `work` within the seed's `town_life.work`;
- `residents`: the residents against the drafted sheets in `sheets/*.json` by name, and each sheet's narrative;
- `plan`: Cullet's `cullet_plan.py --check`, which rebuilds the plan, the land seed and the game's ground map in memory and compares them byte for byte.
- `compile`: the whole seed. `author_world.py <world> --compile-only --seed-out TMP` compiles the world over the tracked seed into a scratch file (about 0.1 s a world), and the two must be equal as JSON. It catches a field the compiler learned after the seed was last compiled, which the targeted blocks above do not name (aske-coast's `sheet.pastimes` from `efcd489a8`, found 2026-11-20).
- `derived`: a tracked seed whose `run` names an authored world without being its seed (aske-coast's `-crypercept`, `-dynamic` and `-yieldnorm`, which differ only in their own `rules`) must carry the compiled world's residents exactly. Nothing recompiles a derived seed: rebuild it by copying the recompiled world's residents into it, keeping its own blocks.

`just living-scene-gate seeds` runs it with the red-on-main list, and `living-merge` runs that before the check. A stale block prints, for example:

```text
scene-gate: seeds: stale cullet looks: look generation c4-e61b01c0 in the seed, c4-cbcc40bf in living/seeds/worlds/cullet/looks.json; recompile: python3 living/tools/cullet_plan.py && python3 living/tools/author_world.py cullet --compile-only
```

A block listed red on main as `seeds:<seed>:<block>` is reported and does not fail. On 2026-11-20 `aske-coast` and `island` are fresh. `cullet` is stale: look generation `c4-e61b01c0` against `c4-cbcc40bf`, and 55 residents' looks. It is listed as `seeds:cullet:looks` until dev-box's `cullet-looks-seed` lands. Seeds that are hand-written, such as `plan-test` with its look fixture, or that read a source at build time, such as the `laws_file` of `cullet-laws`, have nothing to go stale.


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
| Spark | 60 GB (`--floor-gb 60`): its paid trial servers write to the same disk, and several agents build cold at once | 90 GB |
| laptop | 40 GB (the default; set `--floor-gb` when installing) | 70 GB |

When the folders that may go are gone and free space is still under the floor, the report says so (exit 3), and the list shows what holds the rest.

**Merge pre-check.** `living-merge` requires the floor alone before it fetches, and after each attempt's merge, including automatic retries, the floor plus the merged tree's predicted charge ([below](#the-disk-charge)) on each filesystem holding its worktree or Cargo target. A refusal then restores HEAD (exit 12). The merge tool reads the cleaner's installed `--floor-gb` from the systemd user service or launchd agent and uses 45 GB when there is no installed floor (the dev-box's is 40, whatever the charge). A merge running every step on a cold target requires 63 GB with the fallback floor or 78 GB with the Spark's installed 60 GB floor; a docs-only merge whose steps are all stamped requires the floor alone. Units match the cleaner (1 GB = 1,024³ bytes).

#### The disk charge

Until 2026-11-21 every merge needed the floor plus 18 GB plus 1 GB for scenes, whatever it changed: that night a docs-only branch waited over half an hour on the dev-box for 18 GB its check would never use, since the stamps skipped every step. The charge now comes from the stamps themselves ([`check.charge`](../living/tools/check.py), [`disk_charge.py`](../living/tools/disk_charge.py)), one function for the check's own wait, `living-merge` and `gate-merge`:

- **The check's part.** `check.py --plan` on the merged tree keys every step from its inputs exactly as the check will, against the same stamp store. A step whose stamp is there costs nothing. A step that will run costs its measured cold size (`STEP_COST_GB`). The total is never more than the full charge: the greater of 2 GB and 18 GB less what the Cargo target already holds.
- **Any doubt charges the full allowance:** the plan fails or is missing (a tree from before this), a step cannot be keyed, the stamp store cannot be read, a step has no known cost, or the branch does not merge cleanly.
- **The scenes' part.** 1 GB, on a filesystem shared with the trial server, only with `--scenes` and only when the merge touches a path the scene gate runs scenes for (`scene_gate.behavioural` or `scene_gate.rendering`): no scenes selected, no scene charge.
- **The floor never moves.** The charge is added to it. There are two floors, and they differ on purpose; do not align them (general coordinator, 2026-11-21):
  - **45 GB** for `gate_merge.sh`'s start wait and `check.py`'s own disk wait (`SLOP_DISK_FLOOR_GB`): headroom for builds already in flight when a gate or a check starts.
  - **40 GB**, the disk cleaner's floor (its installed `--floor-gb` on the dev-box), for `merge.py`'s pre-check and per-attempt check.
- **`gate-merge`** waits before `living-merge` has merged, so `disk_charge.py start-gb <living-merge's arguments>` makes the same prediction on the branch merged onto the fetched main as a commit object (`git merge-tree`, no ref written), checked out in one persistent prediction checkout (`~/.local/state/slop-merge/disk-charge-<repo>`, reused, never edited), with the real Cargo target's credit. Its default start is `SLOP_DISK_FLOOR_GB` (45, as before) plus that charge; `SLOP_GATE_START_GB` still overrides it, and a prediction that fails falls back to floor plus 18.

The cost of each step alone, on an empty target folder (dev-box, main `9401135c1`, 2026-11-21, `check.py --full --steps NAME`, allocated size after; `STEP_COST_GB` rounds each up to the next 0.5 GB):

| Step | Alone | Charged |
| --- | ---: | ---: |
| `authority` | 0.38 GB | 0.5 GB |
| `authority-tests` | 0.35 GB | 0.5 GB |
| `game` | 2.62 GB | 3 GB |
| `game-tests` | 2.50 GB | 3 GB |
| `rules-tests` | 2.80 GB | 3 GB |
| `mind+viewer` | 8.18 GB | 8.5 GB |
| `viewer-wasm` | 2.07 GB | 2.5 GB |
| `script-gate` | 0.89 GB | 1 GB |

They sum to 19.8 GB: the steps share build directories and dependencies, so a check running all of them takes less (17.6 GB measured on the Spark, below), and the cap is the full charge. So a docs-only branch whose steps are stamped needs the floor alone; a branch touching only `living/authority` reruns `authority` and `authority-tests`, 1 GB; one touching a shared input (the workspace manifest or lock, `living/seeds`, `living/scripts`) reruns every step, the full charge. The self-test, `python3 living/tools/disk_charge_selftest.py`, runs the real plan in a clone with a scratch store: an empty store, everything stamped, docs only, a tool no step reads, the script bench, `living/authority`, every stamp stale, an unkeyable step, the scene charge, and `start-gb` through a remote (docs only, authority with scenes, the prediction checkout reused, a branch that does not merge cleanly).

On the Spark on 2026-11-19, `just living-check` passed in 949 s from a fresh worktree at `49adf9a3`, with an empty private `CARGO_TARGET_DIR`, eight Cargo jobs, the Spark sysroot and stamps forced off. The worktree and target grew by a sampled peak of 17.62 GB (18,915,008,512 allocated bytes), measured with `du -sk` during the check.

The `--scenes` allowance for scratch databases is 1 GB on a filesystem also used by the trial server, as on the Spark (79 GB total for a cold target). This is an estimate. The [trial disk inventory](trial-disk/removal-list-20261112.tsv) records 0.093 GB for one player scene replica. The separately alarmed [trial volume](TRIAL_DISK.md) only adds to the threshold when its filesystem matches the worktree or Cargo target filesystem.

Set `SLOP_MERGE_FLOOR_GB` to override the floor, or `SLOP_MERGE_CHECK_GB` to override the cold check allowance. A host with the 40 GB cleanup floor can set `SLOP_MERGE_FLOOR_GB=45` to retain the dev-box wrapper's 63 GB threshold for a cold check. `SLOP_MERGE_DISK_CHECK=0` disables the pre-check and always prints a warning.

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

### The old reference server's dead replicas (dev-box)

The stopped labs server `sao-living_spacetimedb_1` (SpacetimeDB 2.10.1, volume `sao-living_living-stdb`, 62 GB) is protected: it holds the paused reference worlds. SpacetimeDB keeps a deleted database's replica directory, so 247 of its 259 replica directories (10.6 GB) belong to databases it no longer lists. Listed on 2026-11-23 without touching the volume or the container: a networkless scratch 2.10.1 server on a copy of `control-db` listed the owner identity's 12 databases (every `aske-coast` world, `stage3-village`, `stage4-two`, `stage4-makers`, two `verify-core-20261102-*` worlds; 49.8 GB), and `spacetime logs` on each named its replica ("failed to init replica N").

**Ready for the owner if the disk ever gets tight:** `bash ~/.local/state/sao-living-cleanup-20261123/delete-unlisted.sh` deletes exactly the 247 unlisted directories (refusing if the server runs, a list is missing, or an id is on both lists) and prints free space before and after; 12 directories should remain. The owner approved the clean-up, but it is left unrun: agents' removal safety check refuses an `rm` inside `podman unshare`, and 10.6 GB was not worth the owner's time (general coordinator, 2026-11-23). After a run, re-list read-only the same way and confirm the same 12 databases map to their replicas. The two `verify-core-20261102-*` worlds (4.5 GB) are listed, so removing them would need the protected server started: candidates only if space is short.

### Removing a worktree

`git worktree remove --force` deletes a worktree's untracked and git-ignored files with it, and in this project those are evidence: `.local/` verification runs, stills, measurement series, uncommitted edits. Evidence was lost this way more than once (the dev-box's eight `mechanics-flake` proof runs on 2026-11-20 among them). Remove worktrees with `living/tools/wt_remove.py PATH` (installed on each machine as `~/.local/share/slop-tools/wt-remove`), never with `git worktree remove --force` directly. It:

- archives every untracked and ignored file (`git ls-files --others`), plus `tracked.patch` (`git diff HEAD --binary`), `status.txt` and a `manifest.json` (branch, HEAD, whether HEAD is on `origin/main` or any remote branch, host, time, counts), to `~/archive/worktree-evidence-<YYYYMMDD>/<name>-<HHMMSS>.tar.gz` with a `.sha256` beside it;
- leaves out build caches, the folders holding a `CACHEDIR.TAG` (Cargo targets, sccache), listing them with their sizes (`--keep-caches` archives them too);
- reads the archive back (every member present at its size, the digest recomputed) and only then runs `git worktree remove --force` from another worktree of the repository. The branch is kept.

It refuses, before writing anything, the repository's main worktree, anything under `~/dev/slop-art-online`, a path that is not a worktree root, the worktree it runs in, and a worktree a process is working in (cwd inside it; `/proc` on Linux, `lsof` on macOS). `--dry-run` prints what it would archive. Standard library only, so the same file runs on the dev-box, the Spark and the laptop. Install: `install -m 755 living/tools/wt_remove.py ~/.local/share/slop-tools/wt-remove`.

### Starting a container from a script or an agent

Two rules for any script, queue or agent shell that starts or restarts a SpacetimeDB (or other) container with `podman start` or `podman run`:

- **Its own systemd scope:** `systemd-run --user --scope --quiet podman start NAME`. Rootless podman's `conmon` and `fuse-overlayfs` otherwise join the caller's cgroup: started from an agent's shell, the overlay helper is lost within minutes (`podman exec` then fails with "transport endpoint is not connected"), and started from a systemd unit (the dev-box merge queue), stopping that unit kills the container's processes with it, a forced stop (dev-box, 2026-11-20). `~/.local/state/devbox-queue/run.sh` starts `coord-stdb` this way.
- **No lock fd:** close the gate lock's descriptor in the command that starts the container, e.g. `systemd-run --user --scope --quiet podman start NAME 9>&-` for a lock held on fd 9 (`exec 9>~/.local/state/slop-build/gate.lock; flock -x 9`). A container started while a shell holds the lock inherits the descriptor in `conmon` and `fuse-overlayfs` and keeps the lock after the script exits: on 2026-11-20 a scratch server recycled inside a locked measurement held `gate.lock` for 70 minutes, stalling a merge gate for two hours and Blender's `flock -s` pause. Python's `subprocess` does not pass descriptors on by default (`close_fds=True`). To see who holds the lock: `fuser ~/.local/state/slop-build/gate.lock`, then `ps` on each pid; a container's `conmon` among them is this case, and stopping the (idle) container with `podman kill -s INT` releases it.


### The gate's server

The dev-box's scene gate runs on a SpacetimeDB container of its own (`coord-stdb`, port 3319, `LIVING_GATE_STDB_CONTAINER`, `LIVING_GATE_STDB_URL`). [`living/tools/gate_server.py`](../living/tools/gate_server.py) looks after it:

- **`check`.** `docker exec <c> true` and `GET <url>/v1/ping`, each with a time limit. Exit 0 if it answers, 14 if not, with the error. A container can read as running while its overlay helper is gone ("transport endpoint is not connected"), and only an exec shows that.
- **`start`.** `docker start` in a systemd scope of its own, with no inherited descriptor, then waits until `check` passes.
- **`stop`.** Lists the server's databases, stops it with SIGINT, and waits until it has exited.
  - Only if it held **no database**, it removes every replica directory, in a one-off container of the server's image on its volume.
  - SpacetimeDB 2.14.1 keeps a deleted database's replica on disk, and the gate deletes every world it makes. On 2026-11-21, 216 such directories (12.8 GB) held a gate two hours on disk.
  - A database still listed (a world kept for inspection), or a list that could not be read, keeps every replica. `--keep-replicas` keeps them in any case.
  - It refuses the trial and reference servers by name: their deleted databases' commitlogs are evidence ([TRIAL_DISK.md](TRIAL_DISK.md)).

**A dead server fails the gate at once.**
- **`merge.py --scenes`** runs the same probe before its disk check and before every attempt, and refuses with exit 14. The check no longer runs 15 to 20 minutes before the scene gate finds the server gone.
- **The scene gate's own setup** uses the probe too. Before, it checked only that the container was running.
- **[`living/tools/gate_merge.sh`](../living/tools/gate_merge.sh)**, the dev-box's `gate-merge` (`install -m 755 living/tools/gate_merge.sh ~/.local/share/slop-tools/gate-merge`), probes before it waits for disk and every minute while it waits. So a dead server is not taken for a disk shortage.

**Who clears the replicas.** It is the gate's server tooling (`gate_server.py stop`), not `disk_clean.py`:
- `disk_clean` runs on a timer, clears build trees, and must never touch a container's data or volume.
- The replicas can only be cleared with the server stopped and known to be the gate's alone. Only the tool that starts and stops that server knows both.
- The dev-box's queue (`~/.local/state/devbox-queue/run.sh`) calls `gate_server.py start` before each branch and `gate_server.py stop` after it, in place of its own `podman` lines.

The selftests: `python3 living/tools/gate_server_selftest.py` (a fake `docker`: healthy, every exec failing, not running, no ping, refused names) and `merge_selftest.py`'s "a dead gate server refuses at once (exit 14)".

### Heavy work during a gate

**The rule.** Any cargo build, Blender run or other multi-core build started by hand or by a worker while gates may run goes through [`living/tools/gate_pause.sh`](../living/tools/gate_pause.sh): `living/tools/gate_pause.sh -- CMD [ARGS…]`. It gives a scene gate the machine. On 2026-11-21 a 16-CPU wasm build run by hand in the middle of the `queue-fail-fast` gate helped fail it. Our scripts' heavy steps use it: `genesis_fuel.py`'s stepping build and the render set's build ([below](#building-the-render-asset-set)). The gate's own builds do not need it, and are never paused by it (below).

A scene gate holds `~/.local/state/slop-build/gate.lock` exclusively. The helper:

- **At start:** while a gate holds the lock, waits.
- **While it runs:** the command is in a process group of its own (`setsid`). Every 3 s (`SLOP_GATE_POLL_S`) the helper tests the lock without blocking, and while a gate holds it, stops the group (`SIGSTOP`). It continues the group (`SIGCONT`) when the gate lets the lock go. Before 2026-11-21 Blender's wrapper checked only at start, so a 20-minute file ran straight through a gate: S6's batch loaded a render pass to 15–29.
- **The cap:** a hold longer than `SLOP_GATE_PAUSE_CAP_S` (5,400 s, 90 minutes: longer than any gate with scenes and the render group) is taken for a leaked lock, as on 2026-11-20 (above). The command is continued, a `WARNING` is logged, and it is not paused again during that hold. The wait at start has the same cap. A paused command holds its memory and its files; it does not hang a batch forever. A caller with a timeout allows for it (`genesis_fuel.py`: the build's hour plus 5,400 s).
- **The gate's own work is never paused.** When the helper or any of its ancestors has the lock file open, the caller is the gate, and the command runs without waiting or pausing (logged: "the caller holds the gate lock"). This covers a gate's shell holding the descriptor (`gate-merge`), `flock -x gate.lock python3 scene_gate.py …` (the queue's render pass and recheck), and a gate's Python children, which do not inherit the descriptor (`subprocess` closes it). It is checked at start and before every pause, so a caller that takes the lock mid-run is not paused either.
- **No lock descriptor:**
  - The helper never has the lock open; each test runs `flock` in a child process.
  - A descriptor a caller passed down is closed before the command starts.
- **Nested** (a step run through the helper starts Blender through its wrapper): the inner call runs its command straight, in the outer group, and the outer call pauses it all. A second `setsid` would put the inner command out of the outer pause's reach. `SLOP_GATE_PAUSE_OUTER` names the outer call while it lives.
- **Signals:**
  - INT, TERM and HUP to the helper go to the command's group, continued first so a stopped command acts on them.
  - The command gets the default INT and QUIT back (`env --default-signal`); a script's `&` child has them ignored.
  - The exit code is the command's. A helper killed with `SIGKILL` cannot forward it, and leaves the group running.
- **Switches:** `SLOP_GATE_WAIT=0` turns waiting and pausing off. Without `/proc` or `flock(1)` (macOS) the command runs straight. The log is stderr and `~/.local/state/slop-build/gate-pause.log` (`SLOP_GATE_LOG`).
- **Blender.** On the dev-box, `blender` on `PATH` is [`living/tools/blender_gate.sh`](../living/tools/blender_gate.sh), a thin caller: `gate_pause.sh -- /usr/bin/blender "$@"`, logging to `~/.local/state/slop-build/blender-gate.log`. It finds the helper beside itself, then on `PATH`. Install both into `~/.local/share/slop-tools/build-bin/`, which is on `PATH` there:

  ```bash
  install -m 755 living/tools/gate_pause.sh ~/.local/share/slop-tools/build-bin/gate_pause.sh
  install -m 755 living/tools/blender_gate.sh ~/.local/share/slop-tools/build-bin/blender
  ```
- **The selftest** (a fake command that counts ticks, on a test lock; a gate is another process holding it): `python3 living/tools/gate_pause_selftest.py`. It checks the exit code, the pause and the resume, the cap, INT on the whole group (also while paused), no lock descriptor in the command (also one a caller passed down), the caller holding the lock without passing it down (no wait, and no pause when taken mid-run), the wait at start, `SLOP_GATE_WAIT=0`, a call with no command, and nesting (through the helper and through Blender's wrapper). `python3 living/tools/blender_gate_selftest.py` runs the same cases through `blender_gate.sh`.

## Building the render asset set

The scene gate's verify-ui `render` group draws with the game client's generated assets, which are git-ignored and made on the dev-box only (Blender, the clip library, the KTX2 encoder's AVX2 kernel). The gate therefore reads a fixed, read-only set: `~/slop-assets/<id>/`, with `~/slop-assets/current` linking to the pinned one. [`living/tools/render_set.py`](../living/tools/render_set.py) builds, checks, links and pins sets. How the gate uses one is under the scene gate, [Render asset set](#render-asset-set). In short, it runs `check` and then `link`: exit 1 means corrupt, exit 2 stale. Its fields change only by a name the gate asks for, not by a fork of the format.

**What a set holds.**
- `assets/`, laid out as `living/game/assets`. From the checkout:
  - the VRoid and KayKit bases;
  - the animated bases with their clips, the wolf and the deer;
  - `textures/`, `envs/<name>/`, and `view/` when present.

  From the composed bundle:
  - the types, pages, styles, strands, and `own-clips.glb` with its sidecar `own-clips.clips.json` (every person's gaits, their speeds and foot-down markers: without it the client gives people walk and run only, [CLIP_MARKERS.md](CLIP_MARKERS.md));
  - the look book.
- `bundle/`: the bundle as built, its `MANIFEST.txt` and the world look data it was checked against.
- `SET-MANIFEST.txt`: every file's sha256.
- `set.json`:
  - `bundle`: file, sha256, commit, port and pictures;
  - `main_commit`, for provenance only;
  - `generator_trees` (provenance), `generator_tree` (the generator hash) and `generator_exclude` (the list's file, sha256 and count);
  - `looks`: the book's generations and each world's;
  - `clips`;
  - `book_drift`.

`<id>` is the first 12 hex digits of the bundle file's sha256.

**Stale or corrupt.** `check` compares a set with a checkout:
- **corrupt** (exit 1): a file's sha256 differs, or a file is missing or extra;
- **stale** (exit 2): the checkout's generator hash differs from the set's, or a world's look generation (`living/seeds/worlds/<w>/looks.json`) is not in the set's book.

It also lists `warnings`, which change no verdict: a clip file under `lookdev/anim/` without its `.clips.json` sidecar (every set from `79072c65d37f` to `a7c606d204bb` lacks `own-clips.clips.json`). `build` refuses such a set, and one whose clips `marker_check.py` fails ([CLIP_MARKERS.md](CLIP_MARKERS.md)).

**The generator hash** (schema 2, since `render-set-exclude`) is a sha256 over every file of `living/tools/{blender,characters,textures}` (`git ls-tree -r`: mode, blob and path), less the non-generating tools listed in [`living/tools/render_set_exclude.txt`](../living/tools/render_set_exclude.txt), together with that list's own sha256. `build`, `check` and the bundle match all compute it with one function, `gen_hash`.
- **What it ignores.** A main commit outside those folders, or an edit to a listed check or measuring tool (`cloth_check.py`, `book_drift.py`, the reference's measuring tools, …), leaves a set `ok`.
- **What makes a set stale.** Any other edit inside them does, even one that changes no output: rebuild, or re-pack (below), and pin again after it lands. Changing the list itself does too, so it cannot be widened quietly.
- **How the list is kept.**
  - It holds explicit paths, no globs, each read before it was listed. A new tool stays a generator input until it is listed.
  - A file a generator imports is never listed: `build` refuses a list whose files a non-listed file imports (`exclusion_imported`), and a listed path that is not in the trees.
  - A file that both generates and checks (`pictures.py`, `shade_mean.py`) stays an input. Its check moves to a file of its own first, if it should be left out.
- **The selftest:** `python3 living/tools/render_set_selftest.py`.

**Re-pack, no Blender** (when only listed tools changed, or the hash's definition did). `bundle.py` and `render_set.py build` again, from a worktree at the new main with the last set's generated files in place. First restore the checkout-sourced files from the pinned set if anything rewrote them: `gen_buildings.sh` is not byte-reproducible. About 3 minutes. The assets come out identical (compare the two `SET-MANIFEST.txt`), with a new id and generator hash.

**Rebuild and pin** (dev-box, about 41 minutes beside other Blender work at `JOBS=2`; 2026-11-20: 2,768 files, 407 MB). Work in a worktree at main, with no tracked changes. Use the full clip library, `~/archive/clip-library`. `animate.py` and `gen_person.sh` read it from `.local/kimodo/library` first. The coordinator's `.local/kimodo/outputs/library` is partial.

```bash
mkdir -p .local/kimodo && ln -sfn ~/archive/clip-library .local/kimodo/library   # the full clip library, where the bakes look first
G=living/tools/gate_pause.sh                            # every build step gives a scene gate the machine (Heavy work during a gate)
$G -- just living-game-assets                           # 1-2: bases, textures, scenery, the bases' clip bake (under assets_guard.py)
$G -- living/tools/blender/gen_types.sh                 # 3: the 21 types and their pages
$G -- living/tools/blender/gen_styles.sh                # 3: hair, outfit and overlay styles, strands.png
$G -- python3 living/tools/characters/town.py .local/town --town living/seeds/cullet.json --models-only --no-pages --lod near --jobs 2   # 4: the 64 residents the checks need
$G -- env ONLY=present LOD=near living/tools/blender/gen_person.sh clips=man   # 5: the shared clip bake, own-clips.glb and own-clips.clips.json (marker_check must pass)
$G -- python3 living/tools/characters/bundle.py OUT --name render-set --with-clips --book SHIPPED_LOOKS.json \
    [--allow-book-drift living/tools/characters/book-drift-<generation>.json]   # 6: the checks, PNG and KTX2 bundles
$G -- python3 living/tools/render_set.py build --bundle OUT/render-set-<sha8>-ktx2.tar.gz   # 7: ~/slop-assets/<id>/, read-only
python3 living/tools/render_set.py check ~/slop-assets/<id>    # must print "ok"
python3 living/tools/render_set.py pin ~/slop-assets/<id>      # then, and only then
```

- **`--no-pages` (step 4).** Without it `town.py` writes town pages into `lookdev/pages/`. `pictures.py` then refuses them as pictures of no known class.
- **The book.** It is the one the last bundle shipped (`--book`), never one rebuilt in place.
  - `book_drift.py` rebuilds it into a scratch file. Outfit colours may differ by one level of 255.
  - Known larger differences pass only through a reviewed, tracked list: `book_drift.py --json` writes it, and `--allow-book-drift` reads it. Its path and sha256 go into the manifest and `set.json`.
  - `book-drift-c4-cbcc40bf.json` holds the 6 differences of 2026-11-20 (Wick Marl's smock jersey by 49 levels; the shipped book's colours were measured on an earlier build). The next generation, which rebuilds the book whole, deletes it.
- **A set is never rebuilt in place.** A new bundle has a new id. `pin` replaces `current` atomically.

**A generator branch builds its own** for its own render pass, without touching the pinned set. Its worktree, at its branch with no tracked changes, runs the same steps with `--root` set to a scratch root, and does not pin:

```bash
python3 living/tools/render_set.py build --bundle OUT/…-ktx2.tar.gz --root ~/slop-assets/branches/<branch>
python3 living/tools/render_set.py check ~/slop-assets/branches/<branch>/<id> && python3 living/tools/render_set.py link ~/slop-assets/branches/<branch>/<id> --repo .
```

`link` symlinks `lookdev`, `view`, `textures`, each `envs/<name>` and `characters/looks.json` into the checkout's `living/game/assets`. The client reads its assets from its own checkout (`lookdev::asset_root`, a compiled-in path), so each worktree that draws needs the links or its own build. `.gitignore` matches the links as it matches the folders. With port output (`SLOP_PORT=hair,ink`), pass `--port hair,ink` to `bundle.py`: it refuses a build whose port files do not match.

**Generated assets never change tracked files.** `just living-game-assets` runs under [`assets_guard.py`](../living/tools/assets_guard.py), which fails the run, naming them, if it changed any tracked file. The rules' footprint table (`living/rules/data/buildings.json`) is tracked because the authority and the client compile it in. It changes on purpose:
- `just living-rules-table` gathers it from the generated models' sidecars under `envs/`, Cullet's lots included, and prints the diff to review;
- the change merges as a rules change, through the gate with scenes.

**Follow-up: the table writers' opt-in.**
- **Today.** `gen_buildings.sh`, `gen_city.sh` and `gen_cullet.sh` still write the table on every full run. Their output equals the committed table, so the guard passes: on 2026-11-20 a full recipe run left every tracked file as it was.
- **The opt-in.** Making the write opt-in (`RULES_TABLE=1`) touches the hashed `blender` tree. It therefore goes in with the next change to the generator trees that rebuilds its own set (char-port-2's S6 or S8). The patch is `~/.t3/worktrees/slop-art-online/t3-b749c655-2e53274b9e364084/.local/rs/blender-optin.patch` on the dev-box.

**Known on main** (2026-11-20, `error-lines.txt` of the build). `gen_anim.sh`'s own `marker_check.py` exits 1: `strafe_run_left_v48` has "no contact window" for a foot on both VRoid bases, and so does `run_diag_br_v48` on Vivi. These are clip-library takes. The bake is written anyway, and the set records 84 clips a base.

## Reproducible generators

Two runs of a generator on the same code and the same Blender give byte-identical files. A difference between two runs is a defect in the generator, fixed there, not noise to allow for: the render set's hash, the flag-off parity of a look change and the GLB size checks all compare bytes.

**What made files differ (2026-11-21, Blender 5.2.2).** `bmesh.ops.create_uvsphere` gives the same vertices in every run, but the order of its faces round the poles changes from one Blender process to the next: two to three orders in five runs, at 8x5 and at 16x8. Two generators used it:
- the kerchief's knot (`make_kerchief`, `person.py`): the kerchief style and every resident wearing it differed in the `Cloth` mesh's index order between runs (4 runs, 4 different files), the "known triangle-order noise" of S6b's parity;
- the mushroom caps (`mushroom_cap`, `buildings.py`): small_city's mushroom houses, halls and towers (20 files).

**The fix.** [`living/tools/blender/stable.py`](../living/tools/blender/stable.py)'s `uvsphere` calls the op, then sorts the new faces by their sorted vertex indices (the vertices are stable), keeping each face's winding. Use `stable.uvsphere` wherever a UV sphere goes into a file. Icospheres, cones (with and without caps), cubes and convex hulls of seeded points were the same in every run.

**The selftest:** `python3 living/tools/stable_selftest.py [--runs 3]` builds each of these in separate Blender processes and fails if a stable result differs between them. It also reports how many orders the bare `create_uvsphere` gave (3 in 4 runs on 2026-11-21); that line is a note, not a check.

**The proof for the fix** (dev-box, branch `gen-repro`):
- **The kerchief style:** 4 runs, one file (`a138c5fe68dd`).
- **`gen_buildings.sh`:** two full runs, 1,096 of 1,096 files byte-identical, the 20 with mushroom caps among them.
- **The kerchief's two residents,** `own-nan-fenwick` and `own-vessa-pontil`: two builds each, and their animated GLBs, byte-identical.
- **Against main** (main's residents, and the pinned set `a7c606d204bb`'s 1,096 building files): 1,076 building files are byte-identical. The 20 with mushroom caps and the residents' `Cloth` mesh have the same vertex data and the same triangles with the same winding; only their index order differs. The fix changes bytes once, in order only, so the render set needs one re-pack after it merges.

**Not run twice here:** `gen_city.sh`, `gen_nature.sh` and the other generators build no UV sphere (city and Cullet use `buildings.py`, but not its mushroom caps); `gen_cullet.sh` was already byte-identical on two runs ([CULLET_KIT.md](CULLET_KIT.md)). Another machine or Blender version has not been compared.

**To check a generator:** run it twice into two scratch out_roots and `cmp` every file. For a GLB that differs, compare its JSON, its vertex accessors and its triangles as a set (winding kept) before its index order: only an order difference points at an op like this one. A scratch `gen_buildings.sh` run rewrites the tracked `living/rules/data/buildings.json` ([above](#building-the-render-asset-set)); `git checkout` it afterwards.

## build-slot, the laptop's heavy-job slots

[`living/tools/build-slot`](../living/tools/build-slot) runs a heavy command (a release build, `just living-check`, a Blender bake) only when one of the laptop's slots is free, and starts nothing new while the owner plays (`.local/build-slots/session`, held by `play.py`; [Play with one command](LIVING_CORE.md)). Until 2026-11-21 it lived only as an untracked file in the main checkout's `.local/bin`; the tracked copy is that file plus the fix below. The laptop runs an installed copy, so a change here takes effect only after installing it:

```bash
install -m 0755 living/tools/build-slot /Users/carlid/dev/slop-art-online/.local/bin/build-slot
```

- **Where.** `BUILD_SLOT_DIR` (default `/Users/carlid/dev/slop-art-online/.local/build-slots`) holds `slot-N/` holders (`pid`, `start`, `label`, `since`) and `waiting/<pid>` files (a status line, then `start=<process start time>`). `BUILD_SLOTS` (3), `BUILD_SLOT_MIN_FREE_GB` (25) and `BUILD_SLOT_SCCACHE` are unchanged.
- **Dead and reused pids.** A waiter killed while waiting used to leave `waiting/<pid>` forever, and `--status` kept listing it. Now every scan (`--status`, and each pass of a waiting job before it looks for a slot) drops a holder or waiter whose pid is gone, or whose pid now belongs to a process with another start time (the pid was reused). The start time is `ps -o lstart=` read with `LC_ALL=C TZ=UTC` on macOS (the same text `play.py`'s `proc_identity` reads, spaces squeezed) and field 22 of `/proc/PID/stat` on Linux. A record without a start time, from an older build-slot, is dropped only when its pid is gone. `--status` says what it dropped. `play.py`'s `held_slots` skips a slot whose recorded start differs from its pid's, so a reused pid does not hold the game back either. A waiter that exits normally removes its own file.
- **Self-test.** `bash living/tools/build_slot_selftest.sh` (about 15 s, scratch `BUILD_SLOT_DIR` under `$TMPDIR`): a real holder and a real waiter behind it, a dead waiter in each format, a live pid recorded with another start time and a live old-format waiter; then a dead holder, a reused-pid holder and an old-format live holder, and a job that reclaims reused-pid slots. Only the dead and reused records go.
- **Not fixed.** Two waiters can both judge the same slot dead and one can remove the other's fresh claim (unchanged from before; the slots are advisory).
- **Other machines.** The Spark's merge queue uses its own copy (`~/slop-mq/build-slot`); it is not this file.

## The dev-box's CPU governor

**Since 2026-11-22T12:25:36+01:00 (11:25:36 UTC) the dev-box runs the `performance` governor on all 32 cores** (owner's approval, through the general coordinator). The driver is `amd-pstate-epp`; setting the governor also sets every core's energy-performance preference to `performance`. Before that it ran `powersave` with preference `balance_performance`.

**Why.** Under `powersave` the cores' power states made a busy host faster than a quiet one: a do-nothing process waking every 200 µs made a 200-fighter battle's tick 12% cheaper ([RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md)). A measurement compared against a quieter reference read low (VIEWER_FLOOR's per-viewer costs by about 18%), and the gate's timing-sensitive scenes depended on what else was running.

**How it persists.** `cpupower` is not installed, and neither `tuned` nor `power-profiles-daemon` runs. A oneshot unit, `/etc/systemd/system/cpu-governor-performance.service` (enabled, `WantedBy=multi-user.target`), writes `performance` to every `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` at boot. Check: `cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c` and the same for `energy_performance_preference`; `systemctl status cpu-governor-performance`.

**Measurements before and after the switch are not comparable.** Record the governor with every cost measurement (`host.json`), and compare only runs on the same governor. Runs before the switch should still have been measured warm (a poller keeping the host busy) to approximate it.

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

## Look-dev shoots (`living/tools/lookdev_shoot.py`)

`living/tools/lookdev_shoot.py` (or `just living-lookdev-shoot ...`) reproduces the standard look-dev scene under identical Cullet atmosphere, clear weather, lighting, and camera poses on both macOS (laptop) and Linux/AMD (dev-box), with no host-specific paths:

- **Offline character stage (`--mode characters`, default):** runs `living-game` with `LIVING_GAME_VIEW` + `LIVING_GAME_VIEW_ENV=cullet` + `LIVING_GAME_VIEW_ATMO=1` across `noon` (`12.0`), `dusk` (`17.7`), and `night` (`22.5`) at the five locked camera poses (portrait close-up, 3/4 full-body, 3/4 back-rim, Play Near, Play Middle), stitches one 3×5 contact sheet per character (via Pillow, ImageMagick `montage`, or `uv` + Pillow), and writes `manifest.json`. Add `--ortho` for the orthographic measuring view (`front,side`). Default `--models` are the three Cullet calibration residents (`look:lk_5715bc7d45d32adf`, `look:lk_650c702f194b7d76`, `look:lk_5edbeda57773525d`).
- **Live Cullet plaza (`--mode plaza`, or `--mode both`):** launches a scratch `verify-ui-lookdev-*` Cullet world via `verify.py`, drives `drive.py` at the Counting House yard plaza `(536.5, 767.5)` with 14 held residents across Middle and Near at Noon, Dusk and Night (6 stills + `plaza_sheet.png`), and cleans up the scratch database on exit. Add `--bench` for uncapped steady-state frame-time capture (`LIVING_GAME_FPS_CAP=0`, `LIVING_GAME_FRAMES`), outputting `frametime_summary.json`.
- **Settings and binary discovery:** accepts `--quality low|medium|high`, `--render-scale 67|75|85|100|auto`, `--film`, `--hair-shine`, `--weather`, `--look`, `--perf`, `--size`, and repeatable `--env KEY=VAL` (or inherits `LIVING_GAME_*` from the environment). Finds the release binary from `--bin`, `$LIVING_GAME_BIN`, `$CARGO_TARGET_DIR/release/living-game`, `.local/target/release/living-game`, or `living/target/release/living-game`. Run `python3 living/tools/lookdev_shoot.py --help` for full usage.
- **Live 2x captures:** headless shoots render at scale factor 1, so lines are 1 px at every render scale. To see what a Retina player sees, add `--env LIVING_GAME_WINDOW=1 --env LIVING_GAME_FULLSCREEN=1 --size 1512x982`: the client opens borderless on the whole primary display (`main.rs`; 3024x1898 physical on the laptop's notched panel) and `shot:` photographs the window. Add `--env LIVING_GAME_VSYNC=0` with `--bench` for a live frame-time run. `--perf upscale=bilinear` or `--perf sharpen=S` A/B the scaled composite (`graphics.rs` `Upscale`).
