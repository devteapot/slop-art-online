# Core verification map

| Feature | Driver and proof | File |
| --- | --- | --- |
| Tick, housekeeping, pause and resume | `scenes.py tick` | [tick.md](tick.md) |
| Graph parsing, normalization, evaluation and routines | Cargo, mechanics and steering | [graphs.md](graphs.md) |
| Rhai skills, laws, crafting and exchanges | Cargo and 23 mechanics checks | [mechanics.md](mechanics.md) |
| Hunger, energy, eating, infant appearance and cry routing | `scenes.py needs` and `scenes.py infant` | [needs.md](needs.md) |
| Birth, infancy, aging and death cleanup | `scenes.py lifecycle` and mechanics | [lifecycle.md](lifecycle.md) |
| Species restrictions, grazing and migration floor | `scenes.py wildlife` and Cargo | [wildlife.md](wildlife.md) |
| Blows, threaten, yield and seize | Mechanics and `scenes.py seize` | [combat.md](combat.md) |
| One-off acts, graph coexistence and feedback | Mechanics and Cargo | [acts.md](acts.md) |
| Steering and `living/viewer/src/sync.rs` display-sync math | Five steering checks and three sync tests | [steering.md](steering.md) |
| Town life: daily rhythm, places, weather, gestures, commotion, `act_card`/`doing` | `town.py` on an island run, and Cargo | [town.md](town.md) |
| Town life layer 2 (rules side): the `wakes` and `woken_ring` laws, instinct-only residents' perception rings, waking 20 residents for a tick measurement | `wake_many.py` on an island run; the player-side scene is verify-player's `wake.py` | [town.md](town.md#layer-2-woken-residents-and-their-rings) |
| Seeded lives: authored residents placed, hamlets peopled, sheet relations as rows, carriers' known ways walked and goods moved between stores, outlaws at their spot on the road (threat, yield, seize), gestures by seeded relation | `lives.py` on an island run | [lives.md](lives.md) |
| Sight for minds and graphs: a graph's `sees` and a witnessed fight follow the sight line (rock, walls, shut gates hide); names in percepts follow what the observer knows | `scenes.py sight` | [sight.md](sight.md) |

Use [SKILL.md](../SKILL.md). Admin setup and `mind_act` do not establish player permissions or authentic model behavior. Read [the validation record](../references/validation.md) before treating a check as green.

The `living/viewer/src/sync.rs` tests are all this skill covers of the viewer. Controls, panels and rendering need the future UI skill (not built; see `verify`) once that skill exists.
