# Parallel experiment batches

`run_experiment_batch.py` accepts any nonempty, explicitly listed set of candidates. By default every candidate initializes, waits at the same gate, and runs concurrently when that gate opens. There is no four-candidate limit. Each candidate can use its own frozen implementation, scenario, population, controller configuration, duration and serial interval. It runs the existing authority and participant harness; the coordinator supplies no character decisions.

```sh
python3 scripts/run_experiment_batch.py /absolute/path/batch.json \
  --output /absolute/path/new-evidence --dry-run
python3 scripts/run_experiment_batch.py /absolute/path/batch.json \
  --output /absolute/path/another-new-evidence
```

Both commands require a new output directory. Dry-run verifies bundle hashes, reads JSON inputs, validates settings and controller coverage, and writes the frozen inputs and launch plan. It does not launch processes, contact providers, reserve ports, create databases or advance worlds. It does not validate the entire simulation schema or prove a port will remain available. Use a different output directory for the subsequent real run.

## Explicit configuration

```json
{
  "hypothesis": "How does a teaching change behave at different population sizes?",
  "evaluation": "Compare recorded teaching outcomes, survival, simulation time, model failures and scope checks; retain each event trace.",
  "minutes": 5,
  "calls_per_actor": 12,
  "serial_ms": 15000,
  "disk_reserve_bytes": 3221225472,
  "variants": [
    {
      "id": "baseline-two",
      "port": 18940,
      "implementation": "/absolute/path/frozen-baseline",
      "scenario": "/absolute/path/two-actors.json",
      "controllers": "/absolute/path/two-controllers.json"
    },
    {
      "id": "candidate-eight",
      "port": 18941,
      "implementation": "/absolute/path/frozen-candidate",
      "scenario": "/absolute/path/eight-actors.json",
      "controllers": "/absolute/path/eight-controllers.json",
      "minutes": 8,
      "calls_per_actor": 18,
      "recovery": true
    }
  ]
}
```

Add as many explicit variants as the intended resource budget supports. IDs must contain only ASCII letters, digits, underscores and hyphens. IDs and ports must be unique throughout one batch, including across optional groups. Controller manifests must cover every scenario actor exactly once. The existing Luna-only campaign restriction remains; the script does not choose a model or change provider settings automatically. Relative input paths resolve from the invoking working directory, as before.

Optional top-level `concurrency` limits the number of active experimental runs to that positive integer. The runner partitions the listed variants into ordered groups, runs each group concurrently, finishes its evidence checks, then initializes the next group. Every group has its own common start gate. Omit the field for one simultaneous group containing every variant. There are no implicit waves, generated candidates, retries, resource-based scaling decisions or repeated experiments.

`minutes` (1–60), `calls_per_actor` (0–100) and `serial_ms` (at least 1000) accept per-variant overrides of the top-level defaults (5, 0 and 15000). A call cap of zero retains the existing uncapped-call behavior within the wall-time deadline. `recovery` is a per-variant boolean. Different populations and durations are explicit experimental factors, not automatically matched comparisons. Population and map limits remain properties of the selected engine version; removing the batch limit does not remove those limits.

## Newcomer controllers

Population runs may add a per-variant `newcomer_controller` path. Its JSON contains `role` (`builtin` or `external`) and the ordinary model `config`; it has no actor ID or credential grant. The batch freezes this input with the scenario and initial controller manifest. Omitting it leaves dynamic enrollment disabled. A configured profile requires a host advertising `sao-enrollment-v1` and a valid lifecycle actor bound; it fails explicitly against older hosts.

The authority creates each body and identity through gameplay. The host discovers living new AI individuals, enrolls each once and persists its effective controller configuration and normal participant descriptor. External workers start as new descriptors arrive. This does not copy a creator's mind or spawn substitute inhabitants. The bound counts retained identities, including dead people, and currently cannot exceed 256.

Shutdown stops enrollment, waits for acknowledgement, refreshes the final descriptors and revokes all grants, including arrivals near the deadline. Tests cover a late descriptor appearing while stopping. `summarize_population.py <variant-directory>` adds creation, care, learning, practice, self-support, actual newcomer model calls and support after caregiver loss to the ordinary food and knowledge audits.

## Isolation and finite scheduling

Fresh-run supervisors discard inherited `BEVY_DEV_RESUME_ACTIVE` and `BEVY_DEV_ARCHIVE_ONLY` settings so the experiment cannot accidentally resume another session or enter archive mode. Host process IDs are persisted immediately after launch for cleanup before readiness.

All scenario and controller JSON is read and validated before launch, then copied into `.inputs/<variant>/` with hashes. Each implementation bundle is verified before preparation and again by its supervisor. Changes to original input files after preparation cannot affect this batch. Bundle directories must remain unchanged for the duration of the run; hashes establish identity, not an operating-system write lock.

Hosts initialize one at a time because older frozen hosts use millisecond-based database names. Simulations still start together after the entire group is ready. Readiness has a 100-second limit per host. The child's start-gate allowance is explicitly set to `100 × group size + 30` seconds, preventing the former fixed 180-second gate timeout from silently imposing a practical batch-size limit. Each group's running supervision deadline is the longest configured duration plus 60 seconds for finishing and exporting. Initialization time is separate from the configured experimental duration.

