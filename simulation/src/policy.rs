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
    When {
        condition: Condition,
        child: Box<Node>,
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
    HasKnowledge {
        record: String,
    },
    NeedsCare {
        target: u32,
    },
    Danger {
        location: Option<i32>,
    },
    FoodAt {
        location: i32,
        minimum: i32,
    },
    ShelterAt {
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
    #[serde(default)]
    pub entries: std::collections::BTreeSet<String>,
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
        self.validate_with_laws(&scripting::Registry::default())
    }
    pub fn validate_with_laws(&self, laws: &scripting::Registry) -> Result<Vec<&Action>, String> {
        self.validate_with_map(laws, None)
    }
    pub fn validate_with_map(
        &self,
        laws: &scripting::Registry,
        map: Option<&crate::spatial::Grid>,
    ) -> Result<Vec<&Action>, String> {
        let mut actions = vec![];
        self.check(1, &mut 0, &mut actions, laws, map)?;
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
        laws: &scripting::Registry,
        map: Option<&crate::spatial::Grid>,
    ) -> Result<(), String> {
        count(depth, total)?;
        match self {
            Self::Priority { children } | Self::Sequence { children } => {
                width(children.len())?;
                for c in children {
                    c.check(depth + 1, total, actions, laws, map)?;
                }
            }
            Self::Guard { condition, child } | Self::When { condition, child } => {
                condition.check(depth + 1, total, laws, map)?;
                child.check(depth + 1, total, actions, laws, map)?;
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
    fn check(
        &self,
        depth: usize,
        total: &mut usize,
        laws: &scripting::Registry,
        map: Option<&crate::spatial::Grid>,
    ) -> Result<(), String> {
        count(depth, total)?;
        match self {
            Self::All { conditions } | Self::Any { conditions } => {
                width(conditions.len())?;
                for c in conditions {
                    c.check(depth + 1, total, laws, map)?;
                }
            }
            Self::Not { condition } => condition.check(depth + 1, total, laws, map)?,
            _ => (),
        }
        let mut input = json!(self);
        input["map"] = json!(map);
        let error: String = laws.law("validate_condition", input)?;
        if !error.is_empty() {
            return Err(error);
        }
        Ok(())
    }
    pub fn evaluate(&self, p: &Player) -> (bool, Vec<u64>) {
        scripting::Registry::default()
            .law(
                "guard",
                json!({"condition":self,"player":scripting::subjective(p)}),
            )
            .expect("bundled subjective guard script must be valid")
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
        e.state.entries.retain(|p| !within(p, path));
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
            if status == Status::Failure {
                e.state.cursors.clear();
                e.state.entries.clear();
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
            Node::Guard { condition, child } | Node::When { condition, child } => {
                let entry_only = matches!(node, Node::When { .. });
                let child_path = format!("{path}/{}", if entry_only { "when" } else { "guard" });
                if entry_only && e.state.entries.contains(path) {
                    let status = self.tick_node(i, child, &child_path, e, budget, acted);
                    if status != Status::Running { e.state.entries.remove(path); }
                    return status;
                }
                let (allowed, sources): (bool, Vec<u64>) = match self.scripts.law(
                    "guard",
                    json!({"condition":condition,"player":scripting::subjective(&self.players[i])}),
                ) {
                    Ok(value) => value,
                    Err(error) => {
                        self.event(
                            Some(self.players[i].id),
                            "script_error",
                            vec![e.decision],
                            json!({"error":error,"path":path}),
                        );
                        return Status::Failure;
                    }
                };
                let event=self.event(Some(self.players[i].id),"guard_evaluated",std::iter::once(e.decision).chain(sources).collect(),json!({"path":path,"condition":condition,"result":allowed,"source":"subjective character state"}));
                e.state.last_guard = Some(event);
                if allowed {
                    if entry_only { e.state.entries.insert(path.into()); }
                    let status = self.tick_node(i, child, &child_path, e, budget, acted);
                    if entry_only && status != Status::Running { e.state.entries.remove(path); }
                    status
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
                                let old_path = format!("{path}/{old}");
                                // Priority preemption suspends a task. False continuous
                                // guards and failed/completed sequences still reset it.
                                if e.state.active_path.as_ref().is_some_and(|p| within(p, &old_path)) {
                                    self.abort_leaf(i, e, change, "higher priority suspended this task");
                                }
                                if n < old && (e.state.cursors.keys().any(|p| within(p, &old_path)) || e.state.entries.iter().any(|p| within(p, &old_path))) {
                                    self.event(Some(self.players[i].id), "task_suspended", vec![change],
                                        json!({"path":old_path,"sequence_progress_retained":true}));
                                }
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
                if self.participant_mode {
                    if !*acted {
                        self.event(
                            Some(self.players[i].id),
                            "reconsider_requested",
                            vec![e.decision],
                            json!({"reason":reason}),
                        );
                    }
                    return Status::Success;
                }
                let interval: u64 = match self
                    .scripts
                    .law("reconsider_interval", scripting::facts(&self.players[i]))
                {
                    Ok(value) => value,
                    Err(error) => {
                        self.event(
                            Some(self.players[i].id),
                            "script_error",
                            vec![e.decision],
                            json!({"error":error}),
                        );
                        return Status::Failure;
                    }
                };
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

pub const CONTRACT: &str = r#"Generate this individual's OWN executable persistent reactive behavior policy. Choose runtime conditions and alternative branches so this individual can act as circumstances change without another model response. The policy must contain at least one action node using an actual skill. A root-only reconsider is invalid: reconsider only requests later reasoning and cannot replace executable behavior. Reconsider may occur inside an executable tree. Choose conditions, branches and actions from the vocabulary. has_knowledge {record} checks possession of a personal report ID, not truth or mastery. New knowledge skills require actual local holders/archives and take elapsed time; inspect their contracts. A world seed may supply a starting policy, identified by starting_behavior. It is a revisable habit, not an obligation: inspect current_approach and keep, patch or replace it as experience warrants. Node kinds: when {condition,child} checks the condition only on entry, then retains the running child until it finishes/fails; a higher-priority branch suspends it and it resumes afterward; guard is the separate continuously checked alternative. priority {children} rechecks children in order every tick and selects the first non-failure; sequence {children} remembers its running cursor; guard {condition,child} rechecks its condition whenever reached, returning failure and aborting its subtree when false; action {action} uses the shared skill contract; reconsider {reason} requests asynchronous revision when eligible and succeeds immediately. Wrap a running sequence in a guard when it needs ongoing protection: earlier successful sequence children are not rechecked. A false continuous guard abandons its branch and resets its cursors. Priority preemption instead suspends the lower task: sequence cursors and when entries persist, while its interrupted skill can restart on resumption. The root repeats on subsequent ticks after success/failure, so choose guards that avoid unintended repeated speech/actions. At most one skill advances per tick; actions can run across ticks. Sudden attacks and site hazards interrupt the current skill, not the policy. Gradual cold and starvation reduce health without resetting action progress; death always stops action. Each tick re-evaluates reactive branches using newly perceived evidence while reasoning may remain pending. A failed policy remains installed and asks for revision; the engine never silently reinstalls the starting policy.
Conditions: needs_care {target} reads a retained local observation of that dependent’s care needs, false if unknown or observed elsewhere; has_knowledge {record} checks personal possession, not truth or mastery; all/any {conditions}; not {condition}; at {location}; danger {location:null for current position, or a fixed location} reads retained subjective danger belief, false if unknown; food_at {location,minimum} and shelter_at {location,minimum} use the latest retained direct site observation, false if unknown; resource {resource:health|hunger|energy|food|fear|failures,comparison:below|at_least,value:integer} reads this character's state. Gameplay ranges follow the current rules_description and authoritative validation. Unknown danger is NOT proven safety, reports may be mistaken, observations can age. Consider ongoing intent, recovery, depleted resources and avoiding accidental retreat/return oscillations according to YOUR beliefs and priorities. A fixed-location danger guard can remember a threat after leaving it; a current-location guard alone stops applying once you move. Rethink as needed. Node and condition total <=64, combined depth <=8, each composite 1..8 children. At least one skill action is required. You must supply reason, policy and reflections. Existing installed policy continues while you reason. Proposals from the same policy generation can survive damage; guards and skill prerequisites are checked against current state. Newer subjective beliefs are retained over old-source reflections. Explain your chosen approach briefly without claiming effects have already occurred."#;

impl PolicyState {
    pub fn is_default(&self) -> bool {
        self == &Self::default()
    }
}
