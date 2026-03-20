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

pub fn build_combat_user_prompt(context: &str) -> String {
    format!("Design a combat behavior tree for this NPC.\nCurrent situation:\n{context}")
}

pub fn build_plan_user_prompt(context: &str) -> String {
    format!("Plan actions for this NPC.\nCurrent situation:\n{context}")
}

pub fn build_post_combat_user_prompt(context: &str) -> String {
    format!("Combat has ended. Decide what this NPC should do next.\nContext:\n{context}")
}
