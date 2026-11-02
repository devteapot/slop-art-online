# Checkpoint 4: a world to live in

Direction from the user (2026-09-26, after watching realm-1 in the viewer), to build after [checkpoint 3](CHECKPOINT_3.md). Plan, not implementation evidence.

## What the user saw in realm-1

- People over-cluster in one place and mostly stand still, waiting for something to do; the map is not big enough to give them reasons to go anywhere. Measured: 22 of 32 people did not move over 20 s (night, so some were asleep).
- Some move back and forth between two neighbouring cells all day. Measured: 6 of 32 reversed direction 3–16 times in 20 s within 1–5 tiles. Cause: plans like "if not near A, go to A; otherwise go to the sign" flip as soon as the person steps away, and movement has no commitment, so each once-a-second check can reverse the previous one.
- Speech is almost all survival logistics; no social life is emerging.
- "Cities" were a bigger camp: shelters around a fire. A city should have roads, houses, maybe walls and a gate that someone opens and closes, so people inside are safe and people outside have to come together for what they need.
- The two towns never met: validation that people cluster and do nothing but survive. They think too much about surviving and too little about living.
- Combat reports should not be on a fixed 7 s timer but follow what happens in the fight.

Why survival dominates (diagnosis): hunger itself is modest (5 points a minute, about five berries or one and a half cooked meals per 12-minute day). What dominates is how often the body interrupts the mind: cold every night outside a fire, wolf fear reinforced by the seed text, body alarms and failed survival steps as most reasons to think, habits that only step in at the extremes, and nothing else in the world worth wanting.

## Decisions (user, 2026-09-26)

