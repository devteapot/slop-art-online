# Look: one appearance for players and minds (design, 2026-11-12)

Status: **design agreed 2026-11-12, with the [decisions](#decisions-2026-11-12) below. The authority half is built on branch `look-1-auth` ([§7](#7-the-authority-half-as-built-look-1-auth-2026-11-12)); the minds' and the client's halves are not.** §1–§6 are the design as agreed; Read from main `42ca0b67`. Nothing here has been built, measured or run, and the sizes are estimates from the row layouts. dev-box builds the authority half first. The Spark's minds half starts after it lands.

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

## 7. The authority half as built (`look-1-auth`, 2026-11-12)

Built on dev-box from main `e704ec0d` (char-4's look data merged). This is the authority half only: the Spark's `appearance` in scenes and the laptop's drawing are not built.

### SpacetimeDB documentation, checked again for the build

The pages of §1 were read again on 2026-11-12 (version selector 2.0.0; all loaded), against the pinned `spacetimedb = "=2.14.1"`, SDK 2.14.1 and the `v2.14.1` server image:
- [Indexes](https://spacetimedb.com/docs/tables/indexes/): "For multi-column indexes, pass a tuple of values"; String and integer keys; ranges on a B-tree (`filter(18..=65)`). `look_line.by_person_band().filter((person, band))` compiles against 2.14.1 as a point lookup on both columns, and `look.due().filter(..=now)` as a range on the one `u64` column.
- [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/): adding tables and indexes is safe; a column may be added "to the end of a table with a default value" (listed as potentially breaking: clients need new bindings); changing a column's type, or adding a unique or primary-key constraint to an existing table, is forbidden. Both new tables are new, so their keys are free; `projected.look` and `world.look_book` are appended last with `#[default("")]`.
- [Default values](https://spacetimedb.com/docs/tables/default-values/): `#[default("")]` on a `String` is the page's own example; it cannot be combined with a primary key, `unique` or `auto_inc`.
- [Auto-increment](https://spacetimedb.com/docs/tables/auto-increment/): ids come from a sequence allocated in batches, with gaps after a restart. `look_line.id` is only a row id; nothing reads meaning into it.
- [Views](https://spacetimedb.com/docs/functions/views/): a view is re-evaluated when something in its read set changes, separately for each subscriber, and reads only through indexed lookups. `seen_characters` keeps its read set (`projected.viewer`); a look change writes only the `projected` rows of the person's observers (`projected.body`), so only their views re-run.
- [Tables](https://spacetimedb.com/docs/tables/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions/), [performance](https://spacetimedb.com/docs/tables/performance/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): as §1. Private tables "can only be accessed by reducers and views"; no table or subscription is added for clients.
- Not re-tested: changing a view's row type in place on a world with clients connected (§1). The migration of an older world was tried on a scratch database (below).

### What was built

- **Rules (`living_rules::look`, pure, unit-tested):** `LookBand` (0 infant … 4 elder), `LookBands` (the `look_bands()` law, default 12 and 18), `look_band(stage, age_years, &LookBands)`, `band_at(&Life, age_years, &LookBands)`, `next_change(&Life, age_years, &LookBands) -> Option<f32>` (the age in years of the next band change, `None` for an elder), `splitmix64`, `pool_pick(world_seed, id, pool_len) -> Option<usize>` (`splitmix64(world_seed ^ id × 0xD1B5_4A32_D192_ED03) mod pool_len`), `LookSeen` (`Full | Far | None`), `LookWords` (§2's fields, serde, unknown fields refused), `phrase(&LookWords, LookSeen, LookBand)`, `AppearanceInScene` (`Unnamed | All | None`), `is_line_key`, `is_person_key`.
- **Script:** `Regard.look: LookSeen` (re-exported as `living_rules::script::LookSeen`): `Far` when the law marks the target `far` (never for oneself), else `Full`; a `perceived_of` law may return `look: "full" | "far" | "none"`, anything else is refused at install. `Scripts::look_bands()` and `appearance_in_scene()` read the two laws, checked at install. `skills.rhai` ships `look_bands()` (`#{ youth: 12.0, adult: 18.0 }`) and `appearance_in_scene()` (`"unnamed"`), each with a `_law()` whose `topic` is "", so the minds' world text is unchanged until the Spark writes their words. Cullet's overlay overrides neither.
- **Tables** (private): `look` and `look_line` as §2, `LookWords` as §2; `projected.look` and `SeenCharacter.look` appended with "", `world.look_book` appended with "".
- **Writes:** genesis writes `look_line` and `world.look_book` before people are made (`seed::populate`, so `init`, `create_floor` and the staged people step); `seed::spawn_with` gives every person a pool look (births, joins, newcomers, crowds), and an authored resident is then given its own entry; `grew` rewrites the look in the stage change's transaction; housekeeping's `look::due` reads `look.due().filter(..=now)` after the second's stage changes; `install_source` retimes every row once (`retime_all`); `perception::gone` deletes the row at death; `relook(generation)` (admin, chronicled).
- **Projection:** `project()` adds one point lookup, `look.id().find(target)`, for a person; the key goes on every perceived person row, made out or far (decision 1). A look change rewrites the observers' rows through `projected.body` (`look::reproject`). `perception::appearance(ctx, observer, target, now)` gives a mind's words through `phrase` and the regard's `look`; nothing calls it yet (the Spark's scene).
- **Seed tools:** `author_world.py cullet --compile-only` writes each resident's `look` and the seed's `looks` from `worlds/cullet/looks.json`; `cullet_plan.py` keeps them when it rewrites the rest. `plan-test.json` carries a small fixture (`fixture-1`).

### Where this departs from §1–§6

1. **`look_line`'s key.** §2 makes `key` the primary key. Two people with the same line share its key (§2, "What the key can tell"), so a primary key on `key` would refuse the second person's row. The row has an `auto_inc` `id` as its primary key, `key` is an ordinary column, and lookups go through `by_person_band` only.
2. **Where the pool lives.** §4 says a birth or join picks "over the world's pool" without naming a store. The pool is read from the world's seed (`seed::active()`: the compiled seed, or a floor's `floor_seed`), parsed once per instance, and used only while the seed's `looks.generation` equals `world.look_book`. No table is added for it.
3. **`relook(generation)`'s data.** It reads the module's (or floor's) seed: the generation given must be the seed's, else it is refused. Residents are matched by name among minded characters (a player of the same name keeps a pool look); everyone else gets a pool look. It is one pass over the living people and is rare and explicit.
4. **A resident without `look`** in a seed with looks wears a pool entry rather than being refused.
5. **Two people may draw the same pool entry** and look alike; nothing keeps picks apart.
6. **Bands at odd ages.** §4 does not say what a grown person (stage 2) under `youth` years or a child (stage 1) at or past `adult` years is: both are youths.
7. **`next_change` in years.** It returns the age in years, not world ms; the authority turns it into `next_ms` (a millisecond past the threshold, and at least a second ahead, so one read a hair early looks again a second later).
8. **Retiming** happens at every script install, which covers a changed life law (`year_days` is fixed at genesis).
9. **The `appearance_in_scene` law** ships with placeholder words and no topic, for the Spark to write; `appearance()` is provided but not called.

The general coordinator's brief for this branch asked for `look_band`, `girth`, `height` and `colour` columns on the rows; main's §2 drops them (no stand-in, no night rule), and the coordinator confirmed main's version. They are not built.

### Rows written, how often, and what grows

| Path | Rows read | Rows written | How often |
|---|---|---|---|
| Genesis | the seed | `look_line`: one per (person entry, band) in the data (Cullet 791, plan-test 27); `world` once; `look`: one per person (authored residents twice: the pool pick, then their own) | once |
| Birth, join, newcomer | `world`, the seed (parsed once per instance), `look_line` (point) | one `look` insert | per person made |
| Band change | `look.due` range (only the due rows), `character`, `look_line` (point), `projected.body` | the `look` row; each observer's `projected` row (+ the views of those observers) | at most 4 a life |
| Script install | every `look` row | rows whose band or time moved | per install (admin) |
| `relook` | every living person, `look_line` | `look_line` rewritten, one `look` per person, a chronicle line | admin only |
| Death | – | the `look` row deleted | per death |
| Projection | `look.id` (point) per projected person | – | per projection write, as before |

Growth: `look` is bounded by the living people (deleted at death); `look_line` is static world data (Cullet about 791 rows); `projected` gains 4 B per row plus the key (24 B for an `lk_` key, 4 B for ""). The pool's parsed copy lives in module memory (Cullet's seed is about 1 MB of text; parsed once).

### Verification and cost

**Projection cost before and after** (dev-box, 2026-11-12, `living/tools/look_cost.py`; evidence in the worktree's `.local/look1/cost/`, git-ignored). Each run publishes one module fresh on the worker's own `v2.14.1` server, joins **216 real players** over their own WebSocket connections (`gate-load players`, the gate's client query set), places them in **7 clusters of 31 within 3 m** of lot doors at least 40 m apart, and lets them walk small circles (a new direction every 1.5 s, the gate's walkers: people come into and go out of each other's sight at the edges). After a 30 s warm-up, it profiles a **120 s window**: the module's `Timing span` lines (ms of span per second) and the server's `spacetime_num_bytes_sent_to_clients_total` for the database. At the end, 24 sampled players each read their own `seen_characters`, and their BSATN size is computed. "Before" is main `acfe1be4`'s module on the same seed text without looks (plan-test) or main's Cullet seed; "after" is this branch with plan-test's fixture and with Cullet's char-4 data. No minds, no game client, no observer. The host is shared with other workers: its load average was 9–45 on 32 cores during the runs (recorded per run).

| World (in sight at placement) | Build | `tick.perception` ms/s | `tick` ms/s | perception per tick p50 / p99 ms | bytes sent/s (Update) | `seen_characters` per player: rows, BSATN B | of which `look` |
|---|---|---|---|---|---|---|---|
| plan-test (27) | main | 37.0, 35.4 | 87.8, 82.4 | 0.035 / 8.4, 0.031 / 8.0 | 608 k, 582 k | 14.8, 846; 13.5, 772 | 0 |
| plan-test (27) | look-1-auth | 34.7, 41.7 | 80.1, 91.0 | 0.030 / 7.8, 0.040 / 11.0 | 621 k, 599 k | 14.3, 1,146; 12.8, 1,026 | 23.0 B a row |
| Cullet (43) | main | 347.5, 296.8 | 411.6, 363.5 | 0.035 / 81.7, 0.033 / 64.8 | 1,474 k, 1,532 k | 43.8, 2,809; 46.6, 3,003 | 0 |
| Cullet (43) | look-1-auth | 341.2, 441.1 | 403.0, 495.3 | 0.032 / 81.0, 0.040 / 143.9 | 1,503 k, 1,411 k | 43.8, 3,787; 44.8, 3,901 | 23.0 B a row |

What this shows:
- **The bytes per row are exact:** every perceived person row is 23 B larger (the 4-byte length and the 19-character key; an animal's or an old world's row 4 B). A plan-test row grows from about 57 to 80 B and a Cullet row from about 64 to 87 B. For the 216 gate with 30 in sight that is about 150 KB held across all clients, as §4 estimated.
- **The Update stream** to clients moved by less than its run-to-run spread (plan-test +2.5% between the means, Cullet −3%): most of what a client receives is bodies and frames, not `seen_characters`.
- **`tick.perception` shows no difference this host can resolve.** The two runs of one build differ by up to 17% (Cullet main: 297 and 347 ms/s). Plan-test's means are 36.2 and 38.2 ms/s; Cullet's are 322 and 391, and the high branch run (441) ended with the host's load at 45. The branch adds one point lookup (`look.id().find`) to each projection. Cullet re-projects every row at every sweep, because its `perceived_of` reads the distance (`Scripts::regard_reads_dist`, `perception::sweep_one`), so that is about 216 × 44 × 5 ≈ 48,000 lookups a second. Acceptance should repeat this on a quiet host.
- **Not from this change:** Cullet's sweep costs 300–440 ms of every second at 216 players, ten times plan-test's. Its distance-reading law re-projects every row at every sweep, which is the next perception cost to look at.

**Migration** (a scratch `verify-lookmig-*` world made by main's module on plan-test, then this branch published over it with its data kept): the update is accepted, the old world has no `look` rows, no lines and `look_book` "". `relook("fixture-2")` is refused ("carries looks of generation `fixture-1`"); `relook("fixture-1")` writes 27 lines and the 5 residents' looks and chronicles it.

### The update panic, traced (2026-11-12)

**What was seen.** Publishing this branch over a ticking world made by main's module logged one `PANIC: tick ... datastore_index_scan_point_bsatn: No such index (error 5)` right after "Database updated" (3 of 3 updates; none from main to main). The ticks went on at 60 Hz after it.

**Documentation** (read 2026-11-12, selector 2.0.0): [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) lists adding tables and indexes as always allowed and says "Clients may witness brief interruptions in scheduled reducers (such as game loops)". It says nothing of the order of the schema change against scheduled reducers. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) are silent on updates. [Reducers](https://spacetimedb.com/docs/functions/reducers/): "Global and Static Variables Are Undefined Behavior … Publishing a new module creates a fresh execution environment". No page mentions index ids or "No such index". The server source at `v2.14.1` (`host_controller.rs`, `module_host_actor.rs`): an update builds a new module host and applies the schema steps in one transaction (`update_database`), then swaps the new host in. Appending a column with an incompatible row layout drops the table and creates it again with a new table id and new index ids (`mut_tx.rs`, "ADDING TABLE COLUMN (incompatible layout)").

**Mechanism, shown on the worker's server** (`.local/look1/panic/`):
1. The server log of the update: `ADDING TABLE COLUMN (incompatible layout): projected`, the same for `world`, then `Creating table look`, `Creating table look_line`, "Database update complete", "Database updated". `st_index` before and after: `world_id_idx_btree` 4268 → 4319, `world` table 4192 → 4220.
2. The backtrace: `tick::tick` → `common::world` → `spacetimedb::table::datastore_index_scan_point_bsatn`, the point lookup `world.id().find(0)`.
3. **It is the old module.** Main's module, built with a panic hook that names itself, logged "EXPERIMENT panic in the OLD module (main)" on that panic, 20 ms after "Database updated". The new module's own first tick (a fresh instance) resolved `world_id_idx_btree` to 4319 and ran normally. The bindings keep each table's and index's id in a `static OnceLock` resolved once per instance (`spacetimedb-bindings-macro-2.14.1/src/table.rs`, `index_id()`). So the outgoing host's instance fires one more scheduled `tick` after the update commits, with the id of an index the update dropped. It traps, its transaction rolls back, and the new host carries on.
4. Ruled out: the new module's `init` on the planning database (an `init` that returned at once there changed nothing); `look.due()` (the panic is in `world`, and in main's code); a stale schedule (the timers are the same rows before and after).

**What it costs.** One scheduled call of the old module, rolled back, after an update that rewrites a table that call reads first (`world`, read by every tick and by housekeeping). Nothing is written, no row is lost, the clocks are kept, and the new module ticks from its first call (`updates.json`: ticks, `world`, characters, timers before and after each step). It cannot be fixed in the new module, and pausing does not avoid it: the old tick reads `world` before it checks `paused`. Nor can the clocks be stopped before an update, because SQL DML is refused (HTTP 400) and main's module has no reducer for it.

**The fix, for every update after the guard is in place.** `common::schema_moved(reducer)`, called first in every scheduled reducer (`tick`, `housekeeping`, `genesis_step`): it fingerprints the database's table list (`st_table`, about 150 short rows, scanned through the host's uncached calls) at the instance's first scheduled call. On a later call whose fingerprint differs, the module has been replaced under this instance. The call then returns at once, touching no table, and logs once "the database's tables changed under this module instance (a module update was published); this call does nothing, and the new module carries on". The new module's instances take the fingerprint afresh. Cost: about 11 µs a call (6,000 calls in 65–81 ms), so about 0.7 ms a second at 60 ticks and one housekeeping.

**Shown** (`.agents/skills/verify-core/scripts/updates.py --run core-updates-1112-164613 --relook fixture-1`; record `verify-core/references/validation/`):

| Chain (each step published over the last with its data kept) | Updates | Panics | Guard lines |
|---|---|---|---|
| main → look-1-auth | 1 | **1–2** (main's `tick`, and its `housekeeping` when its once-a-second call falls in the window) | 0 |
| main → main + guard → look-1-auth, three times | 6 | **0** | 1 each, on the step to look-1-auth |
| main + guard → look-1-auth → look-1-auth + a column on `world` | 2 | **0** | 1 each |
| look-1-auth → look-1-auth + a column on `world` | 1 | **0** | 1 |

After every step the world ticked, kept its `world` row, its 9 characters and both timers. The chains ran twice: `core-updates-1112-164613` on look-1-auth `53aa7d02` and main `9d62be70`, and `core-updates-1112-170308` on look-1-auth `68f585e8` (main merged) and main `7a2633b1`, with the same counts (the second unguarded control panicked in `tick` and `housekeeping`). After each chain, `relook("fixture-1")` gave the 5 residents their looks with no panic.

**The safe update path.** The guard must be in the module being *replaced*. A world running main's module today will log the one harmless panic when it is updated straight to look-1-auth. To have none:
1. Update it first to main plus the guard alone (commit "update guard", three files, no schema change). That update rewrites no table, so main's module never trips.
2. Then update it to look-1-auth.

Every update after that is guarded. The paused reference worlds follow the same path whenever the owner updates them; nothing here touched them.

**Verification** (dev-box, own server `look1-stdb`; records in each skill's `references/validation/2026-11-12-1454-look-1-auth.md`):
- **Rules:** `look::tests::` (bands, `next_change` walking a life through every band, `pool_pick` vectors and spread, `phrase` near and far, keys and words), `script::tests::look_laws_are_read_and_checked`, the `look` of `perceived_of` in `what_one_perceives_of_another_is_the_law_s` and Cullet's `names_only_within_knowing_distance`, and `cullet_check::tests::{composed_worlds_keep_the_shipped_look_bands, cullet_s_band_cases_hold}`. The last runs char-4's 11 band cases through Cullet's composed life law.
- **verify-client:** the fixed suite passes 43/43 (scoped) and 43 + the known XFAIL (open). `look_rows.py` passes 15/15 on plan-test and 14/14 on Cullet. It checks that `look` and `look_line` are refused to a stranger, an `lk_` key on every seen person row equal to `look.line` and to no name slug, the far row's key with no name, no hex anywhere, an animal's "", no row for the unseen, and the same keys after a reconnect.
- **verify-player:** `look.py` passes 8/8 on plan-test and on Cullet: a pool pick (recomputed in Python), stable across reconnects, unchanged by every player reducer.
- **verify-generation:** Cullet 344/344 (its 791 lines, 64 looks, char-4's 3 key-hash and 11 band cases), the runtime floor 99/99, plan-test 95/95.
- **verify-core:** `look_bands.py` passes 9/9: a child crosses 12 and 18 (one due rewrite each), an adult's elder change comes from `grew`, a death deletes the row, and no per-second scan is added.

### The interface for the Spark and the laptop

- **`seen_characters` (`SeenCharacter`)** gains one last field, `look: String`: the `lk_` key (`lk_` + 16 lowercase hex digits) of the line the person wears now, for anyone the viewer sees at any distance, its own character included; "" for animals and for a person without a look row (a world from before looks, or a seed without `looks`). It changes only when the person's band changes (about 4 times a life) or at `relook`, and the client respawns the person then. Regenerate bindings with `just living-generate`; the game client compiles unchanged (it reads fields by name).
- **`world.look_book: String`** (public, last field): the generation the world wears ("" without looks); Cullet `c4-aa393793`.
- **`living_rules::look`** (pure; any build of `living-rules`, no `scripting` feature needed): `LookBand { Infant, Child, Youth, Adult, Elder }` with `code()`, `from_code(u8)`, `name()`, `parse(&str)`; `LookBands { youth: f32, adult: f32 }` (`Default` 12, 18); `look_band(stage: u8, age_years: f32, &LookBands) -> LookBand`; `band_at(&Life, age_years, &LookBands) -> LookBand`; `next_change(&Life, age_years, &LookBands) -> Option<f32>`; `stage_code(Stage) -> u8`; `splitmix64(u64) -> u64`; `pool_pick(world_seed: u64, id: u32, pool_len: usize) -> Option<usize>`; `LookSeen { Full, Far, None }` (`Default` `Full`); `LookWords { form, girth: u8, height: u8, hair, top, bottom, head, beard }` (serde; `girth` and `height` default 1; unknown fields refused); `phrase(&LookWords, LookSeen, LookBand) -> String`; `AppearanceInScene { Unnamed, All, None }` with `parse` and `name`; `is_line_key(&str)`, `is_person_key(&str)`.
- **`living_rules::script`:** `Regard.look: LookSeen` (`pub use crate::look::LookSeen`); `Scripts::look_bands() -> LookBands`, `Scripts::appearance_in_scene() -> AppearanceInScene` (and `_law()` forms returning what is wrong).
- **Authority, for the Spark's scene:** `perception::Projection.look` (the key), `perception::appearance(ctx, observer, target, now) -> String` (the phrase as the regard grants it), and the `look` row's `words` and `band` (point lookup `look.id()`).
- **Laws:** `look_bands()` returns `#{ youth: 12.0, adult: 18.0 }`; `appearance_in_scene()` returns `"unnamed"`, `"all"` or `"none"`. Both `_law()` texts are placeholders with no topic, so the world text is unchanged. A world's `perceived_of` may return `look: "full" | "far" | "none"`.

## 8. The client half as built (`look-1-client`, 2026-11-12)

Built on the laptop on look-1-auth (`e15557cd`) and main. The book is char-4's (`living/game/assets/characters/looks.json`, git-ignored; bundle `f81d8a47`, generation `c4-aa393793`, 887 lines, 96 of them decor).

### What was built

- **The book** (`characters/book.rs`): `generation`, `generations` (a book without it holds its own generation only), `lines` (`person`, `words`) and `decor`; read once on first use; `LIVING_GAME_LOOK_BOOK=<path>` reads a test's copy. A key's line is composed on its type at the line's own height, its files checked on disk once a key.
- **The row** (`characters/seen.rs`): `SeenCharacter.look` and `world.look_book`, read in one place.
- **`live::recipe_for(book, land_seed, c)`:** the line under `c.look`; else (no key, a key the book lacks, a file not on disk, no book, `LIVING_GAME_COMPOSE=0`) the VRoid recipe from the land seed and the id, as before looks, `stage_scale` applied to it alone. In a world with looks each such case is one warning line a session; a world made before looks (`look_book` "") falls back quietly with one line at connect; a generation the book does not hold is one warning at connect. My own character comes from my own row; `LIVING_GAME_PLAYER` is look-dev only.
- **A new key** (a band change, a `relook`) redraws the person where and as they are (`live::swap_look`): a new body with the old one's transform and motion; the old drawn and moving with it until the new is fitted (`Live::swaps`; `drawn()` gives the old meanwhile), then the two cross-fade. On real keys the redraw takes one dump of 0.2 s or less, and the person is never off the screen.
- **Labels** (`looks.rs`): someone drawn from a line is named by `living_rules::look::phrase` over the line's words, the words a mind is told: made out, "a woman in a black smock with an apron and dark trousers, grey-haired"; too far to make out, the Log keeps the projection's far words and plates and hover say "a tall figure in a yellow coat and dark trousers, heavy-set". The band is the line's type's (a child type for an infant: the far phrase says "child" for both). A VRoid base keeps its colour words.
- **Chips by piece:** the outermost upper and lower pieces' own colours, the pieces' places from each outfit style file's scene extras `outfit: {piece, slot, layer, trim}` (`upper` and `lower` give a chip, the higher layer worn over the lower; `feet`, `head` and trim pieces none), else their names with the same values.
- **Background people** on an offline or look-dev island take a grown decor line by their own seed (`living_rules::look::pool_pick(seed, 0, n)`), one recipe for their preload and their spawn (`island::person_recipe`).
- **The prewarm** (`loading.rs`): under the loading cover, the fewest lines that wear every type and style file of the looks perceived when the cover is up (connected: `seen_characters`, waiting up to 5 s for the rows; offline and look-dev: the decor). A first version covered the whole book: 64 people whose 101 files stayed resident for the session (`characters::kept`), +345 MiB resident and +470 MiB footprint, steady, on Cullet; the perceived looks need 17 people and cost what no prewarm does.
- **The asset view** shows a line: `LIVING_GAME_VIEW=look:<lk_…>`.

### Memory (bundle `f81d8a47`; Cullet, the play camera; `live_crowd.py`, uncapped, two runs an arm; worlds fresh from each module)

| | main (VRoid) | look-1, prewarm of the looks in sight | look-1, whole-book prewarm (the first version) | look-1, no prewarm |
|---|---|---|---|---|
| Resident, steady (peak) | 846 (849) MiB | 983 (994) MiB | 1,328 (1,430) MiB | 958 (968) MiB |
| Physical footprint, steady (peak) | 1,671 (1,700) MiB | 1,947 (2,037) MiB | 2,416 (2,470) MiB | 1,927 (1,977) MiB |
| Graphics (IOAccelerator), steady | 96 MiB | 99 MiB | 97 MiB | 100 MiB |
| Textures on the GPU (`batches:`) | 260 MiB (147) | 402 MiB (206) | 526 MiB (276) | 400 MiB (204) |
| Main-world meshes (morph targets) | 176 (88) MiB | 207 (96) MiB | 231 (101) MiB | 205 (96) MiB |
| Pictures kept on the CPU | 28.9 MiB | 28.9 MiB | 28.9 MiB | 28.9 MiB |
| glTF files (the two runs) | 26, 26 | 98, 83 | 192, 192 | 94, 90 |

- Composed residents cost about 140 MiB resident and 280 MiB footprint over VRoid bases, most of it the shared types' and styles' pictures on the GPU. Their pictures keep no CPU copy (`thumb_pictures`, as crowd-1's).
- **What grows with a crowd:** every type and style file anyone in sight wears stays loaded for the session. The whole-book prewarm is what a view showing nearly every file costs: about 480 MiB resident over VRoid. Two changes would bound it, neither small: free a file's assets when no one wears it (count `kept`'s users), and drop composed meshes' main-world copies once their summaries (recolour means, bounds, outline directions) are kept.

### Cost before and after (bundle `26d705b5`; `live_crowd.py`, uncapped, three runs an arm)

Before: main `9fa0d254`'s client on a fresh world of main's module (VRoid residents); after: this branch's on a fresh world of its own, each pair launched back to back and measured at once. Load average 7.3 to 11.7. The verify-ui record `2026-11-12-1825-look-1-client.md` has the full table.

| Cullet | main (VRoid) | look-1 (composed) | look-1, no prewarm |
|---|---|---|---|
| Play camera: frame p50 / p99 | 6.31 / 7.13 ms | 5.21 / 6.11 ms | 4.97 / 5.77 ms |
| Materials, mesh-material pairs on people | 33, 35 | 6, 37 | 5, 37 |
| Resident, steady; footprint, steady | 837; 1,654 MiB | 938; 1,904 MiB | 905; 1,832 MiB |
| GPU textures | 260 MiB | 402 MiB | 388 MiB |
| First-sight hitches walking (longest) | 6 (350 ms) | 6 (261 ms) | 6 (196 ms) |
| Full model: frame p50 / p99; resident steady | 6.19 / 7.03 ms; 834 MiB | 5.85 / 6.79 ms; 897 MiB | – |

- Composed residents draw faster than VRoid bases (1.1 ms at the game camera, 0.3 ms on the full model) and hold about 100 MiB more resident memory, 250 MiB more footprint: the shared pictures on the GPU.
- **The prewarm does not reduce the first-sight hitches** here: six while walking in every arm, the longest 200 to 350 ms in all of them, main's too (the walk's own arrivals, not composed people). It costs about 33 MiB resident. It is kept for now; whether to drop it is open.
- Brackenford's people have no looks (the island seed carries none): VRoid both ways, equal within noise.
