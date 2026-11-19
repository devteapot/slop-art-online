# Fast-lane patch evidence

## Installed changes

Counts are per authority-confirmed install, including repeated edits by the same Walker. Each install can touch several classes. Retreat/heal covers changed withdrawal, surrender or healing actions and their guards. Guard/dodge covers changes to defensive actions or their trigger conditions. Target compares selectors. Attack policy covers changes to attack or approach actions and their guards, including removal. Spacing covers changes to movement actions or back-off distance. Other includes edits outside those classes and replies with no detectable change in the action outline. Percentages use the row's install count.

| Arm | Installs | Retreat / heal | Guard / dodge | Target | Attack policy | Spacing | Other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 323 | 245 (76%) | 216 (67%) | 217 (67%) | 156 (48%) | 24 (7%) | 57 (18%) |
| B2 | 394 | 306 (78%) | 289 (73%) | 256 (65%) | 227 (58%) | 52 (13%) | 64 (16%) |
| B100 | 238 | 170 (71%) | 154 (65%) | 150 (63%) | 116 (49%) | 37 (16%) | 41 (17%) |
| C2 | 202 | 158 (78%) | 154 (76%) | 151 (75%) | 135 (67%) | 21 (10%) | 25 (12%) |

### Over the fight

Each install is assigned to the first cumulative thought snapshot containing it. The numbered snapshots group roughly the first, middle and last thirds of the ten-minute fight. The snapshots land partway through the corresponding benchmark cadence, so the groups are approximate.

| Arm | Snapshot group | Installs | Retreat / heal | Guard / dodge | Target | Attack policy | Spacing | Other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 1–3 | 174 | 138 (79%) | 124 (71%) | 132 (76%) | 93 (53%) | 12 (7%) | 21 (12%) |
| B1 | 4–6 | 141 | 100 (71%) | 86 (61%) | 80 (57%) | 61 (43%) | 12 (9%) | 36 (26%) |
| B1 | 7–10 | 8 | 7 (88%) | 6 (75%) | 5 (62%) | 2 (25%) | 0 (0%) | 0 (0%) |
| B2 | 1–3 | 237 | 186 (78%) | 187 (79%) | 172 (73%) | 144 (61%) | 23 (10%) | 29 (12%) |
| B2 | 4–6 | 127 | 96 (76%) | 83 (65%) | 68 (54%) | 67 (53%) | 24 (19%) | 29 (23%) |
| B2 | 7–10 | 30 | 24 (80%) | 19 (63%) | 16 (53%) | 16 (53%) | 5 (17%) | 6 (20%) |
| B100 | 1–3 | 163 | 123 (75%) | 115 (71%) | 123 (75%) | 90 (55%) | 22 (13%) | 23 (14%) |
| B100 | 4–6 | 75 | 47 (63%) | 39 (52%) | 27 (36%) | 26 (35%) | 15 (20%) | 18 (24%) |
| B100 | 7–10 | 0 | — | — | — | — | — | — |
| C2 | 1–3 | 98 | 78 (80%) | 77 (79%) | 74 (76%) | 71 (72%) | 4 (4%) | 11 (11%) |
| C2 | 4–6 | 61 | 43 (70%) | 43 (70%) | 49 (80%) | 37 (61%) | 11 (18%) | 9 (15%) |
| C2 | 7–10 | 43 | 37 (86%) | 34 (79%) | 28 (65%) | 27 (63%) | 6 (14%) | 5 (12%) |

Attack-policy edits fall as a share of installs from the first to the last nonempty group in all four arms. Retreat/heal edits remain frequent among the few late replies. B100 has no late installs. The later windows describe the fighters still generating fast-lane events.

### Direction of the edits

| Arm | Flee or back off | No enclosing retreat condition | Retreat precedes first attack or attack absent | Any attack or close-in | Explicit press | Heal cutoff down/up/same |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 249 (77%) | 112 (35%) | 202 (63%) | 283 (88%) | 12 (4%) | 58/5/198 |
| B2 | 273 (69%) | 127 (32%) | 221 (56%) | 331 (84%) | 22 (6%) | 79/13/187 |
| B100 | 185 (78%) | 60 (25%) | 155 (65%) | 220 (92%) | 23 (10%) | 47/9/123 |
| C2 | 138 (68%) | 52 (26%) | 115 (57%) | 170 (84%) | 7 (3%) | 39/11/97 |

Explicit press is the presence of `close_in` or an offensive action gated on recovery, release, windup or opponent health. It is a narrow indicator. A bare strike or a changed attack selector can still be offensive. Retreat order is measured in graph traversal order. An earlier conditional retreat can fail, allowing the attack to run. Heal cutoffs compare the first visible numeric self-heal guard where both versions have one.

## Persona and observed retreats

