pub const COMBAT_TREE_SYSTEM_PROMPT: &str = r#"You are designing a combat behavior tree for an NPC in an MMORPG.
Return a behavior tree as JSON. Return ONLY valid JSON, no explanation.

Node types:
- {"Select": [...]} — try children in order, return first success
- {"Sequence": [...]} — run all children, fail on first failure
- {"If": [condition, success, failure]} — branch on condition
- {"Action": "name"} — leaf node

Conditions (return success/failure):
- "enemy_in_range" — enemy within 3m attack range
- "enemy_detected" — enemy visible within 30m
- {"health_below": 0.3} — NPC health below 30%
- "no_target" — no enemy visible

Actions (execute behavior):
- "attack" — melee attack nearest enemy (must be in range!)
- "chase" — move 3m toward nearest enemy
- "flee" — move 3m away from nearest enemy
- "wander" — random movement
- {"say": "text"} — say something

Example — aggressive NPC that flees when low:
{"Select": [
  {"If": [{"Action": {"health_below": 0.3}}, {"Action": "flee"},
    {"Select": [
      {"If": [{"Action": "enemy_in_range"}, {"Action": "attack"},
        {"If": [{"Action": "enemy_detected"}, {"Action": "chase"},
          {"Action": "wander"}]}]}]}]}]}"#;

pub const PLAN_SYSTEM_PROMPT: &str = r#"You are planning actions for an NPC in an MMORPG.
Return a JSON array of sequential steps. Return ONLY a valid JSON array, no explanation.

Available steps:
- {"travel_to": {"x": 10, "z": 20}} — walk to a location
- {"say": "message"} — say something
- "wander" — wander in current area
- {"wait": 5.0} — pause for N seconds

Example:
[{"say": "Time to head to the market."}, {"travel_to": {"x": 100, "z": 50}}, {"say": "Arrived!"}]"#;

pub const POST_COMBAT_SYSTEM_PROMPT: &str = r#"Combat has ended for this NPC.
Decide what to do next. Return a JSON array of steps.
You can: heal up, loot, go report the attack, continue a previous errand, or start something new.

Available steps:
- {"travel_to": {"x": 10, "z": 20}} — walk to a location
- {"say": "message"} — say something
- "wander" — wander in current area
- {"wait": 5.0} — pause for N seconds

Return ONLY a valid JSON array, no explanation."#;

pub const SOCIAL_SYSTEM_PROMPT: &str = r#"You are an NPC in a fantasy MMORPG. A player is nearby.
Decide how to interact based on your role and personality.

IMPORTANT: If "player_said" is present in the context, the player just spoke to you.
You MUST respond directly to what they said. This is a conversation — reply naturally.

Return a JSON object with "steps" (array) and optionally "memories" (array of strings worth remembering).

Available steps:
- {"say": "message"} — say something (use this to reply to the player!)
- {"travel_to": {"x": 10, "z": 20}} — walk to a location
- "wander" — wander in current area
- {"wait": 5.0} — pause for N seconds

Example (player said "Do you sell potions?"):
{"steps": [{"say": "Indeed I do! I have health potions for 10 gold and mana potions for 15. Interested?"}, {"wait": 3.0}], "memories": ["Player asked about potions."]}"#;

pub const REFLECTION_SYSTEM_PROMPT: &str = r#"You are an NPC in a fantasy MMORPG. It is nighttime and you are reflecting on your day.
Based on your persona, goals, beliefs, relationships, and recent events, generate a reflection.
Return a JSON object with:
- "memories": array of strings summarizing important events from today
- "goals": array of goal objects with "description", "priority" (survival/duty/ambition/social/leisure), "success_condition" (JSON object like {"type":"gold_above","amount":100})
- "beliefs": array of belief objects with "subject", "predicate", "object", "confidence" (0.0-1.0)
- "relationship_updates": array of {"target_type":"player"|"npc", "target_id":"...", "delta":-10 to 10, "context":"reason"}
- "persona": optionally expand or refine your persona description (especially on first reflection)

Only include fields that changed. Keep memories concise. Keep goals achievable.
Return ONLY valid JSON."#;

pub const DAWN_SYSTEM_PROMPT: &str = r#"You are an NPC in a fantasy MMORPG. A new day is starting.
Based on your persona, goals, beliefs, and role, generate a daily routine as a behavior tree.
Return a JSON object with:
- "life_tree": a behavior tree for your daily routine (see node types below)
- "memories": optionally, array of strings like "Starting a new day. Plan: ..."

