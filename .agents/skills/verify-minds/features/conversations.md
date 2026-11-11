# Conversation turns

## Sub-features

- Player speech creates a `speech` experience for the nearby minded character, `living/authority/src/perceive.rs:165`.
- The real service dispatches a talk turn from the experience callback, `living/mind/src/main.rs:159`.
- The fake reply reaches `mind_say` and the chronicle, `living/mind/src/mind/talk.rs:645`.
- The turn offers every act the rules mark for conversation (`talk` in a skill's spec): the examples in `talk_system` show `prompts::TALK_SHOWN` (conceive, accept, give, offer, teach, host), and `talk_acts()` lists the rest, `living/mind/src/prompts.rs:118`.
- A line heard while the listener's deliberation runs (`ActorMind.running`, set around `deliberate` in `mind.rs` `schedule`) waits for it (`talk.rs` `reply_turn` parks it; log "waits for it to end"). When the deliberation ends, `deliberation_ended` gives the line its turn ("gets its turn"), unless the deliberation spoke to that person after hearing them (`deliberation_says`; log "answered … in its deliberation"). A request that is only pending (queued, held by the rethink gate, off stage) does not hold a turn back. Case `parked`.
- `end: true` closes the exchange. Repeating the same question produces no further talk request, `living/mind/src/mind/talk.rs:336`.

## How to get to it (user POV)

A player speaks to someone nearby. The listener answers as a conversation turn, then may end the exchange. New information or the agreed time can reopen it.

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

## Gotchas

- Addressed questions avoid the probabilistic choice to ignore an overheard remark.
- The authority enforces a two-second speech gap. The driver respects it.
- Speech triggers a talk turn, not a new full deliberation.
- An ended exchange can reopen for new matter. Repetition tests closure without claiming permanent silence.
- The observer does not control a player. The shared player identity is the real command path.

## Ways and who heard

Since `speech-1` (docs/COMMUNICATION.md §13):

- A talk reply may name `"way"`, beside or inside `say`. `talk.rs` `way_of` keeps it when the world's rules have it (`prompts::ways`, from the compiled script) and otherwise says the line aloud. `mind_say` takes the way as its fourth argument. A deliberation's say (`mind_install`) is `say`.
- A line whose words hold the speaker's own name gives the listener an `introduced` row when the name is news, so the mind is told "<Name> told you their name.". Consolidation sees it tagged `{Name=#id}`.
- The mind service subscribes `heard` as the owner. Every prompt and consolidation shows a mind's own `said` line with whom it saw hear it: "… (heard by Bram and a stranger)", or "(no one you saw heard it)" (`Minds::heard_by`).

The `speech` case (`verify_minds.py --case speech`) checks:

1. A player introduces itself and the talk reply names `"way": "say"`: the line is spoken.
2. The mind has one `introduced` row with the player as subject, and a `heard` row of its own lines listing the player.
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
