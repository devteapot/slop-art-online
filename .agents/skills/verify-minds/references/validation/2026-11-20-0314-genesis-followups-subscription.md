# genesis-followups: the mind service's own `genesis` subscription (verify-minds)

Branch `genesis-followups` (from `origin/main` `b6aa74890`), dev-box, `sg-stdb` (v2.14.1, 127.0.0.1:3344). The real `living-mind` debug binary, a fake model profile on a closed local port, `LIVING_ONLY=0` (no mind bootstrapped to think), no Neo4j. No model calls.

**Change.** `SELECT * FROM genesis` left the mind's main subscription for one of its own (`on_applied` and `on_error`, as `cue` and `fast_ask` already have). On a module without the table only that subscription fails: the mind warns, counts the world as made and starts. The wait for the row reads it only after that subscription has answered (a oneshot), so a separate subscription that applies late cannot read as "no row, ready".

Driven:
1. **A world being made** (stepping build of the default world; genesis waits for `resume_genesis`), via `.local/sg/tools/mind_wait.py`:
   - After 10 s the log has "world preparing: waiting for its genesis", has no "world subscribed:", and the mind is alive.
   - After the step and the finishing call it logs "world made: the minds start" and "world subscribed:".
   - No subscription error.
2. **A module without the table:** a scratch build of the mind that subscribes `genesis_absent_probe` instead (patched, copied out, reverted; the shipped binary was checked to have only `SELECT * FROM genesis`), run against the made world `verify-client-gf1`:
   - It logs `no \`genesis\` subscription (SubscriptionError { … no such table … }): this world was made before staged genesis; it counts as made`, then "world subscribed: 271 characters".
   - It stayed alive until stopped.

**Not covered:** the verify-minds cases against a fake model. No mind thinks in either run. The other subscriptions are untouched.

**`maintain-verification-skill`:** no skill page described the mind's `genesis` subscription. docs/STAGED_GENESIS.md "Consumers, as built" now does.

Evidence: `.local/sg/mindwait/` (`mind.log`, `mind-absent.log`, `result.json`, `result-absent.json`; worktree, not in git).
