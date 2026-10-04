---
name: verify
description: Entry point for verifying Slop Art Online's living core. Picks the surface skill for a change or a symptom (core, generation, client, player, minds, llm, knowledge), and owns the shared harness (launch, doctor, scratch databases, SQL, player identity, observer, cleanup, evidence). Use before claiming living-core behavior works, when a change touches a surface, or to find which layer an error comes from.
---

# Verify the living core

The living core (`living/`, see `docs/LIVING_CORE.md`) is verified surface by surface. Each surface has its own skill and feature map, so a failure can be traced to the layer that owns it. This skill holds what they share: the harness, the safety rules, the evidence conventions and the map from changes and symptoms to surfaces.

## Surfaces

| Surface | Skill | What it proves | Free tier | Opt-in tier |
| --- | --- | --- | --- | --- |
| Core rules and loop | `verify-core` | 60 Hz tick, behavior graphs, skills and laws, needs, life course, wildlife, combat, deliberate acts | scripted scenes and cargo tests | – |
| World generation | `verify-generation` | worlds built from seeds: map, settlements, people, animals, resources; authored-world compilation | publishes and compiles | model drafting of authored worlds |
| Client protocol | `verify-client` | what a connecting client sees and may do: subscriptions, table and view visibility, reducer permissions per identity | WebSocket probe client | – |
| Human player | `verify-player` | a person's character: join, move, act, speak, refusals | player identity over HTTP | – |
| Internal agents (minds) | `verify-minds` | the mind service turns requests into installed behavior, speech and consolidated memory | real mind service against a fake model server | real models, short and capped |
| LLM integration | `verify-llm` | model routing, overflow, outage gate, JSON repair, journaling | fake provider scenarios | one live check per provider |
| Knowledge | `verify-knowledge` | know-how, tablets, teaching, learning; the personal memory graph, recall and fading | scripted scenes, scratch Neo4j runs | – |
The browser observer (`living/viewer`) has no verification skill. It is a simple developer client that a proper game UI will replace. When that UI is integrated, create a UI skill with `create-verification-skill` that clicks through it and matches the screen to the authority. Until then, `verify-core` covers the viewer's display sync (`living/viewer/src/sync.rs` tests), and `$V observer shot` takes a screenshot of a scratch world.

External agents (a provider-agnostic connector) are not implemented yet. When the connector exists, `verify-agent-external` gets a scripted tier and a real-agent tier.

Opt-in tiers make paid model calls. Run them only after the user authorizes that specific run.

## Which surface to verify

- **For a change:** run the skill of every surface the change touches.
  - Tables, reducers, subscriptions or views also touch `verify-client`.
  - A rule that minds rely on also touches `verify-minds`.
  - Viewer display sync touches `verify-core`. Viewer controls and panels have no skill until the proper UI exists; check them by hand with `$V observer start` and a browser.
