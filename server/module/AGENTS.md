# SpacetimeDB module guidance

Follow the [root instructions](../../AGENTS.md), especially the mandatory official-documentation check before implementing SpacetimeDB features. Read the [authority source map](spacetimedb/AGENTS.md) for the active simulation path.

## Version and API discipline

The authority manifest currently pins `spacetimedb = "=2.1.0"` with `unstable` enabled for existing procedures. Verify [Cargo.toml](spacetimedb/Cargo.toml), the lockfile, generated bindings and actual service version before selecting APIs. Tool versions can differ: the browser runbook records separate build/generation and control CLI paths. Do not upgrade dependencies or select a server merely because a global CLI default points there.

Use official [Rust SDK documentation](https://docs.rs/spacetimedb/2.1.0/spacetimedb/) and the relevant [SpacetimeDB guides](https://spacetimedb.com/docs/). Prefer verified current examples over copied SDK handbooks. The old language-rule filenames are not required resources in this repository.

- Authority modules use `spacetimedb`; native clients use `spacetimedb-sdk` and generated bindings.
- In this pinned Rust API, authenticate with `ctx.sender()`. Do not trust an identity or actor supplied in the payload.
- Reducers use deterministic supported inputs, `ctx.timestamp` and the supported RNG. No external inference, network or filesystem work inside reducers.
- Mutations are transactional. Return expected errors without inventing effects; reducer completion alone does not expose application result data. Use appropriate state, receipts, views or procedures.
- Table access uses `ctx.db.table_accessor()` and the `Table` trait; point updates use key accessors. Preserve unrelated row fields when updating.
- Views and procedures have distinct transaction, access and invalidation behavior. Check the pinned API before changing either. A procedure export still has real loading and serialization cost.
- Keep private state private. A client-side subscription filter is not authorization. Do not make a table public merely to resolve a client integration error.
- Verify index definitions and generated accessors together. Use indexed keys/ranges for local operations and keep procedural-view read sets small.
- A SpacetimeDB auto-increment ID is not a gap-free audit sequence. Preserve explicit event-order contracts where required.
- Event tables support transient delivery; verify protocol/version compatibility and provide durable records separately where recovery or evidence needs them.

## Deployment and verification

Use explicit task-appropriate server/database destinations and the [browser runbook](../../docs/BEVY_BROWSER_CLIENT.md). Do not infer deployment intent, pricing or reset authorization from CLI defaults. Preserve existing databases and retained experiment evidence.

For schema/interface changes, regenerate affected bindings using the established versioned commands and verify actual clients. For storage or subscription changes, test authorization, atomicity, reconnect behavior and representative query/update load. Source compatibility, serialized byte counts and native timings alone do not certify actual database performance.
