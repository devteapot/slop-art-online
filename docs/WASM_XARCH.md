# Cross-host wasm differences: diagnosis

Status: **diagnosis only, no fix applied** (Spark, 2026-11-22, branch `wasm-xarch`, not merged). Follows [Byte-identical wasm](TOOLING.md#byte-identical-wasm). Since `wasm-remap` the authority wasm builds the same bytes within one OS and architecture, but not across them. The rest of this note explains why and gives a fix to review.

## Facts

Commit `299da4eb`, island seed, `cargo build --locked … -p living-authority --target wasm32-unknown-unknown --release`, rustc 1.99.1:

| Host | sha256 | Size |
| --- | --- | --- |
| Spark, Linux aarch64 (`aarch64-unknown-linux-gnu`) | `c9a6cbaf…f566` | 16,991,630 B |
| Laptop, macOS aarch64 (`aarch64-apple-darwin`) | `724dd073…b9cf` | 16,990,457 B |
| dev-box, Linux x86_64 (`x86_64-unknown-linux-gnu`) | `4435992654c7…` | 16,997,417 B |

## The cause: the host triple in cargo's metadata hash

The only host input left is the `host:` line of `rustc -vV`. It reaches the module through cargo's `-C metadata` hash, which sets each crate's StableCrateId.

**Proof.** The Spark rebuilt `299da4eb` with one change: a `build.rustc` wrapper made `rustc -vV` report a different `host:` and passed every other call to `living/tools/rustc-remap` unchanged.

- Reporting `aarch64-apple-darwin` gave `724dd0730a987e2cc1407167967829129632b7606295729647a2bc1a9ea0b9cf`, 16,990,457 B: the laptop's file, byte for byte.
- Reporting `x86_64-unknown-linux-gnu` gave `4435992654c7ee081de8115f5a7756910c768042c20ed2ce335611eecad1712f`, 16,997,417 B: dev-box's module.

Nothing else differs between the hosts: no host libm, LLVM host folding, `include_bytes!` or build-script output.

**Mechanism.**

- Cargo hashes the `host:` line into the metadata of host units: build scripts and proc-macros.
- A target crate's metadata mixes in its dependencies' metadata, build scripts and proc-macros included.
- So every wasm crate that depends on a build script or proc-macro, directly or transitively, gets a host-dependent StableCrateId.

This matches cargo's `hash_rustc_version`, which omits `host:` for target units. That description is from memory and was not checked against cargo's source. The target directories show the pattern directly:

- `libbitflags-2f49a6056b0b5cdb` and `libsmallvec-69b95b7fd8c734bf` were equal under both "hosts".
- `serde_derive`, `rhai_codegen`, `const_random_macro`, and the `serde`, `serde_json` and `ahash` build scripts differed, and so did `rhai`, `serde_json`, `ahash` and `living_rules`.

In the module, 21 cargo-built crates have a different disambiguator, including `living_authority`, `living_rules`, `rhai`, `serde*`, `spacetimedb*`, `libm`, `ahash`, `decorum`, `ethnum`, `rand`, `smartstring` and `once_cell`. Eight are equal: `bitflags`, `bytes`, `http`, `itoa`, `log`, `rand_core`, `smallvec` and `thin_vec`. The standard library is prebuilt and equal.

## What differs in the module (Spark against laptop)

Functions were compared after demangling, normalizing the duplicate-name prefixes and masking data addresses.

- **Names:** the name section differs in mangled crate hashes and `.llvm.<n>` suffixes (2,630,896 B against 2,628,148 B). It has no runtime effect.
- **Data:** the data section is the same size, 3,898,045 B. It holds the same strings in a different order, and its pointers differ.
- **Code:** 13,942 of about 14,200 functions are identical; 14,198 against 14,204 functions in all.
  - **190 functions, mostly rhai:** 38 distinct `i64.const` values differ. These are TypeIds of types defined in the affected crates, which hash the StableCrateId. rhai mixes TypeIds into its function hashes (`calc_fn_hash`, `FnManifestEntry::calc_hash`, `Engine::resolve_fn`), so its function tables hold different hash values.
  - **About 20 functions:** codegen-unit placement changed inlining, mainly in spacetimedb-sats/lib serialization, rhai package `init` and `living_rules::script::engine_with`. Identical-code folding also kept different names, for example `libm::ldexpf` against `scalbnf`.
  - **24 functions:** function-table indices differ.
  - In all: 256 against 262 changed bodies, and 7 against 13 functions present in only one module.
- **Semantics: unchanged.** Both plain island worlds finished genesis (40 of 40 steps) with byte-equal `land`, `land_plan`, `lot` (718), `terrain_chunk` (16,384), `settlement`, `place` (1,643), `genome`, `community` and `skill_code`. `resource_node` (66,934) is the same multiset; its auto-increment ids differ. `character`, `structure` and `script` differ only in timestamps.

## Effect on genesis fuel

The measurement used a private `clockworklabs/spacetime:v2.14.1` container pinned to CPUs 0-4,10-14 and `genesis_fuel.py` on stepping builds.

| Module | init per run | Δ init | All of genesis (init + 40 steps + finish) | Δ total |
| --- | --- | --- | --- | --- |
| Spark (real) | 11,830,909,661 | — | 107,528,432,349 | — |
| as macOS aarch64 | 11,716,765,633 | −0.965% | 107,404,260,807 | −0.115% |
| as Linux x86_64 | 11,757,102,991 | −0.624% | 107,442,035,674 | −0.080% |

- Plain modules' init on the same server: Spark (`c9a6cbaf`) 11,830,910,341 per run, laptop file (`724dd073`) 11,716,766,313 (−0.965%).
- Step labels are equal on all three. The largest per-step change is in `chunks`: +0.47% and −0.36%.
- The init offset is most likely rhai engine setup hashing TypeId-derived keys. That is not separated from the inlining changes.

This replaces the earlier "about 0.02% from embedded paths" explanation: init fuel moves by up to 1% with arbitrary crate hashes. The same happens on one host whenever a dependency's metadata changes, for example a build-dependency version or a feature.

## Proposed fix (not applied)

For `wasm32-unknown-unknown` compiles only, `rustc-remap` replaces cargo's `-C metadata=<hash>` with a hash of host-independent inputs:

- `CARGO_PKG_NAME`, `CARGO_PKG_VERSION`
- `CARGO_MANIFEST_DIR` with its `CARGO_HOME` or checkout prefix replaced by `/cargo` or `/src`
- `--crate-name`, `--crate-type`, `--edition` and every `--cfg` (features)

Cargo's `-C extra-filename`, file names and native compiles stay as they are.

**Prototype result:** built on the Spark with each of the three `host:` lines, the island module was `fed4fb69599f5c31…`, 16,997,265 B, identical all three times. Its plain init was 11,826,030,090 per run (−0.04% against today's Spark module).

The prototype, inserted in `rustc-remap` after the native `exec` and before `map=`:

```sh
checkout=$(cd "$(dirname "$0")/../.." && pwd)
ch=${CARGO_HOME:-$HOME/.cargo}
mdir=$CARGO_MANIFEST_DIR
case "$mdir" in "$ch"/*) mdir=/cargo${mdir#"$ch"} ;; "$checkout"/*) mdir=/src${mdir#"$checkout"} ;; esac
key="$CARGO_PKG_NAME $CARGO_PKG_VERSION $mdir"
prev=
for a in "$@"; do
  case "$prev" in --crate-name|--crate-type|--edition|--cfg) key="$key $prev=$a" ;; esac
  case "$a" in --edition=*|--crate-type=*) key="$key $a" ;; esac
  prev=$a
done
meta=$(printf '%s' "slop-meta-v1 $key" | sha256sum | cut -c1-16)
n=$#; i=0; skip=
for a in "$@"; do
  i=$((i+1))
  if [ -n "$skip" ]; then skip=; set -- "$@" "metadata=$meta"
  elif [ "$a" = -C ] && [ $i -lt $n ] && eval "case \"\${$((i+1))}\" in metadata=*) true;; *) false;; esac"; then set -- "$@" -C; skip=1
  else case "$a" in -Cmetadata=*) set -- "$@" "-Cmetadata=$meta" ;; *) set -- "$@" "$a" ;; esac
  fi
done
shift $n
```

macOS has `shasum -a 256` rather than `sha256sum`, so a real version needs a fallback. The laptop and dev-box should then each build once and confirm `fed4fb69…`.

**Risks:**

- **Every host's module changes once.** TypeIds and inlining change, so init fuel moves by about 0.04% on the Spark and more elsewhere. Re-record any baselines, bump the `/slop-remap-v1` marker to `v2` so cargo and sccache rebuild, and run the scene gate once.
- **StableCrateId uniqueness** now rests on (package, version, source dir, crate type, features). Two wasm units can share those only if cargo built one package twice for wasm with the same features. That does not happen in this workspace. If it did, rustc would refuse the collision loudly instead of miscompiling.
- **The workspace no longer controls metadata alone.** A dependency's metadata no longer changes a dependent's StableCrateId. That is intended; cargo still rebuilds through its own fingerprints.
- **Not an option: faking `host:` in `rustc -vV`.** Cargo uses it as `TARGET` and `HOST` for native builds, which would make C build scripts cross-compile.
