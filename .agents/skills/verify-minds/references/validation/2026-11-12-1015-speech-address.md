# verify-minds: speech-address

## 2026-11-12 speech-address: the room-address case (Spark)

Branch `speech-address` from `06be6921`, the trial service `slop-trials-stdb`, fake model. `verify_minds.py --run minds-sa-11121008 --case conversation --case room-address`: both pass.

`room-address` passed 5/5. H's prompt (`prompt-address.txt`) holds:

- "A stranger said to the room, calling Walker2 and a stranger: “Walker2! Walker3! …”" (H knows Walker2, not Walker3 or the speaker);
- "A stranger said to the room while talking with Walker2: “Has anyone seen the cart?”".

The line to Walker2 has no room detail.

After merging main `d80a1373`: `minds-sam-11121029` `room-address` passes.