| Arm | Walker installs | Patched Walkers incl. refills | Walkers observed retreating | Retreat starts after any install | Return ≤10 s | No observed return | Censored |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 323 | 219 | — | — | — | — | — |
| B2 | 394 | 252 | 174 | 1505 | 798 | 705 | 2 |
| B100 | 238 | 116 | 84 | 681 | 363 | 318 | 0 |
| C2 | 202 | 176 | 106 | 1133 | 451 | 676 | 6 |

The persona field says “(no persona yet)” in B1 457/457, B2 526/526, B100 339/339 and C2 273/273 captured fast prompts. The installed replies and observed retreat events all join to Walker identities, with the forager habit repertoire and the synthetic fight role. The initial battle graph is a fight desire with heal below 50, dodge or block on threat (by ID parity), and strike the nearest person. The fixture supplies no martial, protective or timid persona cohorts. B1 lacks the comparable actor-level retreat sampling used for Nov 19.

The retreat join uses the same actor ID and the latest preceding install time. All 3,319 sampled starts in B2, B100 and C2 followed a patch. A2 and A100 recorded zero. The sampler counts distinct observed `back_off` or `flee` activity starts and can miss short activity or contact transitions. A return is a sampled transition back into strike reach within ten seconds. Two free 40-fighter instrumentation runs installed the scripted defence-and-strike graph on 69 and 77 distinct Walkers including refills, and recorded zero retreats in both. They verify that an installed edit can preserve a fighting graph in the fixture. The free runs differ from the paid fights in size and reply source.

## What the model received

| Arm | Reply group | Installs | Windup trigger | Median trigger damage when hit | Median recent own hit lines | Recent death/remains cue |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | Withdraw only | 172 | 62 (36%) | 8.5 | 2 | 104 (60%) |
| B1 | Attack edit only | 42 | 8 (19%) | 5 | 2 | 34 (81%) |
| B1 | Both | 79 | 18 (23%) | 8 | 2 | 56 (71%) |
| B2 | Withdraw only | 161 | 51 (32%) | 8 | 2 | 115 (71%) |
| B2 | Attack edit only | 62 | 16 (26%) | 9 | 2 | 39 (63%) |
| B2 | Both | 117 | 41 (35%) | 8 | 2 | 78 (67%) |
| B100 | Withdraw only | 116 | 66 (57%) | 8 | 1 | 39 (34%) |
| B100 | Attack edit only | 33 | 10 (30%) | 8 | 2 | 13 (39%) |
| B100 | Both | 69 | 27 (39%) | 7.5 | 1 | 30 (43%) |
| C2 | Withdraw only | 69 | 13 (19%) | 8 | 2 | 58 (84%) |
| C2 | Attack edit only | 34 | 8 (24%) | 9 | 2 | 26 (76%) |
| C2 | Both | 69 | 15 (22%) | 9 | 2 | 60 (87%) |

“Withdraw” means the replacement contains `flee` or `back_off`, or switches to a routine with no detected attack or approach. “Attack edit” means changed offensive action types or guards with an offensive action still present. Edits can belong to both groups. The four neither counts are 30/54/20/30 in arm order. For the narrower explicit-press indicator, the non-withdrawal samples are only 4/6/5/2. Their hit-only medians are 9/3/3/3 damage, compared with 8/8/8/9 among withdrawals without explicit press. This is compatible with avoiding harder hits in three arms, with too few exclusive press replies to separate context from selection.

Of 383 installed replies triggered by windups, 357 say “A stranger winds up a strike at you” and the other 26 name an attack windup, sometimes from “An old stranger.” Hit prompts give one event's damage, and the recent transcript can show earlier hits, missed or defended attempts, nearby strangers and deaths. In B2, for example, recent death/remains mentions occur in 71% of withdraw-only prompts and 63% of attack-edit-only prompts. In B1 and B100 the direction reverses. The hit-only medians overlap and the hit-line medians are one or two on both sides. A windup tells the fighter what was seen at trigger time. It does not establish that it is still in flight when the reply installs.

The user-message order is **Who you are → Your top level → Your routines → Why now → What has just happened (oldest first)**. The body introduction gives age and sex and lists move timings. The fast call does not include a live scene or a numeric own-HP or stamina reading. `health`, `count` and `doing` let an installed graph query execution-time conditions. They are vocabulary, not values supplied to the model. Participant handles in the percept transcript can refer to distant witnesses, attackers, victims or remains. They cannot be counted as current enemies or allies. No recent-history section in the installed joins used the words ally, allies, friend or friends. That text check establishes no current relationship counts.

Walker15 in B2 (actor 325, install 1795073527349) got “A stranger attacked you (8 damage).” Its replacement kept heal below 50, dodged on a visible hostile windup aimed at it, then used `flee` from the attacker as an unconditional fallback. The reply described being “Surrounded by strangers who all want a piece of me.” That is the model's explanation. The graph and next retreat can be observed separately from the claim that it was surrounded.

## Verbatim prompt excerpts

