/// v2: Unified tree generation prompt. Documents ALL conditions and actions.
pub const TREE_GENERATION_SYSTEM_PROMPT: &str = r#"You are designing a unified behavior tree for an NPC in a fantasy MMORPG.
Return a behavior tree as JSON. Return ONLY valid JSON, no explanation.

The tree should handle ALL situations through priority layers:
1. REACTIVE (highest priority): combat response, conversation
2. AWARENESS: threat evaluation, emotional responses
3. DAILY LIFE: goal pursuit, routine tasks
4. FALLBACK: wander, rest

Node types:
- {"Select": [...]} — try children in order, return first success
- {"Sequence": [...]} — run all children in order, fail on first failure
- {"If": [condition, success, failure]} — branch on condition
- {"Action": "name"} — leaf node
- {"Invert": child} — negate result
- {"AlwaysSucceed": child} — suppress failure

Conditions (return success/failure, no side effects):
WORLD STATE:
- "enemy_in_range" — enemy within 3m attack range
- "enemy_detected" — enemy visible within 30m
- "is_being_attacked" — took damage recently
- "being_addressed_in_conversation" — player recently spoke to this NPC
- {"health_below": 0.3} — health below threshold (0.0-1.0)
- "no_target", "player_nearby", "npc_nearby"
- {"npc_nearby_with_role": "guard"}
- "is_night_time", "is_day_time"
- {"gold_above": 100}, {"gold_below": 10}
- {"at_poi": "Market Square"}
- {"has_item": "Health Potion"}
- {"goal_active": "trade"}
- {"mana_above": 0.5}, {"stamina_above": 0.5}

