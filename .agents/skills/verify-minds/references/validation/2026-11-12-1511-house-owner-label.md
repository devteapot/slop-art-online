# verify-minds: house-owner-label

Scoped maintain-verification-skill pass for `house-owner-label` (Spark, trial server `slop-trials-stdb` 2.14.1, private `CARGO_TARGET_DIR`; branch head `c367e043` = origin/main `e704ec0d` merged). Scope: the features this change touches, read from source by the coordinator (no subagent wave); every other feature of the skill is out of scope and unchanged. `just living-check` passed on the merged tree (all steps, 1702 s). Every scratch world was paused before deletion by `verify.py cleanup`.

The change: `common::owner_label` names a structure's owner whenever the `owner_shown` law shows it (the viewer knows them, or the kind `shows_owner`), whatever the owner's distance (before: `label_for`, which read the owner's distance, so a known neighbour's house read "someone too far away to make out"'s when they were away). Lines about something owned (a notice line, a witnessed theft) carry the owner as subject or object only when they name them, by id, never by a far handle (`perceive::percept_owned`, `witnessed_owned`). docs/PERCEPTION.md "Whose a thing is".

- New case `house-owner` (registered with `@case` where it is defined; features/README.md row, features/sight.md "Whose a house is"): `minds-hol4-155758` pass on the merged build (8/8), `minds-hol3-140549` before.
- Found while building the case: after the label fix alone, a notice line named the owner but the mind service tagged it with the owner's far handle ("You notice a house built by Walker2 … {someone too far away to make out=#1000000046}", `minds-hol2-140120`), tying a far figure to a name; and an owner the line did not name was still tagged. Fixed in the authority (`percept_owned`); the case asserts the id tag and the untagged line.
- Harness note: the mind integrates its experience rows, so the case reads notice lines from `fake-requests.jsonl`, not the `experience` table (an empty read there is not a failure of perception).

Not covered: performance (no tick timings were read; the change adds no per-tick work: one `owner_label` per structure line as before), paid model runs, and the other features of this skill.
