# Look: one appearance for players and minds (design, 2026-11-12)

Status: **design only, not built.** Read from main `42ca0b67`. Nothing here has been built, measured or run. The sizes are estimates from the row layouts.

**The gaps.**
- **The live game draws no generated people.** Every resident, and the player, is a VRoid base that `live::recipe_for` (`living/game/src/live.rs:466`) picks from the land seed and the id. `recipes.json` holds no person lines, so all the character work so far ([characters](CHARACTERS.md), compose-1) shows only in look-dev.
- **Minds see no colours or clothes.** A mind's scene (`perceive::scene_json`) describes a person by name or label, age, family, distance, what they are doing and their wounds. The player's client, meanwhile, names strangers by the colours it draws (`looks.rs`). The two controllers do not perceive the same thing ([strangers](STRANGERS.md), "Proposal: appearance as an authority fact", which this note replaces).

**In short.**
- Each person has one private `look` row on the authority, written at creation and on change.
- What an observer perceives of it travels in the existing per-viewer projection (`projected` → `seen_characters`), under the same `perceived_of` law and far label that already decide names and health.
- **When the observer can make someone out**, the projection carries an opaque key. The client draws the person line it finds under that key in a shipped book, and a mind gets that line's words.
- **When someone is too far away to make out**, both get only a silhouette and one dominant colour.

## 1. SpacetimeDB documentation check

