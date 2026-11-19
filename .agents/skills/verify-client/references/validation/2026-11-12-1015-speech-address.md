# verify-client: speech-address

## 2026-11-12 speech-address: how a line to the room was said, in the player's labels (Spark)

Branch `speech-address` from `06be6921`, the trial service `slop-trials-stdb`, `scoped`. New `room_address.py`, `client-sa-11121014-room`: 4/4, read through the SDK probe (`address-seen.jsonl`, `room_address.json`):

- before K tells their name: "A stranger said to the room, calling a stranger and you: “Walker1! Mara! …”", with no K name before the quote;
- after: "… calling Walker1: …";
- after a line to K, a room line naming no one: "… said to the room while talking with Walker1: …".

`far_label.py`, `client-sa-11121014-far`: 3/3. Each script runs on its own launch because each joins the run's player identity. The `run.py` suite was not run (no schema change).

After merging main `d80a1373`: `client-sam-11121029` `room_address.py` 4/4.
