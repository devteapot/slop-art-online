# Look: one appearance for players and minds (design, 2026-11-12)

Status: **design agreed 2026-11-12, with the [decisions](#decisions-2026-11-12) below; not built.** Read from main `42ca0b67`. Nothing here has been built, measured or run, and the sizes are estimates from the row layouts. dev-box builds the authority half first. The Spark's minds half starts after it lands.

**The gaps.**
- **The live game draws no generated people.** Every resident, and the player, is a VRoid base that `live::recipe_for` (`living/game/src/live.rs:466`) picks from the land seed and the id. `recipes.json` holds no person lines, so all the character work so far ([characters](CHARACTERS.md), compose-1) shows only in look-dev.
- **Minds see no colours or clothes.** A mind's scene (`perceive::scene_json`) describes a person by name or label, age, family, distance, what they are doing and their wounds. The player's client, meanwhile, names strangers by the colours it draws (`looks.rs`). The two controllers do not perceive the same thing ([strangers](STRANGERS.md), "Proposal: appearance as an authority fact", which this note replaces).

**In short.**
- Each person has one private `look` row on the authority, written at creation and on change.
- Anyone who sees the person gets an opaque key in the existing per-viewer projection (`projected` → `seen_characters`), at every distance at which they are seen.
- The client draws the person line it finds under that key in a shipped book.
- A mind gets the same look in words: in full once the person is made out, with fewer details beyond that, and never more than a player's screen shows.
- The far label stays about identity only.

## Decisions (2026-11-12)

The general coordinator decided these on 2026-11-12, after the first draft of this note.

1. **No far stand-in: the full look is drawn at every distance at which the person is seen.**
   - The owner has rejected pop-in twice ("people just pop in and out, which is weird").
   - At the game camera a face is about 12 pixels, so what anyone sees at a distance is clothes and build, and seeing them is real perception.
   - The far label is about identity only: no name, and no link from a handle to a name.
   - **Recognising by look is memory.** A player, or a mind that remembers the dress, may recognise a known neighbour by her blue dress at 40 m. That is memory, not a leak, and it is the same for both.
   - **The night rule ("light" or "dark") is dropped.** A player's screen at night shows colour within sight. The client keeps nights readable (`daylight.rs`: a moon key light from at least about 25°, the night fill, lamp lights brighter at night; the film's moonlit haze, `GAME_BRIEF.md`), and anyone perceived at night is within the night sight anyway: in Cullet 14 m, 20 m with a torch, and 28 m or 48 m in lamplight or carrying a light. If the client's night grading ever removes hue, the rule comes back with it.
2. **Scene descriptions are for unnamed people by default** (`appearance_in_scene = "unnamed"`). The value `"all"` is measured in the next paid stage.
3. **Who builds what:**
   - dev-box builds the whole authority half. That includes verify-client, the projection cost before and after, and the skills that change shape on its side.
   - The Spark keeps the minds' `appearance` key, the first-sight line and verify-minds.

## 1. SpacetimeDB documentation check

