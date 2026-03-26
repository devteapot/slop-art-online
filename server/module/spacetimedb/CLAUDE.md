# SpacetimeDB Game Module — NPC Architecture

This is the implementation reference for the NPC AI system. For design rationale and decision-making, see `docs/adr/005-npc-architecture-v2.md`.

## NPC Identity Model

Every NPC (including mobs) has six identity components. Mobs start with minimal identity and may evolve.

### Personality (`NpcPersonality` table)

Structured traits that define who the NPC is at rest. Evolves slowly through LLM-evaluated significant experiences.

| Trait | Range | Derives | Example |
|---|---|---|---|
| aggression | 0.0–1.0 | anger_baseline | Bandit: 0.8, Monk: 0.1 |
| sociability | 0.0–1.0 | joy_baseline | Merchant: 0.8, Hermit: 0.2 |
| curiosity | 0.0–1.0 | exploration frequency | Scholar: 0.9, Guard: 0.3 |
| courage | 0.0–1.0 | fear_baseline (inverted) | Warrior: 0.9, Coward: 0.2 |
| empathy | 0.0–1.0 | relationship delta magnitude | Healer: 0.9, Bandit: 0.2 |
| discipline | 0.0–1.0 | emotion decay speed | Monk: 0.9, Berserker: 0.1 |

**Personality shapes tree structure at generation time.** An aggressive NPC gets trees with attack-first branches. A cautious NPC gets observe-first branches. You don't need runtime personality checks for most things — the personality is baked into the tree.

### Beliefs (`NpcBelief` table)

Subjective assessments. Can be wrong. Spread through NPC-to-NPC gossip.

```
NpcBelief {
    npc_id: u64,
    subject: String,      // "player:abc", "market", "npc:5", "self"
    predicate: String,    // "is_dangerous", "location_is", "sells_potions"
    object: String,       // "true", "50,0,80", "health_potions"
    confidence: f32,      // 0.0-1.0
    source: String,       // "experience", "told_by:npc:5", "overheard:player:abc"
    updated_at: u64,
}
```

### Knowledge (`NpcKnowledge` table)

Learned world mechanics and facts. **This is the most important table for NPC capability growth.** Knowledge determines what the LLM can generate in behavior trees.

```
NpcKnowledge {
    npc_id: u64,
    category: String,      // "combat", "trading", "crafting", "navigation", "social", "world"
    fact: String,           // "health potions restore 50 HP, cost ~10g at market"
    learned_from: String,   // "experience", "told_by:npc:5", "told_by:player:abc", "observed"
    confidence: f32,        // 0.0-1.0 (inherited from engagement level when learned)
    created_at: u64,
}
```

**How knowledge expands action space — example progression:**

1. **No knowledge** — NPC is hurt, has never encountered healing:
   ```
   Sequence [HealthBelow(0.5), Rest]    // sit and regen slowly, only option
   ```

2. **Vague knowledge** — overheard "potions heal you" (confidence 0.2):
   ```
   Sequence [HealthBelow(0.5), SearchFor("healing")]
   // Wanders looking for anything healing-related
   // If it finds a potion → executes runtime AddKnowledge → learns item_def_id + location
   ```

3. **Concrete knowledge** — has used a potion, knows item_def 12, knows Market Square (POI 3) sells them:
   ```
   Sequence [
     HealthBelow(0.5),
     TravelToEntity(Poi, 3),
     BuyItem { from_npc_id: 5, item_def_id: 12, max_price: 15 },
     UseItem { item_def_id: 12 }
   ]
   ```

When `SearchFor("healing")` executes at runtime, the tick logic checks nearby ground items, NPC shops, POIs. If the NPC discovers a potion:
```rust
// In execute_bt_action for SearchFor
if found_item {
    add_knowledge(ctx, npc.id, "items",
        &format!("item_def:{} is a healing potion, available near POI:{}", item.item_def_id, nearest_poi.id),
        "experience");
}
```
Next tree regeneration, the LLM sees this knowledge and generates concrete references.

### Goals (`NpcGoal` table)

