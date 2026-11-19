# Gaze input and applied senses

Use a fresh Cullet scratch database and its two player identities. The script enables `gaze_on` and cover only for the fixture. The shipped laws default to off.

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
