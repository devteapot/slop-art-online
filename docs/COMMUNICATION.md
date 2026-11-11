# Communication: how characters speak, overhear, whisper and call

Status: **design**, 2026-11-11, merged to main. The owner accepted all six [choices](#11-open-choices-for-the-owner) as recommended (2026-11-11). Approved to build, in order: gap items 3–5 (the `introduced` row, the `heard` table and `my_heard` view, ways as script specs with `human_speak`), then 6, 7, 8 and 10 (whisper, call, truthful silence, overheard names). Items 11–13 (muffling walls, mindspeech, signing) stay later. This document builds nothing. It defines the building blocks of communication, shows that the owner's chat cases follow from them, and lists the work to build them, smallest first. What exists today is marked **built**. What is on an unmerged branch is marked **branch**. Proposals are marked **proposed**.

**The request** (the owner, after play-test 3): "I think it's okay that if your cursor is not on someone and you press enter, you go into general chat. If you are hovering someone and press enter, you enter chat with that person specifically. But I think that conversation should still be kind of public, unless you whisper. But to whisper, you should be close, or maybe through some skills that are telepathic or stuff like that. So I think we need to dig deep and define how communication can happen and have all the right building blocks to build such systems."

**Rules this follows** (AGENTS.md):

- Players and minds speak through the same rules.
- A channel is script (a law or a skill spec in Rhai) over general Rust primitives.
- What a character knows comes from what happened to it. Overhearing is perception: the words reach a bystander's senses, become an experience row, and the bystander's mind may integrate them. Nothing copies knowledge silently because two characters stand close.
- Spatial subscriptions are not permission boundaries. The authority decides who hears what. A client or a mind receives only rows written for its own character.
- Current perception, remembered knowledge and developer audit truth stay separate.

Contents: [building blocks](#1-building-blocks) · [ways of speaking](#2-ways-of-speaking) · [as rules](#3-as-rules-script-over-primitives) · [what exists today](#4-what-exists-today) · [how minds take turns](#5-how-minds-take-turns) · [what a speaker knows afterwards](#6-what-a-speaker-knows-afterwards) · [privacy and knowledge](#7-privacy-and-knowledge) · [what the client needs](#8-what-the-client-needs) · [worked examples](#9-worked-examples) · [SpacetimeDB documentation and data paths](#10-spacetimedb-documentation-and-data-paths) · [open choices for the owner](#11-open-choices-for-the-owner) · [gap list](#12-gap-list-smallest-first)

## 1. Building blocks

An act of communication has six parts. Each way of speaking fills them differently.

| Part | What it is | Who decides it |
| --- | --- | --- |
| **Speaker and words** | Who speaks and what is said, up to 400 characters (built). | The player's keyboard or the mind's reply. |
| **Addressee** (`to`) | The one the line is for, or no one (the room). Saying it to someone does not make it private. | The speaker. |
| **Way** | How it is said: aloud, whispered, called out, by mind, signed, written. | The speaker, within what the way requires. |
| **Carry** | Where the words reach: how far, through what, and whether a listener's own senses are good enough. | The way's spec, with each listener's `senses(a)`. |
| **Reception** | What each creature in range gets: the **words** (who spoke, to whom, what), the **gist** only (that someone whispered or signed to someone, without the words), a **sound** (an animal hears "a person's voice"), or nothing. | The speech primitive, per listener, from the way's spec. |
| **Trace** | The rows left behind: the speaker's own `said` row, one row per listener who received anything, the developer chronicle, and introductions (a name learned). | The authority only. |

Three consequences come from this split:

1. **Addressing and privacy are separate.** `to` says who should answer. The way says who can hear. A line to Bram spoken aloud is heard by everyone in earshot as "a stranger said to Bram: …". That is the owner's "still kind of public".
2. **Reception is per listener.** The same line is words to the addressee, words to a bystander 8 m away, a voice to a deer, and nothing to someone 20 m away. Each gets their own experience row in their own terms (labels by the `perceived_of` projection: a name only when known).
3. **Requirements belong to the way, not to the client.** "Too far to whisper" is the authority's refusal, written in the script. The client only shows it early.

## 2. Ways of speaking

Distances below are Cullet's laws, where the owner plays (`hearing_of_people()` 12 m, names known within 24 m, sight 48 m by day; `seeds/worlds/cullet/laws.rhai`). The shipped island script hears at 9 m. All numbers are law values, so they can change without code.

| Way | Status | Who receives the words | Who receives the gist | Range | Requires and costs |
| --- | --- | --- | --- | --- | --- |
| **To the room** (`say`, no `to`) | built | Every person whose own hearing reaches the speaker | Animals hear "a person's voice" (built) | Each listener's hearing: 12 m | 2 s between lines (built). Nothing else. |
| **To one person** (`say`, `to` = X) | built | X hears "… said to you". Every other person in earshot hears "… said to X" | Animals: a voice | 12 m | X must be within earshot, or the speaker gets "No answer from X" (built). |
| **Whisper** (`whisper`, `to` required) | proposed | X only | Onlookers within 6 m who see the speaker: "Ilsa whispers something to Bram." No words | The words go 1.5 m and only to X | X within 1.5 m (refused "too far to whisper: step closer"). Onlookers can see that it happened. |
| **Call out** (`call`) | proposed | Every person whose hearing × 2.5 reaches the speaker | Animals within that range hear "a person shouting" | 30 m | Lines of at most 80 characters; 6 s between calls. Anyone in range hears it, and animals too. |
| **Mindspeech** (`mindspeech`, an example of a skill-granted channel) | proposed, as content | X only | Nobody | 200 m, through walls | The speaker knows the technique `mindspeech` and knows X's name (an acquaintance); 2 energy a line; 10 s between lines. X can answer in kind only if X knows it too. |
| **Signing** (`sign`, a sight channel) | proposed, later | Those who see the signer within sight and know the technique `signing` | Others who see it: "Ilsa signs to Bram." | Sight with a clear line | Both sides know `signing`. Silent: no listener hears anything. |
| **Writing** (tablets and signs) | built | Whoever later reads it with `read` (a sign within 8 m, a tablet one carries) | Onlookers see "Ilsa put up a sign" (built) | Wherever the artifact is, for as long as it lasts | The technique `writing`, 1 wood, 12 s (built). Slow and durable. A tablet can be given; a sign is public. |
| **Signals** (species calls: howl, snort, a baby's cry) | built | Same species: the named call. Others: "a long howl from a wolf" | — | The signal's own range in `species.json` | A species vocabulary; the `signal` skill (0.8 s). |
| **Gestures** (`wave` 12 m, `nod` 6 m, `face` 15 m) | built | The target and onlookers see it | — | In sight | Skills with specs in `skills.rhai`. |

What a listener learns, by reception:

| Reception | Text a listener gets (examples) | Kind of experience row | Words? | Who spoke? | For whom? |
| --- | --- | --- | --- | --- | --- |
| Words, addressed to me | "A stranger said to you: “Hi”" / "Ilsa whispers to you: “…”" | `speech`; a private way its own (`whisper`, `mindspeech`) | yes | as I perceive them | me |
| Words, overheard | "A stranger said to Bram: “Hi”" / "Ilsa calls out: “…”" | `speech` | yes | yes | yes |
| Gist | "Ilsa whispers something to Bram." | the way's own kind: `whispered` (a sign: `signed`) | no | yes | yes |
| Sound | "You hear a person's voice, north." | `signal` | no | no | no |

An onlooker who learns of a whisper learns only that it happened, between whom. That is a fact of the world: you can see two people lean together. Whether onlookers learn even that is an [open choice](#11-open-choices-for-the-owner).

## 3. As rules: script over primitives

Today speech is a Rust function (`perceive::speak`) with a few laws around it (`senses().hearing`, `address_m`). A new way of speaking would mean new Rust. **Proposed:** ways of speaking are declared in the script like skill specs, and one Rust primitive applies them.

### Why a way is not a skill

Skills have an activity, a duration and a target, and starting one cancels the one under way. People talk while they work and walk. A gesture (`wave`, `nod`) is a skill because it is a short act of the body. Speech stays a separate act that never interrupts the body. It is declared with the same idioms (`about`, `reach`, `needs`, a `_check` law), so it reads like the rest of the script.

### The script's side (proposed)

```rhai
// ---- ways of speaking (read once per script revision; the speech primitive applies them) ----
// words:   who receives the words. `hearing`: a share of each listener's own hearing (senses);
//          `within_m`: a fixed distance; `only_to`: the addressee alone.
// noticed: who receives only the gist (that it happened, between whom): within `within_m`,
//          and only those who see the speaker (`seen`); `kind` names their experience rows.
// to:      "optional", "required", or "known" (someone whose name the speaker knows, perceived or not).
// channel: "voice" (sound: listeners are gathered within hearing), "mind" (the addressee only),
//          "sight" (onlookers in sight).
fn say_speech() { #{ about: "Speak aloud. Everyone within earshot hears you, also when you speak to one person.",
    words: #{ hearing: 1.0 }, to: "optional", gap_s: 2.0 } }
fn whisper_speech() { #{ about: "Whisper to someone beside you. Only they hear the words; people nearby who see you may notice that you whispered.",
    words: #{ within_m: 1.5, only_to: true }, noticed: #{ within_m: 6.0, seen: true, kind: "whispered" },
    to: "required", reach: 1.5, private: true, shows: "whisper", gap_s: 2.0 } }
fn call_speech() { #{ about: "Call out over a distance. Everyone within 2.5 times earshot hears you, and so do animals.",
    words: #{ hearing: 2.5 }, animals: "a person shouting", to: "optional", max_chars: 80, gap_s: 6.0 } }
// Content, not shipped: a skill-granted channel.
fn mindspeech_speech() { #{ about: "Speak into the mind of someone you know, up to 200 m away, through walls. Costs effort.",
    channel: "mind", needs: "mindspeech", to: "known", range_m: 200.0, cost: #{ energy: 2.0 }, private: true, gap_s: 10.0 } }
// Optional, per way: refuse a line in the world's words ("" accepts it).
fn whisper_check(a) { if a.target.dist > 1.5 { return "too far to whisper: step closer"; } "" }
```

The texts that listeners get are templates of the way, labelled per listener as `witnessed` already does (`{a}`, `{b}` become each listener's label): `heard_to_you: "{a} whispers to you"`, `heard: "{a} calls out"`, `noticed: "{a} whispers something to {b}."`.

### The Rust side (proposed): one primitive

`perceive::speak(ctx, speaker, text, to, way, now)` generalizes today's function:

1. Reads the way's spec. It is compiled once per script revision and cached, like `laws()`, so a line costs no Rhai unless the way has a `_check` (event cadence: once per line).
2. Checks the `gap_s` (today's "speaking too fast"), `max_chars`, `needs`, `cost`, `to` and the way's `_check`. A refusal returns `Err` to the reducer and is written as a `failed` row for a mind, as other refused acts are.
3. Gathers listeners. For a voice way it uses the chunk-body cache within the way's widest carry: `reach().hearing × words.hearing`, or `within_m`. This is no longer the world's widest hearing. For a mind way it reads only the addressee's body by primary key. For a sight way it uses the onlookers' rule (`perception::in_sight`).
4. Gives each listener one reception (words, gist, sound or nothing) and writes one experience row for it. Words also run the introduction rule (`mentions` of the speaker's own name), and an `introduced` row follows when the name is news (section 6).
5. Writes the speaker's `said` row, the hearers the speaker perceives (section 6), the `audience` row for the minds' turn-taking (section 5), and the chronicle line. The chronicle keeps the way, so the audit truth says it was a whisper.

The shipped `say` way gives exactly today's behaviour: the same rows, salience and texts. That is the regression check for step 5 of the [gap list](#12-gap-list-smallest-first).

### The same path for both controllers (proposed)

| Controller | Today | Proposed |
| --- | --- | --- |
| Player | `human_say(text, to)` | `human_speak(text, to, way)`. `human_say` stays as `way = "say"` until the client moves over. |
| Mind, conversation turn | `mind_say(actor, say, say_to, seen_ms, thought)` | The talk reply JSON gains `"way"`, and `mind_say` takes it. |
| Behaviour graph | `{"say": "...", "to": T}` | `{"say": "...", "to": T, "way": "whisper"}` (normalizer default `say`) |

Minds learn the ways the way they learn skills: each way's `about` goes into the world text ([laws and descriptions](WORLD_RULES.md#every-law-described-and-the-minds-world-text-built-from-them)), and the talk prompt lists the ways the character can use now.

## 4. What exists today

Read from source on main `0d6f2b4` (2026-11-11).

**`perceive::speak`** (`living/authority/src/perceive.rs:274`):

- Trims the text to 400 characters. A character with a `mind_state` row is refused within 2 s of its last line (`SPEAK_GAP_MS`, "speaking too fast"). Since `fix-graph-say-id` a graph's `say` waits out that gap instead of being lost (`too_soon_to_speak`), and a `say` that cannot be spoken (no such person in sight) is told to the body as a refused leaf.
- Writes a chronicle `speech` row (developer audit truth, private).
- Writes the speaker's own `said` row, salience 0.5, for every controller. If the speaker said nearly the same thing within 90 s (Jaccard ≥ 0.6 over the chronicle), it also writes a `repeat` row, salience 0.3.
- Gathers listeners within `widest_hearing` (the `senses` law's `reach().hearing`), and each one hears when the distance ≤ its own `hearing_for`.
  - Animals get a `signal` row: "You hear a person's voice, north." (0.25).
  - People get a `speech` row: "X said to you: …" when `to` is them, "X said to Y: …" when it is someone else, else "X said: …".
- Salience 0.9 when **addressed**: `to` is them; or `to` is 0 and they are the only person within `address_m` (6 m, a law); or the words contain their name. Otherwise 0.45.
- When `to` did not hear, the speaker gets a `silence` row: "No answer from X; they don't seem to be within earshot." (0.35). "Silence is information": that is how a mind comes to worry about someone.
- When the words contain the speaker's own name (`mentions`), every hearer gets an `acquaintance` row (`perception::introduce`). That changes how they label the speaker from then on. No experience row says so.
- Each hearer's `mind_state.heard_ms` and `speaker` are updated (the loneliness clock).
- Speech ignores walls: hearing is distance only. Sight lines block sight, not sound.

**Entry points:**

- `human_say(text, to)` (`lib.rs:621`): any `to` is accepted.
- `mind_say` (`mind.rs:384`): a talk turn keeps the graph and the deliberation clock.
- `mind_install` speaks a deliberation's `say`.
- The graph's `say` node (`brain.rs:460`) speaks at most every 45 s; the mark is set only when the line is spoken.

**`signal`** (`perceive.rs:107`) is a skill (`signal_spec`, op `signal`) over the species vocabulary in `species.json`:

- Every mind in the signal's range gets a percept: the same species gets the named call, other species get its sound.
- A salient call (≥ 0.7) asks kin to deliberate.
- Repeating a call within 45 s is not news.

**Artifacts:**

- `write` (12 s, 1 wood, knowing `writing`) makes a tablet in the pack or a sign on the ground, with the author and the time.
- `read` writes a `read` experience (0.8), weighed as testimony from the author ([hearsay](LIVING_CORE.md#stories-hearsay-and-shared-belief-2026-10-18)).
- A tablet that describes a technique teaches it.

**Gestures:** `wave` (12 m), `nod` (6 m), `face` (15 m) are skills. The client turns a player to face the person tapped (`{"do": "face"}`).

**Conversations in the mind** (`living/mind/src/mind/talk.rs`, [conversations](LIVING_CORE.md#conversations-checkpoint-4-item-6-first-part)):

- A `speech` row that is addressed (`to` is the listener, or salience ≥ 0.8) gives the listener a reply turn: a `talk` model call.
- A line said to no one gives a turn only to a listener who `cares` about the speaker (family, a close label, |affinity| ≥ 40 or trust ≥ 60). That listener must be in no other exchange, at most once a minute, and only one listener takes a remark (`claimed`).
- How many turns someone takes in one exchange (stamina) follows from sociability, mood and fondness. A remark that asks nothing is answered with probability 0.3 + 0.65 × sociability/100.
- An exchange closes with a `settled` outcome, or on "No answer" or 12 turns. It resets after 90 s of quiet.
- `arm-replies` (merged): a line that arrives while the listener's deliberation is running is **parked** and answered when it ends, unless the deliberation already spoke to the speaker.
- A bystander of a line addressed to someone else never gets a turn (`overheard_ok` requires `to == 0`). It hears the line, and its consolidation may keep it.

**Branch `exp-greet`** (`origin/exp-greet`, 3383026, not merged, all off by default):

- Law `speech_audience`: `speak` writes a private `audience` row per line: speaker, `to`, `at_ms` (btree), and `hearers: [{id, d, off}]`. `off` is the angle from the speaker's facing (`common::heading(body)`, with the turn under way applied). Rows are kept 60 s and deleted by an index range on `at_ms`. The mind service subscribes to it as the owner only when a switch needs it.
- `LIVING_GREET=nearest|curious|facing`: a line said to no one by a stranger or barely known person draws one turn from, respectively, the nearest free hearer within 6 m; a hearer drawn in by curiosity; or the hearer the speaker faces (within 6 m and 0.6 rad). Under every mode, an addressed line from a stranger skips the remark draw, and hostility no longer counts as caring.
- `LIVING_PARK=concurrent`: a line heard within 2 s after a deliberation's prompt was built gets its turn alongside the deliberation. The first answer wins, and the other's words to that speaker are not said.

**The game client** (`living/game/src/talk.rs`, merged as `talk-1`):

- Enter opens the box to the person under the cursor if they are in earshot, **else to the nearest person in earshot**. Tab cycles through those in earshot.
- Earshot is computed from the installed script's `senses` law.
- It sends `human_say(text, to)`. An addressee out of earshot shows the `silence` row as a refused note.

**The dev-box** is adding `human_face(dx, dy)`, which writes `body.heading`, and a field-of-view law (`field_of_view()`, off by default) with "heard, not seen" percepts. Neither is on origin yet. This design treats facing as a cue for whom a room line is meant, used by the minds' turn-taking, not as a hearing rule.

**What is missing:**

1. There is no whisper and no call. Every line is heard by everyone in earshot.
2. There is no way of speaking in the script. Hearing is the only law, and a new channel would be Rust.
3. There is no "room" in the client: an empty cursor addresses the nearest person.
4. A speaker cannot know who heard (no `heard_by`).
5. Learning a name writes an `acquaintance` row but no experience: a mind or a player is never told "the stranger is Ansel".
6. Without the branch's switches, a stranger's line to a crowd is answered by nobody (below).
7. A reply to someone beyond one's own voice fails as "No answer", even when the speaker can see them 20 m away.
8. Walls do not muffle speech.
9. Room-line claims (`claimed`) are in one mind service's memory, so two mind services could both answer one line.
10. A name heard from someone else is never learned (being told a third person's name is not built).

## 5. How minds take turns

A line is heard by many minds and answered by few. Turn-taking is a matter of the mind (pacing, temperament, who cares), not of physics, so it stays in the mind service. It reads only what each listener received. The authority decides reception. The mind decides whether to answer.

| Way | Who gets a reply turn | Who hears but takes no turn |
| --- | --- | --- |
| To the room | **One** listener: today a listener who cares; **proposed** also, for a stranger's line, the nearest hearer within 6 m who is free to talk (`LIVING_GREET=nearest`). Lines heard while a deliberation runs are answered alongside it (`LIVING_PARK=concurrent`). | Everyone else in earshot. Their consolidation may keep the line, and a later deliberation may act on it. |
| To one person | The addressee (salience 0.9). A stranger's addressed line skips the remark draw (exp-greet). | Bystanders, as today. They answer only through their own deliberation. |
| Whisper | The addressee. The talk prompt says it was whispered, and the reply defaults to `whisper` while the speaker stays within 1.5 m. | Noticers get a `whispered` row with no words. talk.rs reacts only to `speech` and `whisper` rows, so a noticer never gets a turn and no words ever reach its prompt. |
| Call out | As for room or one-person lines. The talk prompt says the speaker is *d* m away and beyond a normal voice, so the reply should be a call or a walk over. | As above, within 30 m. |
| Mindspeech | The addressee, if it is a mind. It can reply in kind only if it knows the technique; otherwise the prompt says the speaker cannot hear an ordinary reply. | Nobody. |

**Evidence for the room line.** In play-test 2 the newcomer's two "hi"s to no one drew no turn. The [resident inspector](TRIALS.md#resident-inspector) shows why from the session's evidence.

- None of the hearers knew the newcomer, so none "cares". A line to no one from someone the listener does not care about draws a turn only if it is addressed and the listener's remark draw passes ("hi" asks nothing).
- The draw is deterministic (talk.rs `draw()`). Recomputed for each hearer, it refused every one:
  - first "hi": Maud 0.6435 ≥ 0.560, Cuth 0.8472 ≥ 0.625, Mercy 0.8492 ≥ 0.787, Aldith 0.8958 ≥ 0.657;
  - second "hi": its one hearer, Bram, 0.8731 ≥ 0.755.
- So neither line could have drawn a turn even if it had been addressed. Whether it was addressed is not in the evidence: no salience and no positions near the line were recorded.

The earlier reading was that two or more people stood within 6 m, so the line addressed nobody. That was a diagnosis from source that the evidence did not support, and the second "hi" had only one hearer. The greeting trial (`exp-greet`, [the greeting trial](TRIALS.md); fake model with realistic latencies, one 15-minute run per arm, `gf4`) measured how often such greetings are answered:

| Arm | Crowded greetings answered | Latency median / p90 | Addressed lines answered | False replies | Talk turns/min |
| --- | ---: | --- | ---: | ---: | ---: |
| control (shipped) | 0 of 4 | – | 3 of 4 | 2 | 2.6 |
| `nearest` | 4 of 4 | 1.6 / 3.0 s | 4 of 4 | 2 | 4.1 |
| `curious` | 1 of 4 | 1.5 / 1.5 s | 2 of 3 | 0 | 2.0 |
| `facing` | 3 of 4 | 1.7 / 3.0 s | 3 of 4 | 3 | 6.3 |
| `nearest` + `concurrent` | 4 of 4 | 2.3 / 3.6 s | 3 of 4 | 2 | 2.9 |

`gf5` repeated it after `talk-1` was merged: crowded greetings were answered 0 of 3 (control), 3 of 3 (`nearest` + `concurrent`, median 1.7 s) and 2 of 3 (`facing`), with 3, 1 and 7 false replies. `facing` also addresses residents' own lines to whoever they face, which tripled talk turns and gave the most false replies. The fake's words are canned, so this proves the mechanics, not the quality of the answers.

> **Placeholder: paid greeting batches `gr1a` / `gr1b`.** Results to come from the coordinator: per arm, crowded and addressed lines answered, latency, false replies, talk turns and cost per hour, and whether the answers read as interactive. Until then the recommendation for room lines rests on the fake runs above.

**Recommendation** (pending `gr1`): ship `nearest` + `concurrent` as the default for room lines. Keep facing as a tie-break between equally near hearers only, so residents do not answer every line said in their direction. With the client's new room key (section 8), room lines from players become common, so this rule decides how the town feels to a newcomer.

**One answerer across mind services** (gap 9): `claimed` lives in one service's memory. While one service thinks for a world it is exact. If minds are split across services, the claim needs a shared record. Proposed: the first talk reply to a room line names the line's `audience` id, and the authority refuses a second reply that names the same id ("someone already answered").

## 6. What a speaker knows afterwards

A speaker knows what it perceived: its own words (`said`), whether the addressee answered or was out of earshot (`silence`), and who was around that it could see. It does not know who heard behind a wall or out of sight.

**`heard_by`** (agreed with the laptop: the hearers of the speaker's own line). It lists the hearers of the words whom the speaker perceives at that moment: within its sight, with a clear line (`perception::visible`). For a whisper, that is the addressee. For mindspeech, it is the addressee if reached (the skill gives a felt contact), else a `silence` row: "You reach for Mira's mind and find nothing."

Where it is stored decides whether a live world can take it:

- **On the `said` row** (a `heard_by: Vec<u32>` column on `experience`) is the simplest for clients. But `line_seen.line` embeds the `Experience` type, so the column changes an existing column's type in `line_seen`. Automatic migration forbids that ("Modifying existing columns"). It would need a world reset or an incremental migration.
- **Chosen, and agreed with the laptop: a private table `heard`.** Primary key: the speaker's `said` experience id. Then `speaker` (btree), `hearers: Vec<u32>` and `at_ms`. A per-sender view `my_heard` returns my character's rows by a point lookup on `heard.speaker`. A row is deleted when its `said` row leaves the window (the same trim), so a speaker keeps at most its window's own lines. The mind service reads `heard` as the owner. The talk prompt and consolidation can say "Bram and a stranger heard you".

**`introduced` experience row** (agreed in shape). When `introduce` returns true (the name is news), the hearer also gets a row of kind `introduced`, subject the speaker: "The stranger who spoke is called Ansel." (0.6). Then:

- The mind's consolidation anchors the name to `person:<id>` from a lived event, not from a guess.
- The player's client can refresh the label it shows.
- `lived.rs` keeps it for a played character.

Whisper and mindspeech introduce only the one who received the words. Noticers learn no name.

## 7. Privacy and knowledge

**Where words may go.** Only into experience rows of characters who received the words, the speaker's own `said` row, and the developer chronicle. The table lists every path by which a whisper's words could reach a bystander, and how each is closed.

| Path | Today | Under this design |
| --- | --- | --- |
| Bystander's `experience` rows | Every person in earshot gets the words | A noticer gets a `whispered` row with no words. Others get nothing. |
| Player's client (`my_experience` through `line_seen`) | Copies of that player's own rows only | Unchanged. No words exist in a bystander's rows to copy. |
| The mind service's subscriptions | Experience by controller (owner); `audience` on the branch | A whisper's `audience` row marks each listener `words` or `noticed`. talk.rs gives turns only on `words`. No other subscription carries text. The chronicle is not subscribed by the mind service (checked: no `chronicle()` read in `living/mind/src`). |
| Talk prompts | Built from the listener's own rows and its pair's working memory | Unchanged: the pair's lines are only those the listener received. |
| Deliberation scene (`scene_json`) | Lists no speech | Unchanged. A deliberation's recent experiences are the character's own. |
| Recall, consolidation, sleep (Neo4j, per `actor`) | Per character | Unchanged. A noticer may remember "Ilsa whispered to Bram", which is what it saw. |
| Player memory (`lived.rs`) | The played character's rows only | Unchanged. |
| `mind_state.heard_ms` | Updated for every hearer | Updated only for those who received the words. |
| `said_recently` (echo check) | Reads the chronicle for the speaker's own lines | Unchanged (the speaker's own words). |
| Developer audit (`chronicle`, owner-only observer) | Keeps every line | Keeps every line with its way. That is audit truth, read only with the owner's token. |

**Event tables and visibility filters are not a boundary here.** Event tables were considered for transient speech and rejected (section 10): views cannot read them, and the pinned SDK's row-level security is unimplemented. A public row would reach every subscriber who asked for it.

**Names.** A name is learned only from something that happened to the learner:

- the person said their own name in words the learner received (built);
- or, an [open choice](#11-open-choices-for-the-owner), the learner heard words addressed to someone it perceived that contain that person's name.

Standing near someone never teaches a name. Noticing a whisper never does.

**Overheard speech** is testimony from the speaker, like any speech, so hearsay fades faster until corroborated ([hearsay](LIVING_CORE.md#stories-hearsay-and-shared-belief-2026-10-18)). A line about the overhearer itself counts as lived.

**Mindspeech:**

- The receiver learns the words, that they came by mind, and from whom: a voice it knows, or "a voice" if it does not know the speaker.
- The speaker learns only reached or not reached, never where the receiver is.
- `to` must be someone whose name the speaker knows (`knows_name`). An unknown id is refused with the same words as an absent one, so ids cannot be probed.

**What a player's client receives:** what its character perceived, through `my_experience` (and `my_heard`). It does not receive other players' lines unless its character received them, and it never receives the words of a whisper to someone else.

## 8. What the client needs

**Agreed with the laptop coordinator** (owner of the game client), 2026-11-11, in its thread. The laptop also checked this against dev-box's facing work.

The owner's interface:

| Input | Line sent | The box reads |
| --- | --- | --- |
| Enter, no one under the cursor | `human_speak(text, 0, "say")`: the room | "Say to everyone nearby" |
| Enter with someone under the cursor, or a tap on a person while the weapon is sheathed (`ui-1`) | `human_speak(text, X, "say")`: to X, heard by everyone in earshot | "Say to Bram (others nearby hear)" |
| ↑/↓ in the open box, or a click on a chip | Picks the way. The box shows the ways from `speech_card` as chips ("Say · Whisper · Call"), and Enter sends in the shown way. | "Whisper to Bram"; a way that cannot be used now is greyed with its reason, e.g. "too far to whisper (step closer)" |
| `/w` typed at the start | A typed alias for the whisper way | — |
| Tab | Cycles the people in earshot, plus one stop for "everyone" | — |

**Agreed points:**

1. **One reducer.** `human_speak(text: String, to: u32, way: String)`, with `to = 0` meaning the room. `human_say(text, to)` stays as `human_speak(…, "say")` until the client moves over. `mind_say` gains `way`, so players and minds share one path.
2. **The ways are listed in a public `speech_card` table**, like `skill_card` and `act_card`, derived from the script at install. The client then needs no script evaluation to build the box. Fields:
   - `name`, `label`, `order` (chip order);
   - `needs_to`;
   - `reach_m`: the addressee must be within it (whisper 1.5);
   - `carry_m`: how far the words go now, for a "heard by about N" hint;
   - `requires`: the technique the way needs, or empty, so the box can grey out a way the character lacks using its `my_know_how` rows;
   - `needs_sight`: the addressee must be in sight (false for whisper and mindspeech; true for signing).

   The client's greying is a hint. The authority decides.
3. **No fixed key per way.** Ctrl+Enter is awkward on the owner's MacBook, and Shift is run. Ways come from data, so they are chips cycled with ↑/↓.
4. **Refusals** come back as the reducer's `Err` string and are shown as the refused note: "too far to whisper: step closer", "a whisper needs someone to whisper to", "speaking too fast", "you don't know mindspeech". An addressee out of earshot keeps the `silence` row.
5. **Rows the client draws, all from `my_experience`:**
   - `whisper` (to me, with the words) in whisper style;
   - `whispered` (noticed, without the words) as "…" over the two;
   - `introduced`, which gives the moment for "The stranger is Ansel" (the label itself follows the projection anyway).
6. **"Heard by"** comes from the private `heard` table through the per-sender `my_heard` view ("agree 7b"; the migration reason is in section 6). The client joins `my_heard.line` to the `my_experience` row's id. A line without a `heard` row shows nothing, not "heard by nobody". So the authority writes the `heard` row **in the same transaction** as the speaker's `said` row: both happen inside `speak`.
7. **Until `heard` lands**, after a room line nobody took up within about 10 s, the client says so honestly from the people it perceived in earshot.
8. **Facing.** dev-box's design changes sight through the field-of-view law in `senses(a)`, not hearing. Hearing stays a radius, and creatures heard but not seen appear as "heard, not seen" markers. This document uses facing only as a mind-side cue for whom a room line was meant.

The laptop builds the client side once `speech_card` and `human_speak` are on a branch. Its `ui-1` already builds the box's modes from a small table.

## 9. Worked examples

**The play-test 3 "Hi" to Bram** (Cullet, hearing 12 m). Bram Calloway stands 4 m away with two others within 10 m. The player hovers Bram and presses Enter: `human_speak("Hi", Bram, "say")`.

- Bram receives "A stranger said to you: “Hi”" (0.9) and gets a reply turn. The talk prompt says the speaker is a stranger, and the remark draw is skipped for a stranger's addressed line.
- The two others receive "A stranger said to Bram: “Hi”" (0.45) and take no turn.
- A deer 10 m off hears a person's voice.
- The player's `said` row has `heard_by` = Bram and the two, all in sight.
- When Bram answers "Morning. You're new on the Row?", the player sees it as said to them. The others hear that too.

With the cursor on nobody, the same "Hi" goes to the room. Under the recommended `nearest` rule, the nearest free hearer within 6 m answers, and the rest hear it.

**A whisper in a crowd.** On the market square, Ilsa stands 1 m from Bram among eight people. She whispers "The tally is short." to Bram.

- The check passes (1 m ≤ 1.5 m).
- Bram receives "Ilsa whispers to you: “The tally is short.”" (kind `whisper`, 0.9) and gets a reply turn that defaults to whispering.
- Three people within 6 m who see Ilsa receive "Ilsa whispers something to Bram." (`whispered`, 0.3), or "a stranger whispers something to Bram" for those who do not know her. No words, and no turn.
- The other five receive nothing.
- Ilsa's `heard_by` is Bram.
- The chronicle (audit) keeps the words with way `whisper`.
- A noticer's mind may come to suspect something between them. That is its own inference from what it saw.
- Had Ilsa been 3 m away, the line would have been refused, "too far to whisper: step closer", and nothing written for anyone.

**A call across the square.** Tobiah, 25 m from Marit, calls "Marit! The cart's here!" (`call`).

- Everyone within 30 m receives the words, Marit as addressed (named, and `to`).
- Animals within 30 m hear a person shouting.
- Marit's reply turn is told Tobiah is 25 m away, beyond a normal voice. Her mind may call back or walk over.
- If she answers with `say`, the reply does not reach him. Today's text "No answer from Tobiah; they don't seem to be within earshot" would mislead, because she sees him. Gap 8 makes it "Tobiah is too far to hear you; call out or go closer."

**A telepathic message** (content on a floor whose script adds `mindspeech`). Neve knows `mindspeech` and knows Bram's name. From 120 m away, through the dry-dock walls, she sends "Don't sign the ship over."

- The check passes: she knows the technique, the target is known, he is within 200 m, and she has the energy.
- Bram receives "Neve's voice speaks in your mind: “…”" (kind `mindspeech`, 0.9).
- Nobody else receives anything.
- Neve's `heard_by` is Bram.
- Bram does not know `mindspeech`, so his reply turn says he cannot answer in kind. He may go and find her.
- If Bram were dead, Neve would get "You reach for Bram's mind and find nothing": information, as silence is today.

## 10. SpacetimeDB documentation and data paths

**Versions.** The workspace pins `spacetimedb = "=2.14.1"` and `spacetimedb-sdk = "=2.14.1"` (`living/Cargo.toml`, `Cargo.lock`). The trials container on this machine runs `clockworklabs/spacetime:v2.14.1` (port 3320). The other container here (`sao-living_spacetimedb_1`, port 3300) runs v2.10.1 and is not a target for this work. The live docs' version selector reads 2.0.0. Claims the design depends on were checked against the 2.14.1 crate source in the cargo registry.

**Consulted 2026-11-11:**

| Page | What it says | What follows here |
| --- | --- | --- |
| [Tables](https://spacetimedb.com/docs/tables/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions/) | "Tables are private by default"; "Views can read from private tables and expose only the data appropriate for each client". | Words stay in private `experience` rows. `heard` is private. Clients read only `my_*` views. `speech_card` is public: static data derived from the script, the same for everyone, like `skill_card`. |
| [Performance](https://spacetimedb.com/docs/tables/performance/) | "Make tables public only when clients need to access them"; split tables by access pattern; "Be mindful of unbounded table growth"; prefer indexed lookups. | `heard` is its own table (read by speaker), not columns on the hot `experience` row. `audience` rows expire after 60 s by an index range. Gathering uses the chunk cache. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | B-trees serve equality and ranges; multi-column indexes serve their prefix; indexes "slow down inserts and updates". | One btree on `heard.speaker` (the view's point lookup). `audience.at_ms` for expiry (branch). No index added to `experience`. |
| [Views](https://spacetimedb.com/docs/functions/views/) | Per-sender views compute per subscriber; access only "through indexed lookups"; re-evaluated when the read set changes. | `my_heard` reads `heard.speaker` = my character, a point lookup. It re-runs only when my own lines are heard, never on others' speech. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | Group subscriptions by lifetime. | The client adds `my_heard` to its per-connection view set. The mind service (owner) subscribes `heard` and `audience` once. |
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) | Rows exist "only for the duration of the transaction"; "Event tables cannot currently be accessed within view functions"; clients get `on_insert` only; RLS "applies … with the same semantics as regular tables". | **Not used.** A per-character scope would need a view (not allowed) or RLS. In the 2.14.1 crate, `client_visibility_filter` is behind `unstable` and marked "RLS filters are currently unimplemented, and are not enforced" (`spacetimedb-2.14.1/src/lib.rs`). A public event table would send whispers to anyone subscribed. Speech must also leave durable rows for learning and reconnect recovery (AGENTS.md: transient notifications do not replace them). |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations) | New tables are allowed; new columns only "to the end of a table with a default value" (the macro's `#[default(…)]`); "Modifying existing columns" is forbidden; changed reducers give old clients runtime errors. | `heard` (a new table) migrates in place. A column on `experience` would change `line_seen.line`'s type, so it is not chosen. `human_speak` is a new reducer, so `human_say` keeps working for old clients. |

The RLS page (`/docs/rls`) returned an empty body, so the "unimplemented" status rests on the 2.14.1 source, not on the docs.

**Data paths per line** (proposed; *N* = persons receiving the words, *K* = noticers, *A* = animals in range, *P* = players among the receivers):

| Way or path | Reads | Writes | Index | Recipients | Retained |
| --- | --- | --- | --- | --- | --- |
| say / to one | Speaker body, `mind_state`; chunk-body cache within `hearing` (12 m); each listener's `senses` (memoized per state); chronicle 90 s by `at_ms` (echo) | chronicle 1; `said` 1 (+`repeat`); experience *N* + *A*; `line_seen` *P*; `heard` 1; `audience` 1; `acquaintance` + `introduced` on a self-introduction | PKs, `chronicle.at_ms`, `heard.speaker`, `audience.at_ms` | Each receiver's own `my_experience` at its next frame; the speaker's `my_heard`; the mind service (owner) | Experience ≤ 400 per character (as today); `heard` follows `said`; `audience` 60 s |
| whisper | Speaker and addressee bodies; cache within 6 m; sight lines to *K* candidates | as say with *N* = 1, plus *K* `whispered` rows | as above | addressee, noticers, speaker | as above |
| call | cache within 30 m | as say; *N* grows with the area (6.25× a say's) | as above | as above | as above; bounded by the 6 s gap |
| `speech_card` | The script's way specs | One row per way, rewritten at script install | PK `name` | Every client (public, a few rows) | Replaced at install |
| mindspeech | Addressee body by PK, the speaker's acquaintances by `acquaintance.by_pair`, know-how | chronicle, `said`, 1 experience, `heard`, a vitals settle (energy) | PKs, `by_pair` | addressee, speaker | as above |

**Rates and growth.** Speech is event-driven, not per tick. Measured conversation rates were 0.86 lines a minute per speaker (`talklab-new3`) and 2.9 talk turns a minute for ten minds. A say line in a crowd of 20 writes about 25 rows. A call on a 30 m square in Cullet reaches everyone there; with 40 people that is about 45 rows, and the 6 s gap bounds one caller to 10 calls a minute. Reads are local: the chunk cache, primary keys and one btree. No line reads all players or the whole World, and no view re-runs for someone who did not receive the line. Experience retention is unchanged (the ~400-row window, trimmed every 32nd insert). `heard` adds one row per own line within that window. `audience` holds about a minute of lines: at 2,000 characters speaking once a minute, about 2,000 rows. A call widens only its own gather radius; the world's `widest_hearing` stays the say reach.

**Not measured.** The design has no benchmarks. The 216-character gate should include a talking crowd (scripted room lines and calls at a declared rate) when the primitive is built. The per-sender `my_heard` view is new load per player, one re-run per own line.

## 11. Open choices for the owner

Only choices that change how the game plays.

**The owner's answers (2026-11-11): all six accepted as recommended.** In the owner's words: "Go with the as recommended settings, and we can iterate from there. This will not be the final game anyway, so it's just to see how properly defined environments play out." Choice 3 stands unless the paid greeting batches (`gr1a`/`gr1b`) contradict it. Detailed design and tuning choices below this level are decided by the lab, recorded here, and reported.

| # | Answer |
| --- | --- |
| 1 | Whisper 1.5 m; onlookers within 6 m who see it learn that it happened and between whom, not the words. |
| 2 | Calling out costs no energy; it is public to everyone within 30 m and to animals, lines are short (80 characters), 6 s apart. |
| 3 | A line to the room is answered by the nearest free hearer within 6 m; lines heard during a deliberation are answered alongside it. |
| 4 | Names are learned from someone saying their own name, or from hearing a person addressed by name when you can see who it was for; never from closeness or from noticing a whisper. |
| 5 | Walls muffle speech: yes, later, as a law. |
| 6 | Mindspeech and signing are ordinary taught techniques, for a later world, not Cullet's first version. |

1. **Whisper range, and whether onlookers see a whisper happen.** Recommended: 1.5 m. Onlookers within 6 m who see the speaker learn "X whispers something to Y", without the words. Seeing people lean together is real, and it gives whispers social weight. The alternative is a silent whisper that nobody notices.
2. **Whether calling out costs anything.** Recommended: no energy. Its costs are loudness (everyone within 30 m hears it, and so do animals, which can startle deer or draw wolves), lines of at most 80 characters, and 6 s between calls. A shout is cheap but public.
3. **Who answers a line to the room.** Recommended (pending `gr1a`/`gr1b`): the nearest hearer within 6 m who is free to talk, with lines heard during a deliberation answered alongside it (`nearest` + `concurrent`), and facing only as a tie-break. A room line gets one answer, so a crowd does not reply in chorus. Alternatives: only those who care (today: strangers are ignored), or curiosity (by chance).
4. **How names are learned.** Recommended: from self-introduction (built), and from words addressed to someone you perceive that contain that person's name ("Bram, the cart's here" teaches "Bram" to those who hear it in full and see whom it was for). Never from closeness, and never from noticing a whisper. The stricter choice is self-introduction only: then a newcomer must ask each person's name.
5. **Whether walls muffle speech.** Recommended: yes, later, as a law (a wall or shut door between halves the carry, a whisper does not pass). This makes talking through a door and eavesdropping at one real. Today sound ignores walls.
6. **Skill-granted channels.** Recommended: mindspeech and signing are techniques like any other. They are taught or read from a tablet, never discovered by `experiment`, and belong to a floor whose seed adds them, not to Cullet's first version. The receiver answers in kind only if it knows the technique too.

## 12. Gap list, smallest first

Each item is a law, a skill spec or a primitive, with the verification surface it touches ([verify](../.agents/skills/verify/SKILL.md)). Items that change a surface's shape run `maintain-verification-skill` on that skill in the same change.

| # | What | Kind | Surfaces |
| --- | --- | --- | --- |
| 1 | Client: an empty cursor speaks to the room (`to` = 0); Tab gains an "everyone" stop; the box labels the room and "others nearby hear". | Client only | Game client (owner play-test; no UI skill yet); `verify-player` unchanged |
| 2 | Merge `exp-greet` and make the `gr1` winner the default: law `speech_audience` on, `LIVING_GREET` and `LIVING_PARK` defaults. | Law and mind switches | `verify-minds` (greet, alongside), `verify-core` (scene audience), `verify-client` (audience private) |
| 3 | `introduced` experience row when a name is news. | Primitive (one row in `speak`) | `verify-core` (speech scene), `verify-knowledge` (names), `verify-minds` (consolidation anchors the name) |
| 4 | `heard` table and `my_heard` view (hearers the speaker perceives). | Primitive and view | `verify-client` (scoped to the caller, refused to others), `verify-player`, `verify-minds` |
| 5 | Ways of speaking: `<way>_speech()` specs, `<way>_check`, `speak(…, way)`, `human_speak`, `mind_say` and graph `say` with a way, the public `speech_card` table (fields in section 8), ways in the world text. Shipped `say` identical to today. Then the laptop builds the chips. | Primitive and script | `verify-core`, `verify-player`, `verify-client`, `verify-minds`, `verify-llm` (reply JSON) |
| 6 | Whisper: the `whisper` way, `whispered` rows, the reply in kind in talk.rs, refusal "too far to whisper". Privacy checks: a bystander's experience rows, talk and deliberation prompts in the journal, Neo4j memories and `my_experience` hold none of the words. | Script and mind | `verify-minds` (whisper case), `verify-knowledge` (bystander's graph), `verify-player` (refusal), `verify-client` (another identity's views) |
| 7 | Call: the `call` way, animals hear shouting, the talk prompt gives distance and ways. | Script | `verify-core`, `verify-minds` |
| 8 | Silence that tells the truth: "too far to hear you; call out or go closer" when the addressee is perceived but beyond the way's carry. | Primitive | `verify-core`, `verify-player` |
| 9 | One answerer across mind services: a reply names its line's `audience` id, and the authority refuses a second. | Primitive and mind | `verify-minds` |
| 10 | Overheard names (if choice 4 is taken). | Primitive | `verify-knowledge`, `verify-core` |
| 11 | Walls muffle speech (if choice 5 is taken): a sight-line test on the cached map per listener, as a law. | Law | `verify-core`; the scale gate with a talking crowd |
| 12 | Mindspeech as content: technique, `mindspeech_speech`, `to: "known"` resolved by acquaintance. | Script content | `verify-core`, `verify-knowledge`, `verify-player` |
| 13 | Signing: the sight channel (`channel: "sight"`). | Primitive and script | `verify-core`, `verify-knowledge` |

A talking-crowd workload (room lines and calls at a declared rate) joins the 216-character gate when item 5 lands. Correctness on scratch worlds does not establish the cost at scale.