Long-term desires with priority levels and success conditions.
- Priority: `Survival | Duty | Ambition | Social | Leisure`
- Success conditions: JSON (`{"type":"gold_above","amount":100}`, `{"type":"reach","x":50,"z":80}`, `{"type":"level_above","level":5}`)
- Max 10 per NPC (`MAX_NPC_GOALS`)

### Relations (`NpcRelationship` table)

Disposition toward specific entities.
- `target_type`: "player" or "npc"
- `disposition`: -100 (hostile) to +100 (trusted)
- `context`: reason/history string

### Emotions (`NpcEmotion` table)

Runtime state: anger, fear, joy, sadness, surprise, disgust. All 0.0–1.0.

#### Event Triggers (deterministic rules applied in tick reducer)

| Event | anger | fear | joy | sadness | surprise | disgust |
|---|---|---|---|---|---|---|
| Took damage | +0.3 | +0.2 | | | | |
| Won fight | | -0.2 | +0.3 | | | |
| Was insulted | +0.4 | | | +0.1 | | |
| Was betrayed | +0.5 | | | +0.3 | | +0.4 |
| Received gift | | | +0.2 | | | |
| Near-death | | +0.5 | | | +0.2 | |
| Goal achieved | | | +0.4 | | | |
| Ally died nearby | +0.2 | | | +0.5 | | |
| Witnessed wonder | | | +0.2 | | +0.3 | |

#### Decay Math (applied every tick before tree evaluation)

```
for each emotion:
    baseline = derive_baseline(personality, emotion_type)
    emotion.value = lerp(emotion.value, baseline, decay_rate)

// Where:
anger_baseline     = personality.aggression
fear_baseline      = 1.0 - personality.courage
joy_baseline       = personality.sociability
sadness_baseline   = 0.0  // (or could derive from empathy inversely)
surprise_baseline  = 0.0
disgust_baseline   = 0.0

// Decay rate derives from discipline:
// High discipline (0.9) → decay_rate ~0.15 (fast return to baseline, stoic)
// Low discipline (0.1)  → decay_rate ~0.02 (emotions linger, volatile)
decay_rate = 0.02 + personality.discipline * 0.13
```

#### Same Event, Different NPC Responses

Being insulted (anger +0.4):

| NPC | Key traits | anger after | What tree does |
|---|---|---|---|
| Warrior | aggression 0.8, courage 0.9 | 0.8 → 0.9+ | `EmotionAbove("anger", 0.7)` fires → attacks |
| Monk | discipline 0.9, aggression 0.1 | 0.1 → 0.3 | Decays to ~0.15 in 3 ticks, ignores |
| Merchant | courage 0.3, sociability 0.8 | fear 0.5 | `EmotionAbove("fear", 0.4)` fires → retreats |

**Emotions also provide visual feedback** — the client reads `NpcEmotion` and shows body language: angry NPC stomps, sad NPC looks down, joyful NPC waves. No LLM needed.

## Unified Behavior Tree

One tree per NPC. No mode switching. No separate combat/life trees. No NpcPlan.

### Target Data Model

```rust
pub struct NpcBehavior {
    pub npc_id: u64,           // primary key
    pub current_tree: String,  // JSON: Behavior<NpcBtAction>
}
```

Replaces the current `{ mode, combat_tree, life_tree }` + `NpcPlan { steps, current_step }`.

### Priority Layers

```
Select [
  // REACTIVE (always checked first — interrupts anything)
  Sequence [IsBeingAttacked, CombatResponse]
  Sequence [BeingAddressedInConversation, ConversationProtocol]

  // AWARENESS (perceive without acting — emotions gate the response)
  Sequence [
    EnemyDetected,
    NOT(IsBeingAttacked),
    EvaluateStrength,
    Select [
      Sequence [GoalRequires("eliminate", target), EmotionBelow("fear", 0.6), Attack]
      Sequence [StrengthAdvantage(0.5), EmotionAbove("anger", 0.4), Intimidate]
      Sequence [SetBelief("spotted_threat"), KeepDistance(12.0)]
    ]
  ]

  // DAILY LIFE (goal pursuit, routine tasks)
  Sequence [GoalActive("trade"), TravelToEntity(Poi, 3), TradeProtocol]
  Sequence [HasKnowledge("navigation"), TravelToEntity(Poi, 5), Explore]

  // FALLBACK
  Wander
]
```

