use super::*;
fn stream_config(base: &str) -> Config {
    serde_json::from_value(json!({
        "backend":{"kind":"openai_compatible","model":"gpt-5.6-luna","base_url":base,"auth":{"kind":"none"},"stream":true,
        "capabilities":{"response_modes":["prompt_json"],"token_limit_field":"unsupported"}},
        "structured_output":"prompt_json","max_output_tokens":null,"max_attempts":2
    })).unwrap()
}
fn chunk(text: &str, finish: Value) -> String {
    format!(
        "data: {}\n\n",
        json!({"object":"chat.completion.chunk","model":"served-luna","choices":[{"index":0,"delta":{"content":text},"finish_reason":finish}]})
    )
}
// Real HTTP chunking with independently delayed payload bytes, not a canned JSON response.
async fn stream_server(
    parts: Vec<(u64, Vec<u8>)>,
    clean_end: bool,
) -> (String, tokio::task::JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut request = vec![];
        let mut buffer = [0; 4096];
        loop {
            let n = socket.read(&mut buffer).await.unwrap();
            request.extend_from_slice(&buffer[..n]);
            if let Some(end) = request.windows(4).position(|v| v == b"\r\n\r\n") {
                let header = String::from_utf8_lossy(&request[..end]);
                let len = header
                    .lines()
                    .find_map(|s| {
                        s.to_lowercase()
                            .strip_prefix("content-length: ")
                            .and_then(|v| v.parse::<usize>().ok())
                    })
                    .unwrap();
                if request.len() >= end + 4 + len {
                    break;
                }
            }
        }
        socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n").await.unwrap();
        for (delay, bytes) in parts {
            tokio::time::sleep(Duration::from_millis(delay)).await;
            if socket
                .write_all(format!("{:x}\r\n", bytes.len()).as_bytes())
                .await
                .is_err()
            {
                break;
            }
            if socket.write_all(&bytes).await.is_err() {
                break;
            }
            if socket.write_all(b"\r\n").await.is_err() {
                break;
            }
        }
        if clean_end {
            let _ = socket.write_all(b"0\r\n\r\n").await;
        }
        String::from_utf8(request).unwrap()
    });
    (base, task)
}
#[test]
fn uncapped_is_explicit_and_legacy_cap_defaults_are_preserved() {
    let c = stream_config("https://example.com/v1");
    c.validate().unwrap();
    let b = Backend::mock(c.clone(), "unused".into(), None);
    let payload = b.payload(messages(&pending()), decision_schema());
    assert_eq!(payload["stream"], true);
    for field in [
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "reasoning_effort",
        "stream_options",
    ] {
        assert!(payload.get(field).is_none());
    }
    let mut wrong = c.clone();
    wrong.max_output_tokens = Some(6000);
    assert!(wrong.validate().is_err());
    let mut old = serde_json::to_value(c).unwrap();
    old["backend"].as_object_mut().unwrap().remove("stream");
    old["backend"]["capabilities"]["token_limit_field"] = json!("max_completion_tokens");
    old.as_object_mut().unwrap().remove("max_output_tokens");
    let old: Config = serde_json::from_value(old).unwrap();
    old.validate().unwrap();
    assert_eq!(old.max_output_tokens, Some(6000));
    let payload =
        Backend::mock(old, "unused".into(), None).payload(messages(&pending()), decision_schema());
    assert_eq!(payload["stream"], false);
    assert_eq!(payload["max_completion_tokens"], 6000);
    let mut local = Config::ollama("local".into(), "http://127.0.0.1:11434".into(), 42);
    local.max_output_tokens = None;
    assert!(local.validate().is_err());
}
#[tokio::test]
async fn fragmented_multiline_unicode_sse_retains_exact_body_and_usage_snapshot() {
    let mut proposal = proposal();
    proposal["reason"] = json!("Rest, caffè ☕, then reflect");
    let raw = proposal.to_string();
    let split = raw.char_indices().nth(30).unwrap().0;
    let usage = json!({"prompt_tokens":101,"completion_tokens":29,"total_tokens":130,"completion_tokens_details":{"reasoning_tokens":7}});
    let tail = format!(
        "data: {}\r\n\r\n",
        json!({"object":"chat.completion.chunk","model":"served-luna","choices":[],"usage":usage})
    );
    let first = chunk(&raw[..split], Value::Null).replacen("data: {", "data: {\r\ndata: ", 1);
    let wire = format!(
        "\u{feff}: connected\r\n\r\n{first}: keepalive\r\r{}{}{tail}data: [DONE]\n\n",
        chunk(&raw[split..], json!("stop")),
        tail
    );
    // One-byte HTTP chunks exercise UTF-8, JSON token, CRLF, event and DONE boundaries.
    let (base, task) = stream_server(wire.bytes().map(|b| (0, vec![b])).collect(), true).await;
    let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
    let (_tx, rx) = watch::channel(None);
    let out = dir();
    let result = service
        .reason("sse-test".into(), pending(), rx, out.clone())
        .await;
    assert_eq!(result.raw, raw);
    let reply = &result.metadata["attempts"][0]["reply"];
    assert_eq!(reply["response_body"], wire);
    assert_eq!(reply["served_model"], "served-luna");
    assert_eq!(reply["usage"], usage);
    assert_eq!(reply["finish_reason"], "stop");
    assert_eq!(result.metadata["attempts"].as_array().unwrap().len(), 1);
    let request = task.await.unwrap();
    let body: Value = serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["stream"], true);
    assert!(body.get("max_completion_tokens").is_none());
    assert!(std::fs::read_to_string(out.join("request-42.jsonl"))
        .unwrap()
        .contains("attempt_finished"));
}
#[tokio::test]
async fn stream_failures_never_submit_partial_proposals_or_retry() {
    let raw = proposal().to_string();
    let cases=vec![
        (chunk(&raw,json!("stop")),"missing terminal"),
        (format!("{}data: {{\"error\":{{\"message\":\"upstream failed\"}}}}\n\n",chunk(&raw,Value::Null)),"SSE error frame"),
        (format!("{}data: [DONE]\n\n",chunk(&raw,json!("length"))),"finish reason"),
        ("data: {broken}\n\n".into(),"SSE data JSON"),
        (format!("{}data: [DONE]\n\n",chunk(&raw,Value::Null)),"finish reason"),
        ("data: {\"object\":\"chat.completion.chunk\",\"choices\":[{\"index\":0,\"delta\":{\"refusal\":\"No\"},\"finish_reason\":\"stop\"}]}\n\n".into(),"refusal"),
        ("data: [DONE]\n\n".into(),"finish reason"),
    ];
    for (wire, error) in cases {
        let (base, task) = stream_server(vec![(0, wire.as_bytes().to_vec())], true).await;
        let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
        let (_tx, rx) = watch::channel(None);
        let result = service
            .reason("failure-test".into(), pending(), rx, dir())
            .await;
        assert!(result.raw.is_empty());
        assert!(
            result.metadata["error"].as_str().unwrap().contains(error),
            "{}",
            result.metadata["error"]
        );
        assert_eq!(result.metadata["attempts"].as_array().unwrap().len(), 1);
        assert_eq!(
            result.metadata["attempts"][0]["reply"]["response_body"],
            wire
        );
        task.await.unwrap();
    }
}
#[tokio::test]
async fn heartbeats_do_not_extend_deadline_and_cancellation_keeps_partial_stream() {
    for cancelled in [false, true] {
        let prefix = chunk("{\"reason\":\"unfinished", Value::Null);
        let mut parts = vec![(0, prefix.as_bytes().to_vec())];
        parts.extend((0..40).map(|_| (20, b": keepalive\n\n".to_vec())));
        let (base, task) = stream_server(parts, true).await;
        let mut config = stream_config(&base);
        config.deadline_ms = 300;
        let service = Reasoner::mock(Backend::mock(config, base, None));
        let (tx, rx) = watch::channel(None);
        let stop = tokio::spawn(async move {
            if cancelled {
                tokio::time::sleep(Duration::from_millis(150)).await;
                tx.send(Some("operator stop".into())).unwrap();
            } else {
                tokio::time::sleep(Duration::from_millis(600)).await;
            }
        });
        let started = Instant::now();
        let result = service
            .reason("bounded-test".into(), pending(), rx, dir())
            .await;
        assert!(started.elapsed() < Duration::from_secs(1));
        assert!(result.raw.is_empty());
        assert!(
            result.metadata["error"]
                .as_str()
                .unwrap()
                .contains(if cancelled {
                    "cancelled"
                } else {
                    "wall-time deadline"
                }),
            "cancelled={cancelled}: {}",
            result.metadata["error"]
        );
        let reply = &result.metadata["attempts"][0]["reply"];
        assert!(reply["response_body"]
            .as_str()
            .unwrap()
            .starts_with(&prefix));
        assert_eq!(reply["raw_output"], "{\"reason\":\"unfinished");
        assert_eq!(reply["served_model"], "served-luna");
        assert!(reply["usage"].is_null());
        assert_eq!(result.metadata["attempts"].as_array().unwrap().len(), 1);
        stop.await.unwrap();
        task.await.unwrap();
    }
}
#[tokio::test]
async fn abrupt_stream_disconnect_preserves_evidence_without_retry() {
    let wire = chunk(&proposal().to_string(), json!("stop"));
    let (base, task) = stream_server(vec![(0, wire.as_bytes().to_vec())], false).await;
    let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
    let (_tx, rx) = watch::channel(None);
    let result = service
        .reason("disconnect-test".into(), pending(), rx, dir())
        .await;
    assert!(result.raw.is_empty());
    assert!(result.metadata["error"]
        .as_str()
        .unwrap()
        .contains("transport failure"));
    assert_eq!(
        result.metadata["attempts"][0]["reply"]["response_body"],
        wire
    );
    assert_eq!(result.metadata["attempts"].as_array().unwrap().len(), 1);
    task.await.unwrap();
}
#[tokio::test]
async fn stream_limits_invalid_bytes_and_http_rejection_remain_explicit() {
    for (bytes, error) in [
        (vec![b':'; 131073], "event limit"),
        (
            vec![b'd', b'a', b't', b'a', b':', b' ', 255, b'\n', b'\n'],
            "UTF-8",
        ),
    ] {
        let (base, task) = stream_server(vec![(0, bytes.clone())], true).await;
        let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
        let (_tx, rx) = watch::channel(None);
        let result = service
            .reason("limit-test".into(), pending(), rx, dir())
            .await;
        assert!(result.raw.is_empty());
        assert!(result.metadata["error"].as_str().unwrap().contains(error));
        // Full response may be compacted out of reducer metadata; journal always retains it.
        assert_eq!(result.metadata["attempts"].as_array().unwrap().len(), 1);
        task.await.unwrap();
    }
    let (base, task) = server(vec![(
        400,
        "{\"error\":{\"code\":\"unsupported_parameter\"}}".into(),
        0,
    )])
    .await;
    let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
    let (_tx, rx) = watch::channel(None);
    let result = service
        .reason("http-test".into(), pending(), rx, dir())
        .await;
    assert!(result.raw.is_empty());
    assert_eq!(result.metadata["attempts"][0]["reply"]["status"], 400);
    assert!(result.metadata["error"]
        .as_str()
        .unwrap()
        .contains("HTTP 400"));
    assert_eq!(task.await.unwrap().len(), 1);
}
#[tokio::test]
async fn streamed_credential_echo_split_between_deltas_is_not_journaled() {
    let secret = "test-private-credential";
    let mut p = proposal();
    p["reason"] = json!(secret);
    let raw = p.to_string();
    let i = raw.find(secret).unwrap() + 8;
    let wire = format!(
        "{}{}data: [DONE]\n\n",
        chunk(&raw[..i], Value::Null),
        chunk(&raw[i..], json!("stop"))
    );
    let (base, task) = stream_server(vec![(0, wire.into_bytes())], true).await;
    let service = Reasoner::mock(Backend::mock(
        stream_config(&base),
        base,
        Some(secret.into()),
    ));
    let (_tx, rx) = watch::channel(None);
    let out = dir();
    let result = service
        .reason("secret-test".into(), pending(), rx, out.clone())
        .await;
    assert!(
        !result.raw.contains(secret),
        "raw output must also be redacted"
    );
    let journal = std::fs::read_to_string(out.join("request-42.jsonl")).unwrap();
    assert!(!journal.contains(secret));
    assert!(!journal.contains("credential\\\""));
    assert_eq!(
        result.metadata["attempts"][0]["reply"]["body_redacted"],
        true
    );
    task.await.unwrap();
}

