# Player verification map

| Feature | File |
| --- | --- |
| Player character: join, move, act (a command runs once, `command.py`; a failed command told as an AI is told, `told.py`), walk far by click-to-move, speak, refusals | [player-character.md](player-character.md) |
| Combat skills: use, refusals, strike, killing a person, bow, fire bolt, block, dodge, heal, wolves, death and rejoin | [combat.md](combat.md) |
| Gestures: wave, nod and face through `human_act`, answered by residents; refusals | [gestures.md](gestures.md) |
| Hospitality: a resident takes the player in (`host`), `lodging`, the stay's end, no theft from the host's store during it; the player's own `host` refused without a house; `guest` private | [hosting.md](hosting.md) |
| Verbs from the game client: F on a thing or person, C on oneself, words for writing, the pack and know-how panels, refusals shown with the rules' reason, a skill the world adds appearing with no client change | [verbs.md](verbs.md) |
| Trade offers: a resident's offer read in `my_offers` (incoming, `until_ms`, ids not names), told in `my_experience`; a second player's own offer read as outgoing; neither sees the other's, anonymous none; `accept` refused without the goods (the offer stands), then accepted (goods both ways, the row goes); `trade_offer` private (`offers.py`) | [offers.md](offers.md) |
| Dealings: the player proposes terms through the verbs' node, reads the record in `my_records`, is told it was accepted, what it owes and that it is kept; a demand on the player told, and unpaid when it falls due; `record` and `record_party` private | [dealings.md](dealings.md) |
| What a player perceives of others: names only when known, health as a band, `appraise` revealing exact health to the appraiser only, an introduction teaching a name; what others perceive of a walking player (`approach.py`: `walk → person`, as an AI's `goto → person`) | [perception.md](perception.md) |
| What a player perceives by facing (the `fov_on` law): the `face` act turning the body, someone behind heard (`heard_sounds`, no id) and not seen, seen when faced, the field's edge and margin, `set_world_law` refused to a player (`fov.py`) | [fov.md](fov.md) |
| Across a drop between ground levels: players above and below see each other, the one above cannot step off it or walk over it, and an arrow flies over it (`drop.py`, plan-test seed) | [drop.md](drop.md) |

Baseline: `verify-<run>` published by `$V launch` and `$V doctor` passing. One identity per run; `join` succeeds once per identity while its character lives. For a second player, use a second run name, or mint another identity with `curl -X POST http://127.0.0.1:3300/v1/identity` (`appraise.py` keeps one as `token2` in the run's state).

Every HTTP call is a connection: `$V player` calls connect and disconnect around each call, so after more than the `takeover_s` law (30 s) without a call the world's minds take the character over, and the next call hands it back before it runs ([verify-client presence](../../verify-client/features/presence.md)).
