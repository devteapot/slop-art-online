# World rules in Rhai

**Status:** built on branch `rules-2`, 2026-11-10. Skill specs and descriptions are in the script, a small set of engine primitives lets the script define social state and reactions, and agreements, demands and community regard are built from them as Rhai content. Evidence: [Verification](#verification); costs: [Costs](#costs).

**The user's decisions (2026-11-10):**

- "Export the primitives so that these kinds of things can emerge, but are not hard-coded in the core/engine," and allow custom rules per world.
- Skills declare their spec in Rhai. Adding a skill needs no Rust catalog line.
- Every skill needs a description good enough that a model has the right context to do the right thing.

**Why now.** The social trials ended with a diagnosis ([trials](TRIALS.md#why-the-newcomer-got-so-little-diagnosis-from-ls1ls2-journals-and-rows)): residents offered bed and food for work ("woodpile at my store by dark"), but work-for-keep deals lived in words only. Nothing recorded the job, and nothing told the resident that the wood was stacked. [Seeded lives](SEEDED_LIVES.md#rule-gaps) listed the rule gaps the island's tensions wait on: a community's regard for another, and a toll as an ordinary demand.

## Skills declare their spec in the script

Each skill in [`skills.rhai`](../living/scripts/skills.rhai) has a `<skill>_spec()`, read once when the script compiles. The `_combat` and `_shows` declarations are the precedent.

| Trait | Meaning |
| --- | --- |
| `target` | It is aimed at something. |
| `item` | It takes an item: `true`, or a word for what the item names (`"technique"`, `"signal name"`). |
| `items` | The item words it is given (`build`: campfire, shelter...). These are choices for clients and prompts. They are accepted for the skill even when they are not items, structures or techniques (`lodging`). |
| `args` | Further arguments it reads, for prompts (`qty`, `want`, `text`, `graph`...). |
| `reach` | Tiles within which it is done; an act walks into reach first. |
| `about` | What it is, written for a mind: what it does, when it is useful, what it is not. Required. |
| `takes`, `gives` | What it uses up and what comes of it, built from the rules' own numbers. |
| `listed` | Shown to people (false: only species that name it, such as grazing). |
| `talk` | Offered in a conversation turn among the acts one may do there. |

**Where the specs are read:**

- `Scripts::new` reads every `_spec`, in the order the source declares them. The order matters to the client: the likely act on a bush is `gather`, ahead of `face`.
- `Scripts::skills()` returns them as `catalog::Skills`. The Rust `SKILLS` list is gone.
- `catalog::skills()` is the world's skills in this process. It is set where a process adopts a world's script: the authority's script cache (`common::scripts`), the mind's `prompts::set_rules` and the client's compile in `verbs::Rules`. Until then it holds the shipped script's. `catalog::scoped` overrides it on one thread, for tests. A build without the script runtime (the lab viewer) takes any skill name: it only shows graphs the authority accepted.
- **Graph normalization and validation** (`normalize.rs`, `graph.rs`) take names, target and item needs, and the items a skill accepts from there.
- **The acts path:** `acts::parse`, `human_act` and `mind_act`.
- **The authority:** reach (`act::reach`, `combat::cards`) and founders' knacks (`seed::spawn_creature`).
- **The mind's prompts:** `catalog::skills_help`, `species::skills_help` and `prompts::talk_acts`.
- **The client's verbs:** `verbs::skills_of`, and the items for a target from `items`.
- `skill_io(name)` is the spec's `takes` and `gives`; the Rhai `skill_io` function is gone.

**Install checks** (`script/check.rs`):

- A skill with rules (a `_duration` or `_done`) but no `_spec` is refused: "`whittle` has rules but no `whittle_spec()`".
- A spec without `about` is refused when the script compiles, and so is a spec with an unknown trait.
- **Old scripts:** a script that declares no spec at all (a world's script installed before this change) is given the shipped script's specs, so the world keeps its skills until its next install. `living-publish` installs the tree's script.

**Proof:**

- `a_skill_added_only_in_the_script_is_everyones`: a `whittle` skill exists only in an appended script (its spec, check, duration and done). Graph normalization, graph validation and `acts::parse` accept it, and the mind's skill reference lists "`- whittle(item: wood): Carve a piece of wood...`". The shipped skills do not know it. Without its spec, `validate` refuses the script.
- The client test `a_skill_the_rules_add_is_offered`: a `polish` spec and check offer the skill on a boulder, and not on a bush or on oneself.

## Descriptions for models

Every skill's `about` says what it does, when it is useful and what it is not. Examples:

- "Build a structure... There is no repairing or mending of anything: a structure stands until it is gone."
- "Close wounds at once with your hands... It heals bodies only: it does not mend tools, hinges, nets or anything else." (`heal`)
- "Propose a swap now... For goods in hand; for work, or for something delivered later, offer_terms." (`offer`)
- "Strike a creature beside you. Every blow does its full damage and whoever reaches 0 health dies; there is no holding back. To frighten someone without harm, threaten." (`attack`)

The specs are functions, so a floor overrides a skill's description the way it overrides any law: it redefines `<skill>_spec()` in its overlay ([floors](FLOORS.md#how-a-floor-overrides-laws)).

**The skill reference minds read** (`catalog::skills_help`, in the deliberation grammar) grew from 12,835 to 16,978 characters (56 skills to 58: `offer_terms` and `demand`). In the real run below, a deliberation's prompt averaged 12.0k tokens against 10.9k on main: the longer reference plus the dealings section. Regenerate it with `cargo test -p living-rules --lib print_skill_reference -- --ignored --nocapture`, at `bbf7271` for the old text. Before and after, three lines:

```text
before:
- give(target, item): hand items to another creature
- offer(target, item): offer a trade to a person beside you: item + qty you give, want + want_qty you ask in return; they may accept
- heal(): mend the wounds of yourself or an ally you can see within 8 tiles, quickly, even in a fight; needs mending and a lot of energy
    takes: knowing mending, 15.0 energy, yourself or a hurt ally in sight within 8 tiles; ready again after 8 s
after:
- give(target, item, qty): Hand items from your pack to someone beside you. Nothing is asked in return; for an exchange now, offer. It is also how you pay what you agreed to or what is demanded of you: the world counts it.
- offer(target, item, qty, want, want_qty): Propose a swap now to a person beside you: item × qty you give for want × want_qty you ask. If they accept, both sides change hands at once. For goods in hand; for work, or for something delivered later, offer_terms.
- heal(): Close wounds at once with your hands, your own or an ally's in sight within 8 tiles, even in a fight. Needs the wound_tending technique. It heals bodies only: it does not mend tools, hinges, nets or anything else.
    takes: knowing wound_tending, 15.0 energy, yourself or a hurt ally in sight within 8 tiles; ready again after 8 s
```

Arguments are now listed in full (`qty`, `want`, `text`), and `takes`/`gives` come from the spec for every skill: 13 skills had none before.

### `mending` is now `wound_tending`

The newcomer kit's know-how `mending` was the `heal` skill's wound-closing, and models read it as mending things. In `i8` every newcomer pitched itself as a mender of hinges and tools ([trials](TRIALS.md#fast-iterations), row 8).

**Rename and migration:**

- The technique is now `wound_tending`, with help "close wounds quickly with your hands (the heal skill), your own or an ally's, even in a fight; not mending things".
- Seeds and trials are rewritten: `island.json` has 79 knows entries, plus `wolves.json` and `wolves-valley.json`.
- `catalog::RENAMED` maps the old name to the new. Wherever a name comes in, it is read as the new one: `catalog::technique`, `common::learn`, `common::knows`, and normalization of `teach` items and `write` topics.
- `install_script` renames a world's stored know-how and written topics once (`lib.rs` `rename_techniques`). There is no index by technique, so this reads every know-how row and artifact; an install is a rare admin call.
- Memory graphs in Neo4j keep the word in the characters' own memories. That is history, not a rule.

**Before and after on real replays.**

- **The calls:** the eight newcomer identity requests recorded in `i8` (one per run, on the Spark under `.local/living/trials/i8/*/journal/Arlen.jsonl`, line 1), replayed three times each on glm-flash at `high` effort:
  - as recorded;
  - with `mending` renamed to `wound_tending`, the only difference.
- **Counted:** the narrative only, not the model's thinking.

| | Narratives that read it as mending things ("mend what's torn", nets, hinges) | Narratives about tending wounds |
| --- | ---: | ---: |
| As recorded (`mending`) | 19 of 24 | 0 of 24 |
| Renamed (`wound_tending`) | 1 of 24 | 23 of 24 |

Recorded: "I know how to coax a fire and mend what's torn". Renamed: "nothing but a knack for fire and for closing wounds"; one renamed narrative still added "I'll watch, mend what's broken". 48 calls; 88k prompt and 17k completion tokens, about $0.02. A first attempt with the same calls failed to parse its replies, so the spend was about $0.04 in all.

## Primitives

Four engine primitives, with no engine code per kind of social state:

1. **Records:** durable state.
2. **Event hooks:** laws the engine calls when something happens.
3. **Stances:** standing and regard, read by graphs.
4. **Experiences from rules:** what the rules tell a party, in that party's own terms.

The Rhai side is in `skills.rhai` ("agreements, demands and regard"); the engine side is in `living/rules/src/records.rs` and `living/authority/src/records.rs`.

### Records

A record has:

- a **kind** and a **status** (strings the script defines);
- **parties** by role: a character, or a community as `records::COMMUNITY | id`;
- **terms**: a map of strings, numbers and booleans;
- the character who made it, and the time it was made;
- the time it **falls due**.

**Tables** (private; [table design](https://spacetimedb.com/docs/tables/), [indexes](https://spacetimedb.com/docs/tables/indexes/)):

- `record`: primary key `id`; btree index on `due_ms` (`u64::MAX` means never).
- `record_party`: one row per party; btree indexes on `party` (records involving me) and `record` (a record's parties).
- `record_clock`: one row counting changes to stance records.

**Effect ops,** from a skill's `_done` or a hook:

- `#{ op: "record", kind, status, parties: #{ role: id }, terms, due_h }` makes a record. The actor must be one of its parties, and every character party must be alive.
- `#{ op: "amend", id, status, terms, due_h }` changes the status, merges terms and moves the due time.
- `#{ op: "close", id, status, keep_h }` closes a record. It stays readable for `keep_h` world hours, then the engine drops it.

Only a party to a record, or a hook asked about that record, may amend or close it. Times are world hours ("by dusk" is a law of the script, `due_by_dark`).

**Read access in laws:**

- `a.records`: the actor's records, as a party itself or through its community. Each is `#{ id, kind, status, open, terms, parties, me, by, age_s, due_s }`, where `me` is the role the actor holds.
- `a.record`: the record at hand, for `on_expire`.

The engine fills them only for a law that reads them; the field analysis marks it (`Scripts::reads`, `skill_reads_records`). The lean-context plans cover the new fields: `a.records`, `a.record`, `a.want`, `a.want_qty`, `a.actor.community`, `a.actor.home`, `a.target.community`, `a.target.owner` and `a.target.home`.

**Bounds:**

- A character holds at most 12 open records; making a 13th is refused ("has too many dealings in hand already").
- A record has at most 4 parties and 16 terms of at most 1 KB in JSON, and runs at most 720 world hours.
- Closed records are dropped after their keep time.
- Seeded records (regard) are not counted against a character's bound. Communities are parties to them, not characters.

**Knowledge against audit truth.** A record is audit truth. Who knows of it is perception's:

- the rules tell the parties (`tell`), and onlookers in sight see it made (`witness`);
- a player reads only their own characters' records through `my_records`;
- a mind is shown only its own character's records (`mind/src/mind/dealings.rs`).

Nobody learns of a record by reading the table. A dead party's records are not closed by death; the rules settle them when they fall due, as the survivor would find out.

### Event hooks

The engine calls `on_<event>(a)` where the script defines one:

| Hook | When | Context |
| --- | --- | --- |
| `on_<skill>` | after that skill was done successfully (`on_give`, `on_store`, `on_host` in the shipped rules) | the skill's own context, at completion |
| `on_expire` | a record's due time has come (1 Hz housekeeping, at most 64 a second) | its maker as actor, another character party as target, the record as `a.record` |
| `on_death` | a creature dies, before its things are gone | the dead as actor |

**Limits on what a hook does:**

- A hook returns effects, and only `record`, `amend`, `close`, `tell` and `witness`. It notices and tells; it moves no goods and no bodies (`Effect::of_a_hook`). An install refuses a hook that returns anything else, and so does the engine at run time.
- Hooks run on events only, never per tick. They run under the same Rhai limits as every law: 2,000 operations per call. A hook that fails is logged; the act it follows stands.
- The install probes call every hook over the samples of its event: each body, each target, the items `wood`, `berries` and `lodging`, and seven sample records. A hook for an event the engine does not have is refused: "the engine calls on_<skill> after a skill is done, on_expire and on_death".
- After `on_expire`, a record whose due time has not been moved is dropped: the rules let it run out.

Not built: `on_day`. A daily law (rent, regard that drifts) would take a context per record or per community, once a world day; no content needs it yet.

### Standing and regard (stances)

A record with a `holder` and a `toward` party whose terms carry a `label` (and a `value`, -100..100) is a stance: how the holder regards the other side. The record's kind is the script's (`regard` on the island); the engine reads only the roles and those two terms.

**Where stances are read:**

- **Graph relation filters.** When `me` has no personal relation to `other`, `relation_ok` (`brain.rs`) checks whether my community's stance toward theirs fits the filter word:
  - `enemy`: value ≤ -25, or a label with rival, enemy, threat or foe;
  - `friend`: value ≥ 25, or a label with friend, ally or kin;
  - any other word: a word of the label (`"relation": "rival town"`).

  Stances are cached per module instance and rebuilt when `record_clock` moves (any change to a record with a `holder` party).
- **Laws:** `a.records` includes the stance records of the actor's community. `regard_toward(a, community)` in the script returns their terms.
- **Minds:** the character's own dealings section lists them ("your people hold Kettlebridge as rival town (the broken match...)").

**Seeded records.** A seed's `records` list makes records at genesis, with parties by role naming a community or a person:

```json
{"kind": "regard", "parties": {"holder": {"community": "Brackenford"}, "toward": {"community": "Kettlebridge"}},
 "terms": {"label": "rival town", "value": -35, "why": "the broken match, and Kettlebridge's sharp prices and pride"}}
```

The island seeds 13 regards from the bible's tensions (`world.json` `records`; `author_world.py` copies them into `island.json`). They cover:

- Brackenford and Kettlebridge, each a rival town to the other;
- Brackenford and the Coldwell outlaws;
- Thornby's debt;
- the giants and the cairn-cutters;
- Lanternquay and the dear stone;
- the small folk and the giants (old friends);
- the Lakemead rivals.

Not built:

- **Perception's `perceived_of` does not read stances yet.** A projection label such as "a Kettlebridge carter (rival town)" needs to know whether the observer can tell the target's community. That is the perception work's (`scale-1`).
- **A regard writable by an act.** Rule gap 1 proposed that a community's head could change it. The world has no heads (no roles); a `declare` skill whose check is the script's own condition would be content on the same ops.

### Experiences from rules

- `#{ op: "tell", to: id, text, salience, ask }` tells a character something in the rules' words. The engine rewrites `{actor}`, `{target}` and `{id:N}` as the one told refers to them: a name it knows, "a stranger", or "you". A community's id becomes its name.
  - The text becomes an experience of kind `record`.
  - `ask` has the told character's mind think about it, as an offer does.
  - Told to the actor of a skill, the text is that act's outcome. A player's client shows it as the act's result; a mind reads it as feedback.
- `#{ op: "witness", text }`: everyone with a clear sight line to the actor perceives it, with `{a}` and `{b}` labelled per onlooker.

## Content built from the primitives

All of this is in `skills.rhai`. It is the same for players, minds and graphs: the skills are ordinary skills.

**Agreements** (`offer_terms` → `accept`):

- `offer_terms` (target, item × qty, want × want_qty, text) makes an `agreement` record with status `offered`, roles `from` and `to`, and both sides' homes in its terms. The other side is told the terms and asked to think about them. The proposal stands 4 world hours (`proposal_h`).
- `accept` toward the proposer makes it `agreed`, due at dusk (`due_by_dark`). The proposer is told, and onlookers see "came to an agreement". Without terms standing, `accept` is the trade accept, as before.
- **Deliveries** are counted by hooks:
  - `give` to the other side (`on_give`);
  - `store` into a storage whose owner is the other side, or shares their home (their household's store, `on_store`);
  - `host` for `lodging` (`on_host`).

  When one side has delivered its part, the other is told what it owes, and its mind is asked. When both have, the agreement is `kept`, and both are told.
- **At dusk** (`on_expire`):
  - delivered by one side only: `broken` by the other, and each side is told in its own terms ("they broke your agreement" / "you broke your agreement");
  - by neither: `lapsed`;
  - a proposal never accepted: "did not take up your terms".

  Nothing pays automatically: paying is the debtor's act.

**Demands** (`demand`):

- `demand` (target, item × qty, text: why) makes a `demand` record. The target is told and asked to think; onlookers see it.
- A `give` of the item to the demander counts toward it (`on_give`); paid in full, it is `met` and the demander is told.
- Unpaid after 3 world hours (`demand_h`), it is `unpaid`, and both are told. Refusing is not an act, and what follows is the demander's choice.
- A second demand of the same person while one stands is refused.

**Community regard:** the seeded stances above, read by relation filters, laws and minds.

**How a party reads a record:** `record_text(r)` in the script words each record for its party ("agreement with Mira, by dusk: you give 10 wood, they give 3 berries; so far you delivered 4 of 10, they 0 of 3"). The mind service compiles the world's script once per thread and asks it. The text then goes to:

- the deliberation prompt, in a dynamic section "Your dealings and your people's standing" (so the per-character cached prefix stays stable);
- the talk turn's "between" lines, for the records shared with the other person.

**Prompts.** Skills marked `talk` that the talk turn's examples do not already show (`offer_terms`, `demand`, `welcome`) are listed under the talk turn's acts, from the specs. The deliberation grammar lists every skill from the specs.

**The game client:**

- A skill whose spec reads `want` offers one choice per thing to ask for, from what the player carries and the skill's `items`: `offer`, and now `offer_terms`.
- What the rules tell the player (experiences of kind `record`) shows as a toast.

## How a floor adds its own rules

A floor's overlay is Rhai composed onto the base (`floors::compose`): replaced functions keep the base's as `base_NAME`. The same composition gives a floor its own social rules with no engine change:

```rhai
// A floor where debts outlive the day: agreements fall due after three days, not at dusk.
fn due_by_dark(a) { 72.0 }

// A floor with rent: whoever is hosted owes the host a fish, demanded at once.
fn on_host(a) {
    base_on_host(a) + [#{ op: "record", kind: "demand", status: "open",
        parties: #{ by: a.actor.id, of: a.target.id },
        terms: #{ item: "fish", qty: 1, done: 0, words: "rent for the night" }, due_h: 12.0 },
        #{ op: "tell", to: a.target.id, ask: true, text: "{actor} asks a fish for the night's lodging." }]
}

// A guild that keeps its members' grudges: a broken agreement turns their people's regard sour.
fn agreement_due(r) {
    let fx = base_agreement_due(r);
    // ... add or amend a `holder`/`toward` stance record between the parties' communities.
    fx
}
```

The `dealings` scene composes such an overlay to shorten the hours (below), the way a floor would.

## Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- | --- |
| A law that reads `a.records` (`offer_terms`, `accept`, `demand` checks and effects, the three hooks) | `record_party.party` for the actor and its community, `record.id` and `record_party.record` per row | — | btree `party`, PK, btree `record` | — | per act start and completion of those skills | — |
| A record effect | the record's parties | 1 `record`, 1–4 `record_party` rows; `record_clock` for a stance | PK, btree `record` | — | per dealing step | at most 12 open records per character; closed ones dropped after their keep |
| Tell / witness | the told character; witnesses in sight (`perceive::witnessed`) | `experience` rows | existing | the party (`my_experience`), minds | per dealing step | the existing experience window |
| Due records (housekeeping, 1 Hz) | `record.due_ms` range up to now, at most 64 | `on_expire` effects; deletes | btree `due_ms` | — | 1 Hz, empty most seconds | — |
| Relation filter, no personal relation | 2 `membership.member`, `record_clock` (1 row), the module's stance cache | — | unique `member`, PK | — | per selector candidate with a relation filter | the cache: one entry per stance |
| Stance cache rebuild | every `record_party` row with role `holder` and its record | — | full scan of `record_party` | — | when a stance record changes (rare: the seed's, or a rule changing regard) | — |
| `my_records` (player view) | my characters (`character.controller`), their and their community's `record_party` rows, each record | — | btree `controller`, `party`, PK | the player | when a read row changes | — |
| Mind service | `record`, `record_party` (whole tables, as owner) | — | — | the mind | per change | bounded as above |

No whole-World scan was added to a routine action. The two full scans are in rare paths: the stance cache rebuild, and the install-time technique rename.

[Views](https://spacetimedb.com/docs/functions/views/): `my_records` is a per-caller view built from index lookups only. A view re-runs when its read set changes; its read set is the player's own records and their parties. Adding the tables and the view to a live world is an automatic migration ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations): adding tables is always allowed). The docs pages read are labelled 2.0.0; the code was checked against the pinned 2.14.1 macros by building and publishing it.

## Costs

Measured on the Mac (Apple Silicon, Docker Desktop), on my own SpacetimeDB 2.14.1 container (`sao-rules2-stdb`), island seed modules of main `bbf7271` (base) and this branch (change), each window on a fresh world, 20 s settling, then 60 s profiled with `living/tools/bench.py`. Driver: a scratch `dealbench.py`, not committed; its load is described below. No subscribers. These runs do not establish performance acceptance at the 216-character gate or beyond.

**Fuel per call** (`just living-script-gate`, the bench module under SpacetimeDB's wasmtime config; deterministic):

| Law | main | this branch's code, main's script | this branch |
| --- | ---: | ---: | ---: |
| `rates` (the authority's call) | 7,024 | 7,159 | 7,183 |
| `rates-law` | 127,901 | 134,249 | 138,010 |
| strike (check + done) | 269,046 | 268,355 | 274,912 |
| `perceived_of` | 60,601 | 60,884 | 62,671 |
| `hook`: `on_give` over an agreement, a demand and a regard | — | — | 446,967 |

The new context fields cost up to 5% on the rates path, and the larger script 2–3% per call. Every law is within its budget. The hook is about 1.6 strikes. Its budget is 560,000 (`budgets.json`). It runs only after a give, store or host, never per tick. Most of its cost is turning each of the actor's records into a Rhai map; with no records it is a few thousand instructions.

**Install:** 8,905 calls over 212 functions, 540 ms in the island module on the Mac (`install.validate`). The heaviest are `teach_check` (635 operations), `on_store` (459) and `on_give` (454), against the 2,000 limit. The hook probes add the most calls: each body × each target × four items.

**At rest on the island** (277 people, 34 animals; 13 regard records): mean tick and p50/p99 in ms.

| | run | mean | p50 | p99 | max |
| --- | --- | ---: | ---: | ---: | ---: |
| base | 4 | 1.17 | 1.02 | 3.36 | 4.6 |
| base | 9 | 1.22 | 1.12 | 3.01 | 4.7 |
| change | 2 | 1.19 | 1.04 | 3.19 | 5.3 |
| change | 3 | 1.43 | 1.25 | 3.75 | 7.1 |
| change, a later pair (the Mac busier) | 5 | 2.46 | 2.39 | 4.84 | 13.2 |
| base, the same pair | 6 | 2.32 | 2.25 | 4.78 | 8.8 |

No difference beyond the run-to-run spread. In a minute at rest the hooks ran 17 times and record reads 38 times (0.02 ms/s). Base run 1 overlapped a scratch world's cleanup and is left out. Relation filters reading stances are included in these windows; no separate span was taken.

**With dealings in flight:**

- **The load:** 60 pairs of walkers (397 people), each handing the other a wood every ~4 s for the whole window: about 45 gives a second.
- **On the change arm:** each pair also holds an agreement (`offer_terms`, 900 wood wanted, so it stays open) and a demand. Every give runs `on_give` over the giver's two records (walkers belong to no community, so no regard is among them) and amends the agreement. That is 133 open records.
- **Arms:** alternated base, change, change, base.

| | run | mean tick | p50 | p95 | p99 | max | over 16.7 ms | hook span | record reads |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 3.55 | 3.09 | 7.79 | 9.86 | 13.1 | 0 | — | — |
| change | 2 | 4.38 | 3.85 | 9.54 | 11.63 | 14.9 | 0 | 4.4 ms/s, 2,679 calls | 1.1 ms/s, 5,396 |
| change | 3 | 4.06 | 3.57 | 8.74 | 10.60 | 13.8 | 0 | 4.5 ms/s, 2,495 calls | 1.1 ms/s, 5,024 |
| base | 4 | 3.96 | 3.65 | 8.15 | 10.23 | 14.2 | 0 | — | — |

- **The change:** +0.1 to +0.8 ms mean per tick, from a spread of 0.4 ms between the two base runs, so roughly +10%. About 5.5 ms/s of it is in the hook and record-read spans (about 95 µs per give in the module). The rest is the record writes (an amend per give) and the effects.
- **Mean, not ms/s:** the change arm logs more span lines, which cut the start of bench.py's log window (1,850–1,900 tick samples against 2,530–2,560), so the table compares means.
- **A stress case, not ordinary life.** Each walker delivers on its agreement every 4 seconds without end.
- **An earlier version** told the other side every partial delivery. It wrote about 50 more experiences a second than the base under this load and was dropped: a give is seen by its receiver anyway, and each side reads progress in its dealings. The table is the version without it.

**What grows:**

- at most 12 open records per character;
- closed records for 12 world hours (6 minutes at the island's day);
- seeded stances for the world's life;
- one `record_clock` row.

## Verification

On the Mac, my own SpacetimeDB 2.14.1 container (`sao-rules2-stdb`, `127.0.0.1:3342`), scratch `verify-*` databases only, code `eaee6b0` plus the driver fixes in this commit. Evidence: `.local/living/verify/` (git-ignored).

| Surface | What was driven | Result | Evidence |
| --- | --- | --- | --- |
| Project check | `set -o pipefail; just living-check` | exit 0; rules 120 passed, including `a_skill_added_only_in_the_script_is_everyones`, `agreements_and_demands_are_rules_on_records` and the records tests | — |
| Core | `scenes.py dealings` (island): agreements kept, broken, lapsed and not taken; demands met and unpaid; closed records dropped; regard records seeded and read by a relation filter | 16 of 16, twice (`8bc4f14` and the final code) | `core-rules2-deal1/`, `core-rules2-final-dealings/` |
| Core | `tick`, `needs`, `seize` (default seed), `skirmish` (island) | 6/6, 6/6, 6/6, 8/8 | `core-rules2-final/`, `core-rules2-final-dealings/` |
| Player | `deal.py`: proposes terms with the verbs' node, reads `my_records`, is told accepted, owed and kept; `record` and `record_party` private; a demand on the player told and unpaid when due (world rules, no overlay) | 13 of 13; the first attempt failed 1 on the driver (the outcome begins with a capital) | `player-rules2-deal2/`, `-deal1/` |
| Player | `new_skill.py`: `whittle` only in the script; no spec refused at install; done by a player (`human_act`), a graph leaf and a mind's act; the tree's script reinstalled | 6 of 6; the first attempt failed 1 on the driver (it assumed the player's wood) | `player-rules2-deal2/` |
| Client | `verify-client/scripts/run.py` on my own server | 30 PASS, exit 0. Three harness fixes made it run: any loopback server; the table inventory reads every authority file (`records.rs`); the floor's private tables and reducers (`floor_seed`, `genesis_timer`, `create_floor`, `genesis_step`), missing from its lists since floors merged | `client-rules2-4/` |
| Minds | `verify_minds.py --case dealings` (fake model) | pass: the demand is told, the deliberation shows it under "Your dealings", the model's give pays it, the demand is `met` and the demander told. Three driver fixes: the demander held still; the next thought requested when the cadence drops the ask; the fake rule matching the quoted reason | `minds-rules2-4-dealings/` (failed attempts `-1`–`-3` kept) |
| Minds | `acts`, `roundtrip`, `conversation` | pass | `minds-rules2-1-*/` |
| Fuel gate | `just living-script-gate`, with the new `hook` case | every law within budget (table above) | `target-gate/script-gate/` |

**Not covered:**

- the game client binary drawn and driven (its verbs tests run; no headless session);
- a woken resident proposing terms through a real model (the real run had none);
- `on_death` content (the shipped rules define none);
- `verify-knowledge` (unchanged: memory text keeps the word "mending" as history);
- `verify-generation`'s own driver for seeded records (the core scene checks they exist).

**Maintenance of the verification skills (a scoped pass):** the feature maps of `verify-core` (new `dealings.md`), `verify-player` (new `dealings.md`, `verbs.md`), `verify-minds` (new `dealings.md`), `verify-client` (`visibility.md`, `reconnect.md`, SKILL) and `verify-generation` (`seeded-world.md`) were updated, and `verify`'s surface table. The pass covered the features this change touches and drove each of them live (above). It did not re-read every other feature from source with subagents.

## The real run

**Question:** with agreements, demands and regard available (and the renamed know-how), does help reach the newcomer in the social preset?

**Setup:**

- **Batch:** `r2`, on the Spark's trial service, 2026-11-10 14:04–15:05.
- **Trial:** `life-social` (residents wake into minds when engaged; `LIVING_ONLY=<subject>,woken`), island world seeds 7, 11, 7 (the seeds where the newcomer arrives inside the walls), 60 minutes, glm-flash for the newcomer and the models file's `woken` route for residents.
- **Arms**, each 3 replicates, run in parallel:
  - control: main `bbf7271` (its module built for the same world seeds from its own seed, its rules, models and mind);
  - change: `rules-2` `8bc4f14` (module, rules, mind; same models).
- The change arm ran before the partial-delivery tells were dropped. No delivery happened in it, so this makes no difference.

| | control (main) | change (`rules-2`) |
| --- | --- | --- |
| Asks by the newcomer (food, a lesson, a bed) | 3.3 (0–6) | 2.3 (0–6) |
| Heard | 1.3 (0–4) | 0.3 (0–1) |
| Residents woken | 0.7 (0–1) | 1.0 (1–1) |
| Talk turns | 1.0 (0–3) | 0 |
| Gives, teaches, hosts toward the newcomer decided | 0 | 0 |
| Food, lodging, lessons received | 0 | 0 |
| Agreements or demands made (records other than regard) | — | 0 |
| Tokens per run | 1.22M (0.92–1.48M) | 1.74M (1.52–1.90M) |
| Cost per run | $0.20 | $0.30 |

**Did help arrive?** No, in either arm. The run cannot say whether agreements help: almost no encounter happened.

- The newcomers spoke mostly to no one in earshot ("If these walls won't talk, I'll leave something that can"). They fed themselves by gathering, and built.
- No resident heard more than one ask in the change arm, and no conversation turn ran.
- `i8` had 10–17 asks and 7–11 heard per run on the same preset. Both arms of `r2` share main `bbf7271`'s world (after `hunger-1`, residents make food rounds), so the drop is the world's, not this change's.

**What the change arm did show:**

- The newcomer's identity spoke of tending wounds, not mending things.
- Its prompts and the woken resident's carried their dealings: 20–22 prompts per engaged world, the resident's with its town's regard.
- The change arm made more deliberations (255 against 191 over three runs) with larger prompts (12.0k against 10.9k tokens).

**Spend:** $1.48 for the batch (control $0.61, change $0.87; 8.8M tokens), plus about $0.04 of replays: about $1.52.

**Evidence:**

- archived on the Mac under `.local/living/trials/rules2-r2/` (`trials/r2/` with `report.md`, `social_report.txt`, `r2_final.json`; `journal/`);
- the trial databases deleted; the replays' `rules2_replay_mending.json`;
- the Spark's checkouts removed. Its 6 replica directories were left for the next `trials.py reclaim`, which refused while another batch was live.

**Next, to test the question:** a preset where the newcomer meets people (arrival among residents at their work), or a scripted resident who answers asks. Then compare agreements made, kept and broken, and help received, over 3+ replicates.

## Files

- **Rules crate:** `living/rules/src/catalog.rs` (skill table, `RENAMED`), `records.rs` (new), `script.rs` (specs, hooks, effects, `record_text`), `script/context.rs` (new fields), `script/check.rs` (spec, hook and record-text probes), `normalize.rs`, `graph.rs`, `species.rs`.
- **Script:** `living/scripts/skills.rhai`: specs and descriptions; agreements, demands, regard, hooks, `record_text`.
- **Authority:**
  - new: `living/authority/src/records.rs` (tables, ops, expiry, seed, stances, `my_records`);
  - shared files, small edits: `act.rs` (context fields, record effects, post-skill hook, `on_death`), `brain.rs` (stance in `relation_ok`), `tick.rs` (one call in housekeeping), `lib.rs` (module, `rename_techniques`), `seed.rs` (`records`), `common.rs` (world skills, technique names), `combat.rs` (reach).
- **Bindings:** regenerated (`record`, `record_party`, `record_clock`, `my_records`).
- **Mind:** `living/mind/src/mind/dealings.rs` (new), `prompts.rs` (rules source, `record_text`, `talk_acts`, a dealings section), `mind.rs`, `mind/talk.rs`, `mind/lived.rs`, `main.rs` (subscriptions).
- **Client:** `living/game/src/verbs.rs`.
- **Seeds and tools:** `living/seeds/island.json`, `living/seeds/worlds/island/world.json`, `living/tools/author_world.py`, `living/trials/wolves*.json`, `living/trials/life.json`, `living/tools/script_bench/bench/src/fixtures.rs`.
