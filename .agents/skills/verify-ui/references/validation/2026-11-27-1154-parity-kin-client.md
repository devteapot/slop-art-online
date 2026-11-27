# parity-kin-client: my family, courting offers and community in the game client

**Branch** `parity-kin-client`, from `origin/main` `3d41ec73d` (parity-player-views: `my_kin`, `my_bond_offers`, `my_community`). Laptop, shared SpacetimeDB `v2.14.1` at `127.0.0.1:3300`. The release client was built in `$HOME/.cache/parity-kin-target` through `build-slot` (`BUILD_SLOTS=1`), with assets linked from the main checkout.

**What changed.** The game client and these drivers only. `living/scripts`, `living/authority`, `living/rules` and `living/bindings` are untouched. The details are in [features/kin.md](../../features/kin.md).
- `net.rs`: `KIN_VIEWS` is a subscription set of its own. It is asked when my character is known, again when it changes, and after every reconnect.
- `ui/kin.rs`: Log › People opens with Family and Community. Each courting offer is a card in the other person's window. An incoming card's button sends `conceive` through `human_act`.
- `looks.rs`: `sex_seen` (from the drawn look line's `form`), for the rules' sexed kin words.
- `people.rs`: a person window for someone not labelled this session takes the family or suitor wording for its title and talk chip. Its second line no longer starts with " · " when we have not met.
- `check.py` gains `kin`. The dump gains the `kin` key, and `given_places` now includes my community's name.

## Unit tests

`cargo test --release -p living-game`: **253 passed, 0 failed, 1 ignored** (`ik::spots::uneven_ground_spots`). The new tests are the five in `ui::kin::tests`: the relation words, the shipped script's words and act, naming and fallbacks, the courting card's words, and the community's lines.

## Runs

All runs were on island scratch world `verify-ui-kin-1127-124327`, deleted after the runs. Evidence is in `.local/living/verify/ui-kin-1127-124327/ui/`, with a copy of `kin/` and `checks.json` in `/Users/carlid/dev/slop-art-online/.local/living/parity-kin/evidence/`.
- `kin`: **25/25** on the last two runs.
  - The first run passed 24/25. The nameless parent had been seen as "a stranger in green and black" before the fixture moved them away, and the row used that label. A relative is now named by the known name or else by the relation ("Your parent"), never by a stranger's looks. The check names that case.
- `windows` 16/16, `offers` 24/24, `body-clock` 37/37. Each passed on two runs, the last after the person-window line fix: **102 passed, 0 failed**.
- No `ERROR` lines in any `client.log`.

The world's look generation (`c4-cbcc40bf`) is not in the laptop's look book, so people were drawn as VRoid bases. No sex was seen, and every relation word on screen was the neutral one ("parent", "child", "partner"). The sexed words ("mother", "son", "wife") are covered by the unit tests only.

Stills are in `/Users/carlid/dev/slop-art-online/.local/living/parity-kin/`: `01_people`, `02_partner_offer`, `03_courted`, `04_taken_up` and `05_after_reconnect`.

## Not covered

- A new character after a death: the subscription is asked again when `my_id` changes, but no scene drives a death and rejoin.
- Declining or withdrawing a courting offer: the rules have no act for it (see features/kin.md).
- dev-box's render pass, frame time, and a real window or trackpad.