Pinned: `spacetimedb = "=2.14.1"` and `spacetimedb-sdk = "=2.14.1"`; the server image is `v2.14.1`. All pages were read on 2026-11-12 with the version selector showing **2.0.0**. Where the design depends on a claim, it was checked against the 2.14.1 crates in the cargo registry, or against source evidence already recorded in [perception](PERCEPTION.md#spacetimedb-documentation-consulted-2026-11-09).

| Page | What it says | What follows here |
|---|---|---|
| [Tables](https://spacetimedb.com/docs/tables/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions/) | Private tables are "Visible only to reducers and the database owner". Public tables are "Exposed for client read access through subscriptions". "Views can read from private tables and expose only the data appropriate for each client". | `look` and `look_line` are private. Clients see a look only through `seen_characters`, never by subscribing to a table. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | B-trees take equality and ranges, and strings and `u64` can be keys. Indexes "consume additional memory and slow down inserts and updates". | Two indexes: `look.next_ms`, a range read of the rows that are due, and `look_line (person, band)`, a point lookup. Both tables are written only at creation and on change. |
| [Performance](https://spacetimedb.com/docs/tables/performance/) | "Make tables public only when clients need to access them". Private tables "Don't consume client bandwidth". "Keep tables focused". "Be mindful of unbounded table growth". | Appearance is rare-change data, so it gets its own table instead of columns on churning rows. It is bounded at one row per person, and the static line table is bounded by the world data. |
| [Views](https://spacetimedb.com/docs/functions/views/) | A per-sender view means "1,000 separate view computations" for 1,000 users. Views read only through indexed lookups. A view "must re-execute the entire view function" when a row in its read set changes. Views may declare a primary key, which gives `on_update`. | No new view. `seen_characters` keeps its read set (`projected.viewer`) and gains one column, and its refresh cadence does not change. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | Group subscriptions by lifetime, subscribe before unsubscribing, and avoid overlapping queries. | No new subscription. The client already subscribes to `seen_characters` once per connection. |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/), [default values](https://spacetimedb.com/docs/tables/default-values/) | Adding tables and indexes is always allowed. A new column must go at the end with a default. Changing a column's type is forbidden. | New tables, plus columns appended with defaults to `projected` and `world` (§4). |

**Versioned-source evidence.**
- **Primary keys on views.** `#[view(primary_key = …)]` exists in `spacetimedb-bindings-macro-2.14.1/src/view.rs` (`ViewPrimaryKeyArg`), and `#[default(..)]` in its `table.rs`.
- **Point scans.** A `filter` on all of an index's columns is a point scan (`is_point_scan`, `spacetimedb-2.14.1/src/table.rs:1525`).
- **Carried over from earlier notes, not re-checked:**
  - a range scan is recorded as a full-table read;
  - view rows are ephemeral, and an identical re-insert sends nothing.

  Both are verified in the server source in [perception](PERCEPTION.md#spacetimedb-documentation-consulted-2026-11-09).
- **Changing a view's row type in place.** This rests on an earlier observation: changing a view's row type was accepted on a scratch world, with all clients disconnected and needing regenerated bindings ([perception](PERCEPTION.md#the-players-look-human_face), 2026-11-11). It has not been re-tested for this change.

**Assumption, not verified.** View cost with thousands of subscribers. The same limitation is recorded in [perception](PERCEPTION.md#spacetimedb-documentation-consulted-2026-11-09).

## 2. The projection: what is stored and what is sent

### Weighed

| Shape | What the client needs | Generator data changes on a live world | Leaks | Verdict |
|---|---|---|---|---|
| **A. A function of identity and stage** (dev-box's minimal shape): the line is f(person, stage). The authority projects only identity and stage, plus the minds' words. | The same book and the same deterministic lookup in every build. It also needs a person key it can evaluate. For a seeded resident that key is the name (`tilly-dunlin`), which is perception-scoped, or a character id mapped in the book. | Every client silently redraws everyone at the next book. The minds' words change only when the module is republished, so the two diverge without any record. | **Keyed by name,** a stranger's name goes on the wire. **Keyed by id,** the shipped book gives every client the look of every resident before they have been seen, and the list of resident ids, which is the head count. A clothes change cannot be expressed. | Rejected as stated. Its parts are kept: lines per band from the generator, a seed-id pool for unseeded people, and no generator on the authority. |
| **B. A stored opaque key into a shipped book,** sent to whoever sees the person | The book, which must contain the world's keys | Rows keep their keys, and the book keeps every key a released world uses. A drawn look never drifts from the minds' words. Moving to a new generation is an explicit `relook`. | None, if the key and the book are opaque (below) | **Chosen.** |
| C. The line inline, about 1.4 KB a person | Nothing shipped | Cannot drift | None | Not chosen: about 60× the bytes of B on every perceived row. |
| D. A public `look` table subscribed whole | The book | As B | Births, deaths, the head count and the look of everyone unseen reach every client | Rejected. |

**Where B's per-viewer part goes.**
- **The choice:** one column on `projected` and on `SeenCharacter`.
- **Why not a separate view:** a per-sender `seen_looks` view would hold the same per-viewer rows in its materialization, and would add a second view to each player's refresh.
- **The cost:** about 23 B on every write of the row (§4).
- **Distance does not change it:** the key is sent at every distance, so the column does not change when someone is made out or goes far.

### Opaque keys: no name, no id

- **The line key.** It is `lk_` followed by 16 hex digits, a hash of the line's canonical JSON. Only the fields the client draws go into the hash: `type`, `height`, `proportions`, `identity`, `colors`, `styles`, `belly` and `grey`.
  - **The name comes out.** The generator's line and `<name>.params.json` carry `name` (`tamsin-hollin`), so the name is stripped both from the hash input and from the book entry.
  - **The seed comes out too,** and so does any character id: they are not in the line.
  - **What the key can tell.** Two people with the same line share a key, and they would also look the same.
- **The person key.** It is `lp_` followed by 16 hex digits and links a person's lines across bands. It stays on the authority and in the world data, and is never sent or shipped.
- **The client book holds only lines.** It is keyed by `lk_` and contains no `people` map, no `pool` list and no names. So a client cannot tell from a key:
  - whether the person is a seeded resident or a newcomer;
  - which other lines are the same person at another age;
  - whom they are related to.

  The decor lines are a separate list, disjoint from every line a character can wear.
- **Hash order.** The keys carry no cast order. Sequential numbers in household order would let a client infer families. If char-4 keeps `cullet/0417`-style ids, the number must come from a seeded permutation.
- **What this protects.** It holds on the wire and in the shipped book. An authored world's seed (`cullet.json`) is author data, readable in the repository and not shipped to players.

### Tables (authority; private)

```rust
#[table(accessor = look, index(accessor = due, btree(columns = [next_ms])))]
pub struct Look {            // one row per person (kind "person"); animals have none
    #[primary_key] pub id: u32,      // character id
    pub person: String,      // "lp_…": the person's entry, across bands (never sent)
    pub line: String,        // "lk_…": the line for the current band (sent to whoever sees them)
    pub band: u8,            // LookBand: 0 infant, 1 child, 2 youth, 3 adult, 4 elder
    pub next_ms: u64,        // world ms at which the band next changes (u64::MAX for elders)
    pub words: LookWords,    // copied from look_line at write: what a glance can say
}

#[table(accessor = look_line, index(accessor = by_person_band, btree(columns = [person, band])))]
pub struct LookLine {        // static world data, written at genesis or at `relook`
    #[primary_key] pub key: String,  // "lk_…"
    pub person: String,      // "lp_…"
    pub band: u8,
    pub words: LookWords,
}

#[derive(SpacetimeType)]
pub struct LookWords {       // words the generator wrote for the line (one naming function, its own)
    pub form: String,        // "woman", "man", "girl", "boy", "baby", "old woman"
    pub girth: u8,           // 0 slight, 1 medium, 2 heavy-set
    pub height: u8,          // 0 short, 1 middling, 2 tall (for the band)
    pub hair: String,        // "dark-haired", "grey-haired", "bald", "" (covered)
    pub top: String,         // "a green smock"
    pub bottom: String,      // "dark trousers"
    pub head: String,        // "a cap", "a kerchief", ""
    pub beard: String,       // "a white beard", "stubble", ""
}
```

**`form` is appearance only.** The authority has no sex rule (`Character` has no such field), and no rule may read `form`.

**The new column.** `projected` and `SeenCharacter` gain `look: String`, appended with the default "". It holds the `lk_` key for any person the observer sees, and "" for animals and for a person with no look row. `folk` and `style` stay as they are, for VRoid fallback and for giants and small folk.

## 3. One source, and the words by distance

**The law.** `Regard` (`living_rules::script`) gains `look: LookSeen` (`Full | Far | None`).
- It decides only how much a mind is told: the key reaches the client whenever the person is seen.
- The default needs no new input: `Full` when the observer is the person or the law does not mark them `far`, `Far` when it does.
- A world's `perceived_of` may return `look` to override this.
- No input is added, so the shared regard cache (`REGARDS`, keyed by `RegardIn`) keeps its handful of entries.
- `project()` adds one point lookup, `look.id().find(target)`.

| What the observer perceives | The player's client draws | A mind's scene says (`appearance`) |
|---|---|---|
| Made out (within Cullet's `known_within`, 24 m) | the person line under `look` | "a woman in a green smock and dark trousers, dark-haired, heavy-set, in a kerchief" |
| Seen but too far away to make out | the same line (the client's far model beyond about 10 m, as for any person) | "a tall figure in a green smock and dark trousers, in a kerchief", under the far handle, with no name and no community, as today |
| Not perceived | nothing | nothing |

**The far phrase** leaves out what is face-scale on a player's screen at that range: the form's sex, the beard and stubble, and the hair. It keeps:
- the silhouette, "figure", "child" or "old figure" by band;
- height and girth;
- the garments and the headwear.

That is fewer details than the screen shows, and never more.

**One phrase function.** Both sides build the words with `living_rules::look::phrase(words, seen, band)`. The client calls it for labels and chips, in place of `looks::colour_name` on drawn colours. The book carries each line's `LookWords`, so a player and a mind are told the same words.

**Which people a mind's scene describes.** This is set by the law `appearance_in_scene`, with three values:
- `"unnamed"` (**default**, decision 2): strangers and far figures. In Cullet it costs about 10–15 tokens a scene, since only the newcomer is unnamed. On a world with several settlements it would be about 100–250 tokens with 10–20 unnamed people in sight.
- `"all"`: everyone in the scene. It costs at most about 200 tokens, with the scene's cap of 14 creatures, and is measured in the next paid stage.
- `"none"`.

The same people get their phrase in the first-sight line: "For the first time you see a woman in a green smock, 9 tiles west". Memory names ("a stranger #77") and `label` are unchanged in this pass.

## 4. Writes, growth and migration

### Look bands (agreed)

- **The bands:**
  - infant = stage 0;
  - child = stage 1 and under 12;
  - youth = 12 to under 18, at either stage;
  - adult = stage 2 and 18 or over;
  - elder = stage 3.
- **The function.** `living_rules::look::look_band(stage, age_years, &LookBands) -> LookBand` is pure, and the authority and the client share it. The thresholds come from a world law, `look_bands()` (`#{ youth: 12.0, adult: 18.0 }`). Age is `Life::years_old`, the same years the scene states.
- **How the stages line up.** The person life table (`species.json`: 70 years; infant 0.03, child 0.23, elder 0.85) puts stage 1 at about 2.1 to 16.1 years and stage 3 at about 59.5. So youth covers stage 1 from 12 to 16.1 and stage 2 from 16.1 to 18, and elder starts with stage 3. That is close to char-4's 60+ types.
- **Infants** draw child types with infant proportions for now. The generator writes an infant line for each child type.
- **How a band change is noticed without scanning everyone.**
  - **The candidate checked.** Life stages are decided in `housekeeping` (`tick.rs:349`, scheduled each second by `slow_timer`, `lib.rs:97`). It iterates every character (`character().iter()`, `tick.rs:394`) and calls `grew` when the stage changes (`tick.rs:424`, `:258`).
  - **Why the band check does not ride it.** It could, at no extra read, but that whole-table scan is a prototype constraint, not a pattern to extend.
  - **The `next_ms` index.** Each `look` row stores `next_ms`: the world time of its next band change, whether an age threshold or a stage boundary. It is computed from `born_ms`, `birth_age_days`, the pace and the life table.
  - **The read.** `housekeeping` reads `look.due().filter(..=now)`, an index range over only the due rows. It rewrites those rows: their line comes from `look_line.by_person_band`, and their words and `next_ms` are set again.
  - **`grew` also rewrites the look**, so a stage change and the band change land in one transaction.
  - **A changed life law or `year_days`** (rare and explicit) recomputes every row's `next_ms` once.
  - **At most four band changes in a life.**
- **On a look change** (a band change, or a later clothes change), the rows of the people who perceive that person are re-projected through the `projected.body` index, as `health_moved` does for health bands.

### Who writes a `look` row

| When | Line source |
|---|---|
| Genesis (`init`, `create_floor`) | a seeded resident's `look: "lp_…"` from the seed |
| A birth (`birth`), and a join (`join`, a newcomer or a player) | `look::pool_pick(world_seed, id, pool_len)` over the world's pool, which holds person entries with a line for every band, so a pool person keeps their look as they grow |
| A band change | the same person entry, at the new band |
| `relook(generation)`, admin only, recorded in the chronicle | the new world data, for moving a live world to new lines |

A clothes change is not modelled. When it is, it is one more writer.

### Sizes at 2,000 characters (estimates)

| | Rows | Bytes |
|---|---|---|
| `look` | one per living person, ≤ 2,000; a dead person's row is deleted with their projections | about 170 B each, with its two indexes: **about 0.35 MB** |
| `look_line` | Cullet's 64 at up to 4 bands, plus the pool (e.g. 128 people × 5 bands): about 900 | about 140 B each: **about 125 KB**, static |
| `projected` / `seen_characters` | unchanged count: players × the people each perceives | **+23 B a row** (the key and its length). Examples: the 216 gate with 30 in sight each, about 150 KB; 2,000 players with 40 each, 1.8 MB; a 200-player battle, 0.9 MB |

### Traffic

- **No new subscription and no new view.**
- **At join:** about 23 B for each perceived person, about 0.9 KB for 40.
- **Look changes:** at most about 5 a life, each sent to the people who perceive that person. Even at a lab pace of one life per real day, that is about 5 row updates a second, world-wide.
- **The real extra is on rewrites that already happen:**
  - health-band updates and knowledge epochs each carry 23 B more;
  - in a 200-character battle, with about 2,000 band-row updates a second (an estimate, not a measurement), that is about 46 KB/s across 200 clients, about 230 B/s each.
- **Commit log:** `projected` writes log 23 B more each, and `look` rows log only when they change.
- **Measure before acceptance:** the `tick.perception` span and `seen_characters` bytes, before and after, on the crowd case. dev-box does this.

### Migration of existing worlds

- **Safe, automatic:** adding `look` and `look_line` (new tables); appending `look` with the default "" to `projected`; appending `look_book: String` with the default "" to the public `world` row (the book generation the world was made with).
- **Disconnects clients:** `SeenCharacter` is a view row type, not a column type. Changing it was accepted in place before, with clients disconnected until they had new bindings (`just living-generate`).
- **Existing rows:** a world from before this change has no `look` rows, so its people project `look` "" and draw as VRoid, as today, until an admin runs `relook` with its seed's looks. The paused reference worlds are not touched unless the owner asks.

## 5. The split of work and the interfaces

**The order.** dev-box lands the authority half first. The general coordinator then starts the Spark's minds half, which reads `Projection.look` and `LookWords`.

**dev-box (char-4, the generator).**
- **The client book** (client asset, git-ignored, `assets/characters/looks.json`):
  ```json
  { "generation": "c4-…", "lines": { "lk_…": { "person": { /* the line as compose-1 reads it, without "name" */ }, "words": { /* LookWords */ } } },
    "decor": ["lk_…"] }
  ```
  - The book is append-only across generations while a released world uses a key, and it lists the generations it contains.
  - Its `decor` lines are kept apart from every line a character can wear, for the island's background people.
- **World data** (in the seed, and in `create_floor`'s seed JSON; never shipped to clients): `looks: { generation, people: { lp: { band: lk } }, words: { lk: LookWords }, pool: [lp] }`, plus `look: "lp_…"` on each seeded resident.
- **Test vectors** for `look_band` and `pool_pick`, and the key hash against the canonical line.

**dev-box (the authority, the whole half).**
- The `look` and `look_line` tables, the `projected` and `SeenCharacter` `look` column, and `world.look_book`.
- `Regard.look`, the `look_bands()` and `appearance_in_scene` laws, and the `living_rules::look` module (`look_band`, `pool_pick`, `next_change`, `phrase`).
- Writing looks at genesis, at a birth, at a join and in `grew`, plus the due read in `housekeeping`.
- `relook`, and the bindings.
- verify-client, the projection cost before and after, and the skills on its side that change shape: verify-client, verify-player, verify-generation and verify-core.

**Spark (minds).**
- `perceive::scene_json` gains `appearance` from `phrase`, under `appearance_in_scene` and the far label: a far figure keeps its handle and gets the far phrase.
- The first-sight text, and the law's `about` text.
- verify-minds.

**Laptop (client).**
- **`live::recipe_for(book, land_seed, c)`:**
  - `c.look` found in the book: the composed line;
  - `c.look` empty, a key missing from the book, or a file missing on disk: today's VRoid recipe, with one warning line;
  - `world.look_book` not among the book's generations: one warning at connect.
- **No stand-in.** The client respawns a person with a fade only when their `look` changes: a band change, or `relook`.
- **Height from the line.** A composed line carries its own height, so `bodies.rs` `stage_scale` applies to VRoid fallback only.
- **The rest of the client's part:**
  - prewarm one composed person for each type and style under the loading cover;
  - chips by piece from the line's `colors.outfit`, and words from `phrase`;
  - the player's own look from its own row (`own`); `LIVING_GAME_PLAYER` stays look-dev only;
  - the background people from `book.decor` by their own seed;
  - verify-ui.
- **What the client does not receive:** anyone's age within a band. A child keeps one line from 2 to 12 years, as `stage_scale` keeps one scale now.

## 6. Verification plan

| Skill | Who | What is driven | Changes shape |
|---|---|---|---|
| verify-client | dev-box | As a stranger's identity: SQL on `look` and `look_line` is refused. A seen person's row carries a key, near or far. The key matches `^lk_[0-9a-f]{16}$` and equals the hash of its line's drawn fields. No book entry carries a name. No row for anyone unperceived. The same rows after reconnect. | yes: two private tables, the `seen_characters` column |
| verify-player | dev-box | A joined player's own row carries a pool key that stays the same across reconnects; no player reducer sets a look | yes: `join` writes a look; the own row's look |
| verify-generation | dev-box | Cullet's seed carries `looks`; genesis writes 64 `look` rows whose keys all resolve; `look_line` rows; a runtime floor seed; `pool_pick`, `look_band` and the key hash against char-4's vectors (Cargo) | yes: the seed format |
| verify-core | dev-box | At a lab pace a child crosses 12 and then 18: one rewrite each, through the due index; a stage change rewrites the look in the same transaction; no scan is added | yes: the `look_bands` law, the housekeeping due read |
| verify-minds | Spark | A fake model; the scene's `appearance` for a made-out stranger and for a far figure (its handle, the far phrase without sex, hair or beard); `appearance_in_scene` set to `unnamed`, `all` and `none`; the first-sight line | yes: a scene key, a law |
| verify-ui | laptop | The live client draws composed people from keys at every distance, with no swap at 24 m; the fallback and both warnings | yes: how characters are drawn |
| verify-knowledge | — | Not touched: memory names are unchanged | no |

Each surface's skill gets `maintain-verification-skill` in the change that alters it. None of these runs establishes cost at 2,000 characters; that claim needs the measurement in §4.