- **For a symptom, find the lowest layer that still reproduces it.** Do not stop at the first layer that shows the failure; an authority defect shows in the observer too. At each boundary, check that layer's input and output, and keep going down while the failure persists:
  1. **Screen.** Does the observer show something other than the rows the client receives? Check by hand or with `$V observer shot`; there is no UI skill yet.
  2. **Client.** Does a real client fail to receive or call what it should? Subscribe to the exact rows with `.agents/skills/verify-client/scripts/drive.py --run <run> --query "<SQL>" --seconds 10 --save <name>` (add `--as-player` for the player's view); see `verify-client` "Check one query during triage".
  3. **Who acted.** For something a player did, `verify-player`. For something an AI character did or said, `verify-minds`, then `verify-llm` for what the model was sent and returned, and `verify-knowledge` when it concerns what a character knows or remembers.
  4. **Rules.** `verify-core` for the rule's effect, and `verify-generation` when the world was built wrong.

  Example: a speech line missing from the UI. If the client receives the `chronicle` row, the viewer owns the bug. If no row exists, check who should have spoken. A player's `human_say` is covered by `verify-player`. A mind's line is covered by `verify-minds`; that line exists only if the model replied, which `verify-llm` checks. Only when the reducer was called and still wrote nothing is it `verify-core`.
- **After a surface's shape changes** (its tables, reducers, protocol, controls, seed or config format), run `maintain-verification-skill` on that surface's skill in the same change.

## Shared harness

All surface skills use `scripts/verify.py` (Python standard library only), run from the repository root. Let `V=.agents/skills/verify/scripts/verify.py`. A surface skill may ship its own scripts in its own `scripts/` directory, but launch, cleanup and identity handling stay here.

Every run has a name (`--run <run>`) and a directory `.local/living/verify/<run>/` (git-ignored) holding `state.json`, `actions.log`, saved SQL snapshots and screenshots. Use a distinct run name per surface and attempt, for example `core-0412`, so concurrent runs never share a database.

### Launch

```bash
$V launch --run <run> [--seed world]
```

- Starts the SpacetimeDB container `sao-living_spacetimedb_1` (`http://127.0.0.1:3300`, image `v2.10.1`) if it is down, without Neo4j, and records that the run started it. Startup takes 1–2 minutes. The helper polls `/v1/ping` because `docker compose up --wait` can hang under podman-compose.
- Builds the module from the working tree. The default seed is `living/seeds/world.json` (`realm-4`: 512×512 tiles, about 190 people and 80 animals). Another `--seed <name>` builds in `living/target/verify-<seed>` and leaves the active module alone.
- Publishes a fresh `verify-<run>` with `--delete-data` and installs `living/scripts/skills.rhai`. The world ticks at 60 Hz right away. AI characters run their instinct graphs until a mind connects.
- `--keep-data` updates the run's existing database in place instead, as `just living-publish` does for the active world. Use it to prove that minds and clients recover from a module update with their data intact.
- `--target-dir DIR` builds the module in `DIR`, for example `.local/living/verify/<run>/target`, so a run never shares a build directory with another run. The module is copied into the server's `/wasm` mount as `living_authority_verify_<run>.wasm`, and cleanup removes the copy.

### Doctor

```bash
$V doctor --run <run>
```

Read-only. It confirms:

- the container is up and answers `/v1/ping`;
- the image is `v2.10.1`;
- `verify-<run>` exists, is not paused, and its `stats.ticks` advances;
- the module is newer than the authority sources;
- the observer answers, when this run started it.

Run it before the first drive and after anything surprising.

### Identities and state

- `$V call --run <run> REDUCER 'ARGS_JSON' [--as-player | --as-admin] [--expect-refusal TEXT]` calls any reducer over HTTP. Without a flag it calls anonymously. `--expect-refusal TEXT` succeeds only if the call is refused with `TEXT` in the error, which proves a permission without putting a token on the command line, for example `$V call --run <run> set_paused '[true]' --as-player --expect-refusal "admin only"`.
- `$V player --run <run> join|move|act|say …` calls the player reducers (`join`, `human_move`, `human_act`, `human_say`). It uses a fresh non-admin identity from `POST /v1/identity`, kept in `state.json`.
- `$V sql --run <run> "<query>" [--as-player | --as-admin] [--save NAME]` runs SQL over HTTP.
  - With no flag it runs anonymously and sees only public tables, as an observer does.
  - `--as-player` uses the run's player identity.
  - `--as-admin` uses the world admin's token, read from the container's CLI and kept in memory. It reaches private tables such as `deliberation`. Use it to inspect state, never to prove a permission.
  - `--save` writes the rows to `<run>/NAME.json`.
- Admin calls go through `living/tools/stdb` (the in-container CLI identity is the world admin), for example `living/tools/stdb call -s local verify-<run> place_near 12 40`. Admin calls only set up scenes; they never prove what a player or client can do.

### Observer

```bash
$V observer --run <run> start            # trunk serve on :8330; the first build can take minutes
$V observer --run <run> shot <name>      # headless Chromium screenshot of ?db=verify-<run>
```

One observer on `:8330` serves every run. `.local/living/verify/observer.json` records its process (pid and start time) and the runs using it. A second run's `start` joins it; each run's cleanup leaves it running until the last user leaves. An observer started outside verification is used but never stopped.

### Cleanup

```bash
$V cleanup --run <run> [--keep-db]
```

- Leaves the observer if other runs still use it; otherwise stops it.
- Deletes `verify-<run>`; a scratch world left behind keeps ticking and writing its log.
- Stops the SpacetimeDB container only if this run started it and no other `verify-*` database is live, with a 60 s grace period. Exit code 137 means podman forced the stop with SIGKILL; report it as forced. The server runs as PID 1 and handles SIGINT but not SIGTERM. Cleanup therefore sends SIGINT, and `living/deploy/compose.yml` sets `stop_signal: SIGINT`; a clean stop exits 0 within a second.
- Drops the player token. The evidence directory is kept.

Run cleanup after failed attempts too.

## Safety rules

- Only publish or delete `verify-*` databases. The same server holds paused reference worlds (`aske-coast*`, `stage*`). Never publish, reset, pause or delete them, and never run `living/tools/lab.py --reclaim`.
- `just living-reset` and `just living-publish` target the active world. Do not use them for verification.
- Kill only processes your run started, by pid. Never `pkill -f` a pattern that also appears in your own command line.
- Neo4j: `:7689` (A) is full and holds the paused worlds' minds; never write to it. Mind-side checks use run names starting with `verify-`, and their cleanup removes only nodes with that run.
- The public observer (`sao-observer-web`, `sao-tunnel`, `https://sos.carlid.dev`) is a production service. Do not rebuild or restart it during verification.
- Concurrent runs share the SpacetimeDB server and the observer. Cleanup stops the container only if its own run started it and no other `verify-*` database is live. It stops the observer only when it is the last run using it.
- `LIVING_STDB_URL` may only name the local container (`http://127.0.0.1:3300`). Publishing goes through the container's CLI, so any other URL would split one proof across two servers; the helper refuses it.

## Evidence

A proof contains three things:

- **the action:** `actions.log`, with each reducer call and its status;
- **the resulting state:** before and after snapshots from the authority;
- **the visible result:** a screenshot or client log, for changes a user sees.

Proof standards:

- Exercise the real path for the surface. A player acts through the player identity; a client proof uses a real client connection; a mind proof uses the real `living-mind` binary.
- A `200` response proves acceptance, not effect. Check the effect in the tables.
- Record refusals with their error text when a refusal is the behavior under test.
- Name the commit and whether `living/` had uncommitted changes; `launch` logs both.
- Say what was not covered.
- These skills do not establish performance or scale. Those claims follow `AGENTS.md` and `docs/PERFORMANCE_CONTRACT.md`.

Each surface skill has `features/README.md` (its map) and `references/validation.md` (the last real run). `references/validation.md` in this directory records the first harness run.
