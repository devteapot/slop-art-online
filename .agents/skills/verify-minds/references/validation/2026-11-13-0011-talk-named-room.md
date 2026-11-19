# verify-minds: talk-named-room

## 2026-11-13 talk-named-room: a room line naming one hearer is theirs to answer (Spark)

Branch `talk-named-room` from `talk-turns` (`723998ff`), on my own server `slop-talk-stdb` (:3362), fake model.

- **`named-room-call`:** `minds-tnr-11122355` and `minds-tnr2-11130009`, 6/6 each.
  - Control: an unnamed call to the room draws D, who is in a conversation with P, 19 m away.
  - A call naming N draws N's turn and none from D.
  - N's row reads ", naming you"; D's row names one other.
- **Regressions** (`minds-tnr-11122355`): `named-turn`, `conversation`, `greet`, `alongside` and `room-address` pass.
- **`sissly-scene`** failed there once on its own timing. Agnes's turn came, but her reply waits until Sissly's longer line has had time to be said (`saying_ms`), longer than the case's fixed 3 s. The case now waits up to 20 s for her line. `minds-tnr2-11130009`: 6/6.
- **Unit test:** `a_room_line_naming_one_other_is_theirs_to_answer` (mind).
- **`living-check`:** exit 0.
