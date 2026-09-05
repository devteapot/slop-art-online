//! Incremental SSE framing. Bytes are decoded only after a complete line arrives.
//! Provider token usage is a reported cumulative snapshot, never a sum of chunks.
use super::*;

pub(super) struct Parser {
    pub reply: Reply,
    pub done: bool,
    pub sensitive: bool,
    pub data_events: usize,
    pub comment_lines: usize,
    line: Vec<u8>,
    data: Vec<String>,
    after_cr: bool,
    first_line: bool,
    event_bytes: usize,
}
impl Parser {
    pub fn new(status: u16) -> Self {
        let mut reply = Reply::failure("stream incomplete; missing terminal [DONE]");
        reply.status = Some(status);
        reply.error = None;
        Self {
            reply,
            done: false,
            sensitive: false,
            data_events: 0,
            comment_lines: 0,
            line: vec![],
            data: vec![],
            after_cr: false,
            first_line: true,
            event_bytes: 0,
        }
    }
    pub fn failed(&self) -> bool {
        self.reply.error.is_some()
    }
    fn fail(&mut self, reason: &str) {
        self.reply.error = Some(reason.into());
    }
    pub fn feed(&mut self, bytes: &[u8], backend: &Backend) {
        for &b in bytes {
            if self.failed() {
                break;
            }
            if self.after_cr {
                self.after_cr = false;
                if b == b'\n' {
                    continue;
                }
            }
            match b {
                b'\r' => {
                    self.line(backend);
                    self.after_cr = true;
                }
                b'\n' => self.line(backend),
                _ => {
                    self.event_bytes += 1;
                    if self.event_bytes > 131072 {
                        self.fail("provider SSE event exceeds 128 KiB event limit");
                        break;
                    }
                    self.line.push(b);
                }
            }
        }
    }
    fn line(&mut self, backend: &Backend) {
        let bytes = std::mem::take(&mut self.line);
        let Ok(mut line) = std::str::from_utf8(&bytes) else {
            self.fail("invalid UTF-8 in provider SSE");
            return;
        };
        if self.first_line {
            line = line.trim_start_matches('\u{feff}');
            self.first_line = false;
        }
        if line.is_empty() {
            self.event_bytes = 0;
            if !self.data.is_empty() {
                let data = std::mem::take(&mut self.data).join("\n");
                self.event(&data, backend);
            }
        } else if line.starts_with(':') {
            self.comment_lines += 1;
        } else {
            let (field, value) = line.split_once(':').unwrap_or((line, ""));
            if field == "data" {
                self.data
                    .push(value.strip_prefix(' ').unwrap_or(value).into());
            }
        }
    }
    fn event(&mut self, data: &str, backend: &Backend) {
        self.data_events += 1;
        if self.done {
            self.fail("provider SSE data after terminal [DONE]");
            return;
        }
        if data == "[DONE]" {
            self.done = true;
            return;
        }
        let value: Value = match serde_json::from_str(data) {
            Ok(v) => v,
            Err(_) => {
                self.fail("malformed provider SSE data JSON");
                return;
            }
        };
        if backend.safe_value(&value) != value {
            self.sensitive = true;
        }
        if value.get("error").is_some_and(|v| !v.is_null()) {
            self.fail("provider SSE error frame; see retained stream");
            return;
        }
        if value["object"] != "chat.completion.chunk" {
            self.fail("unsupported provider SSE object");
            return;
        }
        if let Some(model) = value["model"].as_str() {
            if self
                .reply
                .served_model
                .as_deref()
                .is_some_and(|old| old != model)
            {
                self.fail("served model changed within provider stream");
                return;
            }
            self.reply.served_model = Some(model.into());
        }
        if let Some(provider) = value["provider"].as_str() {
            self.reply.served_provider = Some(provider.into());
        }
        if let Some(usage) = value.get("usage").filter(|v| !v.is_null()) {
            self.reply.usage = usage.clone();
        }
        let Some(choices) = value["choices"].as_array() else {
            self.fail("provider SSE chunk has no choices array");
            return;
        };
        for choice in choices {
            if choice["index"] != 0 {
                self.fail("unsupported multiple-choice provider stream");
                return;
            }
            let delta = &choice["delta"];
            if delta
                .get("refusal")
                .is_some_and(|v| !v.is_null() && v.as_str() != Some(""))
            {
                self.fail("model refusal");
                return;
            }
            if let Some(content) = delta.get("content").filter(|v| !v.is_null()) {
                let Some(text) = content.as_str() else {
                    self.fail("unsupported streamed content type");
                    return;
                };
                if !text.is_empty() && self.reply.finish_reason.is_some() {
                    self.fail("provider content after finish reason");
                    return;
                }
                self.reply.raw_output.push_str(text);
                if self.reply.raw_output.len() > 50_000 {
                    self.fail("decision output exceeds authority limit");
                    return;
                }
            }
            if let Some(reason) = choice["finish_reason"].as_str() {
                self.reply.finish_reason = Some(reason.into());
                if reason != "stop" {
                    self.fail("incomplete or unsupported finish reason");
                    return;
                }
            }
        }
    }
    pub fn finish(mut self) -> Reply {
        if !self.failed() {
            self.reply.error = if !self.done {
                Some("stream incomplete; missing terminal [DONE]".into())
            } else if self.reply.finish_reason.as_deref() != Some("stop") {
                Some("incomplete or unsupported finish reason".into())
            } else if self.reply.raw_output.trim().is_empty() {
                Some("empty model output".into())
            } else {
                None
            };
        }
        self.reply
    }
}
