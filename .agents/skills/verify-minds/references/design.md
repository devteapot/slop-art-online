# Driver design

The mind subscribes as the authority admin. Its experience query filters by controller; `my_deliberations` is a sender-scoped view. It also subscribes to the existing public world tables. The production reducer layer checks character ownership with `authorize`. The driver preserves those subscriptions and reducer calls. It replaces only the external HTTP model boundary with the shared fake server.

Two structures were considered. A standalone runner would repeat launch, doctor, fake-server lifecycle, journal copying and cleanup. Extending the existing `verify-llm` runner reuses those operations but needs a local run-name guard, admin SQL for private deliberations and explicit LoD/restart configuration. The latter is the implemented structure. In this fix round the owned `verify-llm` helper accepts only validated `llm` or `minds` caller prefixes and explicit LoD options. Mind setup and restart use that helper. Private SQL uses shared `verify.py sql --as-admin`.

The data shape is one `Run` per case. It owns a `verify-minds-*` database name, evidence directory, token held in memory, journal location and list of started processes. Case results contain `status` and evidence path; consolidation also records each projection result. Ordinary failed assertions stay FAIL. The two handoff defects have XFAIL KNOWN ISSUE expectations that become XPASS when fixed. Consolidation records persona and cursor checks separately from missing patch projections.

The throughput checkpoint is:

- Blocking first steps: read the binding brief, source, shared fake interface and official SpacetimeDB docs before choosing queries or assertions.
- Independent work: feature documents can be written while cases run. Each case has its own database, journal and fake port.
- Shared mutable state: build the real binary once per suite and retain Cargo's shared lock. Do not stop the existing container or write to other skill directories.
- Smallest safe decomposition: one implementation owner keeps lifecycle and evidence rules together. The task prohibits remote model calls; no nested model delegation was used. The full LLM and minds suites run concurrently on separate scratch databases, fake ports and journals.

SpacetimeDB references consulted on 2026-10-04:

- [Official documentation](https://spacetimedb.com/docs/).
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): wait for subscription application, then prove replies by resulting rows rather than only receipt of model requests.
- [Views](https://spacetimedb.com/docs/functions/views/): use the real admin sender for `my_deliberations`; an anonymous SQL snapshot is not proof that the mind sees a request.
- [Indexes](https://spacetimedb.com/docs/tables/indexes/) and [performance guidance](https://spacetimedb.com/docs/tables/performance/): filter diagnostic snapshots by the existing actor, observer and owner keys. Keep full exports explicit and make no scale claim from the fixture.

The site labels these pages 2.0.0. `living/Cargo.toml:9` pins both authority and SDK to 2.10.1; doctor verifies the running v2.10.1 image. The driver uses the existing version-pinned SDK binary and real table queries, not new APIs inferred from current docs. No schema, bindings or product subscriptions change.

Reads are bounded to one selected actor except initial character/world snapshots and explicit diagnostic exports. Inventory uses `owner`; experiences use `observer`; deliberations and cursors use `actor`. The production service retains its existing all-world subscriptions and scans, which this skill does not claim to optimize. Snapshot polling and fake model traffic are diagnostic workload. These runs make no performance or population claim.

The paid wrapper uses a guardian process rather than a `finally` block alone. A finally block cannot run after SIGKILL. The wrapper holds a write end of the guardian's stdin pipe; EOF triggers cleanup if the wrapper dies. The guardian owns one new driver process group, imposes its own monotonic deadline, terminates the group even after its leader exits, and checks the group is gone. Linux child-subreaper mode lets it reap orphaned minds. Inert child fixtures prove each exit path without any database, keys or model calls.

Both paid scripts resolve model configuration through `verify-llm/scripts/models_config.py`. Explicit configuration wins, then active `LIVING_MODELS`, then the product default. This avoids forcing the repository example over the host's `.env` choice of the local Luna proxy.

The reconnect case updates the same run with `launch --keep-data`. It saves the served actor's installed graph, an excluded actor's pending deliberation and the served actor's seeded cursor before and after the update. The excluded pending row avoids an answer racing the snapshot. A short authority pause freezes scene setup while the mind remains running. A new mind PID and new subscription-ready log prove reconnection. Identical `--keep-data` updates may retain the socket; then the driver explicitly stops only its owned mind and records this controlled restart. Unpause, doctor and a new accepted reason prove service resumes.

The LoD case first proves routine hold and player-contact release. It then merges a non-plan reason during a delayed compile. The authoritative updated row and the later thought/pending snapshots distinguish missed updates from failure to release the original request.
