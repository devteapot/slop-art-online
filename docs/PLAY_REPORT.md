# Play session report

Status: **in use** since 2026-11-11. After every owner play session, `living/tools/play_report.py` writes one page, `<out>/index.html`, holding what was on screen and a timeline of the session. Nobody has to ask for it: the play launcher (`play-1`) records each session and runs the report when the client exits.

It was built because play-test 2 left no recording. Finding out why residents seemed silent then took a manual investigation (`.local/living/playtest-2/diagnosis/REPORT.md`), and the owner's feedback came from memory minutes later.

## Run it

```bash
python3 living/tools/play_report.py --db <database> --run <run> \
    --journal <journal dir> --logs <dir with client.log and mind.log> \
    --out <dir> [--capture <dir>] [--player <character id>]
```

- It writes `<out>/index.html`, plus `report.json` (the page's facts, for checks) and the stills and video the page shows. It prints the page's path.
- It reads the world as its owner over SQL, using the in-container CLI identity as the verify harness does. It works on a paused world. It only runs `SELECT`s and never calls a reducer.
- Without `--capture` the page has no pictures. The timeline still comes from the authority's rows, the journal and the logs.
- The played character comes from the client log's `playing character #N`; pass `--player` to override.
- The module's log is read with `spacetime logs` inside the container, read-only. A `module.log.jsonl` in `--logs` is used instead when present.

Example, play-test 2 from its saved evidence:

```bash
S=.local/living/playtest-2/session
python3 living/tools/play_report.py --db verify-play2-20261111-135347 --run play2-20261111-135347 \
    --journal $S/journal --logs $S/run --out .local/living/play-report/play2-20261111-135347
```

## Recording

Three steps around the client, which the launcher (`living/tools/play.py`) runs for every owner session:

```bash
python3 living/tools/play_report.py record-start --db <database> --capture <dir>
LIVING_GAME_RECORD=<dir>/client living-game ...
python3 living/tools/play_report.py record-stop --capture <dir>
```

Then the report, with `--capture <dir>`.

The session's video comes from the game itself. Nothing records the screen from outside, so no OS permission is involved, and the result is the same whether the session starts from Rex, T3 Code or anywhere else. (Until 2026-11-11 `record-start` could also record the window with macOS `screencapture`. That needed the Screen Recording permission for whichever app launched it, and it is removed: the project builds its own tools rather than leaving an outside application on the routine path.)

### The client's own record (`LIVING_GAME_RECORD`)

`living/game/src/record.rs` is off unless `LIVING_GAME_RECORD=<dir>` is set; the launcher sets it. It writes:

- `stills/<unix ms>.jpg`: the session's frames as drawn, HUD included, `LIVING_GAME_RECORD_FPS` a second (default 5), `LIVING_GAME_RECORD_WIDTH` pixels wide (default 960, the view's aspect). The report encodes them into the session's video. With `LIVING_GAME_RECORD_FPS=0` (the launcher's `--no-video`) the client takes only stills, every `LIVING_GAME_RECORD_EVERY` seconds (default 3) and at each line sent, reducer answer, new speech bubble and act note, at most one a second.
- `state.jsonl`: four samples a second. Each holds where I am and face, the camera, the people the HUD knows (label, distance, hovered, targeted, talking), the bubbles and chat lines shown, the target, whether the text box is open, hp, energy, the frame time and the recorder's own main-thread time.
- `events.jsonl`: presses as the game reads them (a tap or a held press and who was under the cursor; keys outside the text box), each line sent, and every reducer call with the authority's answer and its arguments. This settles questions like "did a tap on a person strike them?" that play-test 2 could not answer.
- `captures.csv`: per frame, when it was asked for and when its texels arrived (unix µs), the worker's time and the file size.

