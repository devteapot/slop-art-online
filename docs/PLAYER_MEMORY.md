# Player memory: what a human-played character lives becomes its memory

Status (2026-11-09): design and prototype, off by default (`LIVING_PLAYER_MEMORY=1`). Free tier verified on scratch worlds with the fake model server in direct and batch mode; one small real run compares three models in both modes ([results](#measured-2026-11-09)). The open policy questions are [at the end](#questions-for-the-user).

## The problem

People play characters with `ai = false`. The authority gives them the same experiences as everyone (the `experience` rows, controlled by the player's identity), but the mind service subscribes only to the experiences of the characters it controls, so nothing a played character lives reaches its memory graph. Its Neo4j mind stays empty and its `relation`, `judgment` and `place` rows stay unset.

## What it is for

The design is for three uses, in this order:

1. **The character can pass to AI control with its past.** A player leaves and the character lives on, or a played character is used in a trial. Its mind then needs what it lived: who it met, what it was told, where it was hurt. Without it, a mind taking over a character with a day of history starts from nothing. This is the main reason, and the one the design is measured against: the character's own recall for a situation (see [retrieval](#retrieval)).
2. **Projections stay true.** The `relation`, `judgment` and `place` rows of a played character are derived from what it lived, as for an AI character. They are what a body under a mind acts on and what the observer shows.
3. **Others recall and talk about the character consistently.** This is a consequence, not a mechanism. Each mind is private, so a resident remembers the player from the resident's own experience of them, which already works today. Internalizing the player's life does not put anything into the resident's prompt, and must not. Putting it there would be silent knowledge copying (AGENTS.md). Consistency comes from both minds recording the same events, each as it perceived them: the player's "I asked Walker1 where to find food" and Walker1's "a newcomer named Wren asked me about food" cite different experience rows of one exchange. The free tier checks that a resident's talk prompt contains its own memory of the player and none of the player's private memories.

Whether an offline character keeps living under AI is the user's decision ([questions](#questions-for-the-user)). This design only makes it possible.

## What is internalized

Only the character's experience rows: what the authority already decided reached it.

- **Its own acts and their outcomes:** accepted and failed deliberate acts (gather, give, wave, nod…) as the `act` feedback the authority writes for every controller ("You did what you had decided: gather → tree (+1 wood)", "… did not work out: … no nearest tree in sight").
- **Its own speech.** *Authority change 1:* a human-controlled speaker now perceives its own words (`said`, salience 0.5, `perceive::speak`). An AI's words are already in the reasoning episode that chose them, so AI characters receive no such row and are unaffected.
- **Heard speech**, as testimony (`speech`: `attribute` marks beliefs from it as told by the speaker, so hearsay fades faster).
- **Combat:** being attacked, misses, dodges, blocks and fight reports. The authority tells an attacker about its own landed blows only through fight reports, for every controller alike; that is left unchanged.
- **Gestures** answered or refused, gifts, trades, births and deaths around it: whatever the authority sends.
- **Where:** each experience line carries the position recorded in its row and the settlement it was in or near (`@[584, 192] outside Brackenford`, from the public `settlement` table), so the model can name places. Walking with nothing happening leaves no trace. That is the same rule as for everyone (novelty at the source), but it means a player's route is only known through events along it.

Never internalized:

- the player's input (key presses, `human_move`, commands as typed, UI choices, chat outside the game);
- reasons or intent: the prompt says the person's choices are made by someone the memory cannot see, and asks for acts and words without motives, feelings or plans they did not express;
- developer audit truth: other characters' minds, `deliberation`, hidden stats, transient views (`my_combat`), anything the character did not perceive;
- identity: no persona is inferred ([projections](#projections)).

### Provenance

Every concept, memory and belief a player integration writes carries `lived_under` with `"human"` (a list: an edge later re-asserted by a mind keeps the mark, and a mind's own integrations leave it as it was). Concepts that are created only as an edge's endpoint have no mark of their own; the edge carries it. The `self` node holds `lived_upto` (how far the character is internalized), `lived_t` and `lived_under`. The reasoning episode is a `thought` of kind `internalize` with reference `internalize-<id>-<ms>`, whose detail records `lived_under`, the cadence reason, the mode (direct or batch), the experience ids, the reply and the patch. The exact request and reply are in the journal (`.local/living/journal/<run>/<name>.jsonl`, `purpose: internalize`, `mode: batch` with the job id for batch answers). An experiment can select memories lived under a human with `WHERE 'human' IN n.lived_under`.

### Privacy

- The memory graph is the character's, in Neo4j, which only the mind service reads (the same scope as an AI character's mind). Nothing in it goes to another character's prompt.
- The internalize prompt contains only that character's own rows and mind. One request never mixes two characters ([batching](#how-it-is-batchable)).
- What an admin sees: the graph (Neo4j), the journal and the `thought` rows, like any mind. The projections (`relation`, `judgment`, `place`, `belief`) are public tables today for every character, so an observer, or another player's client, can read a played character's beliefs. That exposure exists for AI characters already; the perception work owns making these private (read through the mind service's identity). Until then the switch stays off on worlds with real players.
- The player does not see their character's internalized memory in the game client yet. Whether they should, and whether they can opt out, is a [question](#questions-for-the-user).

## How it is batchable

Implemented in [lived.rs](../living/mind/src/mind/lived.rs):

- **Off the real-time path.** Nothing a player does waits on it. The service copies each experience into a per-character buffer as it arrives: the authority deletes a dead character's rows, and its window keeps the last 400. Integrations run in the background lane, behind conversations and deliberations, and share the slow-work semaphore with consolidation.
- **A slow cadence:** a character is integrated when any of these holds:
  - 40 meaningful experiences (salience ≥ 0.2) are waiting (`LIVING_PLAYER_MEMORY_BUFFER`), or 200 in all (`_CAP`, kept below the authority's window);
  - one game day (12 real minutes) has passed since the oldest one arrived (`_EVERY_S` overrides);
  - the session has ended, taken as 180 s without a new experience (`_IDLE_S`), because the authority has no presence signal (an authority `client_disconnected` would be the exact signal; see questions);
  - the character has died, at once.

  Up to 120 experiences go in one integration (`_TAKE`).
- **A cheap model**, chosen by measurement (`LIVING_PLAYER_MEMORY_MODEL`, a profile name; default the models file's default).
- **The provider's batch API** (`LIVING_PLAYER_MEMORY_MODE=batch`): every character due at the same check goes into one Mistral batch job with inline requests (`POST /v1/batch/jobs` with `requests`, `endpoint: /v1/chat/completions`, polled, output read from `/v1/files/{id}/content`). The batch price is half. The docs give no completion window, so the job is polled every 15 s and cancelled after an hour (`_POLL_S`, `_BATCH_WAIT_S`). A restart during a job loses only the job: the cursor has not moved, so the experiences go into the next one; nothing is integrated twice.
- **A stable prompt prefix.** The system prompt (`prompts::internalize_system`) holds nothing about any one character. Every player's request starts with the same system text and the same first user line, then the character section, then what changes. Provider-side caching applies to that prefix: the free tier checks that the system text is byte-identical across requests, and the real run records the cached tokens reported.
- **Several characters per request** was considered and not built. It would save only the shared prefix, which caching already prices at 20% of the input price for GLM and 2% for DeepSeek (Ministral 3 14B lists no cached price). It would also put two private lives in one prompt and invite one character's events into the other's memory. Batch jobs give the per-request saving (half price) without mixing. The measured prefix share, 81% of input, is [below](#several-characters-per-request).
- **Restart-safe.** `lived_upto` is on the character's `self` node, so a restarted service resumes after it (free tier: the next integration takes only later ids). Re-applying a patch is idempotent anyway: memories are keyed by experience id and edges merge. The player's experience rows are never consumed (no `mind_consolidated`), because the player's client reads them.

## Projections

Relations, judgments, places and the belief summary are derived from the character's own graph exactly as for an AI character (`Minds::project`), from what passed between it and others. *Authority change 2:* `mind_update` accepts the world's mind service (the admin identity) as well as the controller, for a human-controlled character, and refuses an identity (`persona`) from it ("a human-controlled character's identity is not projected").

Persona is not inferred. A narrative, values, goals and traits read off a person's play is a sensitive inference about the human, not only the character, and it would be wrong in a specific way: it would explain choices by motives nobody perceived. Options, for the user to choose:

1. Never infer it. A mind that takes the character over starts from its lived memory and a neutral "a newcomer who …" description it writes from that memory at handover, marked as inferred.
2. Infer it at handover only, from the graph, labeled `inferred_from: lived` and versioned like any identity change, and only if the player agreed.
3. Let the player author it (a character sheet at join or later), which then is the persona, like an authored resident's.

Recommended: 3, with 1 as the fallback. The prototype implements none of them: the internalize prompt asks for no identity, and the authority refuses one.

## Retrieval

What recall returns afterwards, measured on the free tier's graphs. The replies there are fake, so the wording is the fixture's. The paid run's graphs are in its `report.md`, but recall was not replayed on them before cleanup removed the scratch Neo4j.

| Recall | Cues | Returns | ≈ tokens |
| --- | --- | --- | --- |
| player about the resident | `person:<resident>`, "food market" | its own memory "I asked a resident where to find food." and the beliefs about the resident | 64 |
| player about wolves | `kind:wolf`, "wolf" | "A wolf attacked me out in the wilds and I struck back." and `kind:wolf -ATTACKED-> self` | 54 |
| resident about the player | `person:<player>`, "wren" | its own memory "A newcomer named Wren greeted me and asked where to find food." | 85 |
| resident about wolves | `kind:wolf`, "wolf" | nothing of the player's fight | 31 |

Relevance: every recalled line concerned its cue, and the resident's recall and talk prompt contained none of the player's private memories. Recall budgets are the existing ones (8 beliefs for a talk turn, 32 for an integration), so player memory adds nothing to other characters' prompts, and at most the existing budget to a mind taking the character over.

## Measured (2026-11-09)

Paid run `knowledge-pmem-real-132616`: island world, one scripted session (78 s, 2.6 game hours; 11 lived experiences: a failed and a successful gather, two lines said, two heard from a resident thinking with GLM Flash, a wave, four wolf bites). The same 11 rows were then internalized by each candidate, each in its own memory namespace, with a fresh mind (nothing to recall). It is one session per cell (n = 1), so read the differences as indications, not a ranking. Prices are from docs.mistral.ai/models/<model> (2026-11-09), with batch at half price per mistral.ai/pricing. The batch rate is assumed from the docs; actual billing was not checked. The run used `living/configs/models.json` as it stood at 13:26, with no `reasoning_effort` and no `prompt_cache_key` on these profiles. A later change by the model-cost work (staged, not yet committed) sets GLM Flash's `internalize` effort to `high` and turns on cache keys for GLM and DeepSeek. GLM's output tokens and cost below therefore predate that change.

### Fidelity against the rows

Ten facts from the rows: berries gathered, the tree gather failed, asked about food, the resident's directions (berry patch past the split rock, fish at the stream mouth), the resident "ranging east, hail me", the wave, the wolf attack, being hurt, where (outside Brackenford, east), and the resident's correct id. A fact counts when the graph (memories and beliefs, what recall returns) holds it, not only the thought's summary. Errors were read by hand from every memory and belief.

| Model | Mode | Facts | Memories / beliefs | Errors |
| --- | --- | --- | --- | --- |
| ministral-14b | direct | 7/10 | 2 / 12 | `KNOWS know:berry_patch` (a technique anchor misused) |
| ministral-14b | batch | 6/10 | 2 / 9 | the resident's "ranging east today" became "walked east today" |
| GLM 5.3 Flash | direct | 8/10 | 3 / 10 | `FEARS place:east_woods`: an inner state and woods nobody mentioned |
| GLM 5.3 Flash | batch | 5/10 | 0 / 7 | **anchored the resident as `person:29`**, an experience id that is a real islander's character id; most beliefs cite no experience |
| DeepSeek 4.1 Flash | direct | 6/10 | 2 / 7 | summary says it gathered wood (it said so, but the act failed); memory "I need to get away or defend myself" (an intent) |
| DeepSeek 4.1 Flash | batch | 7/10 | 2 / 9 | none found |

Common to all: no candidate kept the failed gather, most dropped the wave (both are low-salience acts), and every memory and belief carried `lived_under = ["human"]`. Heard speech was kept as what the resident claimed (`CLAIMED`), as the prompt asks. The GLM batch slip led to a guard: an integration may anchor only people its experiences involve or name, or whom the character already has feelings about. Anything else is dropped and noted in the thought (`perceived_people_only`, proved in the free tier with a planted `person:1`). The same slip is possible in AI consolidation, which has no such guard.

### Tokens, latency and cost

| Model | Mode | Prompt / cached / completion tokens | Latency | Cost of the session |
| --- | --- | --- | --- | --- |
| ministral-14b | direct | 3,005 / 0 / 1,309 | 21.7 s | $0.00086 |
| ministral-14b | batch | 3,005 / 2,276 / 1,315 | 31.6 s (job) | $0.00043 |
| GLM 5.3 Flash | direct | 2,810 / 0 / 2,343 | 15.4 s | $0.00159 |
| GLM 5.3 Flash | batch | 2,810 / 0 / 2,800 | 47.2 s (job) | $0.00091 |
| DeepSeek 4.1 Flash | direct | 2,845 / 0 / 710 | 3.2 s | $0.00171 |
| DeepSeek 4.1 Flash | batch | 2,845 / 2,176 / 865 | 31.5 s (job) | $0.00063 |

- **Batch API:** available for all three models served by Mistral, GLM and DeepSeek included. Jobs of one request finished in 24–47 s (the docs promise no window). The output line shape is `{id, custom_id, response: {status_code, body: <chat completion>}, error}`.
- **Prefix caching:** the shared system prompt is 81% of the input (about 2,300 tokens); experience lines cost about 40 tokens each. The batch calls' cached tokens came from the identical direct request sent seconds earlier, so they show that caching works through batch jobs, not what a stream of different players would get. Ministral 3 14B lists no cached price and is charged at full input price.
- **Per game hour, this session:** 1,360–2,150 tokens per game hour (3,555–5,610 tokens over 2.6 game hours). That figure is one integration of a short session, where the fixed prefix dominates.
- **Continuous play (estimate, not measured):** one real hour is 120 game hours. A call at the buffer of 40 experiences carries about 2,300 (prefix) + 1,600 (lines) + about 700 (recalled mind) ≈ 4,600 input tokens. The cadence gives about 5 calls an hour for quiet play (a game day each) and about 13 for play as dense as this session (8.5 meaningful experiences a minute). The table assumes output per call as measured.

| Model | Tokens per call | Tokens per real hour (quiet–dense) | Tokens per game hour | Cost per hour, direct | Cost per hour, batch |
| --- | --- | --- | --- | --- | --- |
| ministral-14b | ≈ 5,900 | 30k–77k | 250–640 | $0.006–0.015 | $0.003–0.008 |
| GLM 5.3 Flash | ≈ 7,100 | 36k–92k | 300–770 | $0.010–0.025 | $0.005–0.013 |
| DeepSeek 4.1 Flash | ≈ 5,400 | 27k–70k | 225–585 | $0.012–0.030 | $0.006–0.015 (about 30% less with the prefix cached) |

Total spent on both paid runs, including the resident's talk and consolidation calls: about $0.017. That includes the first attempt (`knowledge-pmem-real-132240`), whose driver stopped the candidates early, leaving three batch jobs unread.

### Choosing a model

The run favors neither GLM model. GLM batch made the worst error, and GLM's output is two to three times longer than the others'. DeepSeek Flash in batch mode had no errors found; ministral-14b in batch mode is the cheapest. Before choosing, replicate: at least five sessions per cell, including a session with two players and a longer quiet one. The prototype's default model stays the models file's default until then.

### Several characters per request

Several characters per request would save part of the 81% prefix, which matters most for ministral (no cached price). It would also put two private lives in one prompt. Not built. If wanted, it is the next experiment, measured for cross-character contamination.

## Verification

- Free tier: `.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-<name> [--mode direct|batch]` (`verify-knowledge`, [feature](../.agents/skills/verify-knowledge/features/player-memory.md)): switch off (no player graph, residents' conversations as before), switch on (the session internalized with provenance and projections, no persona, a stranger anchor dropped, rows kept), restart (resumes from `lived_upto`), recall (no leak; tokens), death (the authority deletes the rows; the buffer still integrates the last words).
- Paid tier: `player_memory_real.py --allow-live --run knowledge-pmem-real-<name>`, after the user authorizes the run.
- The scripted session is [player_session.py](../.agents/skills/verify-knowledge/scripts/player_session.py): join, walk, gather, talk to a minded resident (admin `spawn_crowd`, `place_at`, `set_behavior` set the scene), wave, fight a bold wolf (admin `place_at`), read back from the rows.

## Questions for the user

1. **Does a character keep living when its player is offline?** Under AI control (with this memory), asleep or absent (removed from the world until they return), or vulnerable but inert? This decides whether the handover use is real.
2. **Persona from behavior:** option 1, 2 or 3 above?
3. **Should the player see and own the memory?** A "what Wren remembers" view in the game client, the ability to delete it, and whether a player can opt out of internalization.
4. **Session end:** an exact presence signal needs an authority change (`client_connected`/`client_disconnected` per player identity). Wanted, or is idle detection enough?
5. **Projections' visibility:** keep the switch off on worlds with real players until the perception work makes `relation`, `judgment`, `place` and `belief` private?
6. **Own speech for AI characters too?** Players now perceive what they said; AI characters do not (their words are in their reasoning episodes). Symmetry would add one experience per utterance to every AI inbox and change what minds consolidate.
