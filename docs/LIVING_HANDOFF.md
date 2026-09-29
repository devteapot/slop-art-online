# Living core handoff (2026-09-29)

The run `aske-coast-3` ended on schedule at 06:55 local on 2026-09-29. This note records the state of things, what the three Aske Coast runs showed, and where to pick up. Evidence and every rule change, with times, are in [STAGES.md](STAGES.md) (entries from 2026-09-28 00:15 onwards). The architecture is in [LIVING_CORE.md](LIVING_CORE.md); authored worlds are in [AUTHORED_WORLDS.md](AUTHORED_WORLDS.md). The previous handoff (2026-09-27) is in git history.

## State

- **Host.** Everything runs on the Fedora Linux machine: rootless podman, SELinux enforcing, IPv6 broken. The laptop's labs and journals are not here.
- **Services.**
  - **SpacetimeDB** on :3300 (`sao-living_spacetimedb_1`).
  - **Neo4j A** on :7689 (`sao-living_neo4j_1`) holds the minds of every run up to `aske-coast-2`. It has reached Neo4j's limit of 65,535 relationship types, so do not use it for new runs.
  - **Neo4j B** on :7690 (`sao-living-neo4j-2`) is used by new runs, through `LIVING_NEO4J_URI` in `.env`.
  - **The Codex proxy** for GPT-6 Luna is at `~/dev/codex-cursor-proxy`, the systemd user service `codex-cursor-proxy` on 127.0.0.1:8787. It has a local, unpushed commit `167b91e`, and its unit sets `--dns-result-order=ipv4first`.
  - **The public observer** is `sao-observer-web` and `sao-tunnel`. Rebuild it with `just living-web-dist`.
- **Models.**
  - **Split by town:** `groups` in the models config sends Brandholm to Luna, and Saltreach and Oathstone to Mistral Small.
  - **Overflow:** Luna and Mistral overflow into each other.
  - **Where the settings live:** host-only settings are in `.env` (`CARLID_NPC_API_KEY`, `LIVING_MODELS=.local/living/models.json`, `LIVING_NEO4J_URI`).
- **Worlds.** All are paused, with their data kept. Nothing is running.

  | db | what it is |
  |---|---|
  | `aske-coast-3` | Aske Coast v3: structured society, graded force, balanced wildlife (8 h) |
  | `aske-coast-2` | Aske Coast v2, first authored world with fixes (5.5 h) |
  | `aske-coast` | Aske Coast v1 (1.5 h; authoring flaws) |
  | `stage4-two`, `stage4-makers`, `stage3-village` | the staged labs of 2026-09-28 |

- **Journals.** Under `.local/living/journal/<run>/`, gzipped. Trends per run are in `.local/living/pulse/<db>.jsonl`; read them with `living/tools/pulse.py <db> --show`.
- **Code.** Everything is committed on `living-core`, 46 commits since the previous handoff, not pushed. The user's uncommitted `Justfile`, `docs/LIVING_CORE.md` observer paragraph and `living/viewer/src/clock.rs` are still left as they were.
- **Care.**
  - `lab.py` no longer reclaims disk by default. `--reclaim` deletes any database idle for 2 hours, paused worlds included.
  - Never `pkill -f` a pattern that appears in your own command line; kill by pid.

## What was built (2026-09-28/29)

- **Retention.** The dead's routines, stats, practice, graph and genes are deleted, as are animals' personas and thoughts. An expecting parent keeps what the child inherits until the birth.
- **Authored worlds.**
  - `author_world.py`: a world bible and cast, then sheets drafted per household by a model, checked, then compiled into a seed.
  - Residents are installed directly from their sheets, and their authored past fades 12× slower ("formative").
  - Seeds support settlement-promised `resources`, named `buildings` (hall, workshop, market, inn) and money (`mark`).
  - A person thinks with their group's model.
- **Feedback that tells the truth.**
  - A campfire in the scene says it is burning.
  - Visible hunger.
  - Missing know-how says how to learn it.
  - Teaching an item or an invented technique names the real techniques.
  - A baby's cry says who is crying, and prompts only those who care about the baby.
  - A gift must fit the receiver's pack; a baby holds 4 things.
