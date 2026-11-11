# Sight that depends on facing

Since 2026-11-11 (`fov-1`; docs/PERCEPTION.md, "The field of view (sixth change)"). One pure function decides every look, `living_rules::sight::sees` (`living/rules/src/sight.rs`), from the observer's `senses(a)` (with a `field` while the world's `fov_on` law is on), its `body.heading` at the instant (`common::heading_at`), the target's `glow` and whether it is already seen. `perception::in_sight` and `perception::visible` call it, and so does every perception path: players' perceived sets, graph scenes, minds' scenes, witnesses, the combat feed, a predator's senses, a player's aimed act. `set_world_law(name, value)` (admin) changes a law on a running world: it writes the value into the installed script (`fn world_law_values()`, a new `script.revision`), keeps it in `world_law`, and records it in `law_change` and the chronicle (kind `law`).

## Sub-features

- **Off as shipped, the old rule.** `cargo test -p living-rules sight` (`without_a_field_the_answer_is_the_old_rule`: 311,040 cases against `dist <= max(sight, glow) (+keep) && sight_clear`), and `scenes.py fov`'s first probe: a graph's `sees` finds someone 5 m ahead, 5 m behind and 1.5 m behind.
- **The zones and margins** (`sight::tests`): full sight within ±70°, a third of it out to ±110°, all round within 3 m (2 m in the dark), 10° and 1 m more for someone already seen; `glow` only within the field; walls hide inside the field too.
- **The law and its values** (`script::tests::sight_depends_on_facing_only_when_the_world_s_law_says`, `cullet_check::tests::cullet_s_sight_takes_the_field_when_the_law_is_on`): no field in any state when off; the field's values from `law(name)`; the dark near ring; the block written once and replaced; a value of another kind or a name that is no law not taken.
- **`set_world_law` on a running world** (`scenes.py fov`): refused for a name that is no law and for a value of another kind; on, the installed script carries the values at a new revision; `law_change` holds name, old, new, when, who, revision; a chronicle row says it.
- **Facing decides** (`scenes.py fov`): with the field on, the watcher facing east sees ahead and within the near ring, not 5 m behind; facing west the reverse. With `fov_near_m` and `fov_near_dark_m` at 0.5 (laws), 1.5 m behind is not seen. Off again: all round.
- **A windup from behind** (`scenes.py fov`): the struck graph guards when `threatened`. On, with the starting near ring, a striker 1 m behind is within it, seen and guarded against. With a 0.5 m ring there is no guard and the blow lands. Off: guarded, as before.
- **Witnesses by facing** (`scenes.py fov`): with the field on, an onlooker 4 m off facing the duel witnesses it (`experience` kind `fight`) and one 5 m off facing away does not; off, both do.

## Driving it

```bash
python3 "$C/scenes.py" fov --run "$R"   # about 3 min on the default seed
```

## Gotchas

- Speech is limited to one line every 2 s (`perceive::speak`, "speaking too fast"): the probe's `say` lines are 2.2 s apart.
- The same graph installed again does not start over, and a `wait` is held to 120 s; the onlookers' graphs differ each round (`wait 60 + n`). With a field the striker must see its target to strike it: with a 0.5 m ring, a striker 1 m behind facing away cannot, the strike does not resolve and the graph backs off for about 40 s. So the striker turns to the watcher's spot first. A strike cannot be a one-off act (`mind_act` refuses real-time skills).
- At night the near ring is `fov_near_dark_m` (2 m), not 3; the scene sets both values when it lowers the ring.
- Witnesses are told a fight's first blow only (more than 30 s after the attacker last hurt the victim, `act.rs` `first_blow`): the duels are 31 s apart.
- Onlookers stand on the open line itself: off the line the map may hide them behind rock.
- The scene leaves `fov_on` false and the near rings at 3 and 2 m (in `finally`), and moves its six actors off the open line, which later scenes (`doing`) use.
