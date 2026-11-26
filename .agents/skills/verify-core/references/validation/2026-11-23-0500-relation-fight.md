# relation-fight: whom one fights, said first, then a relation that decides, then the community

Branch `relation-fight` on main `5655887af`. Spark (aarch64), a private server `slop-layoutseed-20261123` (SpacetimeDB 2.14.1, `127.0.0.1:3591`, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), a private `CARGO_TARGET_DIR`, builds through `build-slot`, pinned to CPUs 0-4,10-14. Fake model only; no paid calls.

**The finding** (free check on E5's evidence, `heed-e5-20261122.tar.zst`): `relation_ok` let any personal relation row decide alone, so a row with trust above -25 and no enemy word hid the community's `enemy` stance. Of E5's 129 such rows about living foes, 68 were truces and 61 were misreadings: 36 neutral first impressions ("stranger", trust 0), 14 wary notes (trust -10 to -20) and 11 hostile rows without the word ("foe", "assailant", "attacker"). The rule was never told to minds, and the fixture's stance read "stance: open" (worded on `sides-layout-seed`).

**The change** (decided by the general coordinator: 1 + 2 + 3):
1. **Decisive override only** (`brain.rs` `personal`, `fight_fits`): a relation decides `enemy`/`friend` only when clear (hostile: trust -25 or less or a label with enemy, rival, threat, thief or foe; peaceful: trust 25 or more or a label with friend, family, partner, ally or kin; signs both ways or neither: undecided). Otherwise the community's stance decides.
2. **An explicit word**, `relation_fight` (a new private table keyed by `(actor, other)`, `fight` `enemy`|`spare`, `by` `mind`|`player`; no column added). It comes first. A mind sets it with `mind_fight` (a new reducer; `mind_update`'s arguments are unchanged), from an optional `fight` on a relation in its consolidation reply, validated in `mind.rs` `fights_of`. A person's own blow (`act::damage`, landed, blocked or dodged) sets `enemy`, `by: player`; `mind_fight` refuses any character a person plays. Rows go when their character dies.
3. **Minds are told** (`prompts.rs` `FIGHT_WORDS`): the graph grammar's `relation` and the consolidation prompt gloss the order, and the relations shorthand lists `"fight": "enemy|spare|null (optional)"`. No tactics are suggested. The mind's prompts show "fight: …" beside the person.

SpacetimeDB documentation consulted: [tables](https://spacetimedb.com/docs/tables/) (private by default: reducers and the owner only), [indexes](https://spacetimedb.com/docs/tables/indexes/) (a two-column btree, `filter((a, b))` for the pair, `filter(a)` as its prefix), [performance](https://spacetimedb.com/docs/tables/performance/) (indexed lookups, no scans on the hot path) and [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations) (adding a table is always allowed; a column must be appended with a default). Design implications: one private table with one pair index, used by `relation_ok` (a point lookup only for `enemy`/`friend` filters), `mind_fight` (≤ 32 rows a call), `act::damage` (a write only when a player's word changes) and death cleanup (index prefix). The mind service subscribes to it separately and reads only its own characters' rows into prompts.

| Proof | Run | Result |
| --- | --- | --- |
| authority test `brain::tests::whom_one_fights_said_then_felt_then_the_community` | living-check | pass |
| verify-core `relation_fight` (default seed) | `core-rfight-031514` | PASS 11/11. Neutral row: A attacks B1. Truce row on the nearer B2: A attacks only B3. `spare` over a hostile row on the nearer B4: only B5. A person of no community: not attacked, then attacked once `enemy` is said. `""` takes it back. A bad word is refused. |
| verify-core `dealings` (island: regard read by a relation filter) | `core-rfisl-032507` | PASS 16/16 |
| verify-core `sides_battle` (Cullet) | `core-rfcul-032752` | PASS 11/11 |
| verify-minds `fight-field` | `minds-rfight-031902-fight-field` | pass: `relation_fight` holds the resident's `spare` by `mind`; the thought's notes left out `"never"` and #999999; 2 system prompts carry the gloss; a later `think` prompt shows "fight: spare" |
| verify-player `combat.py --scene all` (island) | `player-rfight-032010` | 59/59, with "the player's strike makes the one struck its character's enemy (relation_fight: enemy, by player)" |
| verify-client | `client-rfight-20261123-033012` | exit 0; `mind_fight` refused "not your character" for others' characters and anonymous callers, and "a person plays this character" for each player's own (10 of 10); `relation_fight` private |
| det_compare, main `5655887af` against the branch, each with its own script, a `spawn_battle_sides(60, 2)` template (with `sides-layout-seed`'s `det_compare.py` `--sides`) | `.local/relation-fight/det/run1` | identical: 3,600 ticks, 113 tables, 30,788 rows (no relation or fight rows: the stance decides as before) |
| `just living-check` | `.local/relation-fight/check.log` | ok in 380 s (authority, mind and viewer, game and its tests, authority tests, viewer wasm; rules tests and the script gate skipped by check.py: no rules change) |

**E5 re-scored** (`.local/relation-fight/rescore.py` on the 129 rows; E5's minds wrote no `fight`, so the bands decide):

| E5 class | Rows | Still not an enemy (live pair-s) | War restored (live pair-s) |
| --- | --- | --- | --- |
| Conciliatory (truce, stood down) | 68 | 29 (1,261) | 39 (1,976) |
| Hostile, no enemy word | 11 | 0 | 11 (735) |
| Neutral (seen, unmet, named) | 36 | 3 (44) | 33 (2,759) |
| Wary first impression | 14 | 0 | 14 (496) |

58 of the 61 misread rows no longer hide the war. 29 of the 68 truces still hold by trust 25 or more or a friendly word; the other 39 (trust 5–20, "truce-keeper" at 15 and the like) would need the new `spare`, which the minds are now told of. Whether they use it is not measured: that needs a real-mind run.

**Behaviour change on seeded worlds:** a neutral row no longer hides a community stance. On the island ("rival town" -35/-40, "outlaws" -60), a resident with a neutral row toward such a person now counts them as `enemy` in its graphs.

Not covered: a real-mind battle with the new field (paid); a player's `spare` (no act maps to it yet); `friend` filters in a scene (the unit test only); the island's residents' behaviour over time after the change; maintain-verification-skill's full pass (the maps of verify-core, verify-minds, verify-player and verify-client were updated by hand in this change).

Evidence: `.local/living/verify/` (the runs above), `.local/relation-fight/` (`det/`, `check.log`, `suite.log`, `rescore.py`) and `.local/relation-mask/` (E5's rows, classification and tools) in the Spark worktree of `relation-fight`.

## Behind a world law, default off (second pass, 2026-11-23)

The general coordinator decided to ship the order behind a world law, **`relation_fight_on`, off by default**, and to measure its island effect before switching it on.

- **An ordinary law, not value-only.** The minds read it to choose their prompt text, and the mind service compiles the world's `script` row without `law_override` (docs/LAW_OVERRIDE.md). A value-only law would leave the minds on the old value until the next install. The mind test `the_laws_minds_read_change_by_an_install` lists it with `stranger_by_name` and the others.
- **Off (shipped): main's behaviour, byte for byte.**
  - `relation_ok` takes main's code path: any personal row decides alone, and the stance is read only without one. `relation_fight` is not read.
  - A player's blow writes nothing.
  - The prompts are main's text: the grammar's `relation` gloss, the consolidation's paragraph and its `"fight"` field are empty strings. Mind test `whom_one_fights_is_told_only_under_its_law`.
  - The mind ignores a reply's `fight` and shows no "fight: …" line.
  - The table and `mind_fight` stay. A row written while the law is off would act only once it is on, but nothing writes one: the minds are not asked for `fight`, and the players' blows do not set it.
- **On:** everything in the record above.

| Proof (law off unless said) | Run | Result |
| --- | --- | --- |
| det_compare main `5655887af` against the branch, each with its own script, on the two-sided melee (`spawn_battle_sides(60, 2)`, default seed) | `.local/relation-fight/det-law/melee` | identical: 3,600 ticks, 113 tables, 30,864 rows |
| det_compare main against the branch on an island world (the island seed's laws composed over each script, no battle, the residents' routines reading `relation: enemy`/`friend` and the seed's regard stances) | `.local/relation-fight/det-law/island` | identical: 7,200 ticks, 113 tables, 104,497 rows |
| verify-core `relation_fight`: first, with the law off, a neutral row still hides the war; then the law on for the stages above | `core-rflaw-075541` | PASS 12/12 |
| verify-minds `fight-field`, the law set on before the service starts | `minds-rflaw-075740-fight-field` | pass |
| verify-player `combat.py --scene all` (scene `strike` sets the law on and off again) | `player-rflaw-080001` | 59/59 |
| rules tests, mind tests, authority tests | | 362, 144 and 51 passed |

## The island, the law off against on (free, no model)

`living/tools/island_fight.py --wasm <island module of 760dde19d> --worlds 3 --minutes 12`.
- Six island worlds side by side on the private server (pinned to 0-4,10-14): 3 with the law off, 3 set on before anything was read (`law_override` `relation_fight_on = true`, revision 2).
- 12 real minutes each, which is 24 game hours at the island's 12-minute day.
- 277 living persons each and the seed's 13 regard stances ("rival town" -35/-40, "outlaws" -60, "the town that outlawed us" -50, "the cairn-cutters" -45, "old friends" +45, and others).
- Every targeted use, flight, wound and death was read every 2 s as the owner. No poll failed. Every world was paused, confirmed and deleted.

**Exposure:** of the residents' relation rows about people their own people hold as an enemy, 52 are hostile (enemies with the law either way), 67 peaceful (not enemies either way), and **25 neutral**: the pairs the law turns into enemies.

| World | Attacks (on hostile peoples) | Threats | Flights | Wounds (residents) | Deaths (residents) | `face` uses, of them at hostile peoples | `wave` / `nod` at hostile peoples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| off-1 | 0 | 0 | 8 | 0 | 0 | 14,638, 47 | 3 / 2 |
| off-2 | 0 | 0 | 14 | 0 | 0 | 12,724, 32 | 1 / 0 |
| off-3 | 0 | 0 | 49 | 0 | 0 | 14,148, 32 | 2 / 1 |
| on-1 | 0 | 0 | 31 | 0 | 0 | 13,131, 40 | 2 / 0 |
| on-2 | 0 | 0 | 16 | 0 | 0 | 10,904, 65 | 2 / 2 |
| on-3 | 0 | 0 | 27 | 0 | 0 | 13,423, 42 | 0 / 0 |

- **No violence in either arm.** There were no attacks, threats, wounds or deaths, so there were no killing sprees and no new resident deaths. The seeded routines attack only an attacker, and nothing started a fight in 24 game hours.
- **The visible effect:** `face` at people of a hostile people (the routines' "face the nearest enemy within 6 m when standing") averaged 37 per world with the law off and 49 with it on, about +30%. With three worlds each, that is within the spread (32–47 against 40–65).
- **Flights** (from wolves) spread too widely to compare: 8–49 off, 16–31 on.
- **No `wave`/`nod` at friendly peoples** were counted in either arm.
- A first pass, counting attack skills only, read the same: no attacks, wounds or deaths; flights 22/23/29 off and 12/15/24 on (`.local/relation-fight/island-pass1/`).

**What this does not measure:** minds choosing to fight. A resident's mind writes `relation: enemy` into its own graphs, and those choices are where the law matters most (E5). This run had no mind service. A fake model would not exercise that channel either, since its replies are fixed and do not read the prompt, and its canned graphs would replace the residents' routines. The effect of real minds under the law needs a paid run.
