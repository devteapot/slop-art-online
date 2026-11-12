# Conversation turns

## Sub-features

- Player speech creates a `speech` experience for the nearby minded character (`living/authority/src/perceive.rs` `speak`).
- The real service dispatches a talk turn from the experience callback (`living/mind/src/main.rs`, `experience().on_insert` → `Event::Speech` → `talk.rs` `on_speech`).
- The fake reply reaches `mind_say` and the chronicle (`talk.rs` `say`).
- The turn offers every act the rules mark for conversation (`talk` in a skill's spec): the examples in `talk_system` show `prompts::TALK_SHOWN` (conceive, accept, give, offer, teach, host), and `talk_acts()` lists the rest (`living/mind/src/prompts.rs`).
- Under `LIVING_PARK=wait` (the rule before 2026-11-11; the default is `concurrent`, below), a line heard while the listener's deliberation runs (`ActorMind.running`, set around `deliberate` in `mind.rs` `schedule`) waits for it (`talk.rs` `reply_turn` parks it; log "waits for it to end"). When the deliberation ends, `deliberation_ended` gives the line its turn ("gets its turn"), unless the deliberation spoke to that person after hearing them (`deliberation_says`; log "answered … in its deliberation"). A request that is only pending (queued, held by the rethink gate, off stage) does not hold a turn back. Case `parked`.
- `LIVING_PARK=concurrent` (the default since 2026-11-11; `wait` selects the old parking above; talk.rs `Deliberating`, `turn_alongside`, `deliberation_decided`, `unanswered_say`; hooks in `mind.rs` `deliberate`: `deliberation_prompt` after the experiences are read, `deliberation_decided` after the think step, `said_alongside` into the compile prompt, `unanswered_say` before speaking). A line heard within 2 s after the prompt was built gets its turn alongside (log "gets its turn alongside"). A later line waits for the think step and gets its turn as soon as the decision's words are not for the speaker ("has decided, and not to speak to"). Whoever speaks to the speaker first is the answer: a deliberation's words for someone a turn alongside already answered are not said ("already answered … while deliberating"), and a turn alongside after the deliberation spoke says nothing ("spoke to … first"). Case `alongside`.
- `LIVING_GREET=nearest|curious|facing` (`nearest` by default since 2026-11-11, `off` selects the old rule; `facing` stays off and is not for players until `human_face` is on main; talk.rs `Facts::drawn`, `faced`, `familiarity`, `audience_of`). It needs the world's `speech_audience` law (on by default since 2026-11-11), which writes the private `audience` table (perceive.rs `speak`). The mind subscribes to it only under these modes, in its own subscription so that a world without the table still starts (`main.rs`, `mind::greet_audience`; log "no `audience` subscription"). A stranger's line to no one, said with two residents within 6 m, draws no turn under `off` ("drawn in" absent), one turn from the nearest free hearer under `nearest` ("is drawn in by … (Nearest)"), and under `facing` a turn from the hearer the speaker faces ("is faced by … and takes the remark as addressed"). Case `greet`. The exhaustive unit test `greet_off_is_the_old_rule` proves `off` decides every combination of a line's facts as before.
- `end: true` closes the exchange. Repeating the same question produces no further talk request (`talk.rs` `on_speech`, the settled check; log "no turn").

## How to get to it (user POV)

A player speaks to someone nearby. The listener answers as a conversation turn, then may end the exchange. New information or the agreed time can reopen it. A stranger who says something to a group, to no one in particular, is answered by the nearest resident within 6 m who is free to talk; someone busy thinking still answers within a few seconds.

## Driving it with verify_minds.py

```bash
R=minds-talk-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case conversation
```

The driver joins `MindsSpeaker` through `verify.py player join`, moves the player with admin `place_near`, and directs a question with `player say --to`. `heard-speech.json` proves receipt while the fake delays its answer. `talk-speech.json` proves the AI's line is directed back to the player. The recorded talk request must contain `"do": "host"` (the unit test `talk_examples_show_every_shown_act` checks every shown name). `thoughts-after-end.json` records the ending reply. After the repeated question, the journal's talk count must stay unchanged for six seconds and `mind.log` must show `no turn`.

The `parked` case delays the fake's deliberate reply by 8 s. A line said while the first deliberation runs gets no talk request for 3 s, then one after it ends, answered through `mind_say` (`parked-speech.json`). A second deliberation's think step says a line to the player; the player's line during it adds no talk request, and `mind.log` shows "in its deliberation".

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case parked
```

The `alongside` case runs the service with `LIVING_PARK=concurrent` and first asks for a warm-up deliberation, so that each step starts from an accepted plan. It delays the fake's think replies 8 s three times (the warm-up, steps 1 and 2), then 6 s with words for the player (step 3), and compile replies 8 s. (1) A line said as the first think request arrives gets a talk request before any compile request. (2) A line said 4 s into the second think gets none for 2 s, then one before the second deliberation's thought row exists. (3) During the third think, whose decision speaks to the player, the player's line gets its turn alongside, and the deliberation's words never reach the chronicle ("already answered" in `mind.log`).

The `greet` case relies on the shipped rules keeping who heard each line (`speech_audience`, on by default; it checks the skills file says so). It places a resident 1 m west of a joined player and another 3 m east, and runs the service three times, with `LIVING_GREET` set explicitly to off, nearest and facing. Each time it waits for both residents' deliberations, then says one line to no one. Before the facing line it re-places everyone and the player turns to the farther resident with the `face` gesture. Expected answers (`greet.json`): none, the nearer resident, the farther resident, checked against the rule's own reading of each line's `audience` row.

The `parked` case selects `LIVING_PARK=wait` (the old rule); every other case runs on the defaults, `nearest` and `concurrent`.

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case alongside --case greet
```

## Gotchas
- Under load (the Spark at load 30) a harness `player say` subprocess takes about 2 s, the whole freshness window. The `alongside` case sends its two fresh lines straight over HTTP with the player's token from the run's `state.json` (`say_now`, logged "(HTTP, fast)" in `actions.log`).
- Residents walk off on their own ways between the `greet` case's arms, so the case places everyone again before each arm's line. `place_at` takes the nearest free tile, so someone standing on a target tile moves a body elsewhere (`minds-fixreq-g02`: the nearer resident ended 3 m from the player and the farther one 2 m). Since fix-request the case reads the bodies back (`body-placed.json`) and tries another direction until the nearer resident is nearer, the farther within 5 m, and the two more than 1 rad apart as the player sees them. It counts answers by their talk-turn thought rows: the chronicle merges a line repeated word for word into its earlier row, so a second identical fake answer adds no chronicle row.

- In the `greet` case's first arm the residents' think nodes settle about 25 s after the world's birth, with the service already running, and the fake answers at once. The pending deliberation row lives under a second. Before fix-request (2026-11-12), the shared `Run.request` polled only for that row and could time out on a request already answered (`minds-fixtake-full2-013217-greet`). It now also counts the answer's `thought` row ([README](README.md)).
- A restarted service replays speech under 30 s old (`STALE_MS`): the `greet` case lets each arm's line age 25 s more before the next restart, or the next arm answers the previous arm's line (seen in the first attempt). Talk state is in memory, so each restart starts with no exchanges and no once-a-minute history.
- A deliberation already pending when the service starts (it varies) has a think request without the case's marker, and fake rules with `times` are consumed in order by every matching request. The `alongside` case asks for its own warm-up deliberation, counts think requests carrying `verify` rather than matching each step's marker, and sizes its rules to include the warm-up.

- Addressed questions avoid the probabilistic choice to ignore an overheard remark.
- The authority enforces a two-second speech gap. The driver respects it.
- Speech triggers a talk turn, not a new full deliberation.
- An ended exchange can reopen for new matter. Repetition tests closure without claiming permanent silence.
- The observer does not control a player. The shared player identity is the real command path.

## Ways and who heard

Since `speech-1` (docs/COMMUNICATION.md §13):

- A talk reply may name `"way"`, beside or inside `say`. `talk.rs` `way_of` keeps it when the world's rules have it (`prompts::ways`, from the compiled script) and otherwise says the line aloud. `mind_say` takes the way as its fourth argument. A deliberation's say (`mind_install`) is `say`.
- A line whose words hold the speaker's own name gives the listener an `introduced` row when the name is news, so the mind is told "<Name> told you their name.". Consolidation sees it tagged `{Name=#id}`.
- The mind service subscribes `line_heard` as the owner. Every prompt and consolidation shows a mind's own `said` line with whom it saw hear it: "… (heard by Bram and a stranger)", or "(no one you saw heard it)" (`Minds::heard_by`).

The `speech` case (`verify_minds.py --case speech`) checks:

1. A player introduces itself and the talk reply names `"way": "say"`: the line is spoken.
2. The mind has one `introduced` row with the player as subject, and a `line_heard` row of its own lines listing the player.
3. A second line draws a reply in `"way": "shout"`, which the world lacks: it is said aloud.
4. The second talk prompt shows the mind's first line "(heard by …)", the player among those it lists (residents nearby may be listed too).
5. A consolidation request carries "MindsTeller told you their name. {MindsTeller=#id}".

Since `speech-2`:

- A `whisper` row (words whispered to the mind) gives a turn as `speech` does; a `whispered` row (noticed, no words) never does.
- The turn is told "They whispered this to you; …", and a reply that names no way is whispered back. A whisper refused because the speaker stepped away is not said aloud instead.
- A turn answering a call is told how far the caller is, from its own row's words ("MindsTeller calls out to you from about 15 m"; this service does not follow bodies), and what an ordinary voice carries.
- The reply format lists the ways (`"way": "say" or "whisper" or "call"`) when the world has more than one.
- The `speech` case checks both, when the card has the ways:
  - a whispered question from 1 m is answered with a "(whisper)" line, and its prompt says it was whispered;
  - a call from 15 m is answered with a "(call)" line, and its prompt holds the distance, the voice's 9 m and the ways.