**How a frame is taken** (`record_frames.rs`, `record_frames.wesl`). A render system in Bevy's `Core3d` schedule runs after the UI pass and before upscaling, so the frame it reads holds the HUD as shown. On a frame the recorder asks for, it draws the view's main texture into a small `Rgba8UnormSrgb` target with a 16-tap box filter, which keeps dithered fades from aliasing. It applies the view's compositing space as Bevy's own blit does, so the copy has the screen's colours. Bevy's pooled `ReadbackOnce` copies that small target to the CPU: 2 MB at 960×540, against 23 MB for a Retina-size screenshot. One worker thread writes each frame as a JPEG (about 15–25 KB); if it falls behind, a frame is dropped rather than waited for, and `state.jsonl` counts the drops. The state and event lines go to a second writer thread, so a slow disk never holds a frame. The copy is drawn only on the frames that are recorded, and nothing the player sees changes.

**The video.** At the end of the session the report encodes the frames into `<out>/screen.mp4` with ffmpeg (H.264, `libx264 -preset veryfast -crf 26`), each frame held for its own interval, so video time is session time. ffmpeg is only a post-step: without it, the page plays the frames itself in a small built-in player. Either way the page says how its video was made.

Times are unix ms, the authority's `at_ms` base. The module reads only the client's own state, and hooks the client in one place: `Net::on_reply` (net.rs), where every reducer's answer arrives.

**Frame cost** (2026-11-11, 18:05–18:12, measured under the owner-session lock, so no new heavy job started; no other client ran, load average 3.5–5.3). Setup: headless at 3200×1800, the readback size of the owner's 1600×900 window at Retina scale, capped at 60 fps, on the scratch world `verify-report2`, with the island's real assets. Runs were interleaved off and on, about 30 s of steady play each after a 35 s warm-up:

| Run | Frame time p50 / p95 / p99 | Frames over 25 ms | Main-thread work p50 / p95 | The 3 frames after a recorded one, p95 | Recorder's own main-thread time |
|---|---|---|---|---|---|
| off | 18.05 / 20.54 / 21.04 ms | 2 of 1751 | 2.11 / 2.62 ms | – | – |
| 960 px, 5 a second | 18.12 / 20.47 / 20.86 | 0 of 1820 | 2.14 / 2.48 | 20.56 | 0.15 ms/s |
| off | 18.25 / 20.55 / 21.31 | 0 of 1740 | 2.15 / 3.21 | – | – |
| 960 px, 5 a second | 18.41 / 20.61 / 21.17 | 0 of 1727 | 2.13 / 2.55 | 20.63 | 0.17 ms/s |
| **960 px, 10 a second** (the default) | 18.48 / 20.49 / 20.94 | 1 of 1730 | 2.39 / 2.75 | 20.51 | 0.21 ms/s |
| 640 px, 5 a second | 18.41 / 20.49 / 20.98 | 1 of 1737 | 2.42 / 2.87 | 20.49 | 0.19 ms/s |

There is no measurable cost at any of these rates. Frame times with the recorder on are within run-to-run noise of the runs with it off. The frames right after a recorded frame are no slower than the rest: the stall seen after report-1's full-size screenshots is gone. A frame's texels reach the worker about 37 ms (two frames) after the request. Writing the JPEG takes 4 ms on the worker. A frame is 45–65 KB at 960 px with real assets, so at 10 a second the JPEGs come to about 1.6–2.3 GB an hour. Past `LIVING_GAME_RECORD_MAX_MB` (default 4096) of frames, the recorder keeps one every 5 s. The encoded video is far smaller, about 2 MB a minute. 960 px at 10 a second is the default because it costs nothing measurable and shows walking and animation. 5 a second halves the disk.

### The action log (`LIVING_GAME_ACTIONS`)

`living/game/src/actions.rs` writes every reducer call the client sends, with the authority's reply, as one JSON line per call. The Spark's combat arenas use it to replay the owner's exact commands. It is off unless `LIVING_GAME_ACTIONS=<file>` is set. The launcher always sets it to `actions.jsonl` in the session folder, whether or not the session is recorded; `--client-env LIVING_GAME_ACTIONS=` turns it off. `session.json` names the file (`actions`).

