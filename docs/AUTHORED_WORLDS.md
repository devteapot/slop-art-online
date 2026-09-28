# Authored worlds

Status: **implemented, not yet run in a lab** (2026-09-28). Unit tests cover seed parsing, ages, birth order, sheet resolution, model groups and recall of authored memories (against Neo4j). The seeding reducer path compiles but has not been executed against a published module.

A seeded town normally gets its people from occupation counts: generated names, a one-line background, and a model call that invents each identity ([LIVING_CORE.md](LIVING_CORE.md#worlds-of-any-size-towns-and-bands-checkpoint-3)). An authored world names its people instead. Each resident has a sheet (identity, relationships, memories, stances) that the mind installs as written, with no model call. From then on it is ordinary identity: consolidation, fading and revision treat it like anything else the character holds.

## Residents

A town or village in a seed (`towns[]`, `villages[]`, realm maps only) may list `residents`. If the list is non-empty, those people are the settlement's residents and `occupations` is ignored. Without residents, the occupation path runs exactly as before. Example: [`living/seeds/authored-test.json`](../living/seeds/authored-test.json).

```json
{"name": "Pim Hale", "age": 7, "household": "mill", "occupation": "child",
 "parents": ["Oren Hale", "Ilsa Hale"], "knows": [], "inventory": {"berries": 2},
 "sheet": { … }}
```

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | required | Unique across the seed. Every reference to a person uses it. |
| `age` | 30 | Years. Converted with `living_rules::life::days_of_years` at the seed's `year_days` and `life_pace`, so the life stage follows. Ages at or beyond the first deaths of old age are seeded just short of them, with a warning. |
| `household` | own name | Residents with the same key share a house. The layout gets one house per distinct household. |
| `occupation` | `forager` | Chooses the starting habits (`give_repertoire`) and, without `knows`, the know-how, the same way the occupation path does. Children and infants start with a child's habits regardless. |
| `knows` | occupation's + `fire` (adults) | Techniques learned from `seed`. |
| `parents` | none | Up to two names from anywhere in the seed. They are spawned before their children, so the child inherits their genes. A parent in a later settlement is linked afterwards, and the child's genes are then re-derived from both parents. |
| `inventory` | `{"berries": 4}` | What they carry. |
| `sheet` | none | The authored identity. Without a sheet (or without a sheet `narrative`), the mind writes an identity from the background as before. |

Sheet traits that are person temperament traits (`caution`, `sociability`, `empathy`, `curiosity`, `ambition`, `introspection`, `temper`, `nurture`) are written into the genome as `trait:<name>`, so the body and the persona agree. Traits the sheet leaves out keep their drawn or inherited values.

## Sheet

```json
{
  "narrative": "first person, 2-5 sentences (required)",
  "values": ["…"], "goals": ["…"], "mood": "…",
  "traits": {"caution": 72, "nurture": 70},
  "relations": [{"name": "Ilsa Hale", "trust": 90, "affinity": 85, "label": "wife", "note": "in their words"}],
  "memories": [{"gist": "a remembered event in their words", "salience": 0.9, "about": ["Teodor Vane"]}],
  "stances": [{"key": "debt_must_be_paid", "value": 0.9, "why": "…"}],
  "places": [{"name": "the lower field", "x": 30, "y": 40}],
  "secret": "private"
}
```

**Authority** (`living/authority/src/seed.rs`). After every settlement has its people, each sheet is copied into its person's `background` row as `sheet`. `relations[]` gain `"id"`, and each `memories[].about` becomes `[{"name", "id"}]`. Names that match no one are dropped and logged. Relations may name people in other settlements. `secret` is removed, because `background` is a public table. The other background fields are the same as on the occupation path: `origin`, `town`, `town_character`, `walled`, `occupation`, `household`, `home`, `town_center`, and `towns_known` when a realm has several settlements.

**Mind** (`sheet_persona` in `living/mind/src/mind.rs`). A person whose background carries a sheet with a narrative gets it in place of `background_persona` or `birth_persona`, both at bootstrap and on first deliberation (an authored infant receives it once it becomes a child). Installation:

- `person:<id>` nodes for the household, relations and the people in memories.
- Relations as `FEELS` edges, stances as `JUDGES` edges to `stance:` concepts, and places (home, town center, known towns, then the sheet's places) as `place:` concepts. All go through `memory::sugar_into`. The sheet's lists are not truncated the way a model reply's are.
- Memories as `:Memory` nodes with `INVOLVES` edges to the people in them. They carry no experience, so they are numbered from `memory::AUTHORED_MEMORY` (2^40) as `exp:<n>`, and recall, rehearsal and forgetting treat them like any kept memory. They come back through cue words in their gist or through the people involved. Prompts show them as `[before all this] …` without an experience id.
- Identity version 1 (`"who I was when this began"`), with the secret on `self` and on the version node. The persona projection uses the sheet (traits read back from the genome) and a `consolidate` thought, "Who I am (authored).", whose detail is the sheet without its secret.
- Without Neo4j, the persona, relations, judgments, places and thought are published directly (`mind_update`, not replacing).

The secret reaches only the character's own prompts (`Known only to you: …` in its persona text). It is read from the seed file the mind service runs (`LIVING_SEED`), never from a table.

## Model groups

`living/configs/models.json` may map groups to profiles:

```json
"groups": {"Millbrook": "mistral-small", "Reedmouth": "luna"}
```

A person's group is the `town` (towns and villages) or `band` in their background. For someone born in the world, it is the first group found through `parent_a`, then `parent_b`, up to 8 generations back (`llm::group_of`, cached per character). A group profile that has a key takes precedence over `stages.child` and rotation. An explicit `assign` by name still wins. Without a group, the previous order applies. Animals keep their `species` routing. Calls go through `Llm::chat` with that profile, so its `overflow` works as before. The chosen profile is logged when it is first chosen for a character and again if it changes.

## SpacetimeDB

No new tables, columns or reducers, so no migration ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/)). Seeding runs in `init`, which only runs when a database is first published or cleared ([lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle/)), so existing worlds are unaffected. Rows touched at seed time: `character`, `genome`, `vitals` (a late-linked child), `know_how`, `inventory`, `background`, `membership`, `community`, `structure`. Each person's sheet adds one-time size to their `background` row (about 1–3 KB for the test seed's sheets). Every observer subscribes to that table.

## Open points

- Authored memories and stances fade like any others. A salience-0.9 memory that is never recalled is forgotten after about 5 hours of wall time. Stances relax toward 0.5 unless reinforced: a 0.9 stance is no longer held after about 80 minutes. Whether an authored past should fade more slowly has not been decided.
- `thought` rows are public. A mind may still reveal its secret in its own reasoning or speech; that is the character's choice.
