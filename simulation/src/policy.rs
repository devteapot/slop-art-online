//! Simulation-owned reactive behavior vocabulary and durable runtime.
//! Conditions deliberately cannot access World/sites/other players.
use super::*;
pub const POLICY_VERSION: &str = "reactive-policy-v1";
pub const MAX_NODES: usize = 64;
pub const MAX_DEPTH: usize = 8;
pub const MAX_CHILDREN: usize = 8;
pub const TICK_BUDGET: usize = 128;

#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Node {
    Priority {
        children: Vec<Node>,
    },
    Sequence {
        children: Vec<Node>,
    },
    Guard {
        condition: Condition,
        child: Box<Node>,
    },
    Action {
        action: Action,
    },
    Reconsider {
        reason: String,
    },
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Condition {
    All {
        conditions: Vec<Condition>,
    },
    Any {
        conditions: Vec<Condition>,
    },
    Not {
        condition: Box<Condition>,
    },
    At {
        location: i32,
    },
    Danger {
        location: Option<i32>,
    },
    FoodAt {
        location: i32,
        minimum: i32,
    },
    Resource {
        resource: Resource,
        comparison: Comparison,
        value: i32,
    },
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Resource {
    Health,
    Hunger,
    Energy,
    Food,
    Fear,
    Failures,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Comparison {
    Below,
    AtLeast,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    #[default]
    Running,
    Success,
    Failure,
    Interrupted,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct PolicyState {
    pub cursors: BTreeMap<String, usize>,
    pub branches: BTreeMap<String, usize>,
    pub active_path: Option<String>,
    pub status: Status,
    pub last_guard: Option<u64>,
}

fn count(depth: usize, total: &mut usize) -> Result<(), String> {
    *total += 1;
    if depth > MAX_DEPTH || *total > MAX_NODES {
        return Err("policy exceeds depth 8 or 64 total nodes/conditions".into());
    }
    Ok(())
}
fn width(n: usize) -> Result<(), String> {
    if n == 0 || n > MAX_CHILDREN {
        Err("composite needs 1..8 children".into())
    } else {
        Ok(())
    }
}
impl Node {
    pub fn validate(&self) -> Result<Vec<&Action>, String> {
        let mut actions = vec![];
        self.check(1, &mut 0, &mut actions)?;
        if actions.is_empty() {
            return Err("policy needs at least one skill action".into());
        }
        Ok(actions)
    }
    fn check<'a>(
        &'a self,
        depth: usize,
        total: &mut usize,
        actions: &mut Vec<&'a Action>,
    ) -> Result<(), String> {
        count(depth, total)?;
        match self {
            Self::Priority { children } | Self::Sequence { children } => {
                width(children.len())?;
                for c in children {
                    c.check(depth + 1, total, actions)?;
                }
            }
            Self::Guard { condition, child } => {
                condition.check(depth + 1, total)?;
                child.check(depth + 1, total, actions)?;
            }
            Self::Action { action } => actions.push(action),
            Self::Reconsider { reason } => {
                if reason.trim().is_empty() || reason.len() > 1000 {
                    return Err("reconsider reason needs 1..1000 bytes".into());
                }
            }
        }
        Ok(())
    }
}
impl Condition {
    fn check(&self, depth: usize, total: &mut usize) -> Result<(), String> {
        count(depth, total)?;
        match self {
            Self::All { conditions } | Self::Any { conditions } => {
                width(conditions.len())?;
                for c in conditions {
                    c.check(depth + 1, total)?;
                }
            }
            Self::Not { condition } => condition.check(depth + 1, total)?,
            Self::At { location }
            | Self::FoodAt { location, .. }
            | Self::Danger {
                location: Some(location),
            } if !(-10..=10).contains(location) => {
                return Err("condition location outside known world bounds".into())
            }
            Self::Resource { value, .. } if !(0..=100).contains(value) => {
                return Err("resource threshold must be 0..100".into())
            }
            _ => (),
        }
        if matches!(self,Self::FoodAt{minimum,..} if !(1..=100).contains(minimum)) {
            return Err("food minimum must be 1..100".into());
        }
        Ok(())
    }
    pub fn evaluate(&self, p: &Player) -> (bool, Vec<u64>) {
        match self {
            Self::All { conditions } | Self::Any { conditions } => {
                let values: Vec<_> = conditions.iter().map(|c| c.evaluate(p)).collect();
                let result = if matches!(self, Self::All { .. }) {
                    values.iter().all(|v| v.0)
                } else {
                    values.iter().any(|v| v.0)
                };
                (result, values.into_iter().flat_map(|v| v.1).collect())
            }
            Self::Not { condition } => {
                let (b, s) = condition.evaluate(p);
                (!b, s)
            }
            Self::At { location } => (p.position == *location, vec![]),
            Self::Danger { location } => {
                let known = p
                    .beliefs
                    .iter()
                    .find(|k| k.claim.location == location.unwrap_or(p.position));
                (
                    known.is_some_and(|k| k.claim.danger),
                    known.map(|k| vec![k.source]).unwrap_or_default(),
                )
            }
            Self::FoodAt { location, minimum } => {
                let seen = p
                    .memories
                    .iter()
                    .rev()
                    .find(|m| m.kind == "site" && m.location == *location);
                (
                    seen.is_some_and(|m| {
                        m.content["food"].as_i64().unwrap_or(0) >= *minimum as i64
                    }),
                    seen.map(|m| vec![m.source]).unwrap_or_default(),
                )
            }
            Self::Resource {
                resource,
                comparison,
                value,
            } => {
                let actual = match resource {
                    Resource::Health => p.health,
                    Resource::Hunger => p.hunger,
                    Resource::Energy => p.energy,
                    Resource::Food => p.food,
                    Resource::Fear => p.fear,
                    Resource::Failures => p.failures.min(i32::MAX as u32) as i32,
                };
                (
                    match comparison {
                        Comparison::Below => actual < *value,
                        Comparison::AtLeast => actual >= *value,
                    },
                    vec![],
                )
            }
        }
    }
}
fn within(path: &str, prefix: &str) -> bool {
    path == prefix || path.starts_with(&format!("{prefix}/"))
}
impl World {
    fn abort_leaf(&mut self, i: usize, e: &mut Execution, cause: u64, reason: &str) {
        if let Some(attempt) = e.attempt.take() {
            let interrupt = self.event(
                Some(self.players[i].id),
                "action_interrupted",
                vec![e.decision, cause, attempt],
                json!({"node_path":e.state.active_path,"reason":reason,"policy_preserved":true}),
            );
            self.event(
                Some(self.players[i].id),
                "skill_result",
                vec![attempt, interrupt],
                json!({"status":"interrupted","reason":reason}),
            );
        }
        e.remaining = 0;
        e.state.active_path = None;
    }
    fn reset_branch(&mut self, i: usize, e: &mut Execution, path: &str, cause: u64) {
        if e.state
            .active_path
            .as_ref()
            .is_some_and(|p| within(p, path))
        {
            self.abort_leaf(i, e, cause, "reactive branch abandoned");
        }
        e.state.cursors.retain(|p, _| !within(p, path));
        e.state.branches.retain(|p, _| !within(p, path));
    }
    pub(super) fn execute_policy(&mut self, i: usize, tree: &Node, mut e: Execution) {
        let mut budget = TICK_BUDGET;
        let mut acted = false;
        e.state.last_guard = None;
        let status = self.tick_node(i, tree, "root", &mut e, &mut budget, &mut acted);
        e.state.status = status.clone();
        let tick=self.event(Some(self.players[i].id),"policy_tick",vec![e.decision],json!({"status":status,"active_path":e.state.active_path,"cursors":e.state.cursors,"node_visits":TICK_BUDGET-budget,"skill_stepped":acted}));
        if status != Status::Running {
            self.abort_leaf(i, &mut e, tick, "policy cycle ended");
            e.state.cursors.clear();
            if status == Status::Failure {
                self.request(i, "installed policy has no successful branch / reconsider");
            }
        }
        // This is the authoritative persisted execution, not a transient evaluator copy.
        self.players[i].execution = Some(e);
    }
    fn tick_node(
        &mut self,
        i: usize,
        node: &Node,
        path: &str,
        e: &mut Execution,
        budget: &mut usize,
        acted: &mut bool,
    ) -> Status {
        if *budget == 0 {
            self.event(
                Some(self.players[i].id),
                "policy_budget_exhausted",
                vec![e.decision],
                json!({"path":path}),
            );
            return Status::Failure;
        }
        *budget -= 1;
        match node {
            Node::Guard { condition, child } => {
                let (allowed, sources) = condition.evaluate(&self.players[i]);
                let event=self.event(Some(self.players[i].id),"guard_evaluated",std::iter::once(e.decision).chain(sources).collect(),json!({"path":path,"condition":condition,"result":allowed,"source":"subjective character state"}));
                e.state.last_guard = Some(event);
                if allowed {
                    self.tick_node(i, child, &format!("{path}/guard"), e, budget, acted)
                } else {
                    self.reset_branch(i, e, path, event);
                    Status::Failure
                }
            }
            Node::Sequence { children } => {
                let mut cursor = *e.state.cursors.get(path).unwrap_or(&0);
                while cursor < children.len() {
                    match self.tick_node(
                        i,
                        &children[cursor],
                        &format!("{path}/{cursor}"),
                        e,
                        budget,
                        acted,
                    ) {
                        Status::Success => {
                            cursor += 1;
                            e.state.cursors.insert(path.into(), cursor);
                        }
                        Status::Failure => {
                            self.reset_branch(i, e, path, e.decision);
                            return Status::Failure;
                        }
                        other => return other,
                    }
                }
                e.state.cursors.remove(path);
                Status::Success
            }
            Node::Priority { children } => {
                for (n, child) in children.iter().enumerate() {
                    let child_path = format!("{path}/{n}");
                    let result = self.tick_node(i, child, &child_path, e, budget, acted);
                    if result != Status::Failure {
                        let old = e.state.branches.insert(path.into(), n);
                        if old != Some(n) {
                            let change = self.event(
                                Some(self.players[i].id),
                                "branch_selected",
                                std::iter::once(e.decision)
                                    .chain(e.state.last_guard)
                                    .collect(),
                                json!({"path":path,"previous":old,"selected":n,"status":result}),
                            );
                            if let Some(old) = old {
                                self.reset_branch(i, e, &format!("{path}/{old}"), change);
                            }
                        }
                        return result;
                    }
                }
                Status::Failure
            }
            Node::Action { action } => {
                if *acted {
                    return Status::Running;
                }
                if e.state.active_path.as_deref() != Some(path) {
                    self.abort_leaf(
                        i,
                        e,
                        e.state.last_guard.unwrap_or(e.decision),
                        "reactive action switched",
                    );
                    e.state.active_path = Some(path.into());
                }
                *acted = true;
                self.execute_action(i, e, action.clone())
            }
            Node::Reconsider { reason } => {
                let interval = 4 + (100 - self.players[i].introspection) as u64 / 10;
                if self.tick.saturating_sub(self.players[i].last_reflection) >= interval {
                    self.request(i, reason);
                }
                Status::Success
            }
        }
    }
}

/// Current model output. Legacy Decision remains a separate accepted authority input.
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyProposal {
    pub reason: String,
    pub policy: Node,
    pub reflections: Vec<Reflection>,
}

pub const CONTRACT: &str = r#"Generate this individual's OWN executable persistent reactive behavior policy. Choose runtime conditions and alternative branches so this individual can act as circumstances change without another model response. The policy must contain at least one action node using an actual skill. A root-only reconsider is invalid: reconsider only requests later reasoning and cannot replace executable behavior. Reconsider may occur inside an executable tree. Choose conditions, branches and actions from the vocabulary; no authored survival policy is installed for you. Node kinds: priority {children} rechecks children in order every tick and selects the first non-failure; sequence {children} remembers its running cursor; guard {condition,child} rechecks its condition whenever reached, returning failure and aborting its subtree when false; action {action} uses the shared skill contract; reconsider {reason} requests asynchronous revision when eligible and succeeds immediately. Wrap a running sequence in a guard when it needs ongoing protection: earlier successful sequence children are not rechecked. Abandoning a branch resets its sequence cursors and interrupts its current skill; reentry restarts that branch. The root repeats on subsequent ticks after success/failure, so choose guards that avoid unintended repeated speech/actions. At most one skill advances per tick; actions can run across ticks. Damage interrupts the current skill, not the policy: the next tick re-evaluates reactive branches using newly perceived evidence while reasoning may remain pending. A failed policy remains installed and asks for revision, not authored survival actions.
Conditions: all/any {conditions}; not {condition}; at {location}; danger {location:null for current position, or a fixed location} reads retained subjective danger belief, false if unknown; food_at {location,minimum} uses latest remembered food observation, false if unknown; resource {resource:health|hunger|energy|food|fear|failures,comparison:below|at_least,value:0..100} reads this character's state. Locations -10..10; food minimum 1..100. Unknown danger is NOT proven safety, reports may be mistaken, observations can age. Consider ongoing intent, recovery, depleted resources and avoiding accidental retreat/return oscillations according to YOUR beliefs and priorities. A fixed-location danger guard can remember a threat after leaving it; a current-location guard alone stops applying once you move. Rethink as needed. Node and condition total <=64, combined depth <=8, each composite 1..8 children. At least one skill action is required. You must supply reason, policy and reflections. Existing installed policy continues while you reason. Proposals from the same policy generation can survive damage; guards and skill prerequisites are checked against current state. Newer subjective beliefs are retained over old-source reflections. Explain your chosen approach briefly without claiming effects have already occurred."#;

impl PolicyState {
    pub fn is_default(&self) -> bool {
        self == &Self::default()
    }
}