**The tree doesn't literally rearrange** — but its evaluation path changes every tick based on runtime state (emotions, beliefs, knowledge, world). Same structure, dynamic behavior.

### Tree Regeneration Triggers

| Trigger | Type | Detection |
|---|---|---|
| Dawn | Scheduled | Night→day transition |
| Post-reflection | Scheduled | Identity shift > threshold after experience eval |
| Tree exhaustion | Event | N consecutive ticks producing no action |
| Goal completed/failed | Event | `check_goal_conditions()` detects resolution |
| Major knowledge gain | Event | First knowledge entry in a new category |
| Near-death survival | Event | Post-combat health < 10% max |
| `RequestNewTree` | Self-request | BT action node placed by LLM |

### Knowledge-Gated Entity References

**Vague actions** (no knowledge required — NPC explores/discovers):

| Action | What it does |
|---|---|
| `SearchFor(category)` | Wander looking for items/entities matching category |
| `ExploreArea` | Unguided exploration |
| `Investigate(direction)` | Move toward a stimulus |

**Concrete actions** (knowledge required — validated against `NpcKnowledge`):

| Action | What it does |
|---|---|
| `TravelToEntity { entity_type, entity_id }` | Go to a known entity by ID |
| `BuyItem { from_npc_id, item_def_id, max_price }` | Buy from a specific NPC |
| `SellItem { to_npc_id, item_def_id, min_price }` | Sell to a specific NPC |
| `UseItem { item_def_id }` | Use a known item |
| `AttackEntity { entity_type, entity_id }` | Attack a specific entity |
| `SayToEntity { entity_type, entity_id, message }` | Speak to a specific entity |

**Validation:** Checked at tree submission (entity exists?) and at execution (still exists?). Stale refs return `Failure`, tree falls through to next `Select` branch.

### BT Conditions (all runtime, no LLM)

**World state:**
- `EnemyDetected`, `IsBeingAttacked`, `EnemyInRange`
- `HealthBelow(f32)`, `ManaAbove(f32)`, `StaminaAbove(f32)`
- `IsNightTime`, `IsDayTime`
- `AtPoi(String)`, `PlayerNearby`, `NpcNearby`, `NpcNearbyWithRole(String)`
- `GoldAbove(i32)`, `GoldBelow(i32)`, `HasItem(item_def_id)`

**Emotion gates:**
- `EmotionAbove(emotion, threshold)` — e.g., `EmotionAbove("anger", 0.7)`
- `EmotionBelow(emotion, threshold)`
- `EmotionDominant(emotion)` — this is the strongest current emotion

**Identity:**
- `HasKnowledge(category)` — NPC knows something in this domain
- `GoalActive(description)` — NPC has an active goal matching this
- `RelationshipAbove(target, threshold)` — disposition > threshold
- `StrengthAdvantage(threshold)` — level/health/equipment comparison

### BT Actions (side effects)

**Movement:** `TravelToEntity`, `Chase`, `Flee`, `Wander`, `GoHome`, `KeepDistance(f32)`, `Follow(distance)`

**Combat:** `Attack`, `AttackEntity { entity_type, entity_id }`

**Social:** `Say(String)`, `SayToEntity { ... }`, `SayTemplate(template_id)`, `SayFromKnowledge(topic)`, `SayFromBelief(topic)`

**Identity (inline, no LLM cost):** `SetBelief { subject, predicate, object }`, `AddKnowledge { category, fact }`, `AdjustRelationship { target, delta }`, `TriggerEmotion { emotion, delta }`

**Items:** `BuyItem`, `SellItem`, `UseItem`, `EquipItem`, `PickUpNearby`, `SearchFor(category)`, `DropItem`

**Meta:** `Wait(f32)`, `Rest`, `RequestNewTree`, `RequestLlmResponse(context)`, `EndConversation`

