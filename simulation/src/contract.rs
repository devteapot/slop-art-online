//! Model-facing format derived from the same types the authority deserializes.
use super::*;

pub fn decision_schema() -> Value {
    let mut schema = serde_json::to_value(schemars::schema_for!(policy::PolicyProposal)).unwrap();
    // Strict-output endpoints require every property, using null for Option values.
    // Serde defaults remain supported by the authority for existing human/archive inputs.
    strict_schema(&mut schema);

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

pub fn skill_contract() -> Value {
    let registry = scripting::Registry::default();
    json!(registry.catalog().as_array().unwrap().iter().map(|d| {
        json!({"skill":d["id"],"requirements_and_effects":d["description"],"revision":d["revision"]})
    }).collect::<Vec<_>>())
}

pub fn strict_schema(v: &mut Value) {
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
                strict_schema(child);
            }
        }
        Value::Array(a) => {
            for child in a {
                strict_schema(child);
            }
        }
        _ => (),
    }
}
