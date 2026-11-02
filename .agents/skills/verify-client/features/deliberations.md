# Identity-scoped deliberations

## Sub-features

- Subscribe to `my_deliberations` as an anonymous connection.
- Subscribe as the original anonymous connection's identity and two player identities.
- Receive zero deliberations for those non-AI players.
- Subscribe as the admin and receive actual pending requests whose controller matches that connection's identity.

## How to get to it (user POV)

A client subscribes to `SELECT * FROM my_deliberations` with its own token, or without a token for a fresh anonymous identity. `living/authority/src/lib.rs:305` defines the view. It uses the `deliberation.controller` index to filter by `ctx.sender()`.

`living/authority/src/perceive.rs:217` excludes non-AI characters from deliberation requests. Owning a joined player therefore does not produce a positive request, even though that player may call its own `mind_*` reducers.

## Driving it with drive.py

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

Each `view-*.json` must have `status` equal to `applied`. The anonymous and player views must have zero `my_deliberations` rows after the positive admin result. `view-admin-after-players.json` must still contain requests after those foreign views. This rules out an empty global queue as the cause of the zero rows.

The driver uses the shared harness's `admin_token()` helper for the real SDK connection. It calls `verify.py call --as-admin` for admin `set_behavior` with a `think` node on one adult AI person. The authority tick generates the request after the 45-second settling gate in `brain.rs:424`. The client waits up to 55 seconds and ends the observation as soon as that actor appears. In `view-admin.json`, at least one deliberation must exist, the selected actor must appear, and every row's controller must equal the connection identity. The admin connection uses the same real SDK path as the players.

## Gotchas

- Never copy the admin token into shell arguments, logs, or evidence. The driver reads it from captured subprocess output and gives it to the probe through stdin.
- The admin is also the seeded AI controller. The proof has one controller with positive deliberations and three non-AI controllers with empty results. It does not create an AI owned by a second non-admin controller.
- Direct access to the private `deliberation` table is a separate visibility refusal. Use the public view to prove identity selection.
- The admin `set_behavior` call is scene setup, not a player capability.
