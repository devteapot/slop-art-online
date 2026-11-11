# Player memory: what a human-played character lives becomes its memory

Status (2026-11-09, second change, uncommitted): on by default (`LIVING_PLAYER_MEMORY=0` turns it off), because an offline player's character now keeps living under the world's minds and takes its past from this memory ([Presence and the offline character](#presence-and-the-offline-character)). The user's decisions of 2026-11-09 are recorded in [Decisions](#decisions-2026-11-09); the first prototype's free and paid runs are [below](#measured-2026-11-09).

## The problem

People play characters with `ai = false`. The authority gives them the same experiences as everyone (the `experience` rows, controlled by the player's identity), but the mind service subscribes only to the experiences of the characters it controls, so nothing a played character lives reaches its memory graph. Its Neo4j mind stays empty and its `relation`, `judgment` and `place` rows stay unset.

## What it is for

The design is for three uses, in this order:

1. **The character can pass to AI control with its past.** A player leaves and the character lives on, or a played character is used in a trial. Its mind then needs what it lived: who it met, what it was told, where it was hurt. Without it, a mind taking over a character with a day of history starts from nothing. This is the main reason, and the one the design is measured against: the character's own recall for a situation (see [retrieval](#retrieval)).
2. **Projections stay true.** The `relation`, `judgment` and `place` rows of a played character are derived from what it lived, as for an AI character. They are what a body under a mind acts on and what the observer shows.
3. **Others recall and talk about the character consistently.** This is a consequence, not a mechanism. Each mind is private, so a resident remembers the player from the resident's own experience of them, which already works today. Internalizing the player's life does not put anything into the resident's prompt, and must not. Putting it there would be silent knowledge copying (AGENTS.md). Consistency comes from both minds recording the same events, each as it perceived them: the player's "I asked Walker1 where to find food" and Walker1's "a newcomer named Wren asked me about food" cite different experience rows of one exchange. The free tier checks that a resident's talk prompt contains its own memory of the player and none of the player's private memories.

An offline character keeps living under AI (the user's decision, 2026-11-09): [Presence and the offline character](#presence-and-the-offline-character).

## What is internalized

Only the character's experience rows: what the authority already decided reached it.

- **Its own acts and their outcomes:** accepted and failed deliberate acts (gather, give, wave, nod…) as the `act` feedback the authority writes for every controller ("You did what you had decided: gather → tree (+1 wood)", "… did not work out: … no nearest tree in sight").
- **Its own speech.** *Authority change 1:* a speaker perceives its own words (`said`, salience 0.5, `speech::speak`, formerly `perceive::speak`). Since the second change this holds for AI speakers too (the user's decision): every speaker has a `said` row, so a character's history reads the same whoever spoke for it, and a mind's consolidation sees its own words beside what it heard.
- **Heard speech**, as testimony (`speech`: `attribute` marks beliefs from it as told by the speaker, so hearsay fades faster).
- **Combat:** being attacked, misses, dodges, blocks and fight reports. The authority tells an attacker about its own landed blows only through fight reports, for every controller alike; that is left unchanged.
- **Gestures** answered or refused, gifts, trades, births and deaths around it: whatever the authority sends.
- **Where:** each experience line carries the position recorded in its row and the settlement it was in or near (`@[584, 192] outside Brackenford`, from the public `settlement` table), so the model can name places. Walking with nothing happening leaves no trace. That is the same rule as for everyone (novelty at the source), but it means a player's route is only known through events along it.

Never internalized:

- the player's input (key presses, `human_move`, commands as typed, UI choices, chat outside the game);
- reasons or intent: the prompt says the person's choices are made by someone the memory cannot see, and asks for acts and words without motives, feelings or plans they did not express;
- developer audit truth: other characters' minds, `deliberation`, hidden stats, transient views (`my_combat`), anything the character did not perceive;
- the player's private life: the identity is read from the character's conduct only ([projections](#projections)).

### Provenance

Every concept, memory and belief a player integration writes carries `lived_under` with `"human"`, and every one an AI consolidation writes carries `"ai"` (second change): `lived_under` is a list, so a concept or edge both lived under the person and re-asserted under the minds carries both, and a character's history shows both kinds. Which experiences a path integrates follows the experience row's `controller`: rows written while the person controlled the character are internalized as lived by them (`lived.rs`), rows written while the minds controlled it are consolidated as the mind's (`mind.rs`), so nothing is integrated twice. Concepts that are created only as an edge's endpoint have no mark of their own; the edge carries it. The `self` node holds `lived_upto` (how far the character is internalized), `lived_t` and `lived_under`. The reasoning episode is a `thought` of kind `internalize` with reference `internalize-<id>-<ms>`, whose detail records `lived_under`, the cadence reason, the mode (direct or batch), the experience ids, the reply and the patch. The exact request and reply are in the journal (`.local/living/journal/<run>/<name>.jsonl`, `purpose: internalize`, `mode: batch` with the job id for batch answers). An experiment can select memories lived under a human with `WHERE 'human' IN n.lived_under`.

### Privacy

- The memory graph is the character's, in Neo4j, which only the mind service reads (the same scope as an AI character's mind). Nothing in it goes to another character's prompt.
- The internalize prompt contains only that character's own rows and mind. One request never mixes two characters ([batching](#how-it-is-batchable)).
- What an admin sees: the graph (Neo4j), the journal and the `thought` rows, like any mind. The projections (`relation`, `judgment`, `place`, `belief`) and the persona were public when this was first written; the perception work made them private in every build (read by the database owner: the mind service and the lab observer), so the switch is on with real players.
- **Players do not see, delete or opt out of their character's memory** (the user's decision, 2026-11-09). The memory is the character's, like any mind's: nothing is built for a player to view it, edit it or switch it off. What the player sees of what the character lived is its experience window (`my_experience`), as before.
- The projections (`relation`, `judgment`, `place`, `belief`) and the persona are private tables since the perception work, read by the database owner only.

## How it is batchable

Implemented in [lived.rs](../living/mind/src/mind/lived.rs):

- **Off the real-time path.** Nothing a player does waits on it. The service copies each experience into a per-character buffer as it arrives: the authority deletes a dead character's rows, and its window keeps the last 400. Integrations run in the background lane, behind conversations and deliberations, and share the slow-work semaphore with consolidation.
- **A slow cadence:** a character is integrated when any of these holds:
  - 40 meaningful experiences (salience ≥ 0.2) are waiting (`LIVING_PLAYER_MEMORY_BUFFER`), or 200 in all (`_CAP`, kept below the authority's window);
  - one game day (12 real minutes) has passed since the oldest one arrived (`_EVERY_S` overrides);
  - the session has ended: its person left and the world's minds took the character over (the authority's presence signal, `presence.ai`; [below](#presence-and-the-offline-character)). Idle detection (`_IDLE_S`) is gone;
  - the character has died, at once.

  Up to 120 experiences go in one integration (`_TAKE`).
- **A cheap model**, chosen by measurement (`LIVING_PLAYER_MEMORY_MODEL`, a profile name; default the models file's default).
- **The provider's batch API** (`LIVING_PLAYER_MEMORY_MODE=batch`): every character due at the same check goes into one Mistral batch job with inline requests (`POST /v1/batch/jobs` with `requests`, `endpoint: /v1/chat/completions`, polled, output read from `/v1/files/{id}/content`). The batch price is half. The docs give no completion window, so the job is polled every 15 s and cancelled after an hour (`_POLL_S`, `_BATCH_WAIT_S`). A restart during a job loses only the job: the cursor has not moved, so the experiences go into the next one; nothing is integrated twice.
- **A stable prompt prefix.** The system prompt (`prompts::internalize_system`) holds nothing about any one character. Every player's request starts with the same system text and the same first user line, then the character section, then what changes. Provider-side caching applies to that prefix: the free tier checks that the system text is byte-identical across requests, and the real run records the cached tokens reported.
- **Several characters per request** was considered and not built. It would save only the shared prefix, which caching already prices at 20% of the input price for GLM and 2% for DeepSeek (Ministral 3 14B lists no cached price). It would also put two private lives in one prompt and invite one character's events into the other's memory. Batch jobs give the per-request saving (half price) without mixing. The measured prefix share, 81% of input, is [below](#several-characters-per-request).
- **Restart-safe.** `lived_upto` is on the character's `self` node, so a restarted service resumes after it (free tier: the next integration takes only later ids). Re-applying a patch is idempotent anyway: memories are keyed by experience id and edges merge. The player's experience rows are never consumed (no `mind_consolidated`), because the player's client reads them.

## Projections

Relations, judgments, places and the belief summary are derived from the character's own graph exactly as for an AI character (`Minds::project`), from what passed between it and others. *Authority change 2:* `mind_update` accepts the world's mind service (the admin identity) as well as the controller, for a character a person plays (controlled by its person now, or with a `presence` row), identity included since the second change.

**The persona is inferred from behaviour** (the user's decision, 2026-11-09, to iterate on if it does not work). The internalize prompt asks for an `identity` (a first-person narrative, values, traits 0-100, mood) read only from what the character did and said as perceived, revised from the current one, and null when nothing new shows. Goals are intentions nobody perceived, so the current goals stay. A real change (`persona_changed`) becomes a new identity version in the graph (`set_identity`) and the `persona` row through `mind_update`, as for an AI character. A mind that takes the character over starts from that persona.

The first prototype did not infer a persona, for these reasons, kept for the record: A narrative, values, goals and traits read off a person's play is a sensitive inference about the human, not only the character, and it would be wrong in a specific way: it would explain choices by motives nobody perceived. Options, for the user to choose:

1. Never infer it. A mind that takes the character over starts from its lived memory and a neutral "a newcomer who …" description it writes from that memory at handover, marked as inferred.
2. Infer it at handover only, from the graph, labeled `inferred_from: lived` and versioned like any identity change, and only if the player agreed.
3. Let the player author it (a character sheet at join or later), which then is the persona, like an authored resident's.

The first prototype recommended 3 with 1 as the fallback. The user chose inference from behaviour.

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

- Free tier: `.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-<name> [--mode direct|batch]` (`verify-knowledge`, [feature](../.agents/skills/verify-knowledge/features/player-memory.md)): switch off (`LIVING_PLAYER_MEMORY=0`: no player graph, residents' conversations as before), switch on (the session internalized with provenance and projections, the identity inferred, a stranger anchor dropped, ids given as strings kept, rows kept), takeover (the session ends when the minds take the character over; its first deliberation comes after the internalization; what the minds live is consolidated with `lived_under ai`), restart (resumes from `lived_upto`), recall (no leak; tokens), death (the authority deletes the rows; the buffer still integrates the last words). The run raises the `takeover_s` law to an hour (an installed copy of skills.rhai) so its HTTP-driven player is not taken over between calls, and lowers it to 5 s where a session should end.
- Presence and the takeover are also proven by `verify-client` (presence counts, takeover, handback over real WebSocket connections) and `verify-minds` (`takeover`: the minds think for the character, the handback stops their plan and keeps their graph, a reply in flight is refused).
- Paid tier: `player_memory_real.py --allow-live --run knowledge-pmem-real-<name>`, after the user authorizes the run.
- The scripted session is [player_session.py](../.agents/skills/verify-knowledge/scripts/player_session.py): join, walk, gather, talk to a minded resident (admin `spawn_crowd`, `place_at`, `set_behavior` set the scene), wave, fight a bold wolf (admin `place_at`), read back from the rows.

## Presence and the offline character

Second change, 2026-11-09 ([presence.rs](../living/authority/src/presence.rs)).

### SpacetimeDB documentation consulted

[Lifecycle reducers](https://spacetimedb.com/docs/functions/reducers/lifecycle/) and the [reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context/) (the docs' selector reads 2.0.0; claims checked in the pinned `spacetimedb-2.14.1` crate and the `v2.14.1` server source): `client_connected` runs for each distinct connection, WebSocket or HTTP call, with that connection's `ConnectionId`; an error in it disconnects the client; `client_disconnected` runs when a connection ends (close, timeout, error) and the client "is still recorded as disconnected" if it fails; at startup the host runs `client_disconnected` for every connection still in `st_client` ("Disconnect dangling clients", `host_controller.rs`), so a crash of the client or of the server leaves no connection open. Details and what was not verified are in [perception](PERCEPTION.md#spacetimedb-documentation-consulted-2026-11-09).

### Presence

- **Connections.** Each open connection is a private `connection` row (its `ConnectionId`, identity, since when), inserted by `client_connected` and deleted by `client_disconnected`. Several connections of one identity (two tabs, a game client and a tool) count exactly; a repeated event changes nothing; a reconnect is a new connection.
- **Presence.** Each living character a person plays has a private `presence` row from its join (or from its person's next connection, for a character that joined before presence existed): `player`, `connections` (open now), `present` (at least one), `changed_ms`, `ai` (the world's minds control it), `control_ms`, `takeover_ms` (when the minds take over if no connection opens; indexed), and the minds' held behaviour (`ai_graph`, `ai_plan`).
- **Who reads it.** The mind service, as the database owner (`SELECT * FROM presence`). **No client reads it, and there is no public presence bit.** Reasons: human and AI characters share the same authority and physical rules, and nothing in the world tells a resident from a player, so another client (another player) should not learn it either; a public bit would publish when a real person is online, a tracking signal about the person rather than the character; it would let players single out the characters people play, for good or ill, which is a perception leak the views were built to close. If a game wants a friends list or a "who is online" feature, that is an account-level feature for the people who chose it, not world perception.

### Takeover

When the last connection of the person closes, `presence.present` turns false and a takeover is set `takeover_s` later (a law, default 30 s). An HTTP call is a connection of its own (connected and disconnected around the call), and a page reload or a short network drop is not leaving, so control does not flap. Once a second, the authority takes over the due rows (an index range on `takeover_ms`):

- the character's `controller` becomes the world's mind service (the admin identity) with `ai = true`, also in a seed with `rules.minds = false` (the island's, where residents live on graphs alone): a person's character lives on under a mind. With no mind service running it lives on its behaviour graph, with a deliberation pending;
- its person's perceived set is cleared (they see nothing while away);
- if its minds installed a behaviour before, that graph is installed again; otherwise it keeps its last one until it deliberates;
- a deliberation is requested ("A quiet moment to take stock of how things are going.").

From then on it is an AI character like any other: its percepts are written to the mind service's inbox, it deliberates, talks and consolidates, under level of detail when that is on (`LIVING_LOD`; off stage when no player is near). Two things differ, both because it is someone's character:

- **Its experience rows stay.** `mind_consolidated` moves the mind's cursor but deletes no row of a character with a `presence` row, so the person sees what happened while they were away through `my_experience` (the window keeps the last 400 rows).
- **It thinks with its own past.** In the mind service, the takeover ends the session: what the person lived is internalized ("session end"), and the character's first deliberation waits until that integration is done (at most `LIVING_TAKEOVER_WAIT_S`, default 120 s). Its persona is the one inferred from the person's conduct. A conversation turn does not wait.

Everything the minds consolidate for it carries `lived_under = ["ai"]`.

### Handback

When a connection of its person opens, `client_connected` hands the character back at once, before the client subscribes:

- the minds' behaviour graph stays the character's: it is kept on the presence row (`ai_graph`, `ai_plan`) and installed again at the next takeover, but not run for the person;
- the minds' plan stops: the pending deliberation, the acts they decided and not yet done (`act_queue`), and the activity under way are dropped; the character waits for its person (`{"wait": 30}`, "waiting for you");
- `controller` is the person's identity and `ai` false again, so `my_characters`, `my_experience` and the player reducers find it; a deliberation the mind service is still working on is refused when it arrives ("not your character");
- its perceived set is worked out at once.

The person then reads what the character lived meanwhile in its experience window (rows controlled by the mind service, under the same observer).

**Death.** A character that dies under the minds is its person's again (`controller` and `ai` restored in the same transaction), so their death screen finds it in `my_characters`; its presence row goes.

**Not covered.** A module republish with players connected: if the host keeps connections open across an update without running the lifecycle reducers, a connected player has no `connection` row until they reconnect (their character keeps a presence row only from its next connection). Not observed either way.

## Decisions (2026-11-09)

1. **An offline player's character keeps living under AI**, with its past from this memory, under level of detail; control returns at once when the person returns, the minds' plan stops, and what happened meanwhile is in the character's experiences. Everything lived under AI is marked `lived_under ["ai"]`. The behaviour graph the minds installed stays the character's and is not run for the person. Player memory is on wherever this is (the default).
2. **The persona is inferred from behaviour** by internalization (narrative, values, traits, mood). To iterate on if it does not work.
3. **Players do not see, delete or opt out of their character's memory.** Nothing is built for it.
4. **Session end is the exact presence signal** (`client_connected` / `client_disconnected`), not idle detection.
5. **AI speakers perceive their own words** as a `said` experience, as human speakers do.
6. **Projections' visibility:** `relation`, `judgment`, `place`, `belief` and `persona` are private (the perception work), so the switch is on with real players.

## Questions answered

The first prototype's questions, as the user answered them on 2026-11-09:


1. **Does a character keep living when its player is offline?** Yes, under AI control with this memory (decision 1).
2. **Persona from behavior:** inferred from behaviour (decision 2).
3. **Should the player see and own the memory?** No view, no deletion, no opt-out (decision 3).
4. **Session end:** the exact presence signal (decision 4).
5. **Projections' visibility:** they are private now (decision 6).
6. **Own speech for AI characters too?** Yes (decision 5): one more experience per utterance in every AI inbox.
