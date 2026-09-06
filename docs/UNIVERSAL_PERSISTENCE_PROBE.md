# Universal law capability and persistence probe

This is an explicit, no-model tooling fixture. The runner deliberately chooses the law source and directs each action through separate authenticated participant sessions. It demonstrates executable capability and persistence; it does not demonstrate autonomous discovery, autonomous teaching, or general correctness of a law.

The frozen scenario starts with no knowledge or active laws. Actor 1 alone holds the west territorial editing grant. Actors 2 and 3 hold no territorial editing grants. Actor 1 pays for a three-quantum prototype, retrieves its code and private experiment, explicitly inspects and assesses its source, installs it locally, then physically teaches only the code to actor 2. Default catalogs omit source, so both actors obtain source through actual `InspectLaw` observations.

Actor 2 inspects and assesses the taught code. An actual universal installation attempt fails without a matching personally assessed experiment. Actor 2 then pays for a separate three-quantum universal practice of that exact source against the current universal binding, retrieves and assesses its own proof, and installs universal revision 1. The teacher's private case and proof never enter the learner's holdings. Each job consumes six electricity and three water.

Actor 3 stays east and actually gathers at four boundaries. Measured energy costs are expected to be 4 before any edit, 4 after the west-only edit, 1 after the universal edit, and 1 after the installer dies. The scenario schedules fatal damage to actor 2 at 180,000 simulated milliseconds. Setup must finish before 120,000 ms; final observation must occur before 200,000 ms. Execution has a fixed 300-second wall ceiling. These bounds are fixed before authority connection. A failed setup is retained as noncompletion and the diagnostic still attempts to capture the scheduled death boundary.

## Run

Build the additive example from the workspace containing the source:

```sh
cargo build --locked -p bridge --example participant_universal_persistence_probe
```

Preparation is the default and opens no authority connection:

```sh
python3 scripts/run_universal_persistence_probe.py \
  --implementation output/society-lab/implementations/reality-m7-1 \
  --output output/society-lab/universal-probe-prepared
```

For execution, first use a freshly published local authority whose clocks are all paused. Supply its existing `active.json`, a new output directory, the additive example binary, and the explicit local operator CLI config:

```sh
python3 scripts/run_universal_persistence_probe.py --execute \
  --implementation output/society-lab/implementations/reality-m7-1 \
  --active output/society-lab/reality-m7-universal-authority-check/active.json \
  --output output/society-lab/reality-m7-universal-authority-check/new-universal-probe \
  --probe-binary target/debug/examples/participant_universal_persistence_probe \
  --cli-config .local/credentials/bevy-cli.toml
```

The runner creates a uniquely named fresh run in that authority. It retains the declared scenario, fixed bounds, each accepted command receipt, actor-scoped observations, an operator snapshot with contiguous authority events, and validation results. It pauses the owned clock and revokes the four diagnostic identities on completion or failure, then verifies paused clocks and zero remaining grants for its run. Credential files are private local session material and should not be committed or shared.

The authority audit verifies actual teaching, denial before personal proof, teacher local activation, exact source/hash/scope/operator/binding, three paid quanta per job, actual installer death caused by the predeclared disturbance, universal installation surviving that death, and all four east physical effects. The snapshot used for these checks is taken after pausing and before identity revocation; cleanup is recorded separately. No production or frozen implementation code is modified.

## Retained evidence

The first execution is retained under `output/society-lab/reality-m7-universal-authority-check/universal-probe`. It did not complete setup because the initial helper incorrectly expected source in the redacted holding catalog. It observed the fixed installer death, left universal law inactive, paused successfully, and revoked its diagnostic identities. The additive helper was corrected to use actual terminal inspection; the deadline and scenario were unchanged for the fresh retry.

The corrected execution is retained under `output/society-lab/reality-m7-universal-authority-check/universal-probe-retry`.

The retry completed all participant actions. The initial Python audit then reported `KeyError: knowledge` because empty scenario maps are omitted from serialized `World.initial` by `serde(default, skip_serializing_if = "BTreeMap::is_empty")`. That original `result.json` is preserved. A corrected read-only audit of the same snapshot passed; no additional physical run was performed. Consult `final-validation-summary.json`, `authority-validation.json`, and `cleanup-verification.json` for the final result.

The successful universal activation is event 796 at 18,061 ms, authored by actor 2. The predeclared damage caused actual death event 5149 at 180,154 ms. All four east gather costs were 4 → 4 → 1 → 1; the last attempt occurred after the death event. Final inspection of the database found all three clocks paused and no grants for either diagnostic run. The source hash is `203ffd38b29d93b4a40bc37200a2d2055bbe5259f516ddd2ec28e2fb59d2e486`; the captured authority snapshot SHA-256 is `4f124bb36cc6ebf912166001971ef8eb3129ae105d7a9450b8f9ca447492c343`.
