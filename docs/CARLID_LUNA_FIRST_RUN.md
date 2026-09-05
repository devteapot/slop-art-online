# First authenticated Luna NPC run — 2026-09-05

The first bounded hosted experiment completed successfully through `https://codex.carlid.dev/v1/chat/completions`. Four complete replies returned HTTP 200, `finish_reason: stop` and reported model `gpt-5.6-luna`. This verifies authenticated transport and usable proposals for this run; returned identity is endpoint-reported, not independent attestation of the underlying model. No alternate model, mode or provider was tried.

The [read-only inspector](http://127.0.0.1:18881) shows run **sim-1788564912016-24047**: **45 ticks, 626 events**. The complete [archive manifest](../output/carlid-luna-first/manifest.json), [snapshot](../output/carlid-luna-first/snapshot.json), [verification](../output/carlid-luna-first/verification.json), and request journals remain under `output/carlid-luna-first/`. In the inspector, filter by event kind, select the numbered event, and use its parent buttons to follow causes; model-result events link the full journal.

## Outcomes

| Requests | Authority outcome | Evidence |
|---|---|---|
| 25, 18, 229, 425 | Four parsed proposals, all accepted | Results 122, 143, 340, 615 → decisions **123, 144, 341, 616** |
| 174, 297, 450 | Three local waits cancelled after generation became invalid; result records rejected as `stale request` | Results 226, 422, 502 → rejections **227, 423, 503** |

Each request had one attempt. There were no HTTP, parsing or semantic failures among complete replies. The accepted sequences produced **11 completed skill actions**: four moves, three speeches, two gathers and two eats. Eight model-directed identity/reflection events were applied. Some planned actions never ran: Tovan's first sequence was interrupted by damage, and Mira's final sequence reached only its first move before the scenario ended. Automatic behavior also ran throughout; these counts deliberately distinguish actions linked to model decisions.

| Character | Final state |
|---|---|
| Mira | Alive, health 100, hunger 26, energy 50, position 1; caution 65 → 70; trust toward Tovan 0 → 2. |
| Tovan | Died at tick 41 from repeated hazard damage at location 2; caution 25 → 45, with a retained danger belief. |
| You | Human-controlled and unattended; died of starvation at tick 41 with carried food unused. No human intentions were submitted. |

## Inspectable behavior

**Mira fed herself before coordinating.** Decision **144** selected gather → eat → move → speak. Results **155**, **171**, **194**, **212** confirm every step. Eating reduced hunger from 35 to 0. Speech **209** asked Tovan whether the clearing was safe and whether he would travel with her. Her reflections at **146–147** treated the traveller's report as uncertain instead of converting it into observer truth.

**Later behavior used remembered experience and speech.** Request **229** included perception **191** (no food at location 1), perception **130** (two food at location 0), and perception **138** (Tovan's scouting announcement, caused by speech **137**). Decision **341** cited these sources, increased trust toward Tovan by two at identity event **346**, and selected a return to the food site. Speech **349**, move **368**, gather **385** and eat **405** all executed. This is an observed context-to-proposal-to-execution chain, not proof that the explanation fully describes the model's internal cause.

**Mira revised an exhausted resource belief.** Her next supplied context included perception **382**, showing that location 0 had no food after the harvest. Decision **616** replaced her earlier food belief with a depletion belief at **617** and planned another destination. Move **623** executed at tick 45; the planned warning speech and clearing visit did not execute before shutdown. Her plan still referred to Tovan's older observed location. That request was frozen at tick 33, before his death at tick 41; the late response did not receive hidden current world state.

**Tovan's failure was not a series of fresh model choices.** Decision **123** announced scouting, then moved into the clearing. Damage **164** interrupted the sequence at **167** before its planned gather/eat steps. Later harm increased caution and established a danger belief. Automatic decisions nevertheless alternated seeking safety with exploring or gathering remembered food (for example **388**, **409**, **430**). All three later requests for Tovan were invalidated and cancelled, so no new hazard-informed model proposal took effect before death **596**. This exposes a fallback/latency limitation worth a separate experiment; changing world behavior during this run would have changed the experiment. The original proposal also spoke of carried food that had already been consumed while inference was pending.

## Boundaries, timing and usage

All seven actual user messages exactly equal the corresponding frozen subjective context. Every reflection source appears in that request's remembered perceptions. No observer world payload was added. Every journal has attempt-start, attempt-finish and completion records, and its inspector API bytes match the saved file. Snapshot API equality and ordered causal references also passed. The complete responses took about **24.8–28.4 seconds**; the world continued advancing while they were pending.

The four completed replies report a subtotal of **4,985 prompt + 5,487 completion = 10,472 tokens**. This is not a full-run billing total: usage for the three cancelled requests is unknown, provider identity and cost are absent, and cancelling the local wait does not prove remote processing stopped.

All four complete replies reported **1,264–1,511 completion tokens despite `max_completion_tokens: 1200`** in the actual requests. The endpoint accepted that field but its enforcement/accounting is unverified; it must not be treated as a demonstrated hard cost/token cap. No extra paid probes were made to resolve this discrepancy. The run stayed bounded by the 45-tick scenario and one attempt per request. Prompt-only JSON worked here; schema-output support was not tested.

## Baseline and reproducibility limits

The [comparison artifact](../output/carlid-luna-comparison.json) includes existing native Ollama and generic-local baselines without rewriting them. The native `backend-ollama-live` run used the same `m1-3` rules, 45-tick scenario limit and nominal two-second ticks, but ended at tick 41 with all characters dead. It had two accepted model proposals. Here Mira survived and four proposals were accepted. This single-run contrast does not establish model superiority: response latency/order, native versus generic transport, schema versus prompt-only output, sampling configuration and execution histories differ. The earlier `m1-proof-a` also had survivors but used different rules and human participation, making it a weaker comparison.

This run used the previously built runner SHA-256 `d63392344ded3455f08411cc2b88363d239e0fac568ff97940e76804c75187ba` and unchanged module SHA-256 `8b2c96c052a90aa102625d99c9b30b037b02860dd36b57234c85726980424c8b`. No code/protocol fix or follow-up inference was necessary for a valid first experiment. No model catalog request, broad paid sweep, database reset, archive overwrite, push, merge or deployment was performed. The saved credential was loaded by the dedicated launcher; its value was never printed or put in arguments/configs. All work remains uncommitted. No simulation is advancing; preserve the complete ignored archive and journals.