Before releasing a gate, the coordinator verifies that all supervisors are alive and that their recorded `(server, database)` pairs differ from every earlier variant in this batch. A collision, startup failure, cancellation or supervision timeout fails the batch and stops peers. These checks supplement each host's port binding and output isolation; they do not reserve a global namespace across independent coordinator processes. Separate simultaneous batches must be assigned disjoint ports and output directories. Current hosts include the process ID in database names. Very old timestamp-named frozen hosts still need care during cross-batch initialization; a same-name database can collide before the readiness check notices it.

On failure, supervisors receive termination and have a shared 40-second allowance to pause authority and retain evidence; remaining supervisors are killed. Host process groups recorded in their `pilot.json` files also receive termination on failure. `cleanup_errors` records any unconfirmed authority pause. A forced process exit cannot prove that an independently hosted database was paused: inspect that evidence before reusing resources. The runner never deletes databases or searches for unrelated processes.

By default, successful runs pause the authority and leave observer hosts available. The explicit fixed-population `finalization_mode: stopped_host` option instead stops owned workers and the host before pause, grant revocation and coherent final capture; see [external-worker and finalization contracts](EXTERNAL_WORKER.md). Neither mode changes the original duration-plus-sixty-second batch supervision allowance. Thus `concurrency` limits experimental runs and model activity, not total stored evidence or, under the default mode, retained observer processes. Hosts and retained databases still consume resources after completion. The Stage 7 authority diagnostic also encountered a kernel-confirmed global OOM after accumulating several completed database runtimes in one service process; pausing clocks and disconnecting clients did not establish that peak process memory had been released. Its recovery and memory-bounded repeat are documented in [the authority diagnostic](AUTHORITY_SCALE_DIAGNOSTIC.md). Record process lifetime, RSS/high-water memory, host memory headroom and service limits separately from disk/WAL growth. Those diagnostic memory controls are external to the batch coordinator's disk-reserve guard.

To use a separately provisioned authority service, set `BEVY_DEV_SERVER` and `SPACETIME_CONFIG_PATH` for the batch process. The host defaults to `http://127.0.0.1:3101`; the supervisor defaults to `.local/credentials/bevy-cli.toml` when no owner configuration is supplied. The supervisor records the selected endpoint and configuration path, never credential contents. Freeze a host build that supports the endpoint setting before launching on another service. `active.json` records the actual service and database. Isolation changes the experiment environment and must be declared in the comparison; it is not itself evidence of improved core throughput.

The coordinator reserves 3 GiB of free space on the output filesystem by default. Set positive integer `disk_reserve_bytes` in the manifest, or override it with `--disk-reserve-bytes`. Before any supervisor launch and common gate release, it refuses to continue at or below the reserve. During initialization and running it checks at one-second intervals; it also checks before completion validation. A breach records `failure_code: disk_reserve_exhausted` and uses the same parallel graceful shutdown so supervisors can pause and save evidence while space remains. This is a host resource guard, not a world rule. It does not delete files or restart services. Sampling cannot prevent an unrelated writer from consuming the remaining reserve between checks, and a database on another filesystem needs its own capacity monitoring.

The same contract documents the opt-in `external_mcp_mode: persistent` and `external_rpc_concurrency` settings. Admission applies to external `tools/call` RPCs and shares the fifteen-second RPC deadline; it does not cap provider/model concurrency. These declared runtime conditions require their own measured comparison and do not repair earlier failed trials.

## Evidence and interpretation

- `manifest.json`: resolved settings and original absolute input paths.
- `plan.json`: frozen hashes, exact launch commands, group membership and bounded gate settings.
- `batch.json`: incrementally written phase, supervisor IDs, observer URLs, authority identities, gate times, results and cleanup status. `disk_space` records the monitored path, reserve, interval, timestamped free/total-byte samples and any breach stage.
- `<variant>/`: the existing run evidence, `pilot.json`, authority snapshots, model journals and `LIVE_RESULT.json`.
- `comparison.json`: completed summaries, retained incrementally across groups.

Comparisons preserve survival/population, simulation seconds and updates, model call completion/error counts, engine errors and scope violations. They add group identity and observed supervisor wall seconds; missing wall timestamps produce `null`, never an invented duration. Every row links to its detailed evidence. These aggregates do not automatically decide whether a hypothesis was accepted, or count mechanic-specific outcomes such as accepted teaching: inspect the underlying events and reconcile observations against the recorded evaluation criteria. An evidence-check failure marks the batch failed and prevents later groups from launching. Already written evidence remains inspectable.

A shared gate aligns permission to start; it does not guarantee identical reducer start timestamps, provider latency, effective reasoning effort, scheduling or simulation throughput. All candidates in a group share host and provider resources, so resource contention is part of the experiment. Repeated seeds and larger populations do not make fresh model decisions deterministic.

## Verification

```sh
python3 -m unittest discover -s scripts -p 'test_experiment_batch.py' -v
python3 -m py_compile scripts/run_experiment_batch.py scripts/run_living_clearing.py
```

Twenty-three deterministic orchestration checks pass. Disk-space fixtures verify refusal before any launch, a drop during initialization stopping already started peers before the gate, a running drop terminating every supervisor gracefully, configuration override and periodic measurements. Existing checks cover groups, frozen inputs, newcomer admission, completion provenance, early termination and interruption handling. These tests use inert hashed bundles, mocked subprocesses and mocked filesystem capacity; they test scheduling and evidence contracts, not engine behavior, live scalability or provider capacity. They launch no live worlds or model calls.
