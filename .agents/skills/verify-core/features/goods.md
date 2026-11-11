# Goods, recipes and fuel

Rules: [docs/WORLD_RULES.md, "Goods, recipes and fuel"](../../../../docs/WORLD_RULES.md#goods-recipes-and-fuel). Added 2026-11-11 on `goods-1`.

## Sub-features

- **Goods as data.** Items, structure kinds, resource kinds, techniques and recipes are the script's tables (`items()`, `structures()`, `resources()`, `know_how()`, `recipes()`), read once; the rules ask them through `entry_of`, `names_of` and `having`. Requirements match by trait: food has nutrition, fuel has the fire's `burns.fuel` trait, a recipe takes an item or anything with a trait.
- **Fires that eat fuel.** A kind with `burns` is lit only while it holds fuel. Its one value is the public `structure.lit_until_ms`; feeding (`feed`) and a recipe's heat (op `burn`) settle it, nothing is written while it burns, and it goes out on its own. Relighting an out fire takes knowing `fire`.
- **Warmth and light from lit fires only.** `act::warmth` counts a burning structure within `burns.warmth` (and `burns.light`, the `near_light` fact); campfires (`warms` without `burns`) as before.
- **Recipes** (`make`): at a workplace (`at`), burning (`lit`), drawing `fuel` units from it, needing a technique (`knows`).
- **Shared stocks.** `resource_node.pool` names the node whose stock a spot draws on; seeds place nodes with `resource_nodes` and a `pool` name.
- **Old worlds.** The shipped tables hold what the Rust constants held; the shipped world has no fires that burn fuel and no recipes, so `feed` and `make` are not offered there.

## How to get to it

- Cullet's goods: [`living/scripts/cullet_goods.rhai`](../../../../living/scripts/cullet_goods.rhai), composed over the shipped script (`floors::compose`; the scene's `floor_compose` does the same) and installed with `install_script`.
- Fire state: `living/rules/src/fire.rs`; the effects in `living/authority/src/act.rs` (`feed`, `Effect::Burn`, `warmth`, `fire_state`); a mind's scene says "burning, about N hours of fuel left on it" or "out" (`perceive.rs`).
- Scene setup: admin `place_structure`, `place_resource(near, kind, dx, dy, max, pool)`, `grant_know_how`, `place_at`. Offsets are non-negative: the CLI reads `-1` as a flag.

## Driving it

```bash
G=$R-goods
python3 "$V" launch --run "$G" --seed "$PWD/$C/goods" > ".local/living/verify/$G/launch.txt" 2>&1
python3 "$C/scenes.py" goods --run "$G" > ".local/living/verify/$G/goods.txt" 2>&1
python3 "$C/scenes.py" stock --run "$G" > ".local/living/verify/$G/stock.txt" 2>&1
python3 "$V" cleanup --run "$G"
```

The fixture `scripts/goods.json` is a valley with three adults and a fishing ground of three seeded spots sharing a stock of 3 (`resource_nodes`, pool `jetty`). The valley also grows wild fishing spots (pool 0).

- `goods` (about 6 minutes): installs Cullet's goods; places a hearth beside A and a furnace 9 m off (in sight, beyond its 6 m warmth from C); places a kelp bed, a peat bank and a sand bank beside A. A gathers 4 kelp, 8 peat and 2 sand (four acts at a time, `MAX_QUEUED`). Ash at the out hearth is refused ("is out: feed it first"); C, beside it, is not warmed (bit 6 of `vitals.rate_key`). A feeds one peat: `lit_until_ms` is one unit's burn ahead (0.5 a game hour: two game hours, 60 s on a 12-minute day), C sees "lit the hearth" and is warmed. Four kelp make one ash at the hearth. A feeds the furnace five peat and makes glass from the ash and two sand; the furnace's `lit_until_ms` drops by one unit (10 s at 3 an hour) beyond its burning. The hearth then goes out with its row unchanged, and C is no longer warmed. B, who does not know fire, is refused lighting it; A lights it again.
- `stock` (under a minute): the seeded spots' `pool` is the first one's id, and its max 3. A person fishes three fish from the second spot; the stock is empty, and gathering at the third spot is refused as depleted.

## Gotchas

- `{"id": N}` targets resolve creatures before things, and node and creature ids are separate sequences: aim at `{"nearest": kind}`.
- A placed structure stands 0.8 m east of the character; `place_near` puts a character 1 m east of another.
- Needs re-read warmth when the body is next looked at: allow tens of seconds for `rate_key` to follow a fire lit or gone out.
- The script is past 128 KiB: `install_script` goes over HTTP (`Scene.call` does it for large arguments; `living/tools/install_script.py` elsewhere).

## Not covered

- Seeded fuel on a structure (`structures[].fuel`) and seeded nodes of Cullet's kinds: a world installs Cullet's goods only after its seed has placed things, so the fixture uses shipped kinds; the seeded fuel goes through the same `fire::fed` as feeding.
- `near_light`: no shipped law reads it yet.
- Smoking and baking by recipe, lamp oil and lamps live: covered by the rules test `goods_are_data_matched_by_trait_and_fires_eat_fuel` only.