### Mob Default Trees (static, no LLM)

Wolf:
```
Select [
  Sequence [IsBeingAttacked, Attack]
  Sequence [EnemyDetected, StrengthAdvantage(-0.3), Attack]
  Sequence [EnemyDetected, Flee]
  Sequence [IsNightTime, Wander]
  Rest
]
```

This wolf has zero LLM cost. But if it survives many fights and gains knowledge (through inline `AddKnowledge` actions in the default tree), it could eventually hit a significance threshold and get an LLM-generated tree. A wolf that *learned* becomes more dangerous than its kin. This is emergent — not scripted.

## Conversation Protocol

Built into the reactive layer. The tree handles the *protocol* (when to listen, when to respond, when to end). The LLM only generates *content* when templates/knowledge fail.

### Listening (always happens, zero LLM cost)

**Separate from responding.** The NPC absorbs information regardless of response quality.

Every speech event near the NPC is logged:
```json
{
  "type": "heard_speech",
  "time_us": 1679832000000000,
  "location": { "x": 45.2, "z": 82.1, "poi": "Market Square" },
  "speaker": { "type": "player", "id": "abc123", "name": "Alice" },
  "target": { "type": "npc", "id": 5, "name": "Blacksmith" },
  "content": "I heard bandits are hiding in the eastern cave",
  "topic": "bandits",
  "engagement": "overhearing",
  "confidence": 0.2
}
```

### Engagement-Based Confidence

```
effective_confidence = base_confidence * engagement_multiplier * topic_relevance
```

| Level | When | Multiplier |
|---|---|---|
| Focused | Active conversation with speaker | 1.0 |
| Attentive | Nearby and idle/low-priority task | 0.5 |
| Overhearing | Nearby but busy (combat, trading, crafting) | 0.2 |
| Distant | Edge of hearing range | 0.1 |

`topic_relevance`: 1.0 if matches NPC role/goals, 0.5 otherwise.

**Worked example** — Player says "The dragon burned down the eastern village":

| NPC | Engagement | Topic Relevance | Result Confidence |
|---|---|---|---|
| Guard (in convo) | 1.0 | 1.0 (threats = job) | **1.0** |
| Guard (patrolling) | 0.5 | 1.0 | **0.5** |
| Blacksmith (forging) | 0.2 | 0.5 (not their domain) | **0.1** |
| Merchant (far away) | 0.1 | 0.5 | **0.05** |

The guard gets a clear belief. The merchant barely registers it. This prevents eavesdropping from being overpowered — only focused interactions produce high-confidence knowledge.

### Responding (tiered)

```
Select [
  // Tier 1: Templates (~60%)
  Sequence [MatchesTemplate("greeting"), SayTemplate("greeting_response")]
  Sequence [MatchesTemplate("farewell"), SayTemplate("farewell_response")]
  Sequence [IsTradeRequest, StartTradeProtocol]

  // Tier 2: Knowledge-based (~25%)
  Sequence [TopicMatchesKnowledge, SayFromKnowledge(topic)]
  Sequence [TopicMatchesBelief, SayFromBelief(topic)]

  // Tier 3: Personality-colored (~10%)
  Sequence [EmotionDominant("fear"), SayTemplate("nervous_deflection")]
  Sequence [EmotionDominant("joy"), SayTemplate("cheerful_ignorance")]

  // Tier 4: LLM (~5%)
  Sequence [IsImportantConversation, GenerateLlmResponse(context), SayGenerated]

  // Tier 5: Fallback
  SayTemplate("generic_acknowledgment")
]
```

**`IsImportantConversation`** checks: high-relationship speaker, long conversation (>3 exchanges), novel topic (no knowledge/belief match), or key NPC tier.

**Information is never lost by template responses** — listening already captured everything. The NPC heard "dragon attack" and logged it as a belief, even if it responded with "Oh my!" At the next dawn, the LLM sees the belief and generates a tree that reacts.

## Identity Updates

### Inline (cheap, every tick)