The 1,595 captured requests resolve to identical system text, SHA-256 `f50c888e60b89ace4101e9c44748f64cd59f722c2b81b7f416923cb0b9d56aac`. The journal stores it under `journal/system/3e603a6ffd081a2feb3eb12409abe32b.txt`. The full text is in the analysis archive.

> Something has just happened to you (see Why now). Your body goes on doing what your top level and your routines say while you think; what you answer changes them from the next moment on, not the moment that is passing. You may rewrite your `combat` branch, rewrite one of the routines listed under Your routines, switch your `combat` branch to one of them, or keep everything as it is.

The four response examples appear in this order. The request envelope sets `response_format` to `{"type":"json_object"}`, with the graph and schema in the prompt text.

```text
{"patch": {"label": "combat", "graph": {...}}, "thought": "one sentence, in your words"}
{"routine": {"name": "one of your routines", "graph": {...}}, "thought": "..."}
{"switch": "one of your routines", "thought": "..."}
{"keep": true, "thought": "..."}
```

The combat and body text frame the danger in concrete terms.

> A blow lands only if you are still within reach (about 2 m; a wolf's leap about 3.2) when its windup ends: stepping back or running as it winds up makes it miss, but whoever swings stands still meanwhile. You can outrun a person who keeps stopping to swing, not a wolf (a wolf catches the young, old, tired or surprised).

> Death is permanent.

The graph grammar illustrates `first` priority, `seq`, a conditional with an optional `else`, action nodes and routine calls. Its combat conditions include the following examples in order of appearance.

```text
{"health": {"below": 40}}
{"stamina": {"below": 30}}
{"count": {"of": "wolf" or {"kind": "person", "relation": "friend"}, "within": 8, "at_least": 3}}
{"health_of": {"target": T, "below": 30}}
{"doing": {"who": "person", "is": "hostile", "phase": "winding up", "at_me": true, "within": 5}}
{"threatened": true}
```

The target vocabulary includes `self`, `attacker`, IDs, places and nearest visible people filtered by relation. The skill list includes `attack`, `strike`, `bowshot`, `firebolt`, `throw`, `shoot`, `dodge`, `block`, `jump`, `heal`, `follow`, `keep_distance`, `close_in`, `circle`, `back_off` and `flee`. The stock repertoire example gives a complete exit policy.

```json
{"if": {"sees": {"nearest": {"kind": "person", "relation": "enemy"}}}, "then": {"do": "flee", "target": {"nearest": {"kind": "person", "relation": "enemy"}}}}
```

Among the admitted replies, combat rewrite / routine rewrite / routine switch counts are B1 294/9/20, B2 344/11/39, B100 216/6/16 and C2 177/4/21. Keeping the graph cannot enter the installed denominator. Attack and flight both have short legal forms. The asymmetry lies in the examples, the threat-only reason and the effort required to express a reliable return to the fight. The journals do not offer a counterfactual with the same inputs and balanced examples.

## Reconstruction and sources

- Verified SHA-256 for the Nov 19 full bundle, the Nov 13 bundle and the Nov 18 free bundle before extraction. The derived archive contains the reproducible offline join, per-install and per-retreat CSVs, tables and the logged system text. The original archives supply the raw events and replies.
- Excluded authority thought rows prefixed `kept` or `refused`. Paired all 1,157 installed rows to the cumulative detail and the actor's journal by authority timestamp, reply and admissible reply time. Actor and reply checks disambiguate the reused millisecond timestamps. Nothing was inferred from a model's thought where graph fields were available.
- The authority export contains the admitted reply, not a normalized installed graph snapshot. The category counts compare the prompt's outline with the reply graph or selected repertoire outline. The offline reader handles common aliases and malformed guards but does not reproduce all Rust pruning, defaults, nested routine expansion or priority/sequence semantics. Flags describe observable edits and graph content. They cannot guarantee that every clause executes or fully determine behavior under every input.
- Report and timing conventions follow the [replicate report source](https://github.com/devteapot/slop-art-online/blob/c2da8e030f49a87b73f557e434651368de8486ba/living/tools/flb_report.py), [driver](https://github.com/devteapot/slop-art-online/blob/c2da8e030f49a87b73f557e434651368de8486ba/living/tools/battle_diag.py), [fast-lane evidence notes](https://github.com/devteapot/slop-art-online/blob/c2da8e030f49a87b73f557e434651368de8486ba/docs/FAST_LANE.md), [mind service](https://github.com/devteapot/slop-art-online/blob/c2da8e030f49a87b73f557e434651368de8486ba/living/mind/src/mind/fast.rs) and [authority admission](https://github.com/devteapot/slop-art-online/blob/c2da8e030f49a87b73f557e434651368de8486ba/living/authority/src/mind.rs). The [battle scale](BATTLE_SCALE.md) and [mind harness](MIND_HARNESS.md) documents give fixture and journal context.
