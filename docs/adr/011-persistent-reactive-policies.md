# ADR 011: Persistent model-generated reactive policies

Accepted and implemented 2026-09-05. Extends ADR 008/009/010.

The first hosted run exposed an architectural limit: generated sequences were discarded by damage, pending replies became stale, and authored fallback made subsequent risky choices. The fix is a persistent simulation-owned policy vocabulary with reactive priorities/guards, remembered sequences, shared skill actions and asynchronous reconsideration. The LLM generates the actual policy; the executor never fills in a survival tree.

Damage interrupts a skill and records experience without replacing the policy or invalidating its approach generation. Policy replacement, death, controller change, expiry and stop retain their validity boundaries. Delayed outputs are revalidated, current subjective guards/effects apply, and old reflections cannot overwrite newer retained beliefs. Abandoned branches reset; uninterrupted sequence progress persists.

Bound depth, width, node count, per-tick skill execution and payload size. Keep a labeled minimal eat/rest/wait bootstrap only when no policy is installed. Preserve legacy sequence inputs/archives explicitly, refuse cross-version mutation, and expose branch/action/generation evidence in the inspector. The proxy remains read-only and separate from world policy.

See [contract/runtime](../REACTIVE_POLICIES.md) and [verification](../REACTIVE_POLICY_VERIFICATION.md).
