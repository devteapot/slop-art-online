# parity-kin-client: the courting card's acts from the rules' declarations

**Branch** `parity-kin-client`, on `264ab207d` (the [first record](2026-11-27-1154-parity-kin-client.md)). Laptop, shared SpacetimeDB `v2.14.1` at `127.0.0.1:3300`. The release client and the authority module were built in `$HOME/.cache/parity-kin-target` through `build-slot` (`BUILD_SLOTS=1`).

**Why.** dev-box's merge check stopped the branch: `ui::tests::the_game_client_names_no_new_skills` found `game/src/ui/kin.rs` naming the skills `conceive` (`BOND_SKILL`, the act the card sent) and `accept` (a dump key and a tag part).

**What changed.**
- `living_rules::ui`: the `on` vocabulary grows at its end by `bond` (`On::Bond`): an incoming courting offer's card, toward its maker. The reader refuses `bond` on a skill whose spec takes no target, as it refuses `offer`.
- `skills.rhai`: `conceive_ui() { on: ["person", "thing", "bond"] }`, which is its default places plus the card. Nothing else is declared, so its label and look stay the defaults.
- `ui/kin.rs`: no skill is named. The card has a button for each skill on `bond` (`bond_acts`, at most two, in the script's order). Each button sends its skill through `human_act` toward the maker. The acts are read again when the laws change.
  - Dump: `kin.accept` is now `kin.acts` (`[{skill, label}]`).
  - Tag: `person:bond:<ID>:accept` is now `person:bond:<ID>:<ACT>`.
  - A world that also puts `decline` on `bond` (the Spark's `bond-decline`) gets a second button with no client change.
- `check.py kin` uses the new tag and checks `kin.acts`. The changes are also in `features/kin.md`, `features/README.md`, `SKILL.md` and `docs/INTERFACE.md`.

**Presentation only.** The authority reads only `label` from a skill's `_ui()` (`perception.rs`, `heed.rs`), and conceive's `label` is unchanged. The new rules test checks that only `on` differs from the defaults. `ui::tests::the_rules_are_the_same_without_any_declaration` compares the skills, shapes, laws, `validate()`, offered skills and checks with and without every `_ui()`, and it passes. The world installed the changed script: install refuses any `ui_errors`. No det comparison was run.

## Tests

- `cargo test -p living-rules`: **383 passed, 0 failed, 17 ignored**. This includes the guard and the new `ui::tests::a_courting_offer_is_answered_by_the_skills_on_bond`, which checks:
  - the shipped `bond` acts are `conceive`;
  - only `on` is declared;
  - conceive's act node;
  - a declared `decline` adds a second act;
  - `bond` on `eat` is refused.
- `cargo test --release -p living-game`: **253 passed, 0 failed, 1 ignored**.
- `cargo build -p living-authority --target wasm32-unknown-unknown --release`: ok.

## Runs

All runs were on island scratch world `verify-ui-kin2-1127-131156`, deleted after the runs. Evidence is in `.local/living/verify/ui-kin2-1127-131156/ui/`, copied to `/Users/carlid/dev/slop-art-online/.local/living/parity-kin/evidence-take-up/`.
- `kin` **26/26**. This adds "the card's acts are the skills the rules put on `bond`". client.log has `ui: conceive toward #6 (a courting offer)` and `verbs: Conceive → {"do":"conceive","target":{"id":6}}`.
- `offers` 24/24, `windows` 16/16, `body-clock` 37/37: **77 passed, 0 failed**.
- No `ERROR` lines in any `client.log`.

## Not covered

- A second act on `bond` (decline) on screen. It is covered by the rules test only, until `bond-decline` lands.
- The det comparison against main.
