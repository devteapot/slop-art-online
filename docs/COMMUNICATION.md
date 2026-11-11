# Communication: how characters speak, overhear, whisper and call

Status: **design**, 2026-11-11, merged to main. The owner accepted all six [choices](#11-open-choices-for-the-owner) as recommended (2026-11-11). Approved to build, in order: gap items 3–5 (the `introduced` row, the `heard` table and `my_heard` view, ways as script specs with `human_speak`), then 6, 7, 8 and 10 (whisper, call, truthful silence, overheard names). Items 11–13 (muffling walls, mindspeech, signing) stay later. Items 3–5 are **built** on branch `speech-1` (section 13); items 6, 7, 8 and 10 on `speech-2` (section 14). Sections 1–12 are the design as agreed; where the build decided a detail, section 13 says so. The document defines the building blocks of communication, shows that the owner's chat cases follow from them, and lists the work to build them, smallest first. What exists today is marked **built**. What is on an unmerged branch is marked **branch**. Proposals are marked **proposed**.

**The request** (the owner, after play-test 3): "I think it's okay that if your cursor is not on someone and you press enter, you go into general chat. If you are hovering someone and press enter, you enter chat with that person specifically. But I think that conversation should still be kind of public, unless you whisper. But to whisper, you should be close, or maybe through some skills that are telepathic or stuff like that. So I think we need to dig deep and define how communication can happen and have all the right building blocks to build such systems."

**Rules this follows** (AGENTS.md):

- Players and minds speak through the same rules.
- A channel is script (a law or a skill spec in Rhai) over general Rust primitives.
- What a character knows comes from what happened to it. Overhearing is perception: the words reach a bystander's senses, become an experience row, and the bystander's mind may integrate them. Nothing copies knowledge silently because two characters stand close.
- Spatial subscriptions are not permission boundaries. The authority decides who hears what. A client or a mind receives only rows written for its own character.
- Current perception, remembered knowledge and developer audit truth stay separate.

Contents: [building blocks](#1-building-blocks) · [ways of speaking](#2-ways-of-speaking) · [as rules](#3-as-rules-script-over-primitives) · [what exists today](#4-what-exists-today) · [how minds take turns](#5-how-minds-take-turns) · [what a speaker knows afterwards](#6-what-a-speaker-knows-afterwards) · [privacy and knowledge](#7-privacy-and-knowledge) · [what the client needs](#8-what-the-client-needs) · [worked examples](#9-worked-examples) · [SpacetimeDB documentation and data paths](#10-spacetimedb-documentation-and-data-paths) · [open choices for the owner](#11-open-choices-for-the-owner) · [gap list](#12-gap-list-smallest-first) · [built: items 3–5](#13-built-items-35-branch-speech-1) · [built: items 6, 7, 8, 10](#14-built-items-6-7-8-and-10-branch-speech-2)

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
| 3 | **Built** (`speech-1`, section 13). `introduced` experience row when a name is news. | Primitive (one row in `speak`) | `verify-core` (speech scene), `verify-knowledge` (names), `verify-minds` (consolidation anchors the name) |
| 4 | **Built** (`speech-1`, section 13). `heard` table (built as `line_heard`) and `my_heard` view (hearers the speaker perceives). | Primitive and view | `verify-client` (scoped to the caller, refused to others), `verify-player`, `verify-minds` |
| 5 | **Built** (`speech-1`, section 13). Ways of speaking: `<way>_speech()` specs, `<way>_check`, `speak(…, way)`, `human_speak`, `mind_say` and graph `say` with a way, the public `speech_card` table (fields in section 8), ways in the world text. Shipped `say` identical to today. Then the laptop builds the chips. | Primitive and script | `verify-core`, `verify-player`, `verify-client`, `verify-minds`, `verify-llm` (reply JSON) |
| 6 | **Built** (`speech-2`, section 14). Whisper: the `whisper` way, `whispered` rows, the reply in kind in talk.rs, refusal "too far to whisper". Privacy checks: a bystander's experience rows, talk and deliberation prompts in the journal, Neo4j memories and `my_experience` hold none of the words. | Script and mind | `verify-minds` (whisper case), `verify-knowledge` (bystander's graph), `verify-player` (refusal), `verify-client` (another identity's views) |
| 7 | **Built** (`speech-2`, section 14). Call: the `call` way, animals hear shouting, the talk prompt gives distance and ways. | Script | `verify-core`, `verify-minds` |
| 8 | **Built** (`speech-2`, section 14). Silence that tells the truth: "too far to hear you; call out or go closer" when the addressee is perceived but beyond the way's carry. | Primitive | `verify-core`, `verify-player` |
| 9 | One answerer across mind services: a reply names its line's `audience` id, and the authority refuses a second. | Primitive and mind | `verify-minds` |
| 10 | **Built** (`speech-2`, section 14). Overheard names (if choice 4 is taken). | Primitive | `verify-knowledge`, `verify-core` |
| 11 | Walls muffle speech (if choice 5 is taken): a sight-line test on the cached map per listener, as a law. | Law | `verify-core`; the scale gate with a talking crowd |
| 12 | Mindspeech as content: technique, `mindspeech_speech`, `to: "known"` resolved by acquaintance. | Script content | `verify-core`, `verify-knowledge`, `verify-player` |
| 13 | Signing: the sight channel (`channel: "sight"`). | Primitive and script | `verify-core`, `verify-knowledge` |

A talking-crowd workload (room lines and calls at a declared rate) joins the 216-character gate when item 5 lands. Correctness on scratch worlds does not establish the cost at scale.

## 13. Built: items 3–5 (branch `speech-1`)

Built 2026-11-11 on `speech-1` from `a107fdf`. Source: `living/authority/src/speech.rs` (the primitive, `speech_card`, `my_heard`), `living/rules/src/script/speech.rs` (`WaySpec`) and the ways section of `living/scripts/skills.rhai`. Verified by `verify-core` `speech.py` ([speech.md](../.agents/skills/verify-core/features/speech.md)), `verify-player` `speak.py`, `verify-client` `drive.py`, `verify-minds` `speech` and `privacy.py`, and `verify-knowledge` `names.py`.

### What was built

**Ways as script (item 5).**

- `<way>_speech()` maps are read once per script revision (`Scripts::ways`, in `order`, then source order). An install refuses any of these, naming it:
  - an unknown key;
  - `needs` that is not a technique;
  - a way named like a skill;
  - words `only_to` the addressee without `to: "required"`;
  - a `noticed.kind` that is a kind carrying words.
- The keys are `about`, `label`, `order`, `to` (`optional`/`required`), `words` (`hearing` share or `within_m`, `only_to`), `noticed` (`within_m`, `seen`, `kind`, `text`, `salience`), the row templates (`said`, `said_to`, `line_heard`, `heard_to`, `heard_to_you`), `kind`, `animals`, `gap_s`, `max_chars`, `needs`, `reach`, `needs_sight`, `introduces` and `salience` (`addressed`, `overheard`).
- Not accepted yet, so that no way can claim what the engine does not do: `cost`, `channel` (mind or sight), `to: "known"`, `names` (item 10) and `shows`.
- A script without ways speaks by the built-in `say` (`WaySpec::say()`, equal field for field to the shipped `say_speech()`, unit test `ways_of_speaking_are_read_from_the_script`). Once any way is declared, `say` must be one of them.
- An optional `<way>_check(a)` gets the speaker, the addressee as `a.target` and the line as `a.text` (`act::way_ctx`, the fields its plan reads).
- The ways are in the world text: a SPEAKING section after SENSES (`world_topics`, topic `speech`), one "`<name>` = `<about>`" per way.

**The primitive.** `speech::speak(ctx, speaker, text, to, way, now)` replaced `perceive::speak`, as section 3 describes. Its refusals write nothing and come back as `Err`:

- "no way of speaking called `X`";
- "speaking too fast" (2 s across all ways, as before);
- "too soon to `<way>` again: wait N s" (a way's `gap_s` above 2 s, read from the speaker's `line_heard` rows);
- "a `<way>` needs someone to `<way>` to";
- "you don't know `<technique>`";
- "too far to `<way>`: step closer" (an absent or dead addressee is refused the same way, so ids cannot be probed);
- "you can't see whom to `<way>` to";
- the check's own words.

Listeners are gathered once within the way's widest carry (`WaySpec::widest`). Today two gathers of the same radius ran, one for animals and one for people.

**Entry points.**

- `human_say(text, to)`: unchanged signature; the `say` way.
- `human_speak(text: String, to: u32, way: String)`: new; `""` is `say`.
- `mind_say(actor, say, say_to, way: String, seen_ms, thought)`: `way` is the new fourth argument.
- `mind_install`'s say: `say`.
- The graph's `say` node takes an optional `"way"` (`SayNode.way`; the normalizer accepts it in every written form). It waits out the way's limits (`speech::too_soon_to_speak`), and an unknown way fails as a refused leaf the speaker is told about.
- The mind's talk reply may name `"way"` (beside or inside `say`). A way the world lacks is said aloud. The talk prompt does not list ways yet: with `say` the only way, it is unchanged (item 6 adds them).

**`introduced` (item 3).**

- When `perception::introduce` returns true (the name is news), the receiver gets a row of kind `introduced`: subject the speaker, object 0, text "`<Name>` told you their name.", salience **0.55**.
- The design said 0.6. 0.6 is the threshold at which `percept` wakes a body's graph (`common::wake`), so a learned name would have re-run every listener's graph and changed what the regression must keep identical. 0.55 is integrated like any row (consolidation takes ≥ 0.2) without that side effect.
- The row follows the `speech` row that carried the name.
- The mind's consolidation sees it tagged `{Name=#id}`, the anchor `person:<id>`. `names.py` shows the memory graph's node for the person named after it.

**`line_heard` and `my_heard` (item 4).**

- **The table's name is `line_heard`.** The agreed name `heard` was taken on main by fov-1's "heard, not seen" sounds (its `heard` table and `heard_sounds` view) before this merged. The view keeps the name agreed with the laptop, `my_heard`; its rows' type is `LineHeard` in the bindings, with the same columns.

- `line_heard` (private): `line: u64` (primary key, the speaker's `said` experience id), `speaker: u32` (btree), `way: String`, `hearers: Vec<u32>`, `at_ms: u64`. `way` is an addition to the agreed shape. It lets a client draw a whisper's "heard by" differently, and it is where a way's own gap is read.
- It is written in the same transaction as the `said` row whenever one is written (no row for a speaker with no reader, such as an infant or a benchmark body). `hearers` are the people who received the words and whom the speaker saw at that moment, nearest first: the sight rule with the hearer's glow (`perception::in_sight` and `common::sight_to`, as the perceived sets use). An empty list means "no one you saw heard it".
- Retention: the row goes when its `said` row leaves the speaker's window. That is the trim in `perceive::percept`, `mind_consolidated` (a mind's integrated lines) and `forget_dead`. A played character's rows stay as its experience rows do.
- `my_heard` (public, per sender, `primary_key = line`): the current character's rows by one point lookup on `line_heard.speaker`, so it re-runs only for one's own lines.
- The mind service subscribes `line_heard` as the owner. A `said` line in every prompt and consolidation reads "… (heard by Bram and a stranger)", or "(no one you saw heard it)" (`Minds::heard_by`, names only where known).

**`speech_card` (public, item 5).** One row per way, rewritten at every install:

| Column | Meaning |
| --- | --- |
| `name` | The way's name (primary key) |
| `label` | Chip text |
| `order: i32` | Chip order, smallest first |
| `about` | What the way is |
| `needs_to` | A line needs an addressee |
| `reach_m` | The addressee must be within it (0: none) |
| `carry_m` | How far the words go for the world's ordinary hearing |
| `requires` | Technique the way needs, or empty |
| `needs_sight` | The addressee must be in sight |
| `private` | Words for the addressee only |
| `max_chars: u16` | Longest line; longer is cut |
| `gap_ms: u32` | Shortest time between two lines, at least 2000 |

The agreed fields are all there. `about`, `private`, `max_chars` and `gap_ms` are additions, so that the client can show the hint and enforce length and pace early. The shipped script's one row: `("say", "Say", 0, about, false, 0, 9, "", false, false, 400, 2000)`.

### Regression: the shipped `say` is unchanged

`speech.py regress` drives the same scene on both modules, and `speech.py diff` compares the rows with ids and names mapped to roles.

- The base is `a107fdf` (a worktree at the base commit, run `core-speech-base` with `--baseline`); the change is run `core-speech-regress`.
- The scene: four minded people, a deer and a player on a quiet open line (from the speaker: 3 m, about 4 m, 7 m, 8.5 m and 14 m; hearing 9 m). Ten lines through `mind_say`, `human_say` and a looping graph `say`:
  - a room line;
  - a line to one person;
  - a line to someone out of earshot (`silence`);
  - a self-introduction;
  - a repeat;
  - a line naming a listener;
  - three player lines, one of them an introduction;
  - a second mind's introduction.

  Then the 2 s limit, and the graph say's 45 s pacing.
- **Result: identical except the new `introduced` rows.** That covers the 65 speech-kind experience rows across the six listeners, with the same kinds, subjects, objects, texts and saliences in the same order per listener. It also covers the player's `line_seen` copies, the 11 chronicle lines, the 10 new acquaintances, every `mind_state` hearing mark, and each call's result and refusal text ("speaking too fast"). Evidence: `.local/living/verify/core-speech-regress/speech-diff.json`, with both runs' `speech-regress.json`.
- The new rows: 10 `introduced` rows, one per (listener, name) that was news. That is a's name to b, c and the player; the player's to a, b, c and d; b's to a, c and the player.

### Cost of a line, measured

The scene (`speech.py crowd`): 20 minded people (no mind service) in a 10 × 10 m square, a density of 0.2 people/m². Each says room lines in turn, 60 lines at one every 0.5 s: 120 lines a minute in all, each speaker one line every 10 s. Shipped hearing is 9 m, so a line reaches the 16.2 others within 9 m on average. Each module ran once on its own database on the trial server (`slop-trials-stdb`, v2.14.1, the Spark). The numbers are the server's own metrics for that database and reducer (`/v1/metrics`: `reducer_wasm_time_usec`, `reducer_wasmtime_fuel_used`, `spacetime_reducer_plus_query_duration_sec`, `spacetime_num_rows_inserted_total`), divided by the 60 `mind_say` calls.

| Per line | Before (`a107fdf`) | `speech-1` |
| --- | ---: | ---: |
| WASM time | 741 µs | 757 µs |
| Fuel | 1,919,162 | 1,944,417 (+1.3%) |
| Reducer + query | 0.88 ms | 0.94 ms |
| Rows inserted | experience 17.87, mind_state 17.2 (updates), chronicle 1, thought 1 | the same, and `line_heard` 1 |
| Listeners receiving the words | 16.2 | 16.2 (16.2 listed in `line_heard`) |

- A line costs one extra row (`line_heard`) and one sight-line test per receiver, for `hearers`. The two gathers became one. The difference is within what one run of each can tell apart.
- `mind_say` writes a `thought` row of its own, so the speech itself is a little below these figures.
- This is not a scale result. Twenty people, no mind service, no subscribers to `my_heard` (one view re-run per line of a played speaker is the added per-player load), and no other load. The talking-crowd workload belongs in the 216-character gate, as the gap list says.

### Privacy test (condition of item 6, built now)

`verify-minds/scripts/privacy.py` ([privacy.md](../.agents/skills/verify-minds/features/privacy.md)):

- **Scene:** the real mind binary against the fake model, two players, and memory in Neo4j (the trial stack's, under the run's own name, deleted after).
- **Check:** for a way's lines holding a unique word, every character that must not receive them (beyond the way's carry; for a `private` way, everyone but the addressee) has the word in none of these: its experience rows, its journaled prompts, its player's `my_experience`, its Neo4j memories. The fake's consolidation repeats what it was told (`$EXPTEXT:`, new in `fake_llm.py`).
- **Positive controls:** the addressee, and for a public way those in earshot, must have the word in each channel.
- **`--control`:** treats `say` as private. The run must then catch the word in the bystander's experience rows, prompts and the near player's client, which proves the check fails when words reach a bystander.
- **Plugging in a way:** who must not hear comes from `speech_card` (`private`, `carry_m`), so a later whisper plugs in as `--way whisper` with no change to the driver.

Results (2026-11-11, the trial server and its Neo4j):

- **`--way say`** (`minds-privacy-say2`): pass.
  - No violations: the far mind, the decoy speaker and the far player have the word in none of their channels.
  - All positive controls hold: the addressee and the bystander in experience rows, prompts and memory; the near player in its experience rows and `my_experience`.
  - All five minds consolidated after the lines, and 0 nodes were left in Neo4j.
- **`--control`** (`minds-privacy-ctl2`): pass. The check caught the word in the bystander's experience rows, prompts and memory, and in the near player's client, as it must when a bystander receives the words.
- Two earlier attempts (`-say1`, `-ctl1`) are kept as evidence of the driver's own fixes:
  - the fake fills placeholders only for rules marked `cite`;
  - the prompt channel had counted the model's reply, which held the uncited placeholder, so it now reads the request alone;
  - the wait now starts after the lines.

### Found while building

- **Names of two words are never "mentioned".** `mentions(text, name)` compares each word of the line with the whole name. "Vessa Pontil" (every Cullet name, and the island's) never matches a single word, so in Cullet:
  - saying "I'm Vessa" introduces no one;
  - a room line naming a listener does not address them.

  Names of one word (the test crowds' `Walker1`) work. `speech-1` keeps this unchanged, to keep the regression exact. The fix belongs with names (item 10, on `speech-2`).
- **The shared target dir and a second worktree.** Cargo hashes path dependencies without their path, so a base-commit build in the same `CARGO_TARGET_DIR` overwrites the branch's `living-rules` artifact, and the next branch build links the stale one. The base module was built in its own target dir (`--target-dir`, 372 MB for the WASM build).

### SpacetimeDB, re-checked for what this relies on (2.14.1 source)

- `#[spacetimedb::view(..., primary_key = line)]`: the view macro takes any column as the view's primary key (`spacetimedb-bindings-macro-2.14.1/src/view.rs`, `ViewPrimaryKeyArg`). A view may return a table's own row type (`Vec<Heard>`), as `my_vitals` returns `Vitals`.
- A `Vec<u32>` column (`line_heard.hearers`) is an ordinary SATS array, as `MindState.active: Vec<u16>` already is.
- `line_heard`, `speech_card` and the reducer `human_speak` are additions. Automatic migration allows new tables, and a new reducer leaves `human_say` working for old clients. `mind_say` gained an argument: a changed reducer signature gives an old mind service a runtime error ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations)), so the mind service and the module move together. The bindings in this branch are regenerated from the module (`spacetime generate`, the pinned image, as `just living-generate` does).
- `experience` and `line_seen` are untouched, so the type that `line_seen.line` embeds is unchanged (section 6).

## 14. Built: items 6, 7, 8 and 10 (branch `speech-2`)

Built 2026-11-11 on `speech-2`, from `speech-1`, after the owner accepted the six choices (section 11). All of it is script over the section 13 primitive, except three small additions: the truthful silence (item 8), overheard names (item 10) and the `mentions` fix.

### Whisper (item 6)

`whisper_speech()` in `living/scripts/skills.rhai`:

- `to: "required"`, `reach: 1.5`, words `within_m: 1.5, only_to: true`, `kind: "whisper"`.
- `noticed: #{ within_m: 6.0, seen: true, kind: "whispered", text: "{a} whispers something to {b}.", salience: 0.3 }`.
- `said_to: "You whispered to {b}"`, `heard_to_you: "{a} whispers to you"`, a 2 s gap, 400 characters.
- No animals, and no names (`names` defaults to false for words for one ear).
- The two distances are laws of their own (`whisper_reach()`, `whisper_noticed_within()`), so a world can change them.

What each one gets:

| Who | Row | Words? |
| --- | --- | --- |
| The addressee | `whisper`, "A stranger whispers to you: “…”", 0.9; their hearing mark moves | yes |
| Onlookers within 6 m who see the speaker | `whispered`, "A stranger whispers something to Bram.", 0.3 | no |
| Everyone else, and animals | nothing | — |
| The speaker | `said`, "You whispered to Bram: “…”" | its own |
| `line_heard` | `hearers = [the addressee]`, `way = "whisper"` | — |
| The chronicle (audit) | "Ilsa (whisper) to Bram: “…”" | yes |

Refusals are `whisper_check(a)`'s words (see "Refusals are the script's" below): "a whisper needs someone to whisper to", and "too far to whisper: step closer", also for an addressee who is absent or dead. A whispered self-introduction teaches only the addressee.

In the mind:

- `whisper` rows give the addressee a turn as `speech` rows do (`main.rs` `Event::Speech`).
- `whispered` rows never do, so no words and no turn reach a noticer.
- The talk prompt says "They whispered this to you; only you heard the words. To keep it between you, whisper back ("way": "whisper") …", and a reply that names no way is whispered back (`talk.rs` `how_heard`, `way_of`).
- A whisper refused because the speaker stepped away is not said aloud instead. The turn fails and is logged.
- Whispered words count as testimony from the speaker in consolidation, like speech (`told`).

### Call (item 7)

`call_speech()`:

- words `hearing: 2.5`: 2.5 times each listener's own hearing, which is 30 m in Cullet (12 m) and 22.5 m on the shipped island (9 m);
- animals hear "a person shouting";
- `max_chars: 80` (longer lines are cut), `gap_s: call_gap_s()` (6 s), refused by `call_check(a)` as "too soon to call out again: wait a few seconds";
- no cost, as the owner chose.

The templates read "{a} calls out from about {d} m", "{a} calls out to {b} from about {d} m", "{a} calls out to you from about {d} m", "You called out", "You called out to {b}". `{d}` is a new placeholder of every way's templates: the speaker's distance from the reader, in whole metres. Rows are `speech` (words to all in range). The world's widest hearing (`reach().hearing`) stays the voice's; a call gathers within its own wider radius.

The talk prompt tells a turn answering a call how far away the caller is and what an ordinary voice carries: "MindsTeller calls out to you from about 15 m. An ordinary voice carries 9 m: if they are farther than that, call back ("way": "call") or go over to them." The distance comes from the listener's own row (its words before the quoted line). The mind service does not follow bodies (it does not subscribe `body`); the authority, which does, writes the distance. The ways themselves are listed in the talk turn's reply format (`prompts::ways_text`, only when the world has more than `say`), and in the world text's SPEAKING section.

### Refusals are the script's (the coordinator's requirement)

A way's refusal is the words of its `<way>_check(a)`, and the reducer returns exactly those words. The game client compiles the world's script, so it can run the same check before it sends and show the same words.

- **One context builder.** Both sides build the check's context with `living_rules::script::speech::check_ctx(way, actor, addressee, text, since_ms)`:
  - `a.target` is the addressee: class `none` for the room; one who is absent or dead is a creature not alive and 1e9 m away, so a check cannot tell the two apart and ids cannot be probed;
  - `a.text` is the line;
  - `a.qty` is the milliseconds since the speaker's last line in this way. The authority reads it from the speaker's `line_heard` rows, and a client can take the latest `my_heard.at_ms` of that way. It is 4,000,000,000 if never.
- **Only the engine's refusals are Rust:** "no way of speaking called `X`", and "speaking too fast" (2 s across all ways). Neither belongs to a way.
- **The install holds the check to its spec.** Each way that requires an addressee, a reach, a technique or a gap above 2 s must have a `<way>_check` that refuses a sample line breaking it (to no one; 0.5 m beyond the reach; absent or dead; not knowing the technique; 1 s inside the gap). It must also accept a line that breaks nothing, or the install is refused (`check.rs` `ways`).
- **A safety net that is never reached.** The primitive still enforces the spec, and its words name the check that let the line through. A script that passed the install never reaches it. The words of a whisper go only to the addressee within 1.5 m whatever the check says.
- **`needs_sight` is refused at install for now:** no fact in the check's context says whether the addressee is seen. It waits for signing (item 13). Its `speech_card` column stays, always false.
- **The agreement test.**
  - Rules unit test `ways_refuse_in_their_checks_words`: the shipped checks' words on each case through `check_ctx`, and the install refusing a way whose check does not enforce its spec.
  - End to end, `verify-player` `speak.py` gives each way on `speech_card` its refusals through `human_speak`: to no one, beyond its reach, within its gap. It runs the installed script's check on the same facts outside the authority, as a client would (`living/rules/examples/way_check.rs`), and requires the reducer's error to be byte for byte that text.

### Silence that tells the truth (item 8)

When the addressee did not receive the words, the speaker's `silence` row (0.35) now says why:

- **The speaker sees them** (the sight rule): "Bram is too far to hear you; call out or go closer." The suggestion is the farthest-carrying public way that needs no technique, by its label; "go closer" alone when the way used already carries farthest.
- **The speaker does not see them** (out of sight, absent, dead): today's "No answer from X; they don't seem to be within earshot."

The mind's handling is unchanged: a `silence` closes that conversation.

### Overheard names (item 10)

A line to someone (`to` ≠ 0) whose words mention that person's name teaches it to every receiver of the words who sees the addressee. The receiver gets an `acquaintance` and, when the name is news, an `introduced` row: subject the addressee, object the caller, at the addressee's place, 0.55, text "You heard a stranger call Bram Calloway by name."

It is never taught:

- by closeness;
- by a whisper (`names: false`; only the addressee receives the words);
- by a `whispered` row;
- to the addressee itself.

The way's `names` key turns it off.

**`mentions` fixed.** A name is mentioned by its given name (its first word) or in full as words in a row. "I'm Vessa" now introduces Vessa Pontil, and "Vessa, …" addresses her. Before, a name of two words never matched, so in Cullet no one ever introduced themselves. Names of one word behave as before (the `say` regression below covers them). The cost is that a given name that is also a common word ("Rose", "Will") counts as a mention. Unit test: `speech::tests::a_name_is_mentioned_by_its_given_name_or_in_full`.

### `speech_card` rows (shipped script, the island's 9 m hearing)

| name | label | order | needs_to | reach_m | carry_m | requires | needs_sight | private | max_chars | gap_ms |
| --- | --- | ---: | --- | ---: | ---: | --- | --- | --- | ---: | ---: |
| say | Say | 0 | false | 0 | 9 | | false | false | 400 | 2000 |
| whisper | Whisper | 1 | true | 1.5 | 1.5 | | false | true | 400 | 2000 |
| call | Call out | 2 | false | 0 | 22.5 | | false | false | 80 | 6000 |

In Cullet (hearing 12 m), `say` carries 12 and `call` 30.

### Cost of a call, measured

The same `speech.py crowd` scene on a wider square: 30 minded people on a 6 m grid in a 30 × 30 m square, a density of 0.033 people/m². Sixty room lines at one every 0.5 s (120 a minute; each speaker one line every 15 s, past the call's 6 s). Each way ran once on its own database on the trial server.

| Per line | `say` | `call` |
| --- | ---: | ---: |
| People receiving the words | 5.9 | 21.2 |
| WASM time | 472 µs | 828 µs |
| Fuel | 1,378,186 | 2,511,034 |
| Reducer + query | 0.54 ms | 0.99 ms |
| Experience rows inserted | 7.4 | 23.5 |
| `line_heard.hearers` (those the speaker saw) | 5.7 | 6.2 |

- A call costs about 1.8 times a say here. That is in proportion to the people it reaches, with one row and one hearing mark each. The gather is wider, but the chunk cache keeps it local.
- The 6 s gap bounds one caller to 10 calls a minute.
- A whisper writes the said row, one `whisper` row, the noticers' `whispered` rows and `line_heard`. Its gather is within 6 m, so it is cheaper than a say.
- The crowd scene does not drive whispers, because room lines cannot be whispered.
- As before, this is no scale result. The talking crowd belongs in the 216-character gate.

### Verified

On the Spark, the trial server (`slop-trials-stdb`, 2.14.1), the trial Neo4j for memory, fake models only. Evidence under `.local/living/verify/`:

- **`just living-check`** passes (rules 157 tests, among them `ways_refuse_in_their_checks_words` and `ways_of_speaking_are_read_from_the_script`). Authority unit test `a_name_is_mentioned_by_its_given_name_or_in_full`. Bindings regenerated and unchanged (no schema change since `speech-1`).
- **Regression:** `speech.py regress` (`core-speech4-regress`) against the base module (`core-speech-base`): **identical except the `introduced` rows**. The same 65 rows, chronicle, acquaintances, marks and refusals as on `speech-1`. The diff now ignores the repeat row's "N s ago", which follows the scene's own pacing, not behaviour.
- **`speech.py channels`** (`core-speech4-channels`): 22 of 22. Whisper (words, noticing, nothing for others, refusals, a whispered name), call (20 m, animals, 80 characters, the gap), truthful silence (by day), overheard names, and a two-word name.
- **`speech.py ways`** (`core-speech4-ways`): 21 of 21, with the three cards.
- **`verify-player` `speak.py`** (`player-speak5`): 15 of 15. Every refusal of each way on the card comes back as exactly the words of the installed script's check run outside the authority, as a client would.
- **`verify-client` `run.py`** (`client-speech4`): every check passes (33).
- **`verify-minds`:**
  - `privacy.py` passes for every way: `minds-privacy2-say`, `minds-privacy4-whisper`, `minds-privacy4-call`, and the control `minds-privacy2-ctl`.
  - In the whisper run, the bystander mind and the near player were each told four times "… whispers something to …", with no words.
  - The `speech` case: `minds-speech10` passes: a reply with `"way": "say"` spoken; `"shout"` said aloud; a whispered question from 1 m answered "(whisper)" with no way named (the prompt says it was whispered); a call from 15 m answered "(call)" (the prompt reads "MindsTeller calls out to you from about 14 m. An ordinary voice carries 9 m …" and lists the ways); `introduced`, `line_heard` and the tagged consolidation as on `speech-1`. Earlier attempts on `speech-2` failed on the case's own scripting: `-2b` (the fake's rules matched an earlier line kept in the conversation; the latest line's rule comes first now); `-5` (a listener takes at most its stamina's turns per exchange, so the call now waits out the 90 s quiet); `-6` and `-7` (lines that asked nothing were answered only by chance; the lines are questions now); `-8` and `-9` (the distance was missing from the prompt; the mind now quotes its own row's words, then the assertion allowed only 15 m against the 14 m measured)..
- **`verify-knowledge` `names.py`** (`minds-names2-mara`): 7 of 7 with the two-word name "Mara Quill", learned from "I am Mara".

After merging origin/main (`93019a3`, then `b004e6e`, then `48cd022` with fov-1's facing sight and its own `heard` table, hence `line_heard`) into `speech-2`, all of these pass again: the check, the regression diff, `channels`, `speak.py`, the minds case, the whisper privacy test and the client suite.

Not covered:

- the game client's talk box with chips (the laptop builds it);
- the Cullet seed itself: its laws were compiled and checked by the rules tests, but not run as a world here;
- a real model's use of the ways;
- walls muffling speech (item 11);
- one answerer across mind services (item 9).
