# Isolated arena matrix

Rules `m1-9-arenas.1` support multiple bounded experiments in one authoritative SpacetimeDB world. The initial matrix is a 76×35 map containing six 24×16 interiors, separated by sealed walls.

| Row / environment | Left | Middle | Right |
|---|---|---|---|
| Open | Luna low, actors 1–2 | Luna medium, actors 3–4 | Luna high, actors 5–6 |
| Corridors | Luna low, actors 7–8 | Luna medium, actors 9–10 | Luna high, actors 11–12 |

Each pair contains Mira, driven by the host's actual built-in participant harness, and Tovan, driven by a separate model client through MCP. Orange identifies the built-in character; blue identifies the external character. The viewer opens on the whole matrix, disables labels by default, and provides arena focus buttons and individual inspection. `O` toggles labels.

## Isolation and controls

The scenario declares each arena's bounds, membership and observer-only experiment metadata. Initialization rejects overlapping interiors, unsealed perimeters, misplaced actors/sites, and inconsistent membership. Movement destinations, location guards, path search and committed position effects stay within the actor's arena. Cross-arena perception, speech delivery, death observation and damage are denied by the engine even if an operator-authored skill/law would otherwise allow them. Same-arena gameplay formulas remain scripted in Rhai.

Participants receive only their arena's surveyed walls and bounds. They receive no other arena metadata, actor state, resource map, hazard map or model settings. Coordinates remain global cell IDs (`y * 76 + x`), so translated arena coordinates differ. Observer snapshots show the whole world. All arenas use one clock, ruleset, metabolism and update cadence.

The three copies of each environment start with the same pair of personas, supplies, site quantities, hazards and unverified food report, translated into their arena. Open and corridor variants differ only in internal walls. Boundary walls are the same in both. The configured seed is 73; the runtime does not claim repeatable model outputs.

For this matrix both runtimes use serial behavior → communication → learning rotation, with 15 seconds after each completed call and a maximum of six calls per actor. The supervisor releases host harnesses and starts external workers when the shared clock resumes. Initial inference does not pause simulation. Each call has one attempt and a 300-second provider deadline; the five-minute supervisor cancels unfinished work. This is an experimental harness schedule, not a claim of adaptive individual reconsideration. Old two-character launches retain their previous schedules.

The Chat Completions adapter now validates and sends explicit `reasoning_effort` only when configured and declared supported. [OpenAI's Luna model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna) lists low, medium and high among its supported settings. The configured Carlid endpoint returned HTTP 200 and an `OK` completion for all three requested settings. Its response does not attest to effective upstream reasoning effort; experiment labels therefore identify **requested** settings. Initial Python-default-user-agent probes were rejected with 403; probes using the explicit `sao-reasoning/1.0` user agent succeeded, and the production adapter now uses that user agent.

## Run and iterate

Prepare the checked-in example:

```bash
python3 scripts/prepare_arena_matrix.py
```

It produces `scenarios/luna-arena-matrix.json` and `configs/experiments/luna-arena-matrix.json`. The latter maps each actor to a runtime and complete provider configuration containing credential references, never credentials. Edit those artifacts for different providers/settings or authored environments; rerunning the generator restores the six-cell example. Host startup validates the complete manifest and scenario before creating the world.

After building the authority, host, MCP example and Bevy client as in the grid/browser runbooks:

```bash
python3 scripts/run_living_clearing.py \
  --output output/luna-matrix-next --port 18924 \
  --minutes 5 --calls-per-actor 6 \
  --scenario scenarios/luna-arena-matrix.json \
  --controllers configs/experiments/luna-arena-matrix.json
```

Choose an unused port and a new output directory. This starts one session with all twelve controllers, retains inference/receipts and snapshots, pauses at the deadline, and leaves the observer available. A fresh matrix is launched through this supervisor so external processes are enrolled too; the viewer's ordinary fresh-session button is hidden for matrices.

## Verification and evidence

- Core: 56 tests, including bounds rejection, cross-arena visibility/speech/damage denial, scoped surveys, sealed membership validation, reload and movement through the full twelve-character world.
- Bridge: 31 library tests, five host tests and one simulator test, including explicit reasoning effort validation/wire preservation.
- Client: render regression plus WASM build; browser overview, labels-off default and arena focus checked visually, with no browser errors.
- Real published authority: `output/luna-matrix-isolation-check/verification.json` records a denied cross-arena participant command, denied observer command, and identical five-cell routes/energy costs through the participant API. This test uses its own fixture run in the published database and does not alter the live matrix.
- Live run: `output/luna-matrix-20260905`, run `sim-bevy-1788618753300`; per-actor configs, actual inference journals, authority snapshots, measurements and screenshots retained there. See `LIVE_RESULT.json` in that directory for the completed run's aggregate observations.

The five-minute smoke run completed at 300.05 seconds (1,692 authority updates), with 66 started model calls, no detected scope violations in recorded contexts/movement and no script errors. All six internal characters survived at 100 HP; the external character in medium/corridors also survived at 100 HP, while the other five external characters died. These are observed outcomes, not evidence that one reasoning setting or runtime is superior. Rejected proposals and cancelled unfinished calls remain in the journals and supervisor report.

Regenerate the read-only aggregate with:

```bash
python3 scripts/summarize_arena_matrix.py output/luna-matrix-20260905
```

One pair per cell is an exploratory comparison, not a statistical ranking of reasoning levels. Global cell IDs, provider latency/concurrency, nondeterministic generations and finite call budgets affect outcomes. Internal versus external differences also include distinct prompts and personas. Controlled replication and role/persona swaps are needed to attribute effects to a controller. A 50 ms scheduled interval is a target; elapsed authoritative time is measured independently and heavy model/subscription activity can lower the observed update rate.
