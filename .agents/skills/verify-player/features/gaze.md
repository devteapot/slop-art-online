# Gaze input and applied senses

Use a fresh Cullet scratch database and its two player identities. Cullet ships `gaze_on`, `fov_on` and cover on (2026-11-19); the script turns them off first and enables each only for its fixture. For the laws as shipped, run `sight_on.py` ([cover](cover.md)).

```sh
V=.agents/skills/verify/scripts/verify.py
R=player-gaze-$(date +%H%M%S)
"$V" launch --run "$R" --seed cullet --target-dir "$CARGO_TARGET_DIR"
"$V" doctor --run "$R"
"$V" player --run "$R" join VerifyGaze
.agents/skills/verify-player/scripts/gaze.py --run "$R"
"$V" cleanup --run "$R"
```

The scene records accepted, repeated and refused requests, the sweep confirmation, cover composition, sight contacts, scope and death cleanup in `gaze-proof.jsonl`. Set `GAZE_SDK_PROBE` to the built [client probe](../../verify-client/SKILL.md) to also check scope through WebSocket subscriptions.
