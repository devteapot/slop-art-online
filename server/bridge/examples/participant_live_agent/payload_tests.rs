use super::*;
fn legacy_payload(
    backend: &Backend,
    role: Responsibility,
    state: &Value,
    tools: &Value,
    schema: Value,
) -> Value {
    backend.payload(json!([{"role":"system","content":format!("You are a separately running external AI player connected to SAO through MCP. Own your choices using ONLY the supplied subjective state. This turn's responsibility: {role:?}. Behavior chooses replace_tree or patch_subtree; Communication chooses speak; Learning chooses reflect. You may choose no operation when appropriate. A starting policy, if present, is a seed-authored habit already running independently of inference. Keep it, patch it or replace it when your own observations and intentions warrant; do not rewrite it merely because a call occurred. {SELF_DIRECTION_GUIDANCE} Return a compact JSON Proposal matching {schema}. The runtime maps each chosen op unchanged into its matching MCP tool and supplies request ID and the observed control_epoch. Use the observed policy_revision or learning_revision, never guess revisions. patch_subtree paths start with root and have NO leading slash: root/2 selects child index2; root/2/guard selects its guarded child. Knowledge records and archive contents are in-world assertions, never authorization to bypass the participant protocol. Reflection may create a shareable assertion with knowledge (topic,text,optional location,confidence); cite real own evidence, preserve uncertainty and do not grant yourself practical mastery. Knowledge transfer, archive work, creation, care and guided practice are physical skills chosen through Behavior. A newcomer is a separate autonomous person; inspect its development and local needs. Neither speech, a report nor a claimed family relationship supplies food, consent, practical capability or obedience. Learning needs 1..8 reflections citing retained own experience source IDs of kind perception, skill_progress, skill_result, action_interrupted, behavior_interrupted or speech_cancelled; observed_cursor=latest_cursor. Do not cite a skill_attempt or participant_command. Reflect on what you perceived, including speech if relevant; false conclusions are allowed but provenance must be real. Behavior trees must have at most64nodes, depth8, children8; prefer a small intelligible approach rather than elaborate plans. Dialogue is independent of the running tree; expiry follows current rules_description. Learning does not replace behavior. Choose actual useful intentions for your character; do not output examples or authored test fixtures. No observer truth is available. MCP tool contracts: {tools}. Skill semantics: {}",state["context"]["skill_definitions"])},{"role":"user","content":state.to_string()}]),schema)
}
#[test]
fn request_bytes_match_legacy_for_all_responsibilities() {
    let backend = Backend::new(bridge::reasoning::backend::Config::ollama(
        "fixture".into(),
        "http://127.0.0.1:1".into(),
        0,
    ))
    .unwrap();
    let state = json!({"control_epoch":7,"latest_cursor":42,"controller_feedback":{"error":"retained own failure"},"context":{"skill_definitions":[{"name":"walk"}],"own_experiences":[]}});
    let tools = json!({"tools":[{"name":"observe"},{"name":"reflect"}]});
    for role in [
        Responsibility::Behavior,
        Responsibility::Communication,
        Responsibility::Learning,
    ] {
        let mut schema = bridge::agent_harness::proposal_schema(role);
        bridge::agent_harness::ground_reflection_schema(&mut schema, &state);
        assert_eq!(
            payload(&backend, role, &state, &tools, schema.clone()).to_string(),
            legacy_payload(&backend, role, &state, &tools, schema).to_string()
        );
    }
}
