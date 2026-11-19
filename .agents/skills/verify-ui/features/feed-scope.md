# Public-feed scoping on the client

Since `feed-scope-client` (2026-11-19, [docs/FEED_SCOPING.md](../../../../docs/FEED_SCOPING.md), "Client subscriptions", "Remembered vs current", "The look and act path", "Reconnect"). The client's half lives in `living/game/src/feed.rs`. `net.rs` does the switching.

## What the client does

- **The one input.** The public `feed_scope` row is in the static set, beside `world` and `land`. Its `stage` (no row means 0) chooses the feed:
  - **legacy** (stage 0, as main): `gate` whole in the base, and `structure` and `resource_node` in the near window by chunk;
  - **scoped** (stage ≥ 1): `my_things`, `my_remembered_things`, `my_owners`, `my_stock`, `my_fuel_seen` and `my_contents_seen` in the base, and `map_structure` and `map_resource` in the near window over the same chunks.
- **Its own switch.** The feed switch is independent of the perception tiers' switch (`net::perception_law`). Each of the two chooses its own queries: [law-override.md](law-override.md) covers the tiers, and `net::feed_switch_tests` checks every combination of stage, delivery laws and world kind.
- **The base, whole.** The base subscription is the perceived set, the world kind's own queries and the feed's base queries, in one set (`net::base_set`). So a connect or reconnect applies the perceived rows and the feed's views together.
- **A switch, made before broken.** When the stage crosses 0 ↔ 1 (`Net::switch_feed`):
  1. A whole base for the new feed is subscribed beside the old one.
  2. The near window is subscribed again over the same chunks. Its key carries the feed's tag, and it waits instead of settling.
  3. Once both are applied, the old base is dropped, the reads move (`feed::reads`), and the near window settles.
  4. The client logs `feed: subscribing the … set beside the … one` and then `feed: on the … set after N ms (K things; M before, missing now J […])`.
- **Holding the drawing.** While a switch is under way (`feed::switching`), `world::things` keeps what it drew.
  - With the law off at stage 1, the authority clears the map projections in the same transaction that sets stage 0. The scoped rows are gone before the legacy set can arrive (about 80 ms on the laptop).
  - The same happens to a client still subscribing the scoped set when the cut lands.
- **One source for every reader.** `feed::things` and `feed::find` serve `world::things`, `verbs.rs` (aiming, titles, fire facts, warmth) and `sightfield.rs` (`feed::shut_gates`).
  - Under the scoped feed, a key in `my_things` is live.
  - A key in `my_remembered_things` but not in `my_things` is last seen: it is drawn where it was, as it was.
  - `map_*` rows are architecture and landmarks, at full size.
  - Anything else is unknown: not drawn and not offered.
  - Keys are (class, id) under both feeds.
- **Drawing.**
  - A fire glows when its copy says `lit`. A fuel fire never seen burning is drawn out.
  - Every other kind is drawn as main draws it (`Thing::glows`).
  - Under the scoped feed, a resource is redrawn when its `left / max` changes (0.4–1.0).
  - A legacy row is drawn at the size it had when it arrived, as on main.
- **Acting on things** (`verbs.rs`):
  - **A remembered thing:**
    - its title is "…, last seen N ago";
    - it has no live facts;
    - its one choice is "Go to where it was" (`{"do": "goto", "target": {"at": …}}`);
    - it never opens a wheel and is never F's nearest.
  - **A live fire:** its title adds "burning" or "out". After the character has looked it over, it also adds "about N h of fuel left, as of when you looked it over, M ago" (`my_fuel_seen`).
  - **A live container** (a kind that `holds`, remains, a trap; since feed-scope iteration 2): its title adds "not looked inside" until the character has looked in, taken from it or stored in it. After that it adds what was found then, as "3 berries when you looked inside, M ago" or "nothing inside when you looked, M ago" (`my_contents_seen`).
  - **The rules' fuel check:**
    - for a fire it has looked over, the fuel is projected from that look at its burn rate;
    - for a fire it never looked over, the fuel is NaN, which refuses no fuel comparison: the authority decides;
    - for a fire that is out, the fuel is 0.
  - **Looking it over.** The verb (`inspect`, "Look over" on a wheel) is offered from its spec and check. Like every list row, the list names it by its skill.
- **Gates.**
  - The legacy feed blocks with every shut `gate` row.
  - The scoped feed blocks with a gate seen shut now, or else one remembered shut.
  - A gate never seen does not block the Shade.
- **Reconnect and join.**
  - The views are read as "what I see" only once the base is applied, and after `join`'s reply when a join was sent (`feed::settled`).
  - Before then, the scoped source gives the map alone.

## Evidence the client gives

- The dump's `extra.feed_scope` holds:
  - the stage and the reads;
  - `settled`;
  - the counts by source;
  - `shut_gates`;
  - every thing, with its source, `lit`, `gate_open`, `left`/`max`, `fill` and owner.
- `LIVING_GAME_FEED_LOG=<file>` writes one JSON line whenever the things, the drawn keys or the switch's state change, and at least once a second. Each line holds:
  - the stage, the base, `base_next` with its `applied`, the near window's feed and its next, and the reads;
  - `switching` and `settled`;
  - the counts;
  - the keys added and gone, both read and drawn (`drawn_added`, `drawn_gone`);
  - the legacy and scoped row counts in the cache.

## Recipes

Both scenarios cut the world over for good, because stage 2 is latched. Run them on fresh worlds, after any stage-0 scenario you want on the same world.

- `check.py --run <cullet run> feed-scope` (`--seed cullet`, explicit): one client stays connected throughout. Its checks:
  - **stage 0:** main's legacy set, everything drawn from legacy rows;
  - **stage 1** (law on, grace 120): the switch, with legacy rows read and drawn while the scoped set was subscribing, and no drawn map thing lost at any line;
  - **the law off:** back to legacy, the drawing held while the map rows were already gone;
  - **on again with grace 1:** the switch and then the cut, with legacy rows leaving the cache after the switch and nothing drawn going with them;
  - **reconnect at stage 2:** the scoped set only;
  - **a spawned stranger's remains in Cullet's brush:**
    - hidden from outside;
    - live from inside (a few spots);
    - remembered where it lay;
    - live again;
  - **the remains, looked inside from 1.5 m:** "not looked inside" before; `my_contents_seen` and what was found after;
  - **lamp 72 at 1.4 m:**
    - burning or out with no fuel words, and looking it over offered;
    - `act:inspect`;
    - `my_fuel_seen` and the fuel words in the title;
  - **a lone full boulder:**
    - a map landmark at fill 1;
    - after `act:gather`, live at `left / max`.

  Laws are restored with `own_laws`. The stranger is spawned, so no resident is killed.
- `check.py --run <island run> feed-scope-gate` (`--seed island`, explicit): two gates with living keepers, far apart. Its checks:
  - **the far gate, shut by its keeper at stage 0:** in `shut_gates` (legacy);
  - **after the cut:** not in `shut_gates` (never seen);
  - **the near gate:**
    - live and open in sight;
    - remembered open away from it;
    - shut out of sight, still remembered open, and not blocking;
    - live and shut and blocking back in sight;
    - remembered shut and still blocking away again.

  The keepers are restored and both gates reopened.

## Not covered here

- The authority's sight test, memory rules and boundary: see verify-core and verify-client `feed_scope.py`.
- Owner labels from `my_owners` on screen: no fixture grants one in these scenes.
- A depleted node out of sight. It is drawn full as its landmark, because `my_stock` is per cluster and not per node.
- Cost: see the cost gate in FEED_SCOPING.md.
