# A mind hears what it cannot see

Since 2026-11-11 (`fov-1`; docs/PERCEPTION.md, "Heard, not seen"). While the world's `fov_on` law is on, a mind's scene (`perceive::scene_json`) carries `you.facing` and a list under `you hear (out of sight)` of what its character hears and does not see, in a person's words (`{"what": "a person", "where": "behind you, to the east", "how far": "near"}`), never an id. Its body notices a near sound when it begins (a `signal` percept, no subject). Graphs have a `sound` target, and the person instinct (`living/seeds/instincts.json`) carries a branch labelled `turn to a sound`, which the character owns.

## Sub-features

- A resident faces west on open ground with another 4.5 m east of it (admin `place_at`, `set_behavior`), then the admin turns `fov_on` on.
- The percept: "You hear a person near, behind you, to the east." (`experience` kind `signal`, subject 0), read before the mind connects.
- The deliberation scene (`deliberation.scene`) and the prompt the fake model is sent (`sent-prompt.txt`): the other is not among `creatures`, the heard entry has exactly `what`, `where`, `how far`, `you.facing` is `west`, and the other's id appears nowhere in the prompt.
- The habit: given the shipped person instinct, the resident turns to face the sound (a `face` use aimed at where the other stands). The branch is a continuous guard, so the turn may stop once the other comes into view (`broken off`); it is no longer heard then.

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case fov
```

## Gotchas

- Hold both bodies still (`wait`) before placing them: on a loaded host the CLI takes seconds a call, and a resident's own graph walks it to company meanwhile, into the near ring.
- A body in a long `wait` is not evaluated until the wait ends, so it notices nothing; the case gives it `{"wait": 1}` before turning the law on.
- The mind service prunes the experiences it takes in: read the percept before `run.start`.
- Seeded people start from the repertoire's desires (`seed::give_repertoire`), not the person instinct, so the case installs the instinct graph to show the habit acting; the repertoire and the island's ways do not carry it.
