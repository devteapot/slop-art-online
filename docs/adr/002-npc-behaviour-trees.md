# ADR 002 — NPC Behaviour Trees

## Status
Superseded by ADR 003 → ADR 005

This ADR proposed a custom evaluator and ruled out `bonsai-bt`. In practice, `bonsai-bt` works fine in WASM (ADR 003) and is used with a custom stateless evaluator. The unified tree architecture (ADR 005) supersedes the two-layer approach.

## Context

The current NPC AI uses a JSON state machine (nodes + explicit transitions) stored in
`NpcBehaviourGraph`. It works but has two pain points:

1. The LLM must wire every transition manually — error-prone and a known source of
   schema adherence failures.
2. Adding a new priority (e.g. "flee when health critical") requires adding transitions
   in every state the NPC can be in.

Behaviour trees express the same logic more naturally through tree structure: priorities
fall out of node order, no explicit transitions needed.

## Decision

Replace the state machine with a custom recursive behaviour tree evaluator.

### Why not `bonsai-bt`

`bonsai-bt` was considered but ruled out for the SpacetimeDB module:

- The module compiles to `wasm32-unknown-unknown` (bare WASM, not WASI). `bonsai-bt`
  likely depends on `std::time::Instant` which is unavailable on this target.
- BT runtime state lives in a `BT` struct in memory. SpacetimeDB requires all state to
  be in tables and round-tripped every tick — fighting the library rather than using it.

`bonsai-bt` could be used in the bridge or client (regular Rust targets) if needed later.

### Custom evaluator

The recursive tick is ~30 lines of pure Rust with no timing dependencies:

```rust
fn tick_node(node: &BtNode, npc: &Npc, ctx: &ReducerContext) -> Status {
    match node {
        BtNode::Selector { children } => {
            for child in children {
                if tick_node(child, npc, ctx) == Status::Success { return Status::Success; }
            }
            Status::Failure
        }
        BtNode::Sequence { children } => {
            for child in children {
                if tick_node(child, npc, ctx) == Status::Failure { return Status::Failure; }
            }
            Status::Success
        }
        BtNode::Condition { check } => evaluate_condition(check, npc, ctx),
        BtNode::Action { do_ }     => { execute_action(ctx, npc, do_); Status::Success }
    }
}
```

### New JSON schema

```json
{
  "type": "selector",
  "children": [
    {
      "type": "sequence",
      "children": [
        { "type": "condition", "check": "health_critical" },
        { "type": "action",    "do": "flee_from_target" }
      ]
    },
    {
      "type": "sequence",
      "children": [
        { "type": "condition", "check": "in_range" },
        { "type": "action",    "do": "attack_target" }
      ]
    },
    {
      "type": "sequence",
      "children": [
        { "type": "condition", "check": "target_detected" },
        { "type": "action",    "do": "move_toward_target" }
      ]
    },
    { "type": "action", "do": "wander" }
  ]
}
```

## What Changes

- `NpcBehaviourGraph.graph` — new JSON schema (tree instead of state machine)
- `NpcBehaviourGraph.current_node` — no longer needed; BT is stateless per tick
- `evaluate_graph` → `tick_bt` — recursive evaluator replacing the current node walker
- `submit_npc_graph` — same interface, different schema validation
- LLM prompt — updated to describe tree structure; simpler for the model to follow

## What Does NOT Change

- Table names and reducer interfaces
- Available actions (`wander`, `move_toward_target`, `attack_target`, `flee_from_target`)
- Available conditions (`in_range`, `target_out_of_range`, `no_target`, `target_detected`)
- Bridge architecture and revision loop (ADR 001)
- Fallback behaviour (default graph still runs while LLM thinks)