- **Force.**
  - Attacks are made to `hurt` or to `kill`.
  - `threaten`: once per target per 30 s; a child cannot frighten an adult.
  - `yield`.
  - `seize`: take goods from someone who has yielded or is badly hurt.
  - Animals attack people only when desperate, fighting back, or given easy prey.
- **Wildlife.**
  - Scent: prey and kin beyond sight.
  - Wolf metabolism and carried meat that spoils slowly.
  - Deer breed faster.
  - Weaned pups feed themselves.
  - A migration floor.
- **Minds.**
  - An outage gate for unreachable providers.
  - Consolidation keeps its minimum gap under a large backlog.
  - Relationship types stay bounded.
  - Neo4j transient errors are retried.
- **Observer.** Server-synced display time and seamless segments; stutter frames fell from 5.1% to 0.26% in replay.

## What the Aske Coast showed

| | v1 (1.5 h) | v2 (5.5 h) | v3 (8 h) |
|---|---|---|---|
| people at the end (start) | 63 (70) | 72 (70) | 69 (72) |
| starved | 1 | 3 babies | 7 (mostly babies) |
| killed by people | 0 | 3 | 5 (before the fixes) |
| killed by wolves | 5 | 1 | 1 |
| deer / wolves at the end | ~230 / 0 | 0 / 0 | 18 / 11 |
| model calls per minute | ~210 (then an outage) | 440 → 650 | 300 → 800 → 440 |

**Findings, most important first:**

1. **Crying babies become a permanent emergency, and a mind can radicalize in minutes.** With about ten newborns and cold nights, adults put infants first, ahead of their own food and the stores. A mind that consolidated every ~37 s (the 90 s gap was bypassed by a backlog; fixed) hardened "infants first" into "absolute", then "lethal enforcement". Thora killed her own son for his hides. One clear thought ("killing her would not feed Marlo") came only after the killing. The underlying belief that babies need cloaks drives the hide conflicts in every world.
2. **Graded force works as social control once goods can change hands without death.** In v3, Brandholm pressed Grim, the hide-hoarder, with threats and yields over its own law ("the common store… the Headwoman's word"), and nobody died. Killings came only when the goods could not be taken otherwise; `seize` then closed that gap. After the fixes (04:30 to the end) there were no killings, and 30–70 threats per 15 minutes.
3. **Authored institutions shape behavior.** Minds invoke the Oath, the Tally, the council, the Headwoman's authority and the Elders' sign, and the Keeper enforces the Oath with a threat. Offices are used as social rules, with no engine support beyond force and money.
4. **Model load grows with population and crisis, not just head count.** At 70–80 people, both providers saturated: up to 800 calls a minute with 45% rejected. Thinking and deliberating dominate (about 240 calls a minute each, a person every ~17 s). This was left unaltered at the user's request, apart from the consolidation-gap bug. The lever for later is `think_min_s` and `consolidate_min_s` in `species.json`, or the level-of-detail mode.
5. **Wildlife holds with scent, a slow wolf metabolism and the floor.** Deer fell from 60 to 18 over 8 hours under people's hunting and wolves; wolves held at 9–11. The floor (deer below 15) was not reached. People were killed by wolves only when the rules allowed it.
6. **Talk rises over a long run** (0.8 → 3.4 lines per person per minute in v3), passing the staged labs' runaway bar of about 3 in the last hours.

## Where to pick up

- **Babies and the cloak belief.**
  - Check whether infants really lose health at night: babies near a shelter are warm by the rules.
  - If minds' beliefs are wrong, make the truth perceivable: a baby "looks warm" or "looks cold".
  - Consider whether a baby's crying should prompt fewer adults.
- **Talk volume** in long runs, and what drives it (conversation turns, babies, crises).
- **Load:** decide the thinking pace (`think_min_s` 20 → about 45) or the level-of-detail mode before larger worlds.
- **Force monitoring:** `pulse.py` counts threats, assaults, yields, seizes and killings. The next run will show whether `seize` replaces killing.
- **Still open:**
  - a behavioral fault: people pace between two tasks;
  - people's hunting pressure on deer;
  - lifetime counters for practice now that the dead's rows are deleted;
  - pushing `living-core` and the proxy commit when the user wants.
