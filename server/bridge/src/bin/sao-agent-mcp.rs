//! Thin local MCP adapter. Protocol lifecycle belongs to rmcp; all game operations use ParticipantService.
use bridge::participant::ParticipantService;
use rmcp::{
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{CallToolResult, ServerCapabilities, ServerInfo},
    tool, tool_handler, tool_router, ServerHandler, ServiceExt,
};
use serde::Deserialize;
use serde_json::{json, Value};
use simulation::{
    participant::{Command, Request, API_VERSION},
    Node, Reflection,
};
#[derive(Clone)]
struct GameMcp {
    service: ParticipantService,
    tool_router: ToolRouter<Self>,
}
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct Observe {
    after_cursor: u64,
    limit: usize,
}
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct Replace {
    request_id: String,
    control_epoch: u64,
    expected_revision: u64,
    reason: String,
    tree: Node,
}
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct Patch {
    request_id: String,
    control_epoch: u64,
    expected_revision: u64,
    reason: String,
    path: String,
    subtree: Node,
}
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct Speak {
    request_id: String,
    control_epoch: u64,
    text: String,
    expires_tick: u64,
}
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct Reflect {
    request_id: String,
    control_epoch: u64,
    expected_revision: u64,
    observed_cursor: u64,
    reflections: Vec<Reflection>,
    goal: Option<String>,
}
fn result(r: Result<Value, String>) -> CallToolResult {
    match r {
        Ok(v) => CallToolResult::structured(v),
        Err(e) => CallToolResult::structured_error(json!({"error":e})),
    }
}
impl GameMcp {
    async fn apply(&self, id: String, epoch: u64, command: Command) -> CallToolResult {
        match self
            .service
            .command(Request {
                api_version: API_VERSION.into(),
                request_id: id,
                control_epoch: epoch,
                command,
            })
            .await
        {
            Ok(r) => {
                if r.ok {
                    CallToolResult::structured(json!(r))
                } else {
                    CallToolResult::structured_error(json!(r))
                }
            }
            Err(e) => result(Err(e)),
        }
    }
}
#[tool_router]
impl GameMcp {
    #[tool(
        description = "Read ONLY your assigned character, policy/revisions and cursor-paged subjective experiences. Persist next_cursor in your runtime; gap means retained history was missed. No observer truth. Your runtime schedules future thinking/polling."
    )]
    async fn observe(&self, Parameters(p): Parameters<Observe>) -> CallToolResult {
        result(self.service.observe(p.after_cursor, p.limit).await)
    }
    #[tool(
        description = "Atomically install/replace your executable behavior tree using current policy revision and control epoch. Interrupts old active skill, resets tree progress. Installed tree executes while you deliberate. Retry uncertain outcome with SAME request ID and identical args."
    )]
    async fn replace_tree(&self, Parameters(p): Parameters<Replace>) -> CallToolResult {
        self.apply(
            p.request_id,
            p.control_epoch,
            Command::ReplaceTree {
                expected_revision: p.expected_revision,
                reason: p.reason,
                tree: p.tree,
            },
        )
        .await
    }
    #[tool(
        description = "Version-checked atomic subtree replacement at root/0/guard style path. Preserves ancestor/sibling progress; interrupts active skill only if under patched node. Entire resulting tree is validated; next tick rechecks guards."
    )]
    async fn patch_subtree(&self, Parameters(p): Parameters<Patch>) -> CallToolResult {
        self.apply(
            p.request_id,
            p.control_epoch,
            Command::PatchSubtree {
                expected_revision: p.expected_revision,
                reason: p.reason,
                path: p.path,
                subtree: p.subtree,
            },
        )
        .await
    }
    #[tool(
        description = "Queue your chosen speech independently of tree revision, without interrupting movement. Expiry must be in next 30 world ticks. Authority delivers at most one queued utterance per character/tick at actual post-movement position to eligible living listeners."
    )]
    async fn speak(&self, Parameters(p): Parameters<Speak>) -> CallToolResult {
        self.apply(
            p.request_id,
            p.control_epoch,
            Command::Speak {
                text: p.text,
                expires_tick: p.expires_tick,
            },
        )
        .await
    }
    #[tool(
        description = "Independently interpret retained character experiences and update bounded beliefs, caution, trust and optional goal. Cite experience source IDs at/before observed_cursor; expected_revision is LEARNING revision. False conclusions allowed; invented/duplicate provenance, newer evidence and stale revisions are rejected atomically. Does not replace tree."
    )]
    async fn reflect(&self, Parameters(p): Parameters<Reflect>) -> CallToolResult {
        self.apply(
            p.request_id,
            p.control_epoch,
            Command::Reflect {
                expected_revision: p.expected_revision,
                observed_cursor: p.observed_cursor,
                reflections: p.reflections,
                goal: p.goal,
            },
        )
        .await
    }
}
#[tool_handler]
impl ServerHandler for GameMcp {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build()).with_instructions("SAO participant-v1: you are an external agent runtime controlling one character, not an observer/operator. Read your state and retain cursor. Create executable reactive trees for fast behavior; decide independently when to patch, speak, or learn. No universal autonomous loop is started by connecting MCP. Model/provider/tools/private memory and polling belong to your runtime. Reconnect the local adapter with the same private session file; persist cursors and request IDs outside the game. No ACP orchestration. Root repeats; do not put unconditional speech in a repeating tree unless intended.")
    }
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::var("SAO_PARTICIPANT_SESSION")
        .map_err(|_| "SAO_PARTICIPANT_SESSION must name your private scoped session file")?;
    let service = ParticipantService::from_file(std::path::Path::new(&path)).await?;
    let server = GameMcp {
        service,
        tool_router: GameMcp::tool_router(),
    }
    .serve(rmcp::transport::stdio())
    .await?;
    server.waiting().await?;
    Ok(())
}
