//! Model-facing format derived from the same types the authority deserializes.
use super::*;

pub fn decision_schema() -> Value {
    let mut schema = serde_json::to_value(schemars::schema_for!(policy::PolicyProposal)).unwrap();
    // Strict-output endpoints require every property, using null for Option values.
    // Serde defaults remain supported by the authority for existing human/archive inputs.
    fn strict(v: &mut Value) {
        match v {
            Value::Object(obj) => {
                obj.remove("default");
                obj.remove("$schema");
                // Tagged variants remain disjoint; anyOf is accepted by strict chat APIs.
                if let Some(variants) = obj.remove("oneOf") {
                    obj.insert("anyOf".into(), variants);
                }
                if let Some(properties) = obj.get("properties").and_then(Value::as_object) {
                    let required: Vec<_> = properties.keys().cloned().collect();
                    obj.insert("required".into(), json!(required));
                    obj.insert("additionalProperties".into(), json!(false));
                }
                for child in obj.values_mut() {
                    strict(child);
                }
            }
            Value::Array(a) => {
                for child in a {
                    strict(child);
                }
            }
            _ => (),
        }
    }
    strict(&mut schema);

    // Reconsider is a control leaf inside a policy, never an executable root.
    // Keep the recursive Node definition intact so nested control nodes remain legal.
    let mut root = schema["$defs"]["Node"].clone();
    root["anyOf"]
        .as_array_mut()
        .unwrap()
        .retain(|variant| variant["properties"]["kind"]["const"] != "reconsider");
    schema["properties"]["policy"] = root;

    schema["properties"]["reflections"]["maxItems"] = json!(MAX_REFLECTIONS);
    schema
}

// Match every authoritative variant: adding a skill requires describing its contract.
impl Skill {
    pub fn description(&self) -> &'static str {
        match self {
            Self::Move => "requires non-null destination integer -10..10; target/text null; move one cell per tick; costs energy",
            Self::Gather => "destination/target/text must be null; gathers food at own position, not a destination; costs 4 energy; gains one carried food",
            Self::Eat => "requires one carried food; reduces hunger by 35",
            Self::Rest => "duration 1..5 ticks; restores 12 energy each tick",
            Self::Wait => "duration 1..5 ticks; intentional inactivity",
            Self::Speak => "text of 1..1000 characters; heard within distance 2",
            Self::Attack => "known target player ID at same position; costs 8 energy; 20 damage",
        }
    }
}
pub fn skill_contract() -> Value {
    let schema = serde_json::to_value(schemars::schema_for!(Skill)).unwrap();
    json!(schema["enum"]
        .as_array()
        .unwrap()
        .iter()
        .map(|name| {
            let skill: Skill = serde_json::from_value(name.clone()).unwrap();
            json!({"skill":name,"requirements_and_effects":skill.description()})
        })
        .collect::<Vec<_>>())
}