Pinned: `spacetimedb = "=2.14.1"` and `spacetimedb-sdk = "=2.14.1"`; the server image is `v2.14.1`. All pages were read on 2026-11-12 with the version selector showing **2.0.0**. Where the design depends on a claim, it was checked against the 2.14.1 crates in the cargo registry, or against source evidence already recorded in [perception](PERCEPTION.md#spacetimedb-documentation-consulted-2026-11-09).

| Page | What it says | What follows here |
|---|---|---|
| [Tables](https://spacetimedb.com/docs/tables/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions/) | Private tables are "Visible only to reducers and the database owner". Public tables are "Exposed for client read access through subscriptions". "Views can read from private tables and expose only the data appropriate for each client". | `look` and `look_line` are private. Clients see a look only through `seen_characters`, never by subscribing to a table. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | B-trees take equality and ranges, and strings and `u64` can be keys. Indexes "consume additional memory and slow down inserts and updates". | Two indexes: `look.next_ms`, a range read of the rows that are due, and `look_line (person, band)`, a point lookup. Both tables are written only at creation and on change. |
| [Performance](https://spacetimedb.com/docs/tables/performance/) | "Make tables public only when clients need to access them". Private tables "Don't consume client bandwidth". "Keep tables focused". "Be mindful of unbounded table growth". | Appearance is rare-change data, so it gets its own table instead of columns on churning rows. It is bounded at one row per person, and the static line table is bounded by the world data. |
| [Views](https://spacetimedb.com/docs/functions/views/) | A per-sender view means "1,000 separate view computations" for 1,000 users. Views read only through indexed lookups. A view "must re-execute the entire view function" when a row in its read set changes. Views may declare a primary key, which gives `on_update`. | No new view. `seen_characters` keeps its read set (`projected.viewer`) and gains columns, and its refresh cadence does not change. A separate `seen_looks` view was considered and rejected (§2). |
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
| **A. A function of identity and stage** (dev-box's minimal shape): the line is f(person, stage). The authority projects only identity and stage, plus the minds' words. | The same book and the same deterministic lookup in every build. It also needs a person key it can evaluate. For a seeded resident that key is the name (`tilly-dunlin`), which is perception-scoped, or a character id mapped in the book. | Every client silently redraws everyone at the next book. The minds' words change only when the module is republished, so the two diverge without any record. | **Decisive.** Players' rows carry real ids (far-handle concerns minds only). A book keyed by id or name lets any client draw a far figure in full, so the far rule cannot be enforced for players. Keyed by name, it also puts a stranger's name on the wire. A clothes change cannot be expressed either. | Rejected as stated. Its parts are kept: lines per band from the generator, a seed-id pool for unseeded people, and no generator on the authority. |
| **B. A stored opaque key into a shipped book**, sent only when the observer makes the person out | The book, which must contain the world's keys | Rows keep their keys, and the book keeps every key a released world uses. A drawn look never drifts from the minds' words. Moving to a new generation is an explicit `relook`. | None, if the key is opaque (below) | **Chosen** (agreed by the general coordinator). |
| C. The line inline, about 1.4 KB a person | Nothing shipped | Cannot drift | None | Not chosen: about 40× the bytes of B on every perceived row. |
| D. A public `look` table subscribed whole | The book | As B | Births, deaths, the head count and every id's full look reach every client, and the far rule cannot apply per viewer | Rejected. |

**Where B's per-viewer part goes.**
- **The choice:** columns on `projected` and `SeenCharacter`.
- **The alternative weighed:** a separate per-sender `seen_looks` view. It would hold the same per-viewer rows in its materialization, it would re-run on `projected` changes anyway to learn each target's precision, and it adds a second view to each player's refresh.
- **Why columns:** the far↔near transition already rewrites the `projected` row, because its label changes there.
- **The cost:** about 34 B on every write of that row (§4).

### Opaque keys

- **Format.** A line key is `lk_` followed by 16 hex digits, a content hash of the line's canonical JSON. A person key (private, never sent) is `lp_` followed by 16 hex digits.
- **Why a hash.** It carries no name, and no cast order: sequential numbers in household order would let a client infer families. A book from another generation simply lacks the key, so a mismatch shows itself instead of drawing someone else under the same key. char-4 writes the book keyed this way. If char-4 keeps `cullet/0417`-style ids, the number must come from a seeded permutation, never from cast order.
- **What a key reveals.** Two people with identical lines share a key. They would also look identical, so nothing extra is told.
- **When a key is sent.** Only when the observer makes the person out. A far row carries no key: the client holds the whole book, so sending a key would send the full look.
- **What a client may remember.** A client may remember a key it saw earlier, and so may a modded client. That is remembered knowledge of a face, which is legitimate.

### Tables (authority; private)

```rust
#[table(accessor = look, index(accessor = due, btree(columns = [next_ms])))]
pub struct Look {            // one row per person (kind "person"); animals have none
    #[primary_key] pub id: u32,      // character id
    pub person: String,      // "lp_…": the person's entry, across bands (never sent)
    pub line: String,        // "lk_…": the line for the current band (sent when made out)
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
    pub top: String,         // "a kelp-green smock"
    pub bottom: String,      // "dark trousers"
    pub head: String,        // "a cap", "a kerchief", ""
    pub beard: String,       // "a white beard", "stubble", ""
    pub colour: String,      // dominant colour word of the largest worn garment: "green"
}
```

**`form` is appearance only.** The authority has no sex rule (`Character` has no such field), and no rule may read `form`.

### Columns appended (with defaults) to `projected`, and to `SeenCharacter` in the same order

| Field | Type | Made out | Far, by day | Far, at night | Not a person |
|---|---|---|---|---|---|
| `look` | `String` | `lk_…` | `""` | `""` | `""` |
| `look_band` | `u8` | band | band | band | 255 |
| `girth`, `height` | `u8` | from the words | from the words | 255 | 255 |
| `colour` | `String` | the dominant colour word | the dominant colour word | `"light"` or `"dark"` | `""` |

**Why the far colour is a word.** A far row carries the colour as a word, never a hex. Each person's cloth shade is drawn within its name's range, so an exact hex would nearly identify them. The client tints with the book's one swatch for each word.

**`folk` and `style`** stay as they are, for VRoid fallback and for giants and small folk.

## 3. One source, seen the same at every distance

**The law.** `Regard` (`living_rules::script`) gains `look: LookSeen` (`Full | Far | Shade | None`).
- The default needs no new input: `Full` when the observer is the person or the law does not mark them `far`, `Far` when it does, `Shade` when far at night. The night input is `RegardIn.night`; at night an observer's sight is already short.
- A world's `perceived_of` may return `look` to override this, for example a foggy world.
- No input is added, so the shared regard cache (`REGARDS`, keyed by `RegardIn`) keeps its handful of entries.
- `project()` adds one point lookup, `look.id().find(target)`.

| What the observer perceives | The player's client draws | A mind's scene says (`appearance`) |
|---|---|---|
| Made out (within Cullet's `known_within`, 24 m) | the person line under `look` | "a woman in a kelp-green smock and dark trousers, dark-haired, heavy-set, in a kerchief" |
| Too far away to make out, by day | a stand-in figure (below) in the swatch of `colour` | "a tall figure in green" (under the far handle, with no name and no community, as today) |
| Too far away to make out, at night | the stand-in, in light or dark | "a figure in dark clothes" |
| Not perceived | nothing | nothing |

**One phrase function.** Both sides build words with `living_rules::look::phrase(words, seen, band)`. The client calls it for labels and chips, in place of `looks::colour_name` on drawn colours. So a player and a mind are told the same words from the same row.

**Why one colour when far.** Cullet's cloth has about ten names. Several colours together, as in "green top, grey trousers, auburn hair", would nearly identify one of 64 people at any distance, and would defeat the far label for both controllers. One dominant colour does not.

**Which people a mind's scene describes.** This is set by a new law, `appearance_in_scene`, with three values:
- `"unnamed"` (proposed default): strangers and far figures. This is where it does work: it tells two strangers apart. In Cullet it costs about 10 tokens a scene, since only the newcomer is unnamed. On a world with several settlements it would be about 100–250 tokens with 10–20 unnamed people in sight.
- `"all"`: everyone in the scene. It costs at most about 200 tokens, with the scene's cap of 14 creatures.
- `"none"`.

The same unnamed people also get their words in the first-sight line: "For the first time you see a woman in a kelp-green smock, 9 tiles west". Memory names ("a stranger #77") and `label` are unchanged in this pass.

**Owner decisions** (feel, and something a mind sees by default):
1. **The far stand-in.** At 24 m a figure becomes its real self, with a fade. The client's far model already drops the face detail, but hair colour and the lower garments appear at that moment. The alternative is to draw the full line at any distance and tell minds the same, which weakens the far label for both.
2. **The `appearance_in_scene` default.**

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
| `look` | one per living person, ≤ 2,000; a dead person's row is deleted with their projections | about 180 B each, with its two indexes: **about 0.4 MB** |
| `look_line` | Cullet's 64 at up to 4 bands, plus the pool (e.g. 128 people × 5 bands): about 900 | about 150 B each: **about 130 KB**, static |
| `projected` / `seen_characters` | unchanged count: players × the people each perceives | **+34 B a row.** Examples: the 216 gate with 30 in sight each, about 220 KB; 2,000 players with 40 each, 2.7 MB; a 200-player battle, 1.4 MB |

### Traffic

- **No new subscription and no new view.**
- **At join:** about 34 B for each perceived person, about 1.4 KB for 40.
- **Look changes:** at most about 5 a life, each sent to the people who perceive that person. Even at a lab pace of one life per real day, that is about 5 row updates a second, world-wide.
- **The real extra is on rewrites that already happen:**
  - health-band updates, made-out transitions and knowledge epochs each carry 34 B more;
  - in a 200-character battle, with about 2,000 band-row updates a second (an estimate, not a measurement), that is about 68 KB/s across 200 clients, about 340 B/s each.
- **Commit log:** `projected` writes log 34 B more each, and `look` rows log only when they change.
- **Measure before acceptance:** the `tick.perception` span and `seen_characters` bytes, before and after, on the crowd case.

### Migration of existing worlds

- **Safe, automatic:** adding `look` and `look_line` (new tables); appending columns with defaults to `projected` (`look` "", `look_band` 255, `girth` 255, `height` 255, `colour` "") and to the public `world` row (`look_book: String`, default "", the book generation the world was made with).
- **Disconnects clients:** `SeenCharacter` is a view row type, not a column type. Changing it was accepted in place before, with clients disconnected until they had new bindings (`just living-generate`).
- **Existing rows:** a world from before this change has no `look` rows, so its people project `look` "" and draw as VRoid, as today, until an admin runs `relook` with its seed's looks. The paused reference worlds are not touched unless the owner asks.

## 5. The split of work and the interfaces

**Recommendation: dev-box builds the authority half**, as it offered. Cullet is its first user, char-4 already writes the lines, the pool and the lookup, and the Spark's queue is full (battle-scale and its acceptance runs, a possible fix 4, navigation, packs, the fast lane, r2e).
- **The one condition.** The change rewrites the hot `projected` row. dev-box runs verify-client, and compares the projection cost before and after (`tick.perception`).
- **The order.** dev-box lands first. The Spark's minds half reads `Projection.look` and `LookWords` from it.

**dev-box (char-4, the generator).**
- **The book** (client asset, git-ignored, `assets/characters/looks.json`):
  ```json
  { "generation": "c4-…", "lines": { "lk_…": { "person": { /* the line as compose-1 reads it */ }, "words": { /* LookWords */ } } },
    "far": { "<band>-<girth>-<height>": "lk_…" }, "swatches": { "green": "#5d7f4a", "light": "#d8d2bd", "dark": "#2a2a2e" },
    "pool": ["lp_…"], "decor": ["lp_…"], "people": { "lp_…": { "<band>": "lk_…" } } }
  ```
  - The book is append-only across generations while a released world uses a key.
  - `decor` is a pool kept apart from `pool`, for the island's background people, so an extra is never a real newcomer's twin.
- **World data** (in the seed, and in `create_floor`'s seed JSON): `looks: { generation, people: { lp: { band: lk } }, words: { lk: LookWords }, pool: [lp] }`, plus `look: "lp_…"` on each seeded resident.
- **Test vectors** for `look_band` and `pool_pick`.

**dev-box (the authority).**
- The `look` and `look_line` tables, the `projected` and `SeenCharacter` columns, and `world.look_book`.
- `Regard.look`, the `look_bands()` law, and the `living_rules::look` module (`look_band`, `pool_pick`, `next_change`, `phrase`).
- Writing looks at genesis, at a birth, at a join and in `grew`, plus the due read in `housekeeping`.
- `relook`, and the bindings.

**Spark (minds).**
- `perceive::scene_json` gains `appearance` from `phrase`, under `appearance_in_scene` and the far label: a far figure keeps its handle and gets the far phrase.
- The first-sight text, and the law's `about` text.
- verify-minds.

**Laptop (client).**
- **`live::recipe_for(book, land_seed, c)`:**
  - `c.look` found in the book: the composed line;
  - `c.look` empty for a person with a `look_band`: the far stand-in `book.far[band-girth-height]`, tinted with `swatches[colour]`;
  - a key missing from the book, or a file missing on disk: today's VRoid recipe in the `colour` swatch, with one warning line;
  - `world.look_book` not among the book's generations: one warning at connect.
- **Height from the line.** A composed line carries its own height, so `bodies.rs` `stage_scale` applies to VRoid fallback only.
- **The rest of the client's part:**
  - prewarm one composed person for each type and style under the loading cover;
  - chips by piece from the line's `colors.outfit`, and words from `phrase`;
  - the player's own look from its own row (`own`, always made out); `LIVING_GAME_PLAYER` stays look-dev only;
  - the background people from `book.decor` by their own seed.
- **What the client does not receive:** anyone's age within a band. A child keeps one line from 2 to 12 years, as `stage_scale` keeps one scale now.

## 6. Verification plan

| Skill | What is driven | Changes shape |
|---|---|---|
| verify-client | As a stranger's identity: SQL on `look` and `look_line` is refused; a far person's row has `look` "", a band, a colour word and no hex; a made-out row's key matches `^lk_[0-9a-f]{16}$` and equals no name slug; no row for anyone unperceived; the same rows after reconnect | yes: two private tables, `seen_characters` columns |
| verify-player | A joined player's own row carries a pool key that stays the same across reconnects; no player reducer sets a look | yes: `join` writes a look; the own row's look |
| verify-minds | A fake model; the scene's `appearance` for a made-out stranger, a far figure (its handle, the far phrase, no key) and a far figure at night; `appearance_in_scene` set to `none` and to `all`; the first-sight line | yes: a scene key, a law |
| verify-generation | Cullet's seed carries `looks`; genesis writes 64 `look` rows whose keys all resolve; `look_line` rows; a runtime floor seed; `pool_pick` and `look_band` against char-4's vectors (Cargo) | yes: the seed format |
| verify-core | At a lab pace a child crosses 12 and then 18: one rewrite each, through the due index; a stage change rewrites the look in the same transaction; no scan is added | yes: the `look_bands` law, the housekeeping due read |
| verify-ui | The live client draws composed people from keys; the far stand-in and its fade at made-out; the fallback and both warnings | yes: how characters are drawn |
| verify-knowledge | Not touched: memory names are unchanged | no |

Each surface's skill gets `maintain-verification-skill` in the change that alters it. None of these runs establishes cost at 2,000 characters; that claim needs the measurement in §4.