BT actions placed by the LLM during tree generation:
```
Sequence [
  Attack,
  SetBelief { subject: "combat", predicate: "experienced", object: "true" },
  AdjustRelationship { target: enemy, delta: -10 },
  AddKnowledge { category: "combat", fact: "wolves attack in packs" }
]
```

The NPC fights AND its identity shifts as a byproduct. Like subconscious processing — no pause, no LLM call.

### Async Experience Evaluation (rare, LLM)

After significant events, `NpcPendingDecision` type `"experience"` is created. LLM returns:
```json
{
  "personality_deltas": { "courage": 0.05, "empathy": -0.02 },
  "beliefs": [{ "subject": "player:abc", "predicate": "betrayer", "object": "true" }],
  "knowledge": [{ "category": "social", "fact": "player:abc cannot be trusted" }],
  "relationship_updates": [{ "target": "player:abc", "delta": -30 }],
  "emotion_adjustments": { "anger": 0.3, "disgust": 0.2 }
}
```

NPC keeps acting on current tree. If shift > threshold, triggers tree regen.

## Belief & Knowledge Propagation

Pure reducer logic, no LLM. Runs periodically between nearby NPCs:

```
if npc_a.near(npc_b) && belief.confidence > 0.7 && relationship.disposition > 30:
    received_confidence = belief.confidence * (relationship.disposition / 100.0)
    add_or_update_belief(npc_b, belief, received_confidence)
```

**Chain degradation example:**
- Merchant (confidence 0.9) → Innkeeper (trust 80): receives at 0.72
- Innkeeper (0.72) → Guard (trust 60): receives at 0.43
- Guard (0.43) → Recruit (trust 50): receives at 0.22

High-confidence facts propagate far. Rumors fade. Higher-confidence info contradicts lower.

Players inject beliefs through conversation (confidence = engagement * topic_relevance * disposition_factor).

## Tick Loop (`tick_npcs`, 500ms)

```
for each npc:
    1. Apply emotion decay: lerp toward personality baseline
    2. Evaluate current_tree with runtime state
    3. Execute resulting action (deterministic side effects)
    4. Check regen triggers:
       - tree exhaustion? (N ticks no action)
       - goal completed? (check_goal_conditions)
       - near-death? (health < 10% after combat)
    5. If significant event → create NpcPendingDecision("experience")
```

## Cost Model

| NPC Tier | Count | LLM Usage | Cost |
|---|---|---|---|
| Mobs | Thousands | Static default trees, no LLM | Zero |
| Common NPCs | Hundreds | Tree at dawn + rare events | ~2-5 calls/day each |
| Key NPCs | Dozens | Trees + novel conversations | ~10-30 calls/day each |

## Current Implementation Status

**Implemented (v1):**
- Behavior trees with `bonsai-bt` (combat_tree + life_tree + NpcPlan — separate trees)
- Mode-switching tick loop (sleeping/combat/plan/life_tree/idle)
- NpcPendingDecision flow with 8 decision types
- NpcBelief, NpcGoal, NpcRelationship, NpcMemory tables
- NpcEventLog with 5min TTL
- Day/night cycle (40min period) triggering sleep/wake/reflection
- Chat system (player→NPC heard_chat events, NPC→NPC via SayToNpc)
- NpcInventory, NpcEquipment, NpcSkill tables
- Combat trees generated per-role (aggressive, defensive, flee-first, passive)
- Life trees generated at dawn by LLM

**Needs migration to v2 (see docs/TODO.md):**
- [ ] Unified tree (replace mode switching + combat_tree/life_tree/NpcPlan)
- [ ] NpcEmotion table + event triggers + tick-driven decay
- [ ] NpcKnowledge table (separate from beliefs)
- [ ] NpcPersonality table (structured traits replacing persona string)
- [ ] Knowledge-gated entity references (vague/concrete action forms)
- [ ] Emotion conditions in BT (EmotionAbove, EmotionBelow, EmotionDominant)
- [ ] Conversation protocol in BT (listen with engagement confidence, respond tiered)
- [ ] Belief/knowledge propagation reducer
- [ ] SearchFor runtime resolution (discover items → AddKnowledge)