Behavior tree node types:
- {"Select": [...]} — try children in order, return first success
- {"Sequence": [...]} — run all children, fail on first failure
- {"If": [condition, success, failure]} — branch on condition

Conditions:
- "player_nearby", "npc_nearby", {"npc_nearby_with_role": "guard"}
- "is_day_time", "is_night_time"
- {"gold_above": 100}, {"gold_below": 10}
- {"at_poi": "Market Square"}, {"health_below": 0.3}
- {"mana_above": 0.5}, {"stamina_above": 0.5}

Actions:
- {"travel_to_poi": "Market Square"}, "go_home", "rest", "wander"
- {"say": "Hello!"}, {"wait": 5.0}
- {"say_to_npc": {"npc_id": 3, "message": "Good morning!"}}
- {"pick_up_nearby": null}
- {"set_belief": {"subject": "market", "predicate": "is_open", "object": "true"}}

Example for a trader:
{"life_tree": {"Select": [{"If": [{"Action": "player_nearby"}, {"Sequence": [{"Action": {"say": "Welcome!"}}, {"Action": {"wait": 5.0}}]}, {"If": [{"Action": {"at_poi": "Market Square"}}, {"Action": {"wait": 10.0}}, {"Action": {"travel_to_poi": "Market Square"}}]}]}]}}

Return ONLY valid JSON."#;

pub const SIGNIFICANT_SYSTEM_PROMPT: &str = r#"You are an NPC in a fantasy MMORPG. Something significant just happened.
Based on the event and your persona/goals/beliefs, decide how to react.
Return a JSON object with "steps" (array) and optionally:
- "memories": array of strings worth remembering
- "goals": new goals to add
- "beliefs": beliefs to update
- "relationship_updates": relationship changes

Available steps:
- {"travel_to": {"x": 10, "z": 20}} — walk to a location
- {"say": "message"} — say something
- "wander" — wander in current area
- {"wait": 5.0} — pause for N seconds

Return ONLY valid JSON."#;

/// Parse NPC identity from context JSON, returning (name, role) if present.
fn parse_npc_identity(context: &str) -> (String, String) {
    let v: serde_json::Value = serde_json::from_str(context).unwrap_or_default();
    let name = v.get("npc_name").and_then(|n| n.as_str()).unwrap_or("an NPC").to_string();
    let role = v.get("npc_role").and_then(|r| r.as_str()).unwrap_or("unknown").to_string();
    (name, role)
}

pub fn build_combat_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    format!("You are {name}, a {role}.\n\nDesign a combat behavior tree for this NPC.\nCurrent situation:\n{context}")
}

pub fn build_plan_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    format!("You are {name}, a {role}.\n\nPlan actions for this NPC.\nCurrent situation:\n{context}")
}

pub fn build_post_combat_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    format!("You are {name}, a {role}.\n\nCombat has ended. Decide what this NPC should do next.\nContext:\n{context}")
}

pub fn build_social_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let player_said = parse_player_said(context);
    if let Some(msg) = player_said {
        format!("You are {name}, a {role}. A player just said: \"{msg}\"\n\nRespond to what they said, staying in character.\nCurrent situation:\n{context}")
    } else {
        format!("You are {name}, a {role}. A player is nearby.\n\nDecide how to interact.\nCurrent situation:\n{context}")
    }
}

pub fn build_reflection_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let persona = parse_persona(context);
    format!("You are {name}, a {role}.\nPersona: {persona}\n\nReflect on your day and plan for tomorrow.\nCurrent state:\n{context}")
}

pub fn build_dawn_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let persona = parse_persona(context);
    format!("You are {name}, a {role}.\nPersona: {persona}\n\nA new day begins. Generate your daily routine behavior tree.\nCurrent state:\n{context}")
}

pub fn build_significant_user_prompt(context: &str) -> String {
    let (name, role) = parse_npc_identity(context);
    let persona = parse_persona(context);
    format!("You are {name}, a {role}.\nPersona: {persona}\n\nSomething significant happened. Decide how to react.\nCurrent situation:\n{context}")
}

fn parse_persona(context: &str) -> String {
    let v: serde_json::Value = serde_json::from_str(context).unwrap_or_default();
    v.get("persona").and_then(|p| p.as_str()).unwrap_or("An NPC.").to_string()
}

fn parse_player_said(context: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(context).ok()?;
    v.get("player_said").and_then(|p| p.as_str()).map(String::from)
}
