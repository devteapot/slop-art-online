//! Versioned physical laws. Source installation is a participant action; engine
//! storage/type bounds are host contracts, not political or cultural privileges.
use crate::*;
use serde::de::DeserializeOwned;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    sync::{Mutex, MutexGuard},
};

pub const HOOKS: &[&str] = &[
    "metabolism",
    "aftermath",
    "food_renewal",
    "cost",
    "action_interval_ms",
    "on_damage",
    "visible",
    "observation",
    "reflection",
    "population_costs",
    "needs_care",
    "development",
    "research_authoring",
    "research_use",
    "authorize_law_edit",
    "authorize_effect",
];
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum LawScope {
    Universal,
    Territory { region: String },
}
impl LawScope {
    pub fn key(&self) -> String {
        match self {
            Self::Universal => "universal".into(),
            Self::Territory { region } => format!("territory:{region}"),
        }
    }
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LawDraft {
    /// Law interface version: must be 1.
    pub interface_version: u32,
    /// Rhai hook definitions only. Declare each permitted hook as fn hook_name(argument),
    /// substituting its listed name, followed by its body. Functions are public by default;
    /// Rhai has no pub keyword. No top-level statements or new helper declarations.
    /// Local bindings use let x = ... and are mutable without a mut keyword.
    pub source: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LawArtifact {
    pub interface_version: u32,
    pub source: String,
    pub source_hash: String,
    pub hooks: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LawRef {
    pub scope: LawScope,
    pub revision: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LawBinding {
    pub base: scripting::DefinitionRef,
    pub overlays: Vec<LawRef>,
    pub disabled: Vec<LawDisabled>,
    pub digest: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LawRevision {
    pub reference: LawRef,
    pub artifact: LawArtifact,
    pub author: u32,
    pub origin: u64,
    pub installed_ms: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PendingLaw {
    pub update: u64,
    pub expected_binding: LawBinding,
    pub revision: LawRevision,
    pub location: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LawDisabled {
    pub reference: LawRef,
    pub hook: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LawFault {
    pub reference: LawRef,
    pub hook: String,
    pub error: String,
}
/// Owned, serde-transparent fault collection. Deep cloning preserves World
/// transaction rollback; synchronization lets native async hosts share &World.
#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct FaultLog(Mutex<Vec<LawFault>>);
impl Clone for FaultLog {
    fn clone(&self) -> Self {
        Self(Mutex::new(self.lock().clone()))
    }
}
impl FaultLog {
    pub fn lock(&self) -> MutexGuard<'_, Vec<LawFault>> {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LawState {
    pub active: BTreeMap<String, u64>,
    pub history: BTreeMap<String, BTreeMap<u64, LawRevision>>,
    pub pending: Vec<PendingLaw>,
    #[serde(default)]
    pub faults: FaultLog,
    #[serde(default)]
    pub reported_faults: usize,
}
pub fn digest(value: &impl Serialize) -> String {
    format!(
        "{:x}",
        Sha256::digest(
            serde_json::to_vec(&serde_json::to_value(value).expect("serializable law data"))
                .expect("canonical law data")
        )
    )
}
pub fn compile(draft: &LawDraft) -> Result<LawArtifact, String> {
    if draft.interface_version != 1 || draft.source.is_empty() || draft.source.len() > 8192 {
        return Err("law source requires interface 1 and 1..8192 bytes".into());
    }
    let ast = scripting::compile_participant_law(&draft.source)?;
    let functions = ast.iter_functions().collect::<Vec<_>>();
    if !(1..=8).contains(&functions.len())
        || functions.iter().any(|f| {
            !HOOKS.contains(&f.name)
                || f.params.len() != 1
                || f.access != rhai::FnAccess::Public
                || f.this_type.is_some()
        })
    {
        return Err("law patch needs 1..8 known public single-argument hook functions and no other functions".into());
    }
    let mut hooks = functions
        .iter()
        .map(|f| f.name.to_owned())
        .collect::<Vec<_>>();
    hooks.sort();
    hooks.dedup();
    if hooks.len() != functions.len() {
        return Err("duplicate law hook".into());
    }
    Ok(LawArtifact {
        interface_version: 1,
        source: draft.source.clone(),
        source_hash: digest(&("scoped-law-v1", 1, &draft.source, &hooks)),
        hooks,
    })
}
pub fn validate(artifact: &LawArtifact) -> Result<(), String> {
    let actual = compile(&LawDraft {
        interface_version: artifact.interface_version,
        source: artifact.source.clone(),
    })?;
    if &actual != artifact {
        return Err("law artifact hash/manifest mismatch".into());
    }
    Ok(())
}
/// Concrete output contracts are checked before typed conversion or effects.
pub fn validate_output(hook: &str, v: &Value) -> Result<(), String> {
    let n = |v: &Value, lo: i64, hi: i64| v.as_i64().is_some_and(|n| (lo..=hi).contains(&n));
    let object = |fields: &[(&str, i64, i64)], bools: &[&str]| -> bool {
        v.as_object().is_some_and(|m| {
            m.len() == fields.len() + bools.len()
                && fields
                    .iter()
                    .all(|(k, lo, hi)| m.get(*k).is_some_and(|v| n(v, *lo, *hi)))
                && bools
                    .iter()
                    .all(|k| m.get(*k).is_some_and(Value::is_boolean))
        })
    };
    let valid = match hook {
        "cost" => n(v, 0, 1_000_000),
        "action_interval_ms" => n(v, 1, 3_600_000),
        "food_renewal" => n(v, 0, 1_000_000),
        "metabolism" => object(&[("hunger", 0, 100), ("fear", 0, 100)], &[]),
        "aftermath" => v.as_object().is_some_and(|m| {
            m.contains_key("starvation")
                && m.contains_key("hazard")
                && m.iter().all(|(k, v)| {
                    ["starvation", "hazard", "cold", "power_depletion"].contains(&k.as_str())
                        && n(v, 0, 1_000_000)
                })
        }),
        "on_damage" => {
            object(
                &[
                    ("health", 0, 100),
                    ("fear", 0, 100),
                    ("caution", 0, 100),
                    ("confidence", 0, 100),
                ],
                &["learn_danger", "interrupt", "dead"],
            ) && v["dead"].as_bool() == Some(v["health"] == 0)
        }
        "visible" | "needs_care" | "development" | "research_authoring" | "research_use"
        | "authorize_law_edit" | "authorize_effect" => v.is_boolean(),
        "observation" => object(
            &[("food", 0, 1_000_000), ("shelter", 0, 1_000_000)],
            &["buildable"],
        ),
        "reflection" => object(
            &[
                ("caution", 0, 100),
                ("trust", -100, 100),
                ("confidence", 0, 100),
            ],
            &[],
        ),
        "population_costs" => object(
            &[
                ("offer_ms", 1, 3_600_000),
                ("reproduction_ms", 1, 3_600_000),
                ("parent_food", 1, 100),
                ("parent_energy", 1, 100),
                ("fabrication_ms", 1, 3_600_000),
                ("fabrication_food", 1, 100),
                ("fabrication_energy", 1, 100),
                ("care_ms", 1, 3_600_000),
                ("care_energy", 1, 100),
                ("nutrition", 1, 100),
                ("practice_ms", 1, 3_600_000),
                ("practice_energy", 1, 100),
            ],
            &[],
        ),
        _ => true,
    };
    if valid {
        Ok(())
    } else {
        Err(format!("invalid output contract for law hook {hook}"))
    }
}
impl World {
    pub(super) fn region_contains(&self, region: &society::Region, position: i32) -> bool {
        self.initial.map.as_ref().is_some_and(|m| {
            let b = &region.bounds;
            position >= 0
                && position < m.width * m.height
                && position % m.width >= b.x
                && position % m.width < b.x + b.width
                && position / m.width >= b.y
                && position / m.width < b.y + b.height
        })
    }
    pub(super) fn scope_here(&self, scope: &LawScope, position: i32) -> bool {
        match scope {
            LawScope::Universal => true,
            LawScope::Territory { region } => self.initial.society.as_ref().is_some_and(|s| {
                s.regions
                    .iter()
                    .any(|r| r.id == *region && self.region_contains(r, position))
            }),
        }
    }
    pub(super) fn local_law_grant(&self, actor: u32, scope: &LawScope) -> bool {
        let Ok(i) = self.idx(actor) else {
            return false;
        };
        match scope {
            LawScope::Universal => false,
            LawScope::Territory { region } => self.initial.society.as_ref().is_some_and(|s| {
                s.regions.iter().any(|r| {
                    r.id == *region
                        && r.territorial_editors.contains(&actor)
                        && self.region_contains(r, self.players[i].position)
                })
            }),
        }
    }
    pub fn law_binding_at(&self, position: Option<i32>) -> LawBinding {
        let mut overlays = vec![];
        if let (Some(pos), Some(seed)) = (position, &self.initial.society) {
            let mut regions = seed
                .regions
                .iter()
                .filter(|r| self.region_contains(r, pos))
                .collect::<Vec<_>>();
            // Weakest first: higher priority, smaller area, lexicographically smaller ID wins.
            regions.sort_by(|a, b| {
                a.priority
                    .cmp(&b.priority)
                    .then_with(|| {
                        (b.bounds.width * b.bounds.height).cmp(&(a.bounds.width * a.bounds.height))
                    })
                    .then_with(|| b.id.cmp(&a.id))
            });
            for r in regions {
                let scope = LawScope::Territory {
                    region: r.id.clone(),
                };
                if let Some(revision) = self.laws.active.get(&scope.key()) {
                    overlays.push(LawRef {
                        scope,
                        revision: *revision,
                    });
                }
            }
        }
        if let Some(revision) = self.laws.active.get("universal") {
            overlays.push(LawRef {
                scope: LawScope::Universal,
                revision: *revision,
            });
        }
        let base = self.scripts.resolve("law").expect("world base law exists");
        let faults = self.laws.faults.lock();
        let disabled: Vec<_> = faults
            .iter()
            .filter(|f| overlays.contains(&f.reference))
            .map(|f| LawDisabled {
                reference: f.reference.clone(),
                hook: f.hook.clone(),
            })
            .collect();
        let hash = digest(&(&base, &overlays, &disabled));
        LawBinding {
            base,
            overlays,
            disabled,
            digest: hash,
        }
    }
    pub(super) fn binding_for_scope(
        &self,
        i: usize,
        scope: &LawScope,
    ) -> Result<LawBinding, String> {
        if !self.scope_here(scope, self.players[i].position) {
            return Err("law scope is not locally accessible".into());
        }
        Ok(
            self.law_binding_at(if matches!(scope, LawScope::Universal) {
                None
            } else {
                Some(self.players[i].position)
            }),
        )
    }
    pub(super) fn candidate_layers(
        &self,
        binding: &LawBinding,
        scope: &LawScope,
        artifact: &LawArtifact,
    ) -> Result<Vec<(LawRef, LawArtifact)>, String> {
        let mut layers = self.law_layers(binding)?;
        layers.retain(|(r, _)| r.scope != *scope);
        layers.push((
            LawRef {
                scope: scope.clone(),
                revision: u64::MAX,
            },
            artifact.clone(),
        ));
        let rank = |scope: &LawScope| -> (bool, i32, i32, String) {
            match scope {
                LawScope::Universal => (true, 0, 0, String::new()),
                LawScope::Territory { region } => self
                    .initial
                    .society
                    .as_ref()
                    .and_then(|s| s.regions.iter().find(|r| r.id == *region))
                    .map(|r| {
                        (
                            false,
                            r.priority,
                            -r.bounds.width * r.bounds.height,
                            r.id.clone(),
                        )
                    })
                    .unwrap_or((false, 0, 0, region.clone())),
            }
        };
        layers.sort_by(|(a, _), (b, _)| {
            let a = rank(&a.scope);
            let b = rank(&b.scope);
            a.0.cmp(&b.0)
                .then(a.1.cmp(&b.1))
                .then(a.2.cmp(&b.2))
                .then_with(|| b.3.cmp(&a.3))
        });
        Ok(layers)
    }
    pub(super) fn law_layers(
        &self,
        binding: &LawBinding,
    ) -> Result<Vec<(LawRef, LawArtifact)>, String> {
        binding
            .overlays
            .iter()
            .map(|r| {
                self.laws
                    .history
                    .get(&r.scope.key())
                    .and_then(|h| h.get(&r.revision))
                    .map(|d| (r.clone(), d.artifact.clone()))
                    .ok_or("bound law source unavailable".into())
            })
            .collect()
    }
    pub(super) fn bound_law<T: DeserializeOwned>(
        &self,
        binding: &LawBinding,
        hook: &str,
        input: Value,
    ) -> Result<T, String> {
        let layers = self.law_layers(binding)?;
        let mut faults = self.laws.faults.lock();
        let value =
            self.scripts
                .call_law_layers(&binding.base, &layers, &mut faults, hook, input)?;
        serde_json::from_value(value).map_err(|e| format!("law result: {e}"))
    }
    pub(super) fn law_at<T: DeserializeOwned>(
        &self,
        position: i32,
        hook: &str,
        input: Value,
    ) -> Result<T, String> {
        self.bound_law(&self.law_binding_at(Some(position)), hook, input)
    }
    pub(super) fn actor_law<T: DeserializeOwned>(
        &self,
        i: usize,
        hook: &str,
        input: Value,
    ) -> Result<T, String> {
        self.law_at(self.players[i].position, hook, input)
    }
    pub(super) fn bound_skill<T: DeserializeOwned>(
        &self,
        binding: &LawBinding,
        reference: &scripting::DefinitionRef,
        hook: &str,
        input: Value,
    ) -> Result<T, String> {
        let layers = self.law_layers(binding)?;
        let mut faults = self.laws.faults.lock();
        self.scripts
            .call_scoped_skill(reference, &binding.base, &layers, &mut faults, hook, input)
    }
    pub(super) fn validate_scoped_action(&self, i: usize, action: &Action) -> Result<(), String> {
        let reference = self.scripts.resolve(action.skill.id())?;
        if reference.id == "law" {
            return Err("world law is not a skill".into());
        }
        let binding = self.law_binding_at(Some(self.players[i].position));
        let reason:String=self.bound_skill(&binding,&reference,"validate",json!({"action":action,"actor":scripting::facts(&self.players[i]),"map":self.map_for_actor(self.players[i].id)}))?;
        if reason.is_empty() {
            Ok(())
        } else {
            Err(reason)
        }
    }
    pub(super) fn law_scope_revision(&self, scope: &LawScope) -> u64 {
        self.laws.active.get(&scope.key()).copied().unwrap_or(0)
    }
    pub(super) fn activate_laws(&mut self, update: u64) -> Result<(), String> {
        let pending = std::mem::take(&mut self.laws.pending);
        for staged in pending {
            if staged.update > update {
                self.laws.pending.push(staged);
                continue;
            }
            let actual = self.law_binding_at(
                if matches!(staged.revision.reference.scope, LawScope::Universal) {
                    None
                } else {
                    Some(staged.location)
                },
            );
            if actual != staged.expected_binding {
                self.event(Some(staged.revision.author),"law_edit_rejected",vec![staged.revision.origin],json!({"scope":staged.revision.reference.scope,"reason":"effective binding changed before activation"}));
                continue;
            }
            let revision = staged.revision;
            let reference = revision.reference.clone();
            let origin = revision.origin;
            self.laws
                .active
                .insert(reference.scope.key(), reference.revision);
            self.laws
                .history
                .entry(reference.scope.key())
                .or_default()
                .insert(reference.revision, revision.clone());
            let event=self.event(Some(revision.author),"law_activated",vec![origin],json!({"reference":reference,"source_hash":revision.artifact.source_hash,"hooks":revision.artifact.hooks,"effective_update":update,"persistence":"installed source remains operative after its author dies"}));
            for i in 0..self.players.len() {
                if self.players[i].health > 0
                    && self.scope_here(&reference.scope, self.players[i].position)
                {
                    self.perceive(i,event,"law_changed",Some(revision.author),self.players[i].position,json!({"reference":reference,"source_hash":revision.artifact.source_hash,"hooks":revision.artifact.hooks}))?;
                }
            }
        }
        Ok(())
    }
    pub(super) fn flush_law_faults(&mut self) -> Result<(), String> {
        let faults = self.laws.faults.lock().clone();
        for fault in faults.iter().skip(self.laws.reported_faults) {
            let event = self.event(
                None,
                "law_hook_quarantined",
                vec![],
                json!({"fault":fault,"fallback":"next valid applicable implementation"}),
            );
            for i in 0..self.players.len() {
                if self.players[i].health > 0
                    && self.scope_here(&fault.reference.scope, self.players[i].position)
                {
                    self.perceive(
                        i,
                        event,
                        "law_fault",
                        None,
                        self.players[i].position,
                        json!({"reference":fault.reference,"hook":fault.hook,"fallback":true}),
                    )?;
                }
            }
        }
        self.laws.reported_faults = faults.len();
        Ok(())
    }
}

/// Examples describe the actual input shape, not hidden world-query handles.
/// Experiment inputs are supplied assumptions; live calls get authority facts.
pub fn hook_contracts() -> Value {
    let actor = json!({"id":1,"position":0,"health":100,"hunger":40,"energy":70,"food":2,"caution":20,"empathy":50,"introspection":50,"fear":10,"failures":0});
    let site = json!({"position":0,"food":10,"shelter":1,"hazard":0});
    json!(HOOKS.iter().map(|hook|{
        let (input,output)=match *hook {
            "cost"=>(json!("gather"),"integer 0..1000000"),
            "action_interval_ms"=>(json!("rest"),"milliseconds 1..3600000; system pulse periods remain fixed"),
            "metabolism"=>{let mut p=actor.clone();p["body"]=Value::Null;p["pulses"]=json!(1);p["elapsed_ms"]=json!(2500);(p,"object {hunger:0..100, fear:0..100}")},
            "aftermath"=>(json!({"actor":actor,"site":site,"body":null,"weather":null,"time_ms":2500,"pulses":1,"elapsed_ms":2500,"last_hazard_pulse_ms":null}),"object {starvation:nonnegative integer,hazard:nonnegative integer,cold?:nonnegative integer,power_depletion?:nonnegative integer}; each <=1000000"),
            "food_renewal"=>(json!({"source":{"position":0,"interval_ms":2500,"amount":1,"capacity":100},"food":10,"pulses":1,"elapsed_ms":2500}),"nonnegative integer; resulting physical food stock <=1000000"),
            "on_damage"=>(json!({"actor":actor,"amount":20,"nature":"attack"}),"object {health:0..100,fear:0..100,caution:0..100,learn_danger:bool,confidence:0..100,interrupt:bool,dead:bool}; dead must equal health==0"),
            "visible"=>(json!({"viewer":actor,"other":actor,"kind":"speech","distance":1}),"boolean; arena and local capabilities still apply"),
            "observation"=>(site.clone(),"object {food:0..1000000,shelter:0..1000000,buildable:bool}; input can be null where no site exists"),
            "reflection"=>(json!({"actor":actor,"trust":0,"caution_delta":1,"trust_delta":0}),"object {caution:0..100,trust:-100..100,confidence:0..100}"),
            "population_costs"=>(json!({}),"object with offer_ms,reproduction_ms,fabrication_ms,care_ms,practice_ms in 1..3600000 and parent_food,parent_energy,fabrication_food,fabrication_energy,care_energy,nutrition,practice_energy in 1..100"),
            "needs_care"=>(json!({"dependent":true,"hunger":40,"health":100}),"boolean"),
            "development"=>(json!({"body":"biological","age_ms":60000,"care_meals":2,"practice":1}),"boolean"),
            "research_authoring"=>(json!({"own_forecast_assessed":false,"own_practice_assessed":false,"own_prototype_assessed":true,"proofs":[]}),"boolean; proof facts are authority-derived"),
            "research_use"=>(json!({"held_interpreted":true,"own_matching_practice_assessed":true}),"boolean; proof facts are authority-derived"),
            "authorize_law_edit"=>(json!({"actor":actor,"scope":"universal","local_grant":false,"own_matching_assessed_experiment":true}),"boolean; universal requests resolve universal/base authorization only, before the proposal is installed"),
            "authorize_effect"=>(json!({"actor":actor,"action":{"skill":"gather","duration":1},"effect":{"kind":"actor","fields":{"energy":66}}}),"boolean; current source and destination authorization applies to every committed effect"),
            _=>unreachable!(),
        };
        json!({"name":hook,"signature":format!("fn {hook}(input)"),"example_input":input,"output":output})
    }).collect::<Vec<_>>())
}
