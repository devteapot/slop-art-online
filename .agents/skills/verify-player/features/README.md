# Player verification map

| Feature | File |
| --- | --- |
| Player character: join, move, act (a command runs once, `command.py`), walk far by click-to-move, speak, refusals | [player-character.md](player-character.md) |
| Combat skills: use, refusals, strike, killing a person, bow, fire bolt, block, dodge, heal, wolves, death and rejoin | [combat.md](combat.md) |
| Gestures: wave, nod and face through `human_act`, answered by residents; refusals | [gestures.md](gestures.md) |
| Waking residents: a player's speech, wave, gift, offer and lesson wake the resident they are aimed at into a mind; an overhearing resident keeps the line in its ring; nobody else wakes; `woken` and `prior` private | [waking.md](waking.md) |
| Hospitality: a resident takes the player in (`host`), `lodging`, the stay's end, no theft from the host's store during it; the player's own `host` refused without a house; `guest` private | [hosting.md](hosting.md) |
| Verbs from the game client: F on a thing or person, C on oneself, words for writing, the pack and know-how panels, refusals shown with the rules' reason, a skill the world adds appearing with no client change | [verbs.md](verbs.md) |
| Dealings: the player proposes terms through the verbs' node, reads the record in `my_records`, is told it was accepted, what it owes and that it is kept; a demand on the player told, and unpaid when it falls due; `record` and `record_party` private | [dealings.md](dealings.md) |
| What a player perceives of others: names only when known, health as a band, `appraise` revealing exact health to the appraiser only, an introduction teaching a name | [perception.md](perception.md) |

Baseline: `verify-<run>` published by `$V launch` and `$V doctor` passing. One identity per run; `join` succeeds once per identity while its character lives. For a second player, use a second run name, or mint another identity with `curl -X POST http://127.0.0.1:3300/v1/identity` (`appraise.py` keeps one as `token2` in the run's state).

Every HTTP call is a connection: `$V player` calls connect and disconnect around each call, so after more than the `takeover_s` law (30 s) without a call the world's minds take the character over, and the next call hands it back before it runs ([verify-client presence](../../verify-client/features/presence.md)).
