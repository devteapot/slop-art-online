# Hospitality (`host`)

Since 2026-11-09 (docs/TOWN_LIFE.md, "What residents can do"). A grown person takes someone in as its household's guest until the morning hour the rules name: a bed in the house at its home door and food from its household's store. Players reach it through `human_act` (`{"do": "host", "target": {"id": N}}`), minds through acts, residents through graphs; the same skill rules (`skills.rhai`) and engine primitive (`town::host`).

## Sub-features

- Hosting oneself is refused by the rules ("you cannot be your own guest"); a person with no house at its home door is refused by the engine ("you have no house to offer").
- A resident whose household owns a stocked store hosts the player through its graph: a private `guest` row (host, house), the player's experience ("… takes you in as their guest until 07:00 …"), a `lodging` row in `my_places` at the house, a `host` chronicle row.
- The stay ends at the next `until_hour` of the world's day (`host_done`; the world starts at 07:00).
- Before the stay, onlookers perceive the newcomer taking from the household's store ("… took 1 berries from …'s storage"); during it, nobody does.
- `guest` is refused to the player and to an anonymous client.

## Driving it

```bash
V=.agents/skills/verify/scripts/verify.py
$V launch --run player-host-<n> --seed island --target-dir .local/living/target-wake-island
.agents/skills/verify-player/scripts/host.py --run player-host-<n>
$V cleanup --run player-host-<n>
```

Admin scene calls: `set_weather`, `place_at`, `set_behavior` (the resident's graph: `host` the player, then wait). The driver reads `until_hour` from the rules. Evidence: `<run>/host.json`, `actions.log`.

## Gotchas

- Run it on a fresh world: on a world where the player is already a guest, "before the stay" no longer holds.
- The stay's end is not waited for (up to a world day, 12 minutes); housekeeping's `guests_leave` is covered by its index range and by reading `until_ms`.