- **Population**: about 150 people on a 512×512 map (four times realm-1's area): 3–4 cities of 25–35, a few villages, several bands; wildlife scaled to the land. Model load stays bounded by the budget; minds think somewhat less often.
- **Survival**: a background concern in towns (about two meals a day; homes and walls keep people warm and safe); the wilds stay harsh, so leaving town is a real decision and bands still struggle.
- **Cities**: seeded fully built and growable. Established cities start laid out (walls, gate, roads, houses, workshops, fields outside); everyone can also build houses, roads, walls and gates, so bands and villages can grow toward that.

## Plan

1. **Commitment in movement.** A started movement continues for a short minimum (or until arrival) unless something urgent preempts it (threat, being hurt, a body habit), so plans stop flickering between two targets.
2. **Event-driven fight reports.** A report when something changes in the fight: the first exchange, health crossing 75/50/25%, a streak of blocks, dodges or misses on either side, the opponent changing what they do, a lull; with a minimum gap of a few seconds instead of a fixed timer.
3. **Living over surviving.**
   - Homes keep people warm at night; cities are safe from wolves (walls, wolves avoid lit, walled places); cold and wolves remain real in the wilds.
   - Habits handle eating and sleeping earlier and silently; body alarms only reach the mind when habits cannot cope.
   - What asks a mind to think shifts toward its own goals, relationships, conversations and events; prompts and seed text stop foregrounding danger.
4. **Real cities.**
   - Structures: house (a household's home, warm, with its own store), road (laid on a tile; faster walking), wall segment (blocks movement), gate (a person opens or closes it; the community decides who may; blocks movement when closed), workshop and market as places.
   - Walls and closed gates are obstacles for movement and pathfinding (a dynamic blocked-tile overlay on the static terrain, invalidated on build/open/close).
   - A city generator lays out established cities: wall ring with gates, a road grid, houses per household, a market square, workshops, stores; fields and pastures outside.
   - Building rules in the Rhai script, with know-how (masonry for walls, carpentry for houses and gates) so bands can grow toward cities.
5. **Reasons to move and trade.** Regional resources (stone and ore in the hills, fish and salt on the coast, clay by rivers, wood in forests, game on plains), crafted goods with uses (tools that speed work, clothing, pottery, preserved food), so towns want what others have and people travel.
6. **Social life as a mechanic.**
   - Conversations: when two people talk, a short multi-turn exchange between both minds (not one line per deliberation), grounded in their memories and relationship. First part built 2026-09-26 (reply turns, no silent repeat drop): see [living core: conversations](LIVING_CORE.md#conversations-checkpoint-4-item-6-first-part).
   - Shared activities with effects (a meal together, a story by the fire, work side by side) that feed relationships and mood.
7. **Scale.** 512×512 realm, about 150 people, benchmarked (2,000 characters and a 200-character battle on the larger map) before minds are added; LLM budget and pacing measured per character.

## Evidence to look for

People spread out and move with purpose (no flickering; idle time measured); cities with walls and gates where someone decides who comes in; trips between cities and first contact within the first days; trade of regional goods; conversations that are about people, not logistics; bands that build toward a village; fights whose reports follow the fight; benchmarks within the performance contract; bounded model load.

## Decided along the way (user, 2026-09-26)

- **No injected behavior.** A character's graph is all its body does; it starts as the species' instincts and belongs to the character. Mistakes get feedback (sensations, failures, fight reports, noticing it keeps turning back), not silent correction; fighting is learned by fighting (the rules text keeps only fighting physics). The movement "commitment" and sticky distance tests planned in item 1 were built and then removed in favor of feedback. See [living core](LIVING_CORE.md#robustness-layers-found-necessary-in-live-runs).
- **Models:** GPT-6 Luna and Mistral Small for people (Luna is also the default and the retry for unusable replies), Ministral and Mistral Small for animals; Mistral Medium dropped as too expensive; no call budget.

## Progress (2026-09-26)

Built: items 2, 4, 5 (first form), 6 (conversations; shared activities not yet), 7; item 3 as houses that keep households warm and walls that keep wolves out, with body habits removed rather than made silent.

- **Cities** ([city.rs](../living/rules/src/city.rs)): a wall ring with a gate on each side where land continues, main streets through the gates, an inner ring road, side streets every 6 tiles, a paved market square with the hearth, stores and the elders' sign, a house per household along the streets, planted fields outside. Villages are an open crossroads with houses. Walls and roads are terrain (one chunk row changes when someone builds); a gate's open/shut state and keeping community live in their own `gate` table, and a shut gate blocks movement and pathfinding. People can build houses, walls, gates, lay road (faster walking) and open or shut their community's gates.
- **Regional goods:** stone in the western hills, clay along rivers, wood in forests, fish on the coast; houses need wood, clay and stone, walls and roads need stone; axe and pick halve woodcutting and stone-breaking time; masonry, carpentry and toolmaking know-how, discoverable by experimenting.
- **Conversations:** being addressed gives the listener a reply turn, a small fast call on its own model with its identity, feelings about the speaker, shared memories and the conversation so far; exchanges run up to 8 turns. Repeating yourself is spoken and fed back to the speaker, not dropped. Since then (2026-09-26): pacing follows each person's sociability and mood, a turn can close an exchange with what was settled (written to the speaker's mind as an agreement), settled pairs stay quiet until the agreed time, news or a new matter, and every reasoning episode recalls what the situation cues rather than the most recent part of the mind; see [living core](LIVING_CORE.md#situational-recall).
- **Scale:** realm-2/realm-3 seed (512×512, four walled cities of 27, three villages, five bands; 149 people, 70 deer, 12 wolves): seeding under a second; 2,000 characters p99 5.3 ms, 200-fighter battle p99 5.7 ms, no tick over 16.7 ms.

**realm-2, first 30 minutes (then re-seeded as realm-3 with the city layout above):** 134 of 149 people moving at a sample, 1 flickering, three exploring 48–54 tiles from home, a first contact between a band and a village. Speech changed character: people teased each other, made plans to teach one another ("you can show me the spear while I teach you what I know of planting"), argued about how records should "honor the maker", hummed songs, arranged walks. Model load: about 320 calls/min and 1.44M tokens/min (conversation turns 127/min but only 142k tokens; consolidation 99/min; deliberation 94/min), 3 errors in 10 minutes. Houses had been packed around each market inside walls far too large for the town, so the layout was changed and the world re-seeded as realm-3.