It hooks the client where every call goes out: `Net::on_reply`, which each call site passes the reducer's name and arguments, and `Net::report` (net.rs). So a new call site is logged the same way, and the compiler asks for its arguments. A line, its fields in this order:

```json
{"seq":12,"t_ms":52183.2,"wall_ms":1794431570095,"reducer":"human_act","what":"wave","args":{"node":"{\"do\":\"wave\"}"},"yaw":45.0,"control":"travel","reply":"refused","error":"graph.do: skill `wave` needs a target","reply_ms":17.2,"server_ms":1794431570093}
```

- `seq` counts calls from 1 in the order sent. Lines are written as replies arrive, so sort by `seq` for the order sent.
- `t_ms` is when the call went out, in ms since the client started. `wall_ms` is the same moment as unix ms (UTC).
- `reducer` is the reducer's name: `join`, `human_move`, `human_act`, `human_say`, `use_skill`, `release_skill`, and any added later. `what` is the feature that sent the call: `move`, `say`, `skill`, `release`, `act`, `goto`, `face`, or a gesture's name. Gestures, facing someone and walking to a point are all `human_act`.
- `args` holds the reducer's arguments under the bindings' names, exactly as sent. A `human_act` node is the JSON string that the authority parses.
- `yaw` and `control` give the camera and the control scheme at the start of that frame. `yaw` is in degrees, 0 = north up, clockwise. `control` is `cursor` or `travel` (F3).
- `reply` is one of:
  - `ok`;
  - `refused`: the reducer returned an error, and `error` holds its text;
  - `failed`: the host aborted it;
  - `not_sent`: the SDK would not queue it;
  - `none`: no reply came before the connection dropped or the client closed. SDK 2.14.1 drops a pending call's callback along with its connection.
- `reply_ms` runs from the call to its callback. The callback runs in a later frame's `frame_tick` (`net::pump`), so a long frame adds to it: the first move after loading waited 0.9–2.3 s behind pipeline compiles. `server_ms` is the authority's timestamp of the reducer run, in unix ms.

The log holds no keystrokes, tokens or identities, only commands. Spoken lines are in `human_say`'s arguments, and the Spark's store holds this file back from publishing by default.

**Cost.** Each call costs the main thread its arguments (built only while logging) and one channel send. A writer thread formats, buffers and writes the lines, flushing within half a second and when the client exits (`AppExit`). A killed client loses at most its last half second and any calls still waiting for a reply. At exit the client logs the main thread's total time in the log (`actions: N calls logged; main-thread time …`). In the 2026-11-11 launcher runs (17 calls each, headless, load average 26–35 from other agents' builds), that came to 11.9 µs a call on average (20.9 µs at most) and 27.2 µs (116.5 µs at most): about 0.2–0.5 ms over a minute of play. Frame times with the log on and off differed by more than the run-to-run noise at that load, so an A/B of frame time could not resolve the cost. The per-call time is the measure.

**The report** reads `actions.jsonl` from `--logs` and adds a "Commands sent" table: calls per reducer, the replies by kind, the most common errors, and reply latency (p50 and p95). `report.json` carries the same as `actions`.

### The authority's rows (`record-start`)

`record-start` starts one detached process. It writes its PID to `<dir>/recorder.pid` and its notes to `<dir>/recorder.json`, and records into `<dir>/authority.jsonl`:

- **New `skill_use` rows** and **everyone's position** (the `body` row, advanced to the sample time), every second. The authority keeps only the last 24 skill presses per character.
- **New `experience` rows**, every 2 s. Residents' rows are deleted when their mind consolidates them, and all of a character's rows when it dies. In play-test 2 that took most hearers' rows; they were recovered only from model prompts.
- **New `chronicle` rows**, every 10 s.