EMOTION GATES (check NPC's current emotional state):
- {"emotion_above": ["anger", 0.7]} — anger > 0.7
- {"emotion_below": ["fear", 0.3]} — fear < 0.3
- {"emotion_dominant": "joy"} — joy is the strongest emotion

IDENTITY:
- {"has_knowledge": "trading"} — NPC knows something about this category
- {"strength_advantage": 0.2} — NPC is 20%+ stronger than target
- {"strength_advantage": -0.3} — even 30% weaker is acceptable

Actions (execute behavior):
MOVEMENT:
- "attack" — melee attack nearest player
- "chase" — move toward nearest player
- "flee" — move away from nearest player
- "wander" — random movement
- {"travel_to_poi": "Market Square"} — travel to named POI
- "go_home" — travel to home location
- {"keep_distance": 12.0} — maintain minimum distance from threat
- {"follow": {"distance": 5.0}} — follow target at distance
- {"travel_to_entity": {"entity_type": "poi", "entity_id": 3}} — travel to entity by ID (ONLY use IDs from NPC's knowledge!)
- {"travel_to": {"x": 10.0, "z": 20.0}} — travel to coordinates

COMBAT:
- {"attack_entity": {"entity_type": "npc", "entity_id": 7}} — attack specific entity

SOCIAL:
- {"say": "Hello!"} — broadcast speech
- {"say_template": "guard_greeting"} — use predefined template
- {"say_to_npc": {"npc_id": 3, "message": "Good morning!"}} — speak to specific NPC
- {"say_from_knowledge": "trading"} — speak from NPC's knowledge on topic
- {"say_from_belief": "danger"} — speak from NPC's beliefs on topic

IDENTITY (inline updates, no LLM cost):
- {"set_belief": {"subject": "market", "predicate": "is_open", "object": "true"}}
- {"add_knowledge": {"category": "combat", "fact": "wolves attack in packs"}}
- {"adjust_relationship": {"target": "player:abc", "delta": -10}}
- {"trigger_emotion_action": {"emotion": "anger", "delta": 0.3}}

ITEMS:
- {"search_for": "healing"} — explore looking for items in category
- "pick_up_nearby" — pick up nearest ground item

OTHER:
- "rest" — stand still (gives night regen bonus)
- {"wait": 5.0} — pause for N seconds
- "request_new_tree" — request LLM to generate a new tree

IMPORTANT RULES:
- Only use entity IDs (travel_to_entity, attack_entity) for entities listed in the NPC's knowledge
- Use travel_to_poi or search_for when the NPC doesn't know specific entity IDs
- Combat should be in the REACTIVE layer (highest priority)
- Include night behavior (is_night_time → go_home → rest)
- Use emotion gates to vary behavior (e.g., emotion_above anger for aggressive responses)

Example — guard NPC:
{"Select": [
  {"Sequence": [{"Action": "is_being_attacked"}, {"Action": "attack"}]},
  {"Sequence": [{"Action": "being_addressed_in_conversation"}, {"Action": {"say_template": "guard_greeting"}}]},
  {"Sequence": [{"Action": "enemy_detected"}, {"Action": {"emotion_below": ["fear", 0.6]}}, {"Action": {"strength_advantage": -0.2}}, {"Action": "chase"}]},
  {"Sequence": [{"Action": "enemy_detected"}, {"Action": {"keep_distance": 12.0}}]},
  {"Sequence": [{"Action": "is_night_time"}, {"Action": {"travel_to_poi": "North Gate"}}, {"Action": "rest"}]},
  {"Sequence": [{"Action": "is_day_time"}, {"Action": {"travel_to_poi": "North Gate"}}, {"Action": {"wait": 5.0}}]},
  {"Action": "wander"}
]}"#;

/// v2: Experience evaluation prompt. Returns identity deltas.
pub const EXPERIENCE_SYSTEM_PROMPT: &str = r#"You are an NPC in a fantasy MMORPG. A significant event just happened to you.
Evaluate how this experience changes who you are.

Return a JSON object with ONLY the fields that changed:
- "personality_deltas": {"aggression": 0.05, "courage": -0.02, ...} — small trait changes (-0.1 to 0.1)
  Traits: aggression, sociability, curiosity, courage, empathy, discipline (all 0.0-1.0)
- "beliefs": [{"subject": "player:abc", "predicate": "is_dangerous", "object": "true", "confidence": 0.8}]
- "knowledge": [{"category": "combat", "fact": "wolves attack in packs", "confidence": 0.9}]
  Categories: combat, trading, crafting, navigation, social, world
- "relationship_updates": [{"target_type": "player", "target_id": "abc...", "delta": -20}]
- "emotion_adjustments": {"anger": 0.3, "fear": -0.1}
- "memories": ["I barely survived the wolf attack near the gate."]

Only include fields that actually changed. Keep personality deltas small (this is gradual evolution).
Return ONLY valid JSON."#;

/// v2: Conversation prompt. Returns a single message.
pub const CONVERSATION_SYSTEM_PROMPT: &str = r#"You are an NPC in a fantasy MMORPG having a conversation.
Generate a natural, in-character response to what was said to you.

Consider your personality, emotions, knowledge, and relationship with the speaker.
Stay concise (1-3 sentences). Stay in character.

Return a JSON object: {"message": "your response here"}
Return ONLY valid JSON."#;

/// Parse NPC identity from context JSON.
fn parse_npc_identity(context: &str) -> (String, String) {
    let v: serde_json::Value = serde_json::from_str(context).unwrap_or_default();
    let name = v.get("npc_name").and_then(|n| n.as_str()).unwrap_or("an NPC").to_string();
    let role = v.get("npc_role").and_then(|r| r.as_str()).unwrap_or("unknown").to_string();
    (name, role)
}

fn parse_persona(context: &str) -> String {
    let v: serde_json::Value = serde_json::from_str(context).unwrap_or_default();
    v.get("persona").and_then(|p| p.as_str()).unwrap_or("An NPC.").to_string()
}

fn parse_player_said(context: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(context).ok()?;
    v.get("player_said").and_then(|p| p.as_str()).map(String::from)
}

pub fn build_tree_generation_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let persona = parse_persona(context);
    format!(
        "You are {name}, a {role}.\nPersona: {persona}\n\n\
        Generate a unified behavior tree for this NPC that handles combat, social interaction, and daily routine.\n\
        Current situation:\n{context}"
    )
}

pub fn build_experience_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let persona = parse_persona(context);
    format!(
        "You are {name}, a {role}.\nPersona: {persona}\n\n\
        A significant event just happened. Evaluate how it changes who you are.\n\
        Current situation:\n{context}"
    )
}

pub fn build_conversation_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let persona = parse_persona(context);
    let player_said = parse_player_said(context);
    if let Some(msg) = player_said {
        format!(
            "You are {name}, a {role}.\nPersona: {persona}\n\n\
            A player just said: \"{msg}\"\n\
            Respond naturally, in character.\n\
            Current situation:\n{context}"
        )
    } else {
        format!(
            "You are {name}, a {role}.\nPersona: {persona}\n\n\
            Generate a greeting or comment for a nearby player.\n\
            Current situation:\n{context}"
        )
    }
}
