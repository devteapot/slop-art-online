# Heed for players on a connected client: the throng, pins and focus

Since `heed-client` (2026-11-26; [docs/ATTENTION_BUDGET.md](../../../../docs/ATTENTION_BUDGET.md), "Built: the player side"). With the world's `heed_on` and `heed_players` laws both on (both off as shipped), a player perceives as individuals only whom its character heeds; the rest it sees is its **throng**, counted per 6 m cell in the public table `seen_throng` (row-level security `viewer = :sender`, at most 48 rows a viewer). The client draws the throng as simple figures and lets the player pin up to four individuals and focus one, through `human_heed`. The authority side is verify-player's [heed.md](../../verify-player/features/heed.md) and verify-client's [perception.md](../../verify-client/features/perception.md).

## How the client takes it

- **The subscription** (`net.rs`): `Feed::throng`, bit 6 of the perception set's key, set by `Delivery::throng` = `heed_on && heed_players` from the compiled script with the `law_override` rows laid over it (`delivery_laws`). On, `Feed::queries` adds `SELECT * FROM seen_throng` after the rest; nothing is replaced. The switch is `perception_law`'s make-before-break, like the other delivery laws (no table to wait for). **Both laws off: the same queries in the same order, the same key and the same log lines as before heed** (`heed_off_leaves_every_set_as_it_was_and_on_adds_only_the_throng`). `net::throng` reads the rows only while the set in place has the table (`PlayerConnection::throng_table`).
- **The figures** (`throng.rs`): per row, `count` cards (E1b's mock look: a person card standing, walking or with a spear forward, or an animal stand-in by `kinds`), on a sunflower spiral round the square's centre within half the `spread`, never outside the square; the `fighting` share fights, then the `moving` share walks (mirrored toward `heading`, stepping along it), the rest stand. Cards are kept per square (`(cell, size)`): a row changed in place moves its cards, new cards fade in and dropped ones fade out over the person fade's times (`fade::IN_S`, `OUT_S`), so a person moving between the individuals and the throng crossfades. **No colours:** the rows carry none, so every card is one neutral placeholder tint (`throng::PLACEHOLDER`; `tops` is where a colour summary will be read). Settings › Play › The throng (`settings:throng`, `Prefs::throng`, on by default) turns the drawing off.
- **Pins and focus** (`heed.rs`): T (`Act::Pin`) on whoever the cursor points at (`pick.rs`) pins or unpins them; Y (`Act::ClearPins`) unpins everyone; a fifth is warned about first and asked for on a second press within 3 s. A throng figure has no id: until the authority takes a position pin (`pin_at`), T on a figure pins the individual I perceive nearest it in its square (`heed::in_throng`), else a note says no one there can be picked out yet. Focus is whom the open text box speaks to, else the creature my last creature-aimed skill went to (10 s). One call carries the whole choice; calls are coalesced, at most one in flight and 0.3 s apart (the authority takes one per 250 ms), carry only those I perceive now, and are never sent when they change nothing (`heed::Sender`).
- **Refusals** are the authority's words, exactly, in the notes (`verbs.rs` toasts), and in the dump's `heed.refusals`.
- **The strip** (`ui/heed.rs`): "Keeping track N/4: … — focus: …" at the top left, with the keys. Ground rings: green under a pin, amber under the focus (`throng.rs` `rings`).
- **Settings rows** for heed (the throng's switch, the Keeping track keys) carry `ui::settings::HeedOnly` and show only while heed applies.
- **The live script:** `heed:ID` asks the authority to pin ID as it is, past the client's own check that I perceive ID, so a check sees the authority's refusal words.
- **The log:** `rules: heed for players true|false (heed_on and heed_players; …)` when it changes (never while it stays off); `heed: players heed true|false`; `heed: pin #ID (…)`, `unpin`, `cleared every pin`, `focus … → …`, `sent pins […] focus …`, `accepted …`, `refused: <words>; …`, `refused (paced): too many inputs; …`; `settings: the throng drawn true|false`.
- **The dump** (`dump:`): `heed` (`on`, `pins`, `focus`, `acked`, `pending`, `out_of_sight`, `refusals`, `log`) and `throng` (`on`, `drawn`, `rows`, `count`, `cards`, `leaving`, `tint`, and per square its row's fields with the cards drawn: `cards`, `stand`, `walk`, `fight`, `people`, `animals`, `inside`, `tinted`); both null while heed is off.

## Drive

On an island world (`verify.py launch --seed island`), all explicit. Run them after the ordinary scenarios: `heed-throng` leaves 200 fighters and their remains by the arrival.

```sh
S=.agents/skills/verify-ui/scripts
$S/check.py --run "$R" heed-throng    # a 200-fighter battle, laws off then on then heed_players off
$S/check.py --run "$R" heed-pins      # five residents: four pins, a fifth refused, unpin, focus, clear
$S/check.py --run "$R" heed-refusal   # an id not perceived, and one nobody has: the authority's words
```

- **`heed-throng`**: `spawn_battle_sides(200, 2)` (admin) and the player put 9 m south of the fighters' centroid; laws off: no `throng`/`heed` in the dump, the first set without `seen_throng`, no heed rows in Settings; both laws on (`set_world_law`, admin): the set subscribed again with one query more and switched to, then at the play camera and zoomed out (`notches:-6`) every square drawn as its row says and the client's rows the authority's (owner SQL `seen_throng WHERE viewer = 0x<identity>` right after the dump: at least 70% alike); Settings › The throng off and on; `heed_players` off: no rows of mine on the authority, no throng in the dump, the set the first one again. Shots `off`, `on`, `far`, `hidden`, `after`.
- **`heed-pins`**: five residents held 1.6 m round the player (`place_at`, `set_behavior`); T on four: the client's pins and the authority's `heed_choice` row hold the four; T on a fifth: the warning note, nothing sent; T again: refused with `You can keep at most 4 others pinned at once.` in the notes, the row still the four; T on a pinned one unpins; the box opened on one: focus on them in the row; closed: no focus; Y: no pins. Every `heed: sent` at least 250 ms after the one before, none paced. Shots `five`, `focus`.
- **`heed-refusal`**: a resident put 80 m off; `heed:ID` and then an id nobody has: both refused with `You can only keep track of someone you can see now.`; the row names neither. Shot `refusal`.

Each restores the heed laws to the world's own values (`law_values.own_laws`, else the shipped ones), and the residents.

## Not covered

- The crowd-card click as a position pin: the authority has no `pin_at` yet (the client's interim rule pins only individuals it perceives).
- Colours in the throng: `seen_throng` has no colour summary yet; the placeholder tint is checked (`tinted` 0).
- Frame time with the throng drawn, a real window and the owner's eye: a rendering branch's dev-box render pass, and a play-test.
