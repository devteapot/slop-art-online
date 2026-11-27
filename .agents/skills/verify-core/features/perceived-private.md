# Facts no player has a view of (`perceived_private_on`, `seen_pasture`)

Perception parity phase 1, item 7 ([audit](../../../../docs/PERCEPTION_PARITY_AUDIT.md), the private-table rows: courting, family, `rhythm`, `smells`, `pasture`, `brain::alerts` `sole`). What each one became:

| Audit row | Now | Why it is parity |
|---|---|---|
| `Target::Suitor`, weight `courted` (`bond_offer`) | unchanged | a player reads the same offers through `my_bond_offers` (main, `parity-player-views`) |
| `Target::Partner` (the other parent of one's youngest child), `Target::Parent` | unchanged | `my_kin` (partner, children, parents) and `my_characters` (own `parent_a`/`parent_b`) |
| `bedtime`, `evening`, `work_hours` (`rhythm`) | unchanged | the character's own schedule over the public hour: when it means to sleep, idle and work is its will, as a player's own plan is theirs; the only world fact read is the hour (`world`, the HUD clock). Compiling the hours into each graph's `hour` ranges would move the same numbers, not change who knows them |
| `smells` (and the body's scent in acts and steering) | under the law, a person never smells (`common::scent_for`) | smell is a species' sense (`species.json` `scent`: deer and wolf); no shipped species gives a person one, and players play persons only. The law keeps it so if a seed's species did |
| `nearest grass` skipping grazed-bare chunks (`pasture`) | exposed: the view `seen_pasture` | how grazed grass is can be seen; the graph reads it within its sight, and a player now reads the same rows of the chunks within its sight. A graph is unchanged |
| `brain::alerts` "You alone know how to …" (`sole`) | under the law, never raised | it came from a scan of every living character's know-how, which no one perceives; whom one taught and who taught one is the mind's own memory to weigh |

The law `perceived_private_on` (an ordinary law, off as shipped) holds the two changes to the rules; `seen_pasture` is always there. Off, every rule is as before.

Cost: off, a law read per minute per calm grown person (where the `sole` check would run) and, only for a person whose species has a scent (none shipped), per scent read. On, the `sole` scan of every `know_how` row (per technique, about once a minute per calm grown person) is gone. `seen_pasture`: at most 49 point lookups per re-run (Cullet's 48 m day sight), on a change of the player's body, senses or one of those pasture rows; only for a client that subscribes (the game client does not yet).

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py perceived_private --run "$R" > ".local/living/verify/$R/perceived_private.txt" 2>&1
```

`scenes.py perceived_private` (any seed, about 3 minutes): a fresh grown person P is given a technique no one alive knows (`grant_know_how`, the first of a list missing from `know_how`), its health set full. Law on: in 75 s P has no "You alone know how to" feeling. Law off (the control on the same person): within 75 s P feels it, naming the technique. `seen_pasture` is verify-client's (`drive.py`, `seen_pasture`).

Evidence: `perceived_private-cast.json`, `perceived_private-feelings-<on|off>.json`, `perceived_private-needs-<on|off>.json`.

## Gotchas

- The `sole` check runs about once a minute per person (`LEGACY`, module memory) and only while it is calm (hunger under 60, energy over 35, health over 60): the scene records P's needs before each wait.
- With the law on the check is skipped, not run: P's minute starts again when the law goes off, so the control's feeling comes at once.
- A person's scent is not driven: no shipped species gives one.
- The scene restores `perceived_private_on` (off) in a `finally`.