This load is about 2.6 owner SQL requests a second, each one `SELECT … WHERE id > N` on a primary key. SpacetimeDB 2.14.1 accepts one statement per request. Each request opens and closes an HTTP connection, so the authority runs its connect and disconnect hooks: each request commits two short transactions that insert and delete the admin's `connection` row (presence.rs; `adopt` returns early for the admin, so presence is untouched). That is about 5 small transactions a second beside the tick, while recording. The final run made 249 requests in 96 s, with round trips p50 4.7 ms, p95 7.9 ms and max 13.6 ms (an earlier run under heavy build load had p95 80 ms). One report run makes about 10 such requests, so reading a paused world writes only those connection rows; it stays paused.

The SpacetimeDB documentation ([HTTP database API](https://spacetimedb.com/docs/http/database)) says the HTTP SQL API is "intended primarily for management, debugging and interactive developer use" and is less optimized than the WebSocket API; [subscriptions](https://spacetimedb.com/docs/clients/subscriptions) are the pattern for following rows. This recorder is a developer-audit diagnostic of one owner session, not a game path. That is why polling by owner SQL is acceptable here. A subscription-based recorder (a small Rust SDK client) would replace it if the load ever matters, for example with several sessions at once or a long soak.

## What the page shows

- **What stands out:** one line per thing the owner would ask about. That covers each line said and whether it got a conversation turn, the first reply and its latency, fights and killings with the time since the victim last spoke to the player, the longest silences, unprompted approaches, refused commands, errors and the cost.
- **On screen:** the session's video, made from the game's own frames, with a line saying how it was made (how many frames, their size and rate, and whether ffmpeg encoded them or the page plays them), and the timeline's times seeking it; a strip of the frames; the client's state as a table.
- **What you said:** for each line, the hearers (with experience ids, salience and distance), who was in earshot by the world's own hearing law, the conversation turns, parked lines and the answers with their latency and source (a conversation turn or a deliberation, and that deliberation's trigger). Each hearer without a turn gets the reason the mind log gives: parked, settled, or an unaddressed line the gate passed over, which it does not log.
- **Timeline:** everything above in order, plus lines heard, gestures, blows and the client's presses, each with the nearest still.
- **Fights and deaths**, with the player's skill presses and their outcomes (`skill_use`).
- **Refused commands**, with the authority's reasons: `act` rows ("What you had decided did not work out: …"), `skill_use` refusals ("refused: too tired"), reducer errors from the module log, and the client's `refused` log lines. Repeats within 10 s are counted on one row.
- **Commands sent:** every reducer call from the action log, per reducer, with replies, errors and reply latency.
- **Errors** from the client, the mind service, the module and model calls, from a minute before the arrival to a minute after the quit.
- **Cost** at the prices in `living/tools/trials.py`, by purpose and model, for the session (arrival to quit) and for the whole journal, split into people, animals and the player's own character.
- **Sources and limits.**

### Where the facts come from

- **The session** runs from the client's `playing character #N` to the `presence` row's `changed_ms` when `present` is false (the quit). Rows written after the takeover, whose `controller` is the mind service's identity, are left out.
- **Hearers** of a line are the `speech` rows written in the same instant (`at_ms`) with the player as subject. When those rows were deleted, they are recovered from the residents' model requests. Consolidation prompts show `[id]` experience ids, and those rows are the actor's own. Think, deliberate and talk prompts show `[day D HH:MM]` lines, matched by text and game minute. The line's rows have consecutive ids (said, repeat, then hearers nearest first), so a single unexplained gap is filled by a hearer seen only in an id-less prompt.
- **Turns** are the journal's `talk` calls whose `# You and … (#player)` header names the player and whose `# What you are answering` or `# The conversation so far` carries the line. **Parked** and **settled** come from mind-log lines.
- **Replies** are the player's own `speech` rows addressed to them. Each is matched to the model call that produced its words, and through that call to the player's lines it answered.
- **Distances:** the recorder's positions when there are any, else the distance to the player in the hearer's nearest model prompt (`# What you perceive right now`), within 20 s. The player's own track also comes from the client log's 2-second `island perf … at (x, y)` line.
- **Silences** are stretches of at least 60 s with no line, no act and no skill on anyone. Dodges and jumps do not break one.
- **Blows** on others are the victims' own `attacked you (N damage)` rows, from the recorder or from their prompts (to ±0.5 s).

## Evidence

Archived in `/Users/carlid/dev/slop-art-online/.local/living/play-report/` (the main checkout's `.local`):

- **Play-test 2**, from its saved evidence, with no recording: `.local/living/playtest-2/report/index.html`. Point by point against the hand-made diagnosis (`playtest-2/diagnosis/REPORT.md`):

  | REPORT.md | The page |
  |---|---|
  | First "hi", 13:54:22.0, `to = 0`, heard by Maud, Mercy, Cuth and Aldith (a crowd), no talk turn | Same time and hearers, with ids 1060–1063. Maud, Mercy and Aldith come from consolidation prompts; Cuth from an id-less think prompt, put in the one unexplained gap (1062). "No conversation turn" |
  | Cuth's reply 28.3 s later, from a deliberation triggered by a failed plan | "Cuth Marrow spoke to you 28.3 s later, from a deliberation (its think step) whose trigger was: What you had decided did not work out: teach medicine → person: they moved away" |
  | Second "hi", 13:54:43.5, heard by Bram, no turn; "6.8 s after the second" | Same, with the repeat note. Cuth's reply is not credited to it, because Cuth is not among its hearers |
  | First strike 13:55:06.6, 16 s after her greeting | "You struck Cuth Marrow at 13:55:06.6, 16.3 s after Cuth Marrow spoke to you" |
  | The blows: 8, then 26 (fire-bolt size), 8, 9, 9 | The same five blows from Cuth's prompts, ±0.5 s |
  | The killing at 13:55:36.2, after the yield | "Diego killed Cuth Marrow, who had yielded", the yield at 13:55:23.1 and the strike after it at 13:55:31.8 |
  | Silent for 3 min 49 s, 13:55:50 → 13:59:39; only Sissly spoke near him; residents saw him at 11–35 m | "Silent for 3 min 49 s (13:55:50.3 → 13:59:39.7) … you heard 1 line(s): Sissly Fenner at 13:59:19. Residents' prompts saw you at 11–35 m" |
  | "ssssssssshi": Mercy after 12.7 s, parked while deliberating | "Mercy Abbot after 12.7 s (parked: the listener was deliberating)", heard by Mercy (1706) and Osric (1707) |
  | "wassup": Linnet after 2.6 s, Mercy after 3.5 s | Same, both conversation turns, heard by Mercy, Osric and Linnet (1732–1734) |
  | The three refused "take wound tending" | "3× What you had decided did not work out: take wound_tending x1 → nearest remains: no wound_tending there." |
  | 0 model errors; `mind_say: character is dead` | 0 model-call errors; that WARN and its module-log ERROR |
  | Not in REPORT.md | 17 refused skill presses from `skill_use` at 14:00:04–10: strikes at Mercy and Osric ("too tired", 12× "out of reach") and bowshots ("too tired"); a dodge and two jumps at 13:56:15–18 during the silence; the session cost, $0.174 for 130 calls |

  REPORT.md listed "1180–1181" as unidentified hearers of the second "hi". Bram's journal shows 1180 is his own next row ("You failed to face → speaker"), so the page does not count it as a hearer; it flags the rows after the hearers it knows as not held.
- **Play-test 3** (`verify-play2-20261111-161445`, 16:15–16:19, no recording): `.local/living/play-report/play2-20261111-161445/index.html`. Diego's "Hi", addressed to Bram by the new tap-to-talk, was heard by four people and answered by Bram after 3.2 s through a conversation turn. Then came 3 min 16 s of silence with ten dodges and jumps. The session cost $0.091 for 67 calls. The player-memory internalization of the session is shown.
- **The recording, end to end** on the scratch world `verify-report-e2e` (island seed, a throwaway identity, headless client, no minds, deleted afterwards): `evidence-report-1/`, with the capture, the page, the A/B runs (`ab2/`, `ab3/`: frames, captures, state) and the driver (`ab.sh`, `frames.py`). It shows stills with the HUD and chat, client events with each reducer call's arguments, a `wave` refused with the authority's reason ("graph.do: skill `wave` needs a target", from the client and the module log as one row), strikes refused from `skill_use`, and hearers from rows the recorder kept.

## Replaying a session instead (not built)

Re-rendering a session afterwards in the client, at full quality and at no cost during play, would need more than the recorder keeps. What it keeps (the client's state at 4 Hz, every press and reducer answer, the authority's rows and everyone's position at 1 Hz) is enough for the timeline, not for the picture. A replay would need:

1. **The client's own row stream:** every insert, update and delete it received from its subscriptions, with the receive time. That covers `seen_bodies` motion segments (positions at 1 Hz cannot reproduce walking, turns, gait or the timing of combat clips), `seen_characters` (labels, folk, dress as perceived then), `seen_doing`, `seen_fighters`, `my_*` (vitals, combat events, experience), `weather`, and the chunk windows of `lot`, `structure`, `resource_node` and `terrain_chunk`. The client throws these away once applied.
2. **The view at frame rate:** the camera's yaw, pitch, distance and framing context, and the cursor (hover highlights, aim indicators). Today these are sampled at 4 Hz.
3. **The interface's own state:** open windows and menus, text being typed, tips shown and dismissed.
4. **A replay connection:** `net.rs` reads a live `DbConnection` throughout. A replay needs the same tables fed from a file, and every system that reads them (live.rs, combat, town, verbs, the HUD) must run unchanged on it.
5. **The same build and assets** as the session, since the look changes from commit to commit.

Items 1 and 4 are the real work, a "row tape" in the client. It would also give exact repros of client bugs. Until then, the in-engine frames are the session's video.

- **The in-engine video** (report-2): `.local/living/play-report/evidence-report-2/` holds:
  - the measurement runs (`runs/q-*`: frames, captures, state, client logs; `quiet.log` with the load and the other clients after each run);
  - the driver (`r2.sh`, `quiet.sh`, `frames2.py`);
  - the sample session: a 70 s scripted headless session on `verify-report2` with a throwaway identity, deleted afterwards. Its page is `sample-report/index.html`, with `screen.mp4` (647 frames, 960×540, 10 a second, 2.4 MB) and `contact.jpg`, a frame every 6 s from the video.
  - A frame and a full-size `shot:` of the same moment match in colour and HUD (`runs/func1`).

## Not covered

- **A windowed session.** All measurement and capture runs were headless (rendering into an image of the window's Retina size). The copy reads the view's main texture, the same path in both modes, but the owner's windowed session has not been recorded yet.
- **Minds and replies through the recorder.** The scratch world ran without minds, so its page has no conversation turns. Turns, parking and reply latencies were checked only on play-test 2's and play-test 3's real journals.
- **Hearers of a line whose rows were deleted and who never showed it in a later prompt** cannot be recovered without the recorder. Play-test 2's pages say so where rows after a line's block are missing.
- **Several players in one world:** the page follows one played character (`--player` picks another).
- **Turn arcs:** recorded positions follow a body's straight segment to its end, not the arcs the authority's `common::pos` follows, so distances during turns are approximate.
- **Why an unaddressed line got no turn** is inferred: the mind service's gate does not log it (DEBUG lines are never recorded).
