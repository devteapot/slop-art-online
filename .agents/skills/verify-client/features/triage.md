# Ad-hoc client subscriptions

## Sub-features

- Subscribe to one diagnostic SQL query through the real Rust SDK.
- Print complete initial rows, then live inserts, updates and deletes.
- Choose an anonymous identity or the harness player's identity.
- Save the stream without overwriting earlier evidence.
- Fail on subscription refusal or connection loss.

## How to get to it (user POV)

When a speech line is missing from the UI, check whether a client receives the matching `chronicle` row. Use a `client-*` scratch run launched and checked with the shared harness. Build the standalone probe as described in [SKILL.md](../SKILL.md).

## Driving it with drive.py

In one terminal, start the subscription:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R" \
  --query "SELECT * FROM chronicle WHERE kind = 'speech'" \
  --seconds 10 --save speech-anonymous
```

Wait for the `initial` JSON line. In another terminal, join if this run has no player and speak:

```bash
V=.agents/skills/verify/scripts/verify.py
$V player --run "$R" join ClientTriage
$V player --run "$R" say VERIFY_CLIENT_TRIAGE_SPEECH
```

`speech-anonymous.jsonl` must contain an `insert` event for `chronicle` with the spoken marker in `row.text`. An initial snapshot cannot prove live delivery. The automatic full suite also proves this using `adhoc-suite.jsonl` and the already joined `ClientPrimary`.

After joining, repeat with the player's identity and a fresh evidence name:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R" \
  --query "SELECT * FROM chronicle WHERE kind = 'speech'" \
  --as-player --seconds 0 --save speech-player
```

The initial identity must equal the harness player's identity in `state.json`. The earlier speech row must be in `initial.tables.chronicle`.

To observe update callbacks on a small table:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R" \
  --query "SELECT * FROM world" --seconds 10 --save world-updates
```

While it runs, use the harness for admin scene setup on this scratch database:

```bash
$V call --run "$R" set_paused '[true]' --as-admin
$V call --run "$R" set_paused '[false]' --as-admin
```

Both transitions must be `update` events with complete `old` and `row` objects. Repeat with a fresh name and `SELECT * FROM world WHERE paused = false`. The same transitions must produce a client-cache `delete` followed by an `insert`.

## Gotchas

- Initial rows appear only after `on_applied`. The probe suppresses initial insert callbacks so they cannot masquerade as live changes.
- JSONL records contain `event`, `table` and `row` for live changes, plus `old` for updates. The initial record contains `tables`, query, duration, database and identity. A final `complete` record proves the requested live interval finished.
- An empty applied query records empty `tables` and exits 0. Refusals exit 1 and keep their exact error. A missing speech insert still needs triage through `verify-player` or `verify-minds`.
- The SQL must select complete rows from tables or views in the generated bindings. Keyless views emit inserts and deletes, rather than primary-key updates.
- A delete means a row left the client's subscription result. It need not mean the authority deleted the stored row.
- `--as-player` requires a joined harness identity. Tokens travel over stdin, never command-line arguments or evidence.
- The duration is 0 through 300 seconds. Evidence grows with matching updates; keep the query and duration narrow.
- Run shared cleanup after manual attempts, including failures. Admin pauses above affect only the scratch run and must end with `false` before doctor or other tick checks.
