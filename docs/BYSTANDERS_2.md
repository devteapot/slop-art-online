# Speech, action, and one act repair

The conversation and deliberation frames now explicitly allow speech and an independently chosen one-off act in one turn. A normal exchange can leave the acts array empty. Immediate walks and gifts use `goto` and `give` with the ordinary argument shapes. An ongoing `follow` uses a behavior graph leaf. The compiler keeps speech already chosen at the think step. No event-triggered thought law is part of this change.

The authority passes synchronous act refusals back to the mind through `mind_act_checked`. The existing reducer still supports callers that use experience feedback. Both submit through the same act parser and queue. The procedure checks the controlling identity and alive state inside the transaction, writes the original feedback, and returns the same batch's refusals. Parse failures and immediate refusals include the valid one-off names from the current rules. The mind gives the model just the refused slots and their reasons for a single repair request in the same turn. Already delivered speech and accepted acts stay out of the replacement batch. A second refusal remains recorded without another repair request. Later physical or queued outcomes use the existing experience path.

The pinned SpacetimeDB 2.14.1 Rust module and SDK provide the procedure and caller-scoped typed return. The Rust module enables `unstable` for procedures. The procedure opens a transaction with `try_with_tx`. Returning a reducer error for an invalid act would roll back its original feedback and other accepted work in the same transaction. There is no new table or subscription. The procedure uses the existing actor-indexed queue and experience paths. Its transaction updates reach subscribers as unknown transactions in this SDK version, and the authoritative refusal itself goes straight to the caller. Reducer-name counters for `mind_act` in the soak and offers tools still describe the reducer. The checked procedure's submissions are a separate path. [SpacetimeDB procedures](https://spacetimedb.com/docs/functions/procedures/) · [SpacetimeDB reducers](https://spacetimedb.com/docs/functions/reducers/)

The act outcomes use `outcomes/act_attempts.jsonl` with the source turn reference, separate from model-call rows. The repair call inherits the think route's settings unless overridden and retains the source turn's lane.

## Frame excerpts

Before, talk presented the array as `"acts": [] or deliberate acts you carry out now`, followed by individual act examples. The compile frame said “express that decision as deliberate acts to carry out now (in order)” and “leave speech to the decision (speaking is not an act).”

After the change, both frames put the same instruction before the reply schema.

> Speech and action are separate choices in the same turn. If you only mean to talk, leave acts empty. If you independently decide to do something now, include the act even when you also speak.

The talk reply still carries `thought`, `say`, `to`, `way`, `acts`, `settled`, `until` and `end` in one JSON object. The paired examples are a berry offered verbally alongside `{"do":"give","target":{"id":4},"item":"berries","qty":1}` and announcing an immediate walk alongside `{"do":"goto","target":{"place":"home"}}`. The new guidance also says “Merely discussing a possible walk or gift calls for words alone.” The think frame directs speech into `say` and the action into `intend`. The compile frame shows the valid graph form `{"do":"follow","target":{"id":4},"distance":2,"qty":10}` and keeps the preceding step's speech.

The act names in the examples follow the rules catalog. The authority uses the installed skill names when it explains a refusal. A request using `go` still fails as an unknown skill. Speech uses the separate `say` field.

## Refusal repair on the real authority

The fake provider sent `go` alongside a valid `give`, and tried to send speech and the gift again in its repair reply. The authority refused the unknown skill and named the available one-off acts. The mind submitted just the replacement. The original speech was heard once in each case, and the recipient gained one stone in each case.

| Case | Second submission | Result | Repair requests |
| --- | --- | --- | ---: |
| Deliberation | `goto` | Walk completed | 1 |
| Deliberation with a second refusal | `go` | Second refusal recorded | 1 |
| Conversation | `goto` | Walk completed | 1 |

Both submissions share the original turn reference. A player identity calling the procedure for the resident received `not your character`. These cases used the running mind service and authority with a local fake provider at $0.

## Calm conversation replay

Six archived resident-to-resident turns from before the first blow in play8 were replayed with DeepSeek V4.1 Flash. Four seeds per turn made 24 pairs. The two arms received the same conversation and scene. The after arm added the new talk guidance. Alternating arm order reduced the effect of request order. This measures the acts emitted by the real model for fixed inputs.

| Frame | Turns | Emitted acts | Acts per turn | Speech-only turns | Acts per turn observed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before | 24 | 3 | 0.125 | 21 | 0–1 |
| After | 24 | 3 | 0.125 | 21 | 0–1 |

In 22 pairs the act count stayed the same. One went up by one and one went down by one. In both arms, all three acts were Petra choosing to teach Agnes smoking during an existing lesson conversation. For instance, the old frame produced “Watch my hands, not my mouth” with the `teach` act. The new frame produced “Bank it, then the wood” with the same act and target. Greetings and ledger conversations emitted speech alone. The replay cost $0.012800608. These are six fixed conversational turns. The replay measured model output directly before authority submission.

## Staged play8 fight

The trial used the archived play8 script and the island seed. Four nearby residents ran the model. A player landed an initial strike. Aldric called to Cuth and yielded, then a second player strike killed him 4.084 seconds after the yield. The authority's chronicle recorded the kill after yielding. All four residents appeared in the fight's onlooker list and received both the yield and the death-after-yield experience. The independent event-to-thought rule was absent. The player asked Maud and Agnes “What will you do now?” after the killing to give them a conversation turn.

| Resident | Reply and submitted act | Observed result |
| --- | --- | --- |
| Cuth Marrow | Called “I'm here, Aldric — what's happened? Are you hurt?” and submitted `{"do":"goto","target":{"id":1}}`. | Walk completed before the fatal hit. Cuth moved 3.10 m to Aldric. |
| Maud Marrow | Asked why the player had killed her father after he yielded. The reply included an empty acts array. | Speech delivered. No movement observed. |
| Agnes Fenner | Said she was going back to her pots at the inn. Her reply included an empty acts array. | Speech delivered. Her position stayed fixed through the observation window. |
| Bram Fenner | Had no conversation turn or act. | His position stayed fixed through the observation window. |

One of the three talk replies carried an act. Cuth's protective reply paired speech with a completed walk. Agnes's reply shows that the new frame can still produce an announced move with no corresponding act. The trial yielded no real-model refusals. The fake-provider cases cover the repair path. This was one live staging with directed lines, so it shows what happened in this run without measuring a change in how often spontaneous protective replies turn into acts.

The paid staging cost $0.006608064 for seven provider calls, including four consolidations. Combined with the calm replay, 55 provider calls cost $0.019408672. The spend watcher reserved at most $0.571685 against its $1.95 admission ceiling and the $2 combined budget.

## Verification and evidence

`just living-check` passed through the build slot. The mind unit suite passed 125 tests with 14 ignored. The seven focused verify-minds cases, four verify-llm regression cases and the verify-core `outcomes` scene all passed. The audit of the verification maps covered the changed conversation, frame, deliberation and repair features.

The raw frames, provider exchanges, authority exports, logs and cleanup records are in `~/slop-evidence/bystanders-2-2026-11-19.tar.zst`. Its `.sha256` companion was verified after the archive was written.
