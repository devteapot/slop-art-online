# Conversation turns

## Sub-features

- Player speech creates a `speech` experience for the nearby minded character, `living/authority/src/perceive.rs:165`.
- The real service dispatches a talk turn from the experience callback, `living/mind/src/main.rs:159`.
- The fake reply reaches `mind_say` and the chronicle, `living/mind/src/mind/talk.rs:645`.
- `end: true` closes the exchange. Repeating the same question produces no further talk request, `living/mind/src/mind/talk.rs:336`.

## How to get to it (user POV)

A player speaks to someone nearby. The listener answers as a conversation turn, then may end the exchange. New information or the agreed time can reopen it.

## Driving it with verify_minds.py

```bash
R=minds-talk-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case conversation
```

The driver joins `MindsSpeaker` through `verify.py player join`, moves the player with admin `place_near`, and directs a question with `player say --to`. `heard-speech.json` proves receipt while the fake delays its answer. `talk-speech.json` proves the AI's line is directed back to the player. `thoughts-after-end.json` records the ending reply. After the repeated question, the journal's talk count must stay unchanged for six seconds and `mind.log` must show `no turn`.

## Gotchas

- Addressed questions avoid the probabilistic choice to ignore an overheard remark.
- The authority enforces a two-second speech gap. The driver respects it.
- Speech triggers a talk turn, not a new full deliberation.
- An ended exchange can reopen for new matter. Repetition tests closure without claiming permanent silence.
- The observer does not control a player. The shared player identity is the real command path.
