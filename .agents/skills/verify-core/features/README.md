# Core verification map

| Feature | Driver and proof | File |
| --- | --- | --- |
| Tick, housekeeping, pause and resume | `scenes.py tick` | [tick.md](tick.md) |
| Graph parsing, normalization, evaluation and routines; a refused start counted and told; `say` to an id in every form, waiting out the speaking limit, told when it cannot be said | Cargo, mechanics, steering, `scenes.py refusal` and `scenes.py say` | [graphs.md](graphs.md) |
| Rhai skills, laws, crafting and exchanges | Cargo and 23 mechanics checks | [mechanics.md](mechanics.md) |
| Hunger, energy, eating, infant appearance and cry routing | `scenes.py needs` and `scenes.py infant` | [needs.md](needs.md) |
| "food" as anything with nutrition: eat and give of `food`, the most nourishing first | `scenes.py food` | [needs.md](needs.md) |
| Birth, infancy, aging and death cleanup; the laws of starting a family (`conceive_roof`, `conceive_food`) and of the longing for a child (`longing_after_min`, `longing_food`) | `scenes.py lifecycle`, `scenes.py family_laws` and mechanics | [lifecycle.md](lifecycle.md) |
| Species restrictions, grazing (shown as a `doing` row) and migration floor | `scenes.py wildlife` and Cargo | [wildlife.md](wildlife.md) |
| Remains of every death (the `carcass` law's items), taking from them by any creature, their expiry (`remains_s`, the private `rot` table), and a wander keeping its heading (`wander_turn`, `wander_keep_s`) | `scenes.py remains` and Cargo | [wildlife.md](wildlife.md#remains) |
| Blows, threaten, yield and seize | Mechanics and `scenes.py seize` | [combat.md](combat.md) |
| One-off acts, graph coexistence and feedback | Mechanics and Cargo | [acts.md](acts.md) |
| Dealings on records: agreements kept, broken, lapsed and not taken; demands met and unpaid; regard read by a relation filter; hooks and install checks | `scenes.py dealings` on an island run, and Cargo | [dealings.md](dealings.md) |
| Steering and `living/viewer/src/sync.rs` display-sync math | Five steering checks and three sync tests | [steering.md](steering.md) |
| Moving as a per-creature law (`motion(a)`): flight share of the walk, turning on the spot; an installed law changes both | `scenes.py moves` | [steering.md](steering.md#moving-as-a-law) |
| Flight from a creature: steering runs from the threat until `flee_clear` farther | `scenes.py flee` on a `stage1-acts` run | [steering.md](steering.md#flight) |
| Town life: daily rhythm, places, weather, gestures, commotion, `act_card`/`doing` | `town.py` on an island run, and Cargo | [town.md](town.md) |
| Rhythms at any hour (working hours, a second sleep, `work_hours`) and Cullet's trades at their workplaces with their starting habits; Cullet's life law | `rhythm.py` on its derived Cullet seed, and Cargo | [town.md](town.md), [laws.md](laws.md) |
| Hospitality (`host`): the skill's rules, the engine's house lookup, the `guest` row and its end in housekeeping, the theft exemption | verify-player's `host.py` on an island run | [town.md](town.md#hospitality) |
| Seeded lives: authored residents placed, hamlets peopled, sheet relations as rows, carriers' known ways walked and goods moved between stores, outlaws at their spot on the road (threat, yield, seize), gestures by seeded relation | `lives.py` on an island run | [lives.md](lives.md) |
| Goods as script data matched by trait; fires that eat fuel (`structure.lit_until_ms`), warm only while lit and are relit by someone who knows fire; recipes at a burning workplace drawing its fuel (kelp → ash → glass with peat); a fishing ground's shared stock (`resource_node.pool`) | `scenes.py goods` and `scenes.py stock` on the goods fixture, and Cargo | [goods.md](goods.md) |
| A world's own day and laws: `day_minutes`, a seed's laws overlay installed at creation, rates per game hour in real time, sight to 48 m by day, names within 24 m, the dark, lamplight and a carried light at night (`glow`, `lights`), `daylight` | `scenes.py laws` on a `cullet-laws` run, and Cargo (`cullet_check`) | [laws.md](laws.md) |
| Sight for minds and graphs: a graph's `sees` and a witnessed fight follow the sight line (rock, walls, shut gates hide; drops and things below eye height do not, and block the foot); names in percepts follow what the observer knows, including at a death (the dead's community keeps their name; the killer reads "you"). How far each creature sees and hears is the `senses(a)` law (day, night, torch; installed overlays change it). What someone is seen doing: an AI body's activity label, unchanged by the derivation from the body | `scenes.py sight`, `scenes.py senses`, `scenes.py doing`, `scenes.py death-names`, `scenes.py drop` on a `plan-test` run, `scenes.py low` on an island run | [sight.md](sight.md) |

Use [SKILL.md](../SKILL.md). Admin setup and `mind_act` do not establish player permissions or authentic model behavior. Read [the validation record](../references/validation.md) before treating a check as green.

The `living/viewer/src/sync.rs` tests are all this skill covers of the viewer. Controls, panels and rendering need the future UI skill (not built; see `verify`) once that skill exists.
