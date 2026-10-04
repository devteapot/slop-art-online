# Core verification map

| Feature | Driver and proof | File |
| --- | --- | --- |
| Tick, housekeeping, pause and resume | `scenes.py tick` | [tick.md](tick.md) |
| Graph parsing, normalization, evaluation and routines | Cargo, mechanics and steering | [graphs.md](graphs.md) |
| Rhai skills, laws, crafting and exchanges | Cargo and 23 mechanics checks | [mechanics.md](mechanics.md) |
| Hunger, energy, eating and night cold | `scenes.py needs` | [needs.md](needs.md) |
| Birth, infancy, aging and death cleanup | `scenes.py lifecycle` and mechanics | [lifecycle.md](lifecycle.md) |
| Species restrictions, grazing and migration floor | `scenes.py wildlife` and Cargo | [wildlife.md](wildlife.md) |
| Hurt, kill, threaten, yield and seize | Mechanics and `scenes.py seize` | [combat.md](combat.md) |
| One-off acts, graph coexistence and feedback | Mechanics and Cargo | [acts.md](acts.md) |
| Steering and `living/viewer/src/sync.rs` display-sync math | Five steering checks and three sync tests | [steering.md](steering.md) |

Use [SKILL.md](../SKILL.md). Admin setup and `mind_act` do not establish player permissions or authentic model behavior. Read [the validation record](../references/validation.md) before treating a check as green.

The `living/viewer/src/sync.rs` tests are all this skill covers of the viewer. Controls, panels and rendering need the future UI skill (not built; see `verify`) once that skill exists.
