# My family, courting offers and community

Perception parity, phase 0 (`docs/PERCEPTION_PARITY_AUDIT.md`): a character's graphs read its own kin (`Target::Parent`, `Target::Partner`), the courting offers made to it (`Target::Suitor`, `Weight::Courted`) and its community (`membership`), and a human player could see none of them. The authority's identity-scoped views `my_kin` (`id`, `relation`), `my_bond_offers` (`id`, `incoming`, `from`, `to`, `at_ms`) and `my_community` (`id`, `name`, `founder`, `founded_ms`, `home_x`, `home_y`, `since_ms`) carry them ([verify-player kin](../../verify-player/features/kin.md)). The client subscribes to them as a set of their own (`net.rs` `KIN_VIEWS`, `keep_kin_views`: asked when the character I play is known, again for a new character and after every reconnect; a world from before the views logs `kin views unavailable` and plays on). `ui/kin.rs` shows them; nothing is added to the always-visible HUD.

- **Log › People** (L, the People tab) opens with **Family**: a row per parent, partner and child (parents, partner, then children; at most 8), each a click to their window (tag `log:kin:<I>`). Then **Community** (tag `log:community`): its name, "Founded by … on day N · you joined on day M" (or "You founded it on day N"), and "Home: 140 m northeast" from where I stand. Then "People met" and the people as before.
- **Naming.** Only from what the client already has. A relative: the name my character knows (`my_known_names`, where the rules put kin and community members), else the relation alone ("Your parent"; never a stranger's looks for one's own parent, even one seen earlier). A suitor or a founder: that name, else how I see them (`looks.rs`, the perceived projection, kept for the session), else "A suitor" or no name. A row's note is the relation and "here now" (perceived and made out) or "not in sight" (unseen, or too far to make out: one far figure is not told apart). No `alive`, health or position of a relative is in the views, and none is shown.
- **The rules' words.** The relation's word is the world's `kin_terms()` (the words a speaker uses for a relative, `Scripts::kin`): the first word for the sex I have seen the body to be (`looks.rs` `sex_seen`, from the drawn look line's `form`: "mother", "son", "wife"), else the relation's sex-neutral word ("parent"), else the relation's name as the views and minds' scenes give it ("child", "partner"). The home's way and distance are `living_rules::bearing::from_here` (the words every scene uses); days are the clock's (`living_rules::day_of`).
- **Courting offers.** One card in the other one's person window, under the trade offers' cards: theirs, "A woman in green wants to start a family with you.  ·  1:42 left", with a button per skill whose `_ui()` puts it `on` `bond` (`On::Bond`, `kin::bond_acts`, at most two, in the script's order; the client names no skill), each with its rules' label and sent through `human_act` toward them. As shipped that is `conceive` alone (`conceive_ui() { on: ["person", "thing", "bond"] }`: its default places plus the card), which takes the offer up (its `done` gives `op: "bond"`): `{"do":"conceive","target":{"id":N}}`; a world with no skill on `bond` shows the card without buttons; mine, "You asked Wren to start a family.  ·  1:42 left", with none. The time left is the `bond_window_s` law from the offer's `at_ms`; a card goes when its row does or its window ends. A new one opens their window when the left anchor is free (or holds Log and people), as a trade offer does, and is noted once. The rules have no act to decline or withdraw a courting offer: it lapses at the window's end (the authority drops the row a minute later).

## Sub-features

- `family`: the rows, their order, names and relation words, "here now" or "not in sight", a row opening their window.
- `fallback`: a relative the rules give no name, out of sight: "Your parent", "not in sight".
- `no-leak`: nothing of an unseen relative's health, life or place; the client's `my_kin` rows hold `id` and `relation` only.
- `community`: the name, founder and days, the home's way and distance; the name counts as given me (`given_places`).
- `courting`: an incoming card with the rules' act, the act sent and taken up; my own card without buttons; taking one up drops mine.
- `reconnect`: the views asked again; the rows back.

## Dump keys

`kin` (`rows`: `id`, `relation`, `word`, `title`, `note`, `here`, `named`; `community`: `name`, `lines`; `bonds`: `id`, `with`, `incoming`, `text`, `until_ms`; `acts`: the card's acts, `skill` and `label` each, in button order). `naming` holds every row's title and note (`kin`), the community's name and lines (`community`) and the cards (`bond`); `given_places` includes my community's name. Tags: `log:kin:<I>`, `log:community`, `person:bond:<ID>:<ACT>` (ACT 0 is the first skill on `bond`; shipped, conceive).

## Driving it with drive.py

Preconditions: baseline; five adult residents. Scene setup is owner SQL and admin calls, never player acts: `UPDATE character SET parent_a, parent_b` (me: A and B; C: me and D), B's name blanked (the rules then give none), my and E's vitals fed, `INSERT INTO community` and `membership` (ids 990001), `INSERT INTO bond_offer` (`"from"`, `"to"` quoted: me to D); E's offer by admin `mind_act` (`{"do":"conceive","target":{"id":{me}}}`, as a mind decides; E within the act's 2 m reach). A, C and E are placed beside me, B and D 40 m off (sight is 11 m by day), all held still.

- `ready;sync:scene;sync:kit;wait:3;key:KeyL:tap;click:@log:tab:1;dump:people` → `kin.rows` parents, partner, child; `perceived` holds A and C, not B or D.
- `click:@log:kin:2` → `Person<D>` Left, `kin.bonds` my offer to D, no `person:bond:<D>:<ACT>`.
- `click:@win:Person<D>:close;sync:court;wait:4` → `Person<E>` Left, `person:bond:<E>:0` (no `:1`), `kin.acts` the skills on `bond` (shipped: `conceive`), one note "… wants to start a family with you".
- `click:@person:bond:<E>:0` → client.log `verbs: Conceive → {"do":"conceive","target":{"id":<E>}}`; owner SQL `expecting` has `b = me`; no `bond_offer` to me; both cards gone.
- `reconnect;wait:10` → `kin views applied for #<me>` twice in client.log; the rows back.
- Scenario: `check.py --run $R kin` (25 checks). It puts every row back (also after a failed drive), and the borrowed residents' places and graphs.

## Gotchas

- Under the shipped rules every relative is known by name (`my_known_names` holds parents, children and their other parent), so "Your parent" shows only for a relative with no name; the scene blanks one to reach it. Suitors and founders who are not kin or community members are the ordinary unnamed case.
- Taking up the offer makes a child on the way (`expecting`); the scene deletes it at the end, so no birth follows on the scratch world.
- Not covered by the scene: a new character after a death (the subscription is asked again when `my_id` changes; the views themselves follow the caller's living character), and a sexed word for a relative never seen this session (it is the neutral word by design).
