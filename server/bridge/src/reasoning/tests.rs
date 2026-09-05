use super::*;
use backend::BackendConfig;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
static IDS: AtomicU64 = AtomicU64::new(0);
fn dir() -> PathBuf {
    let p = std::env::temp_dir().join(format!(
        "sao-reasoning-test-{}-{}",
        std::process::id(),
        IDS.fetch_add(1, Ordering::SeqCst)
    ));
    std::fs::create_dir_all(&p).unwrap();
    p
}
fn config() -> Config {
    serde_json::from_value(
        json!({"backend":{"kind":"openrouter","model":"openai/gpt-4.1-mini","provider":"openai"}}),
    )
    .unwrap()
}
fn proposal() -> Value {
    json!({"reason":"A deliberate rest before looking for food","policy":{"kind":"action","action":{"skill":"rest","duration":2}},"reflections":[]})
}
fn response() -> Value {
    json!({"id":"mock-generation","model":"actual-model-revision","provider":"OpenAI","choices":[{"finish_reason":"stop","message":{"content":proposal().to_string()}}],"usage":{"prompt_tokens":11,"completion_tokens":12,"cost":0.0003}})
}
fn pending() -> Pending {
    Pending {
        id: 42,
        actor: 1,
        generation: 2,
        tick: 3,
        context: json!({"player":{"id":1,"name":"Mira","memories":[],"motive":"find safety","personality":{"caution":70}}}),
    }
}
async fn server(
    responses: Vec<(u16, String, u64)>,
) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        let mut requests = vec![];
        for (status, body, delay) in responses {
            let Ok(Ok((mut socket, _))) =
                tokio::time::timeout(Duration::from_secs(2), listener.accept()).await
            else {
                break;
            };
            let mut bytes = vec![];
            let mut buf = [0; 4096];
            loop {
                let n = socket.read(&mut buf).await.unwrap();
                if n == 0 {
                    break;
                }
                bytes.extend_from_slice(&buf[..n]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let h = String::from_utf8_lossy(&bytes[..end]);
                    let len = h
                        .lines()
                        .find_map(|l| {
                            l.to_lowercase()
                                .strip_prefix("content-length: ")
                                .and_then(|s| s.parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if bytes.len() >= end + 4 + len {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(bytes).unwrap());
            tokio::time::sleep(Duration::from_millis(delay)).await;
            let _=socket.write_all(format!("HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nRetry-After: 0\r\n\r\n{body}",body.len()).as_bytes()).await;
        }
        requests
    });
    (base, task)
}
fn catalog(parameters: Vec<&str>) -> Value {
    json!({"data":{"endpoints":[{"tag":"openai","supported_parameters":parameters}]}})
}
#[test]
fn explicit_capabilities_and_no_silent_settings_loss() {
    let c = config();
    c.validate().unwrap();
    let b = Backend::mock(c, "unused".into(), None);
    b.check_capabilities(&catalog(vec![
        "max_tokens",
        "response_format",
        "structured_outputs",
    ]))
    .unwrap();
    assert!(b
        .check_capabilities(&catalog(vec!["response_format"]))
        .is_err());
    for value in [
        json!({"backend":{"kind":"openrouter","model":"openai/gpt-4.1-mini","provider":"openai","allow_fallbacks":true}}),
        json!({"backend":{"kind":"ollama","model":"local","reasoning":{"mode":"effort","effort":"high"}}}),
        json!({"backend":{"kind":"ollama","model":"local"},"structured_output":"json"}),
    ] {
        assert!(serde_json::from_value::<Config>(value).is_err());
    }
    let mut c = config();
    c.backend = BackendConfig::OpenRouter {
        model: "openrouter/auto".into(),
        provider: "openai".into(),
        credential_env: "KEY".into(),
        reasoning: None,
    };
    assert!(c.validate().is_err());
    let mut c = config();
    c.seed = Some(42);
    let b = Backend::mock(c, "unused".into(), None);
    assert!(b
        .check_capabilities(&catalog(vec![
            "max_tokens",
            "response_format",
            "structured_outputs"
        ]))
        .is_err());
}
#[test]
fn schema_comes_from_authoritative_decision_and_skills() {
    let schema = decision_schema();
    assert!(schema["properties"].get("policy").is_some());
    assert!(schema["properties"].get("actions").is_none());
    assert_eq!(schema["additionalProperties"], false);
    let variants = schema["$defs"]["Skill"]["anyOf"].as_array().unwrap();
    let skill_names = variants.iter().find_map(|v| v["enum"].as_array()).unwrap();
    assert!(variants
        .iter()
        .any(|v| v["properties"].get("script").is_some()));
    assert!(serde_json::from_value::<simulation::Skill>(json!({"script":"stride"})).is_ok());
    assert_eq!(
        skill_names.len(),
        skill_contract().as_array().unwrap().len()
    );
    for name in skill_names {
        assert!(serde_json::from_value::<simulation::Skill>(name.clone()).is_ok());
    }
    assert_eq!(schema["required"].as_array().unwrap().len(), 3);
    let roots = schema["properties"]["policy"]["anyOf"].as_array().unwrap();
    assert_eq!(roots.len(), 4);
    assert!(roots
        .iter()
        .all(|v| v["properties"]["kind"]["const"] != "reconsider"));
    assert!(schema["$defs"]["Node"]["anyOf"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v["properties"]["kind"]["const"] == "reconsider"));
    let m = messages(&pending());
    assert_eq!(m[1]["content"], pending().context.to_string());
    assert!(!m.to_string().contains("hazard"));
}
#[test]
fn provider_errors_refusals_truncation_and_unknown_usage_remain_distinct() {
    let b = Backend::mock(config(), "unused".into(), None);
    assert_eq!(
        b.parse(200, "invalid").error.as_deref(),
        Some("malformed provider JSON")
    );
    let mut v = response();
    v["choices"][0]["finish_reason"] = json!("length");
    let r = b.parse(200, &v.to_string());
    assert!(r.error.is_some());
    assert!(!r.raw_output.is_empty());
    let mut v = response();
    v["choices"][0]["message"]["refusal"] = json!("refused");
    assert_eq!(
        b.parse(200, &v.to_string()).error.as_deref(),
        Some("model refusal")
    );
    let mut v = response();
    v.as_object_mut().unwrap().remove("provider");
    v.as_object_mut().unwrap().remove("usage");
    let r = b.parse(200, &v.to_string());
    assert!(r.served_provider.is_none());
    assert!(r.usage.is_null());
    assert!(!b.parse(200, "{\"error\":{\"code\":503}}").retryable);
    assert!(b.parse(429, "{\"error\":\"rate limited\"}").retryable);
    assert!(!b.parse(401, "{\"error\":\"unauthorized\"}").retryable);
}
#[tokio::test]
async fn openrouter_http_contract_records_actual_provider_usage_and_excludes_credentials() {
    let key = "mock-private-credential-do-not-persist";
    let mut v = response();
    v["echo"] = json!(key);
    let (base, task) = server(vec![(200, v.to_string(), 0)]).await;
    let service = Reasoner::mock(Backend::mock(config(), base, Some(key.into())));
    let out = dir();
    let (_tx, rx) = watch::channel(None);
    let r = service
        .reason("test-run".into(), pending(), rx, out.clone())
        .await;
    assert!(!r.raw.is_empty());
    assert_eq!(
        r.metadata["attempts"][0]["reply"]["served_model"],
        "actual-model-revision"
    );
    assert_eq!(r.metadata["attempts"][0]["reply"]["usage"]["cost"], 0.0003);
    assert!(!r.metadata.to_string().contains(key));
    assert!(!std::fs::read_to_string(out.join("request-42.jsonl"))
        .unwrap()
        .contains(key));
    let requests = task.await.unwrap();
    assert!(requests[0]
        .to_lowercase()
        .contains(&format!("authorization: bearer {key}")));
    let body: Value = serde_json::from_str(requests[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(
        body["provider"],
        json!({"only":["openai"],"order":["openai"],"allow_fallbacks":false,"require_parameters":true})
    );
    assert_eq!(body["response_format"]["type"], "json_schema");
    let schema = &body["response_format"]["json_schema"]["schema"];
    assert!(schema["$defs"]["Action"]["properties"]["duration"]
        .get("format")
        .is_none());
    assert_eq!(
        schema["$defs"]["Action"]["properties"]["duration"]["type"],
        "integer"
    );
    assert!(body.get("models").is_none());
    assert!(requests[0].starts_with("POST /chat/completions"));
}
#[tokio::test]
async fn ollama_keeps_native_settings_and_schema_without_remote_auth() {
    let v = json!({"model":"local-actual","done":true,"done_reason":"stop","message":{"content":proposal().to_string()},"prompt_eval_count":20,"eval_count":30});
    let (base, task) = server(vec![(200, v.to_string(), 0)]).await;
    let c = Config::ollama("local".into(), base.clone(), 42);
    let s = Reasoner::mock(Backend::mock(c, base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("local-run".into(), pending(), rx, dir()).await;
    assert!(!r.raw.is_empty());
    assert!(r.metadata["attempts"][0]["reply"]["served_provider"].is_null());
    let request = task.await.unwrap().remove(0);
    assert!(!request.to_lowercase().contains("authorization:"));
    let body: Value = serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert!(body["format"].is_object());
    assert_eq!(body["options"]["num_ctx"], 16384);
    assert_eq!(body["options"]["seed"], 42);
    assert_eq!(body["keep_alive"], "5m");
}
#[tokio::test]
async fn explicit_feedback_is_recorded_without_changing_context_or_retrying() {
    let (base, task) = server(vec![(200, response().to_string(), 0)]).await;
    let service = Reasoner::mock(Backend::mock(config(), base, None));
    let out = dir();
    let (_tx, rx) = watch::channel(None);
    let feedback =
        json!({"previous_raw_output":"{invalid proposal}","authority_error":"invalid destination"});
    let result = service
        .reason_with_feedback(
            "feedback-test".into(),
            pending(),
            rx,
            out.clone(),
            Some(feedback.clone()),
        )
        .await;
    assert_eq!(result.metadata["validation_feedback"], feedback);
    let requests = task.await.unwrap();
    assert_eq!(requests.len(), 1);
    let body: Value = serde_json::from_str(requests[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(
        body["messages"][1]["content"],
        pending().context.to_string()
    );
    assert!(body["messages"][2]["content"]
        .as_str()
        .unwrap()
        .contains("invalid destination"));
    let journal = std::fs::read_to_string(out.join("request-42.jsonl")).unwrap();
    assert!(journal.contains("invalid destination"));
    assert_eq!(result.raw, proposal().to_string());
}
#[tokio::test]
async fn retry_requires_opt_in_and_records_every_attempt_without_switching() {
    let (base, task) = server(vec![
        (503, "{\"error\":\"busy\"}".into(), 0),
        (200, response().to_string(), 0),
    ])
    .await;
    let mut c = config();
    c.max_attempts = 2;
    let s = Reasoner::mock(Backend::mock(c, base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("retry".into(), pending(), rx, dir()).await;
    assert!(!r.raw.is_empty());
    assert_eq!(r.metadata["attempts"].as_array().unwrap().len(), 2);
    let requests = task.await.unwrap();
    assert_eq!(
        requests[0].split("\r\n\r\n").nth(1),
        requests[1].split("\r\n\r\n").nth(1)
    );
    let (base, task) = server(vec![(503, "{\"error\":\"busy\"}".into(), 0)]).await;
    let s = Reasoner::mock(Backend::mock(config(), base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("no-retry".into(), pending(), rx, dir()).await;
    assert!(r.raw.is_empty());
    assert_eq!(r.metadata["attempts"].as_array().unwrap().len(), 1);
    assert_eq!(task.await.unwrap().len(), 1);
}
#[tokio::test]
async fn latency_does_not_block_world_and_cancellation_preserves_evidence() {
    let (base, task) = server(vec![(200, response().to_string(), 150)]).await;
    let service = Reasoner::mock(Backend::mock(config(), base, None));
    let (tx, rx) = watch::channel(None);
    let out = dir();
    let job =
        tokio::spawn(async move { service.reason("cancel".into(), pending(), rx, out).await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    let scenario =
        serde_json::from_str(include_str!("../../../../scenarios/survival.json")).unwrap();
    let mut w = simulation::World::new("advancing".into(), scenario).unwrap();
    for _ in 0..3 {
        w.step();
    }
    assert_eq!(w.tick, 3, "{:?}", w.events.last());
    assert!(!job.is_finished());
    tx.send(Some("generation changed".into())).unwrap();
    let r = job.await.unwrap();
    assert!(r.raw.is_empty());
    assert!(r.metadata["error"].as_str().unwrap().contains("cancelled"));
    assert_eq!(r.metadata["attempts"].as_array().unwrap().len(), 1);
    task.await.unwrap();
}
#[tokio::test]
async fn deadline_and_invalid_decision_never_submit_valid_looking_partial_output() {
    let (base, task) = server(vec![(200, response().to_string(), 120)]).await;
    let mut c = config();
    c.deadline_ms = 25;
    let s = Reasoner::mock(Backend::mock(c, base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("timeout".into(), pending(), rx, dir()).await;
    assert!(r.raw.is_empty());
    assert!(r.metadata["error"].as_str().unwrap().contains("deadline"));
    task.await.unwrap();
    let mut v = response();
    v["choices"][0]["message"]["content"] = json!("{\"unrecognized\":true}");
    let (base, task) = server(vec![(200, v.to_string(), 0)]).await;
    let s = Reasoner::mock(Backend::mock(config(), base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("invalid".into(), pending(), rx, dir()).await;
    assert!(r.raw.is_empty());
    assert!(r.metadata["error"]
        .as_str()
        .unwrap()
        .contains("malformed decision"));
    task.await.unwrap();
}
#[test]
fn reasoning_budget_is_native_and_required_not_an_npc_trait() {
    let c:Config=serde_json::from_value(json!({"backend":{"kind":"openrouter","model":"vendor/model","provider":"vendor","reasoning":{"mode":"tokens","max_tokens":512}},"max_output_tokens":2048})).unwrap();
    c.validate().unwrap();
    let b = Backend::mock(c, "unused".into(), None);
    let p = b.payload(messages(&pending()), decision_schema());
    assert_eq!(p["reasoning"], json!({"max_tokens":512,"exclude":true}));
    assert!(b
        .check_capabilities(&catalog(vec![
            "max_tokens",
            "response_format",
            "structured_outputs"
        ]))
        .is_err());
}

#[test]
fn unsupported_reasoning_effort_or_budget_is_rejected_before_inference() {
    let mut c = config();
    if let BackendConfig::OpenRouter { reasoning, .. } = &mut c.backend {
        *reasoning = Some(backend::ReasoningBudget::Effort {
            effort: backend::Effort::High,
        });
    }
    let b = Backend::mock(c, "unused".into(), None);
    let mut catalog = catalog(vec![
        "max_tokens",
        "response_format",
        "structured_outputs",
        "reasoning",
    ]);
    assert!(b.check_capabilities(&catalog).is_err());
    catalog["model_details"] = json!({"data":{"reasoning":{"supported_efforts":["low"]}}});
    assert!(b.check_capabilities(&catalog).is_err());
    catalog["model_details"]["data"]["reasoning"]["supported_efforts"] = json!(["low", "high"]);
    b.check_capabilities(&catalog).unwrap();
}
#[tokio::test]
async fn oversized_response_is_explicit_and_refused_output_has_no_effect() {
    let (base, task) = server(vec![(200, "x".repeat(140000), 0)]).await;
    let s = Reasoner::mock(Backend::mock(config(), base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("oversized".into(), pending(), rx, dir()).await;
    assert!(r.raw.is_empty());
    assert_eq!(r.metadata["attempts"][0]["reply"]["body_truncated"], true);
    task.await.unwrap();
    let mut v = response();
    v["choices"][0]["finish_reason"] = json!("length");
    let (base, task) = server(vec![(200, v.to_string(), 0)]).await;
    let s = Reasoner::mock(Backend::mock(config(), base, None));
    let (_tx, rx) = watch::channel(None);
    let r = s.reason("truncated".into(), pending(), rx, dir()).await;
    assert!(r.raw.is_empty());
    assert!(!r.metadata["attempts"][0]["reply"]["raw_output"]
        .as_str()
        .unwrap()
        .is_empty());
    task.await.unwrap();
}

#[tokio::test]
async fn large_metadata_keeps_proposal_and_full_journal_with_bounded_cli_envelope() {
    let mut v = response();
    v["provider_debug"] = json!("p".repeat(80000));
    let (base, task) = server(vec![(200, v.to_string(), 0)]).await;
    let s = Reasoner::mock(Backend::mock(config(), base, None));
    let (_tx, rx) = watch::channel(None);
    let out = dir();
    let r = s
        .reason("large-metadata".into(), pending(), rx, out.clone())
        .await;
    assert!(!r.raw.is_empty());
    assert!(r.metadata["error"].is_null());
    assert!(r.metadata.to_string().len() < 60000);
    assert!(r.metadata["evidence_storage"].is_string());
    let journal = std::fs::read_to_string(out.join("request-42.jsonl")).unwrap();
    assert!(journal.contains(&"p".repeat(80000)));
    task.await.unwrap();
}

fn compatible(base: &str, mode: &str) -> Config {
    serde_json::from_value(json!({"backend":{"kind":"openai_compatible","model":"chosen-local:model","base_url":base,"auth":{"kind":"none"},"capabilities":{"response_modes":[mode],"token_limit_field":"max_tokens","temperature":true,"seed":true}},"structured_output":mode,"temperature":0.3,"seed":42})).unwrap()
}
#[tokio::test]
async fn generic_prefix_and_response_modes_need_no_catalog_or_provider_fields() {
    for (prefix, mode) in [
        ("", "json_schema"),
        ("/v1/", "json_object"),
        ("/gateway/team/api/v1", "prompt_json"),
    ] {
        let mut v = response();
        v.as_object_mut().unwrap().remove("provider");
        v.as_object_mut().unwrap().remove("model");
        let (origin, task) = server(vec![(200, v.to_string(), 0)]).await;
        let c = compatible(&format!("{origin}{prefix}"), mode);
        let backend = Backend::new(c).unwrap();
        let declared = backend.catalog().await.unwrap();
        assert_eq!(declared["remote_capabilities_verified"], false);
        backend.check_capabilities(&declared).unwrap();
        let service = Reasoner::mock(backend);
        let (_tx, rx) = watch::channel(None);
        let out = dir();
        service.preflight(&out).await.unwrap();
        let r = service.reason("generic".into(), pending(), rx, out).await;
        assert!(!r.raw.is_empty());
        assert!(r.metadata["attempts"][0]["reply"]["served_model"].is_null());
        assert!(r.metadata["attempts"][0]["reply"]["served_provider"].is_null());
        let requests = task.await.unwrap();
        assert_eq!(requests.len(), 1);
        let request = &requests[0];
        assert!(request.starts_with(&format!(
            "POST {}/chat/completions ",
            prefix.trim_end_matches('/')
        )));
        assert!(!request.to_lowercase().contains("authorization:"));
        let body: Value = serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap();
        for key in ["provider", "reasoning", "models", "options", "format"] {
            assert!(body.get(key).is_none());
        }
        match mode {
            "json_schema" => assert_eq!(body["response_format"]["json_schema"]["strict"], true),
            "json_object" => assert_eq!(body["response_format"], json!({"type":"json_object"})),
            _ => assert!(body.get("response_format").is_none()),
        }
        assert_eq!(body["max_tokens"], 6000);
        assert_eq!(body["seed"], 42);
        assert_eq!(body["temperature"], 0.3);
        assert_eq!(
            body["messages"][1]["content"],
            pending().context.to_string()
        );
    }
}
#[tokio::test]
async fn generic_bearer_environment_auth_and_alternate_token_limit_are_explicit() {
    let key = "synthetic-generic-credential";
    let env_name = format!(
        "SAO_GENERIC_TEST_KEY_{}",
        IDS.fetch_add(1, Ordering::SeqCst)
    );
    let (origin, task) = server(vec![(200, response().to_string(), 0)]).await;
    let mut c = compatible(&format!("{origin}/proxy/v1/"), "json_schema");
    if let BackendConfig::OpenaiCompatible {
        auth, capabilities, ..
    } = &mut c.backend
    {
        *auth = backend::ChatAuth::BearerEnv {
            credential_env: env_name.clone(),
        };
        capabilities.token_limit_field = backend::TokenLimitField::MaxCompletionTokens;
    }
    assert!(Backend::new(c.clone()).is_err());
    std::env::set_var(&env_name, key);
    let transport = Backend::new(c).unwrap();
    std::env::remove_var(&env_name);
    let service = Reasoner::mock(transport);
    let (_tx, rx) = watch::channel(None);
    let out = dir();
    let result = service
        .reason("auth".into(), pending(), rx, out.clone())
        .await;
    assert!(!result.raw.is_empty());
    assert!(!result.metadata.to_string().contains(key));
    assert!(!std::fs::read_to_string(out.join("request-42.jsonl"))
        .unwrap()
        .contains(key));
    let req = task.await.unwrap().remove(0);
    assert!(req
        .to_lowercase()
        .contains(&format!("authorization: bearer {key}")));
    assert!(req.starts_with("POST /proxy/v1/chat/completions "));
    let body: Value = serde_json::from_str(req.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["max_completion_tokens"], 6000);
    assert!(body.get("max_tokens").is_none());
}
#[test]
fn generic_invalid_urls_and_undeclared_features_fail_without_downgrade() {
    for url in [
        "ftp://example.com/v1",
        "https://user:password@example.com/v1",
        "https://example.com/v1?api_key=secret",
        "https://example.com/v1#fragment",
        "https://example.com/v1/chat/completions/",
    ] {
        assert!(compatible(url, "json_schema").validate().is_err());
    }
    let mut c = compatible("https://example.com/team/v1", "json_schema");
    c.structured_output = backend::StructuredOutput::JsonObject;
    assert!(c.validate().is_err());
    c.structured_output = backend::StructuredOutput::JsonSchema;
    if let BackendConfig::OpenaiCompatible { capabilities, .. } = &mut c.backend {
        capabilities.temperature = false;
    }
    assert!(c.validate().is_err());
    c.temperature = None;
    if let BackendConfig::OpenaiCompatible { capabilities, .. } = &mut c.backend {
        capabilities.seed = false;
    }
    assert!(c.validate().is_err());
    c.seed = None;
    c.validate().unwrap();
    let mut value = serde_json::to_value(&c).unwrap();
    value["backend"]["provider"] = json!("openai");
    assert!(serde_json::from_value::<Config>(value).is_err());
    for kind in ["openrouter", "ollama"] {
        let mut old: Config = serde_json::from_str(if kind == "ollama" {
            include_str!("../../../../configs/reasoning/ollama.json")
        } else {
            include_str!("../../../../configs/reasoning/openrouter.json")
        })
        .unwrap();
        old.validate().unwrap();
        old.structured_output = backend::StructuredOutput::PromptJson;
        assert!(old.validate().is_err());
    }
}
#[tokio::test]
async fn generic_mode_failure_refusal_and_malformed_content_are_evidence_not_fallbacks() {
    for (status, body) in [
        (
            400,
            json!({"error":{"message":"unsupported response_format"}}).to_string(),
        ),
        (200, "not JSON".into()),
        (200, {
            let mut v = response();
            v["choices"][0]["message"]["content"] = json!("not a decision");
            v.to_string()
        }),
        (200, {
            let mut v = response();
            v["choices"][0]["message"]["refusal"] = json!("refused");
            v.to_string()
        }),
    ] {
        let (origin, task) = server(vec![(status, body, 0)]).await;
        let mut c = compatible(&format!("{origin}/v1"), "json_schema");
        c.max_attempts = 2;
        let service = Reasoner::new(c).unwrap();
        let (_tx, rx) = watch::channel(None);
        let r = service.reason("error".into(), pending(), rx, dir()).await;
        assert!(r.raw.is_empty());
        assert!(r.metadata["error"].is_string());
        assert_eq!(r.metadata["attempts"].as_array().unwrap().len(), 1);
        let req = task.await.unwrap().remove(0);
        let body: Value = serde_json::from_str(req.split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(body["response_format"]["type"], "json_schema");
    }
}
#[tokio::test]
async fn generic_modes_all_reach_the_same_authoritative_semantic_validation() {
    for mode in ["json_schema", "json_object", "prompt_json"] {
        let scenario =
            serde_json::from_str(include_str!("../../../../scenarios/survival.json")).unwrap();
        let mut world = simulation::World::new(format!("mode-{mode}"), scenario).unwrap();
        world.step();
        let p = world
            .pending
            .iter()
            .find(|p| p.actor == 1)
            .unwrap_or_else(|| panic!("missing decision: {:?}", world.events.last()))
            .clone();
        let before = serde_json::to_value(&world.players[0].execution).unwrap();
        let invalid = json!({"reason":"typed but beyond the simulation policy bound","policy":{"kind":"sequence","children":vec![json!({"kind":"action","action":{"skill":"rest","duration":1}});simulation::policy::MAX_CHILDREN+1]},"reflections":[]});
        let mut v = response();
        v["choices"][0]["message"]["content"] = json!(invalid.to_string());
        let (origin, task) = server(vec![(200, v.to_string(), 0)]).await;
        let service = Reasoner::new(compatible(&format!("{origin}/v1"), mode)).unwrap();
        let (_tx, rx) = watch::channel(None);
        let r = service.reason(world.run.clone(), p, rx, dir()).await;
        assert!(!r.raw.is_empty());
        assert!(world
            .model_result(r.request_id, &r.raw, r.metadata)
            .is_err());
        assert_eq!(
            serde_json::to_value(&world.players[0].execution).unwrap(),
            before
        );
        assert!(world.events.iter().any(|e| e.kind == "model_rejected"));
        task.await.unwrap();
    }
}

#[test]
fn non_json_gateway_failure_keeps_http_cause_and_does_not_retry() {
    let b = Backend::new(compatible("http://127.0.0.1:1/v1", "prompt_json")).unwrap();
    let reply = b.parse(524, "error code: 524\n");
    assert_eq!(reply.status, Some(524));
    assert!(reply.error.unwrap().contains("HTTP 524"));
    assert!(!reply.retryable);
    assert_eq!(reply.response_body, "error code: 524\n");
}

mod streaming;
