# Heed for AI characters (`heed_on`)

Built for AI characters and minds, off by default until the owner's play-test (docs/ATTENTION_BUDGET.md,
"Built"; the experiments in docs/ATTENTION_E4.md and docs/ATTENTION_E5.md stay on `heed-e4`). A mind's
own policy (`mind_heed`, the `heed_policy` table) is driven by verify-minds' `heed` case.

**What it is.** With the law `heed_on` (off as shipped; an ordinary law, since the mind service reads it), a character the authority runs
(no person plays it) perceives as individuals only those it heeds: at most its capacity
(`heed_capacity(a)` clamped by `heed_ceiling`), filled by its own policy if its mind wrote one, else its species' heed instinct
(`living/seeds/heed.json`, the shared selector `living_rules::heed`), plus whoever it acts on and
whoever made contact with it within `heed_contact_s`. Everyone else it sees is a throng: counted,
never named. Players are unchanged. `authority/src/heed.rs` keeps the set in module memory.

| Reader | Under heed |
| --- | --- |
| graph `sees`, `nearest`/`id` targets, `attacker`, `speaker`, `named` (`seen_by_id`, `first_seen`) | individuals only |
| graph `count`, the crowd alert | individuals and throng (a throng's numbers are perceived) |
| graph `doing`, `threatened`, the `threatened` desire signal | individuals only (a windup from the throng is not seen coming) |
| cues | matched against everyone in sight; a throng match is `cued` and takes the event pass |
| first sights, `familiar` rows | individuals only |
| a mind's scene (`perceive::scene_json`) | the individuals in full (no 14-nearest cap), `throngs` lines (count, direction, rough area, heading, activity, kinds), earshot read by sight with throng hearers anonymous, `_stage.throng_players` for the mind service's level of detail (stripped from every prompt) |
| witness, fold and speech lines (`perceive::witnessed*`, `fold::flush`, `speech::speak`) | a throng member is "someone in the throng to the …", subject/object 0; a fight, shot or death whose parties are both no one in particular to the onlooker gives it no line (the combat feed's rule) |
| a player's combat feed (`combat::show`) | an onlooker's row only when its individual set holds the actor or the target (always, while heed does not apply to players) |
| `mind_reach`, the fast lane's move count | a throng member is not perceived as them |

**Scene:** `scenes.py heed` (any seed, about 3.5 min), beside its control in the same run: off,
O sees S by id and counts 8; on with O's capacity 2, S is throng (not by id) and O still counts 8;
the scene lists at most 2 creatures, the rest as `throngs` with no throng member's id; with O's
capacity 0, S's first strike lands unforeseen and its contact makes the second seen and blocked
(the module log, law `heed_trace`, says so; no `heed invariant` line); W's heard line names no one in its
throng; W at capacity 0 gets no fight line for a blow between two of its throng, and with a policy of
its own heeding S (`mind_heed`) its line names S and tells O as someone in the throng. Off-identity with the base: `det_compare.py run --scripts BASE,CAND` on a
Cullet battle of 200 and on `prepare --arena pack`.
