//! Versioned authoritative content. Runtime caches are disposable; only source/state is persisted.
use crate::{Action, Player};
use rhai::{packages::Package, Dynamic, Engine, Scope, AST};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    rc::Rc,
};

pub const API_VERSION: u32 = 1;
const MAX_SOURCE: usize = 32_768;
const MAX_CONTENT: usize = 1_048_576;
const MAX_VALUE: usize = 65_536;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DefinitionRef {
    pub id: String,
    pub revision: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Definition {
    pub id: String,
    pub revision: u64,
    pub source: String,
    pub description: String,
    #[serde(default)]
    pub dependencies: Vec<DefinitionRef>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Update {
    pub api_version: u32,
    pub expected_revision: u64,
    pub definitions: Vec<Definition>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Pending {
    pub activate_tick: u64,
    pub definitions: Vec<Definition>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Registry {
    pub api_version: u32,
    pub revision: u64,
    pub active: BTreeMap<String, u64>,
    pub history: BTreeMap<String, BTreeMap<u64, Definition>>,
    pub pending: Option<Pending>,
}

impl Default for Registry {
    fn default() -> Self {
        let mut registry = Self {
            api_version: API_VERSION,
            revision: 1,
            active: BTreeMap::new(),
            history: BTreeMap::new(),
            pending: None,
        };
        for (id, source, description) in [
            (
                "law",
                include_str!("../scripts/law.rhai"),
                "Default laws: action duration 1..5 units of 2500 ms; legacy simulation_tick/expiry units are 2500 ms regardless of update frequency; locations use supplied map cell IDs (legacy worlds -10..10); resource thresholds 0..100; food minimum 1..100; speech expiry within 30 ticks. Skill descriptions describe their authored defaults; current law validation is authoritative.",
            ),
            (
                "move",
                include_str!("../scripts/move.rhai"),
                "destination is a surveyed walkable map cell ID (legacy -10..10); shortest cardinal route around walls, no automatic danger avoidance; costs 1 energy per cell, one cell per 250 ms; continues to destination",
            ),
            (
                "gather",
                include_str!("../scripts/gather.rhai"),
                "gather one food at own position; costs 4 energy, 1000 ms cooldown",
            ),
            (
                "eat",
                include_str!("../scripts/eat.rhai"),
                "consume one carried food at ANY position, including while away from camp; reduce hunger by 35, 1000 ms cooldown",
            ),
            (
                "rest",
                include_str!("../scripts/rest.rhai"),
                "rest at ANY position, even without a site or shelter; restore 12 + 2 per local shelter unit energy per 2500 ms, capped at 100; duration 1..5 of those units",
            ),
            (
                "wait",
                include_str!("../scripts/wait.rhai"),
                "intentional inactivity; duration 1..5 units of 2500 ms",
            ),
            (
                "speak",
                include_str!("../scripts/speak.rhai"),
                "free-form text; hearing determined by active world law",
            ),
            ("give", include_str!("../scripts/give.rhai"), "give one carried food to a perceived living target at the same cell; recipient receives a direct perception; no automatic reciprocity; 1000 ms cooldown"),
            ("deposit", include_str!("../scripts/deposit.rhai"), "place one carried food in the existing site at your position, available for anyone to gather; 1000 ms cooldown"),
            ("build", include_str!("../scripts/build.rhai"), "contribute one shelter unit at the existing site at your position; costs 8 energy; shelter maximum 12, remains shared; 2500 ms cooldown"),
            ("observe", include_str!("../scripts/observe.rhai"), "refresh direct local site and nearby-character observations; 1000 ms cooldown"),
            ("teach", include_str!("../scripts/teach.rhai"), "teach one of your held knowledge record IDs to a living target at your cell; record and target required; takes 2000 ms and 2 energy. Transfers an unassessed report, not practical skill mastery. Does not consume your copy."),
            ("record", include_str!("../scripts/record.rhai"), "copy one of your held knowledge record IDs into an intact archive at your cell; record and archive IDs required; takes 2500 ms and 4 energy. Capacity limited; your own copy remains."),
            ("consult", include_str!("../scripts/consult.rhai"), "read a selected record ID from an intact archive at your cell into your own durable knowledge; archive and record IDs required; takes 1500 ms and 1 energy. Local site observations list archive catalogs but do not reveal record contents. Reading does not automatically establish truth or grant skill mastery."),
            ("destroy_archive", include_str!("../scripts/destroy_archive.rhai"), "destroy a physical archive at your cell and all its stored records; archive ID required; takes 5000 ms and 8 energy. Copies held by living people or other archives remain; audit history is never an in-world recovery source."),
            ("offer_reproduction", include_str!("../scripts/offer_reproduction.rhai"), "explicitly offer paired reproduction to a living independent biological target at your cell; duration 1. Offer lasts 90000 ms and quotes your commitment of 2 food and 10 energy, paid only upon completed reproduction. The partner must independently offer to you. Repeating the same live offer retains its source; withdrawal or replacement invalidates work begun under it."),
            ("withdraw_reproduction", include_str!("../scripts/withdraw_reproduction.rhai"), "withdraw your own reproduction offer; duration 1, no target. Invalidates unfinished attempts using it; does not erase an already created individual."),
            ("reproduce", include_str!("../scripts/reproduce.rhai"), "with a target who mutually offered reproduction, remain together for 30000 ms; duration 1. Both exact offers must remain valid and both pay their quoted costs atomically. Creates one distinct dependent biological individual, consuming both offers; no possessions, private knowledge or mastery are inherited. Population renewal must be configured; finite retained-identity capacity applies."),
            ("fabricate", include_str!("../scripts/fabricate.rhai"), "at a local workshop, an independent character can spend 45000 ms, 6 carried food as nutrient material and 30 energy to create a distinct dependent artificial individual; duration 1. This representative artificial body still uses food; no charging or compute infrastructure is implied. Care and learning are still required; creation gives no obedience or inherited mastery."),
            ("care", include_str!("../scripts/care.rhai"), "provide one actual carried meal to a living dependent target at your cell; caregiver must be independent. Takes 3000 ms and 2 energy; recipient hunger must be at least 35 and falls by 35. Meal is consumed, not put in the recipient inventory. needs_care {target} checks your retained local observation; duration 1. This records support but does not alone grant self-support."),
            ("practice", include_str!("../scripts/practice.rhai"), "a dependent learner performs guided gathering with a living local target who previously cared for them; record selects a personally interpreted report whose typed location matches this cell. Takes 5000 ms and 4 energy; transfers one actual site food into the learner inventory. Default self-support requires age 60000 ms, two care meals and one successful practice. Independent characters use ordinary gather; duration 1."),
            (
                "attack",
                include_str!("../scripts/attack.rhai"),
                "perceived target at same position; costs 8 energy; deals 20 damage",
            ),
        ] {
            registry.insert(Definition {
                id: id.into(),
                revision: 1,
                source: source.into(),
                description: description.into(),
                dependencies: vec![],
            });
        }
        registry
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Invocation {
    pub definition: DefinitionRef,
    #[serde(default)]
    pub evaluated_ms: u64,
    #[serde(default)]
    pub wake_at_ms: u64,
    #[serde(default)]
    pub state: Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StepResult {
    #[serde(default)]
    pub wake_at_ms: Option<u64>,
    #[serde(default)]
    pub cooldown_until_ms: Option<u64>,
    pub status: crate::Status,
    pub reason: String,
    pub remaining: u32,
    pub state: Value,
    pub effects: Vec<Effect>,
    pub progress: Value,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Effect {
    Actor { fields: BTreeMap<String, i32> },
    SiteFood { value: i32 },
    TransferFood { target: Option<u32>, amount: i32 },
    SiteShelter { amount: i32 },
    Observe,
    Speech { text: String },
    Damage { target: u32, amount: i32 },
    Teach { target: u32, record: String },
    RecordKnowledge { archive: u32, record: String },
    ConsultKnowledge { archive: u32, record: String },
    DestroyArchive { archive: u32 },
    OfferReproduction { partner: u32, expires_ms: u64, food: i32, energy: i32 },
    WithdrawReproduction,
    Reproduce { partner: u32, own_offer: u64, partner_offer: u64 },
    Fabricate { food: i32, energy: i32 },
    Care { target: u32, energy: i32, nutrition: i32 },
    Practice { guide: u32, record: String, energy: i32 },
}

struct Compiled {
    engine: Engine,
    ast: AST,
}
thread_local! { static CACHE: RefCell<BTreeMap<String, Rc<Compiled>>> = RefCell::new(BTreeMap::new()); }

fn engine() -> Engine {
    let mut e = Engine::new_raw();
    rhai::packages::StandardPackage::new().register_into_engine(&mut e);
    e.set_max_operations(50_000);
    e.set_max_call_levels(24);
    e.set_max_expr_depths(32, 24);
    e.set_max_string_size(8_192);
    e.set_max_array_size(512);
    e.set_max_map_size(512);
    e.set_max_variables(128);
    for symbol in ["eval", "import", "print", "debug"] {
        e.disable_symbol(symbol);
    }
    e
}

fn compile(e: &Engine, source: &str) -> Result<AST, String> {
    if source.len() > MAX_SOURCE {
        return Err("script source exceeds 32 KiB".into());
    }
    // Content contract is functions only. No top-level code runs on installation or cache rebuild.
    e.compile(source)
        .map(|ast| ast.clone_functions_only())
        .map_err(|e| format!("script compile: {e}"))
}

// Explicit numeric conversion is essential: serde_json/arbitrary_precision serializes
// numbers through a private map token, which generic Serde-to-Rhai conversion preserves.
fn input_value(value: Value) -> Result<Dynamic, String> {
    Ok(match value {
        Value::Null => Dynamic::UNIT,
        Value::Bool(v) => v.into(),
        Value::String(v) => v.into(),
        Value::Number(v) => v
            .as_i64()
            .ok_or("script numbers must fit signed 64-bit integers")?
            .into(),
        Value::Array(v) => v
            .into_iter()
            .map(input_value)
            .collect::<Result<rhai::Array, _>>()?
            .into(),
        Value::Object(v) => v
            .into_iter()
            .map(|(k, v)| Ok((k.into(), input_value(v)?)))
            .collect::<Result<rhai::Map, String>>()?
            .into(),
    })
}

fn output_value(value: Dynamic, depth: usize, remaining: &mut usize) -> Result<Value, String> {
    if depth > 32 || *remaining == 0 {
        return Err("script output nesting/node budget exceeded".into());
    }
    *remaining -= 1;
    if value.is_unit() {
        return Ok(Value::Null);
    }
    if value.is::<bool>() {
        return Ok(json!(value.cast::<bool>()));
    }
    if value.is::<rhai::INT>() {
        return Ok(json!(value.cast::<rhai::INT>()));
    }
    if value.is::<rhai::ImmutableString>() {
        return Ok(json!(value.cast::<rhai::ImmutableString>().to_string()));
    }
    if value.is::<rhai::Array>() {
        return value
            .cast::<rhai::Array>()
            .into_iter()
            .map(|v| output_value(v, depth + 1, remaining))
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array);
    }
    if value.is::<rhai::Map>() {
        return value
            .cast::<rhai::Map>()
            .into_iter()
            .map(|(k, v)| Ok((k.to_string(), output_value(v, depth + 1, remaining)?)))
            .collect::<Result<serde_json::Map<String, Value>, String>>()
            .map(Value::Object);
    }
    Err("script output must be plain serializable data".into())
}

impl Registry {
    fn insert(&mut self, d: Definition) {
        self.active.insert(d.id.clone(), d.revision);
        self.history
            .entry(d.id.clone())
            .or_default()
            .insert(d.revision, d);
    }
    pub fn resolve(&self, id: &str) -> Result<DefinitionRef, String> {
        Ok(DefinitionRef {
            id: id.into(),
            revision: *self.active.get(id).ok_or("unknown scripted skill")?,
        })
    }
    fn definition(&self, r: &DefinitionRef) -> Result<&Definition, String> {
        self.history
            .get(&r.id)
            .and_then(|v| v.get(&r.revision))
            .ok_or("script revision unavailable".into())
    }
    fn dependencies<'a>(
        &'a self,
        d: &'a Definition,
        visiting: &mut BTreeSet<String>,
        result: &mut BTreeMap<String, &'a Definition>,
    ) -> Result<(), String> {
        if visiting.len() >= 16 || !visiting.insert(d.id.clone()) {
            return Err("cyclic or too-deep script dependencies".into());
        }
        for reference in &d.dependencies {
            if reference.id == "law" {
                return Err("laws are always resolved from the active revision".into());
            }
            let dep = self.definition(reference)?;
            if result
                .get(&dep.id)
                .is_some_and(|old| old.revision != dep.revision)
            {
                return Err("conflicting dependency revisions".into());
            }
            self.dependencies(dep, visiting, result)?;
            result.insert(dep.id.clone(), dep);
        }
        visiting.remove(&d.id);
        Ok(())
    }
    fn compiled(&self, r: &DefinitionRef) -> Result<Rc<Compiled>, String> {
        if self.api_version != API_VERSION {
            return Err("unsupported scripting API".into());
        }
        let definition = self.definition(r)?;
        let law = self.definition(&self.resolve("law")?)?;
        let mut dependencies = BTreeMap::new();
        self.dependencies(definition, &mut BTreeSet::new(), &mut dependencies)?;
        let key = format!(
            "{:x}",
            Sha256::digest(
                serde_json::to_vec(&(API_VERSION, definition, law, &dependencies))
                    .map_err(|e| e.to_string())?
            )
        );
        if let Some(value) = CACHE.with(|cache| cache.borrow().get(&key).cloned()) {
            return Ok(value);
        }
        let mut e = engine();
        let law_ast = compile(&e, &law.source)?;
        let module =
            rhai::Module::eval_ast_as_new(Scope::new(), &law_ast, &e).map_err(|e| e.to_string())?;
        e.register_static_module("law", module.into());
        for (id, dep) in dependencies {
            let ast = compile(&e, &dep.source)?;
            let module =
                rhai::Module::eval_ast_as_new(Scope::new(), &ast, &e).map_err(|e| e.to_string())?;
            e.register_static_module(id, module.into());
        }
        let ast = if r.id == "law" {
            law_ast
        } else {
            compile(&e, &definition.source)?
        };
        let compiled = Rc::new(Compiled { engine: e, ast });
        CACHE.with(|cache| {
            let mut cache = cache.borrow_mut();
            if cache.len() >= 32 {
                cache.clear();
            }
            cache.insert(key, compiled.clone());
        });
        Ok(compiled)
    }
    pub fn call<T: DeserializeOwned>(
        &self,
        reference: &DefinitionRef,
        function: &str,
        input: Value,
    ) -> Result<T, String> {
        if serde_json::to_vec(&input).map_err(|e| e.to_string())?.len() > MAX_VALUE {
            return Err("script input budget exceeded".into());
        }
        let compiled = self.compiled(reference)?;
        let input = input_value(input)?;
        let result: Dynamic = compiled
            .engine
            .call_fn(&mut Scope::new(), &compiled.ast, function, (input,))
            .map_err(|e| {
                format!(
                    "script {}@{}::{function}: {e}",
                    reference.id, reference.revision
                )
            })?;
        let result = output_value(result, 0, &mut 8_192)?;
        if serde_json::to_vec(&result)
            .map_err(|e| e.to_string())?
            .len()
            > MAX_VALUE
        {
            return Err("script output budget exceeded".into());
        }
        serde_json::from_value(result).map_err(|e| format!("script output contract: {e}"))
    }
    pub fn law<T: DeserializeOwned>(&self, function: &str, input: Value) -> Result<T, String> {
        self.call(&self.resolve("law")?, function, input)
    }
    pub fn validate_action(&self, action: &Action, actor: &Player) -> Result<(), String> {
        self.validate_action_on_map(action, actor, None)
    }
    pub fn validate_action_on_map(
        &self,
        action: &Action,
        actor: &Player,
        map: Option<&crate::spatial::Grid>,
    ) -> Result<(), String> {
        let reference = self.resolve(action.skill.id())?;
        if reference.id == "law" {
            return Err("world law is not a skill".into());
        }
        let reason: String = self.call(
            &reference,
            "validate",
            json!({"action":action,"actor":facts(actor),"map":map}),
        )?;
        if reason.is_empty() {
            Ok(())
        } else {
            Err(reason)
        }
    }
    pub fn stage(&mut self, update: Update, tick: u64) -> Result<(), String> {
        if update.api_version != API_VERSION
            || update.expected_revision != self.revision
            || self.pending.is_some()
        {
            return Err(
                "stale scripting revision, unsupported API, or update already pending".into(),
            );
        }
        if update.definitions.is_empty() || update.definitions.len() > 32 {
            return Err("script update needs 1..32 definitions".into());
        }
        let allowed: bool = self.law("authorize_update", json!({"operator":true}))?;
        if !allowed {
            return Err("active law denies this edit".into());
        }
        let mut next = self.clone();
        let mut seen = BTreeSet::new();
        for d in &update.definitions {
            if d.id.is_empty()
                || d.id.len() > 48
                || !d.id.bytes().all(|c| c.is_ascii_lowercase() || c == b'_')
                || !seen.insert(&d.id)
                || d.revision != self.active.get(&d.id).copied().unwrap_or(0) + 1
                || d.description.len() > 2_000
                || d.dependencies.len() > 8
            {
                return Err("invalid script identity, revision, or dependencies".into());
            }
            next.insert(d.clone());
        }
        if next.active.len() > 64
            || next.history.values().map(|v| v.len()).sum::<usize>() > 256
            || serde_json::to_vec(&next).map_err(|e| e.to_string())?.len() > MAX_CONTENT
        {
            return Err("script registry storage budget exceeded".into());
        }
        for d in &update.definitions {
            let compiled = next.compiled(&DefinitionRef {
                id: d.id.clone(),
                revision: d.revision,
            })?;
            let functions: BTreeSet<_> = compiled
                .ast
                .iter_functions()
                .map(|f| (f.name.to_owned(), f.params.len()))
                .collect();
            let required = if d.id == "law" {
                LAW_FUNCTIONS
            } else {
                &["validate", "step"][..]
            };
            if required
                .iter()
                .any(|name| !functions.contains(&(name.to_string(), 1)))
            {
                return Err("script is missing a required single-argument entry point".into());
            }
        }
        self.pending = Some(Pending {
            activate_tick: tick.checked_add(1).ok_or("tick overflow")?,
            definitions: update.definitions,
        });
        Ok(())
    }
    pub fn activate(&mut self, tick: u64) -> bool {
        if !self
            .pending
            .as_ref()
            .is_some_and(|p| p.activate_tick <= tick)
        {
            return false;
        }
        let pending = self.pending.take().unwrap();
        for d in pending.definitions {
            self.insert(d);
        }
        self.revision += 1;
        true
    }
    pub fn catalog(&self) -> Value {
        json!(self.active.iter().filter(|(id,_)| id.as_str() != "law").map(|(id,revision)| {
            json!({"id":id,"skill":{"script":id},"revision":revision,"description":self.history[id][revision].description})
        }).collect::<Vec<_>>())
    }
}

const LAW_FUNCTIONS: &[&str] = &[
    "needs_care",
    "development",
    "population_costs",
    "authorize_update",
    "cost",
    "validate_common",
    "metabolism",
    "aftermath",
    "on_damage",
    "reflection",
    "visible",
    "observation",
    "memory_limit",
    "reconsider_interval",
    "bootstrap",
    "guard",
    "validate_reflection",
    "authorize_effect",
    "validate_dialogue",
    "validate_condition",
    "system_periods_ms",
    "retry_delay_ms",
];

pub fn facts(p: &Player) -> Value {
    json!({"id":p.id,"position":p.position,"health":p.health,"hunger":p.hunger,"energy":p.energy,"food":p.food,"caution":p.caution,"empathy":p.empathy,"introspection":p.introspection,"fear":p.fear,"failures":p.failures})
}

pub fn subjective(p: &Player) -> Value {
    let mut value = facts(p);
    value["beliefs"] = json!(p.beliefs);
    // Policy guards need personal record IDs and observed resource quantities.
    // Full reports/catalogs remain in private model and human context, but cannot
    // expand this bounded interpreter input with every physical archive copy.
    let guard_percept = |m: &crate::Percept| {
        let mut v = json!(m);
        if m.kind == "knowledge_report" {
            v["content"] = json!({"record":{"id":m.content["record"]["id"]}});
        } else if m.kind == "site" {
            if let Some(content) = v["content"].as_object_mut() { content.remove("archives"); content.remove("lifecycle"); }
        }
        v
    };
    value["memories"] = json!(p.memories.iter().map(guard_percept).collect::<Vec<_>>());
    value["site_observations"] = json!(p.site_observations.iter().map(guard_percept).collect::<Vec<_>>());
    let mut care_observations: BTreeMap<u64, Value> = BTreeMap::new();
    for memory in &p.site_observations {
        for person in memory.content["lifecycle"]["people"].as_array().into_iter().flatten() {
            if let Some(id) = person["id"].as_u64() {
                if care_observations.get(&id).is_none_or(|old|old["source"].as_u64().unwrap_or(0) < memory.source) {
                    care_observations.insert(id,json!({"id":id,"location":memory.location,"source":memory.source,
                        "dependent":person["dependent"],"needs_care":person["needs_care"]}));
                }
            }
        }
    }
    value["care_observations"] = json!(care_observations.into_values().collect::<Vec<_>>());
    value["knowledge"] = json!(p.knowledge.iter().map(|h| json!({"record":{"id":h.record.id},"source":h.source})).collect::<Vec<_>>());
    value
}