#[tokio::test]
async fn sse_capture_prefix_limit_does_not_cut_off_valid_modest_generated_content() {
    let mut p = proposal();
    p["reason"] = json!("A long but valid explanation ".repeat(80));
    let raw = p.to_string();
    let mut wire = String::new();
    for c in raw.chars() {
        wire.push_str(&chunk(&c.to_string(), Value::Null));
    }
    wire.push_str(&chunk("", json!("stop")));
    wire.push_str("data: [DONE]\n\n");
    assert!(wire.len() > 131072 && raw.len() < 50000);
    let (base, task) = stream_server(vec![(0, wire.as_bytes().to_vec())], true).await;
    let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
    let (_tx, rx) = watch::channel(None);
    let out = dir();
    let result = service
        .reason("capture-test".into(), pending(), rx, out.clone())
        .await;
    assert_eq!(result.raw, raw);
    assert!(result.metadata["error"].is_null());
    let journal = std::fs::read_to_string(out.join("request-42.jsonl")).unwrap();
    let finished: Value = journal
        .lines()
        .map(|l| serde_json::from_str::<Value>(l).unwrap())
        .find(|v| v["phase"] == "attempt_finished")
        .unwrap();
    let reply = &finished["record"]["reply"];
    assert_eq!(reply["response_body"], &wire[..131072]);
    assert_eq!(reply["body_truncated"], true);
    assert_eq!(reply["stream"]["done_received"], true);
    assert_eq!(reply["stream"]["wire_bytes"], wire.len());
    assert_eq!(reply["stream"]["capture_truncated"], true);
    task.await.unwrap();
}
#[tokio::test]
async fn total_stream_wire_limit_bounds_heartbeat_flood_independently_of_capture() {
    let wire = b": keepalive\n\n".repeat(350000);
    let (base, task) = stream_server(vec![(0, wire)], true).await;
    let service = Reasoner::mock(Backend::mock(stream_config(&base), base, None));
    let (_tx, rx) = watch::channel(None);
    let result = service
        .reason("wire-bound-test".into(), pending(), rx, dir())
        .await;
    assert!(result.raw.is_empty());
    assert!(result.metadata["error"]
        .as_str()
        .unwrap()
        .contains("4 MiB total wire"));
    assert_eq!(result.metadata["attempts"].as_array().unwrap().len(), 1);
    task.await.unwrap();
}

#[test]
fn explicit_chat_effort_is_validated_and_preserved_on_wire() {
    let mut config: serde_json::Value = serde_json::from_str(include_str!("../../../../../configs/reasoning/codex-carlid-luna-streaming-proof.json")).unwrap();
    config["backend"]["auth"] = json!({"kind":"none"});
    config["backend"]["base_url"] = json!("http://127.0.0.1:9999/v1");
    for effort in ["low","medium","high"] {
        config["backend"]["reasoning_effort"]=json!(effort);
        config["backend"]["capabilities"]["reasoning_efforts"]=json!([]);
        let c: backend::Config=serde_json::from_value(config.clone()).unwrap();
        assert!(c.validate().is_err());
        config["backend"]["capabilities"]["reasoning_efforts"]=json!(["low","medium","high"]);
        let c=serde_json::from_value(config.clone()).unwrap();
        let b=backend::Backend::new(c).unwrap();
        assert_eq!(b.payload(json!([]),json!({}))["reasoning_effort"],effort);
    }
}
