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

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
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
            ("infrastructure", include_str!("../scripts/infrastructure.rhai"), "Operate a local utility station with the typed infrastructure field. Requires local presence and asset rights; duration 1, 1000 ms cooldown. Electricity is separate from stamina; eating/rest do not recharge. Build/repair consume parts. Compute consumes electricity and cooling water per completed quantum and pauses on missing supply/access. Retrieve locally; retrieve_ready chooses your oldest completed uncollected job. Use once {child} around one submission. Prototype authors numeric Rhai after personally paid, retrieved and interpreted terminal work. PracticeProgram requires interpreted held code and a prediction. RunProgram requires your own interpreted successful exact-source experiment. Declare fn technique(input) followed by its body. Rhai functions are public by default; there is no pub keyword. Takes and returns at most 64 integers; source<=8192 bytes, helpers allowed, no top-level statements or globals. Read research facts for contracts and personal evidence. Code and private experiment reports are separate physical records, retrieved atomically. Teach code without private inputs. InspectProgram reads held source; reflecting on that inspection assesses the held code but does not grant paid practice. EraseJob removes terminal copies without refunds. PrototypeLaw/PracticeLaw test law-hook source and predictions through the same paid queue. InspectLaw reads held source; reflecting on it assesses that held code. InspectInstalledLaw reads locally operative source without granting a personal record. InstallLaw supplies scope, held record, evidence and expected revision/binding. Law research facts document precedence, contracts and authority. For forecast, numeric and law experiment sources, use at most eight unique ID strings from your own player.knowledge[].record.id, or [] for uncited assumptions; not prose or numeric experience source IDs. Operation schemas accompany the action contract."),
            ("give", include_str!("../scripts/give.rhai"), "give one carried food to a perceived living target at the same cell; recipient receives a direct perception; no automatic reciprocity; 1000 ms cooldown"),
            ("deposit", include_str!("../scripts/deposit.rhai"), "place one carried food in the existing site at your position, available for anyone to gather; 1000 ms cooldown"),
            ("build", include_str!("../scripts/build.rhai"), "contribute one shelter unit at the existing site at your position; costs 8 energy; shelter maximum 12, remains shared; 2500 ms cooldown"),
            ("observe", include_str!("../scripts/observe.rhai"), "refresh direct local site and nearby-character observations; 1000 ms cooldown"),
            ("teach", include_str!("../scripts/teach.rhai"), "teach one of your held knowledge record IDs to a living target at your cell; record and target required; takes 2000 ms and 2 energy. Transfers an unassessed report, not practical skill mastery. Does not consume your copy."),
            ("record", include_str!("../scripts/record.rhai"), "copy one of your held knowledge record IDs into an intact archive at your cell; record and archive IDs required; takes 2500 ms and 4 energy. Capacity limited; your own copy remains."),
            ("consult", include_str!("../scripts/consult.rhai"), "read a selected record ID from an intact archive at your cell into your own durable knowledge; archive and record IDs required; takes 1500 ms and 1 energy. Local site observations list archive catalogs but do not reveal record contents. Reading does not automatically establish truth or grant skill mastery."),
            ("reread_record", include_str!("../scripts/reread_record.rhai"), "reread a personally held record; record ID required, duration 1, takes 1500 ms and 1 energy. An acquisition source can age out of your retained trace while the copy remains. Rereading creates fresh personally citable knowledge_report evidence; then reflect on that new source. Preserves record identity, origin, ownership, copies and existing interpretation. Does not disclose executable source or grant practical capability."),
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
    #[serde(default)]
    pub law_binding: Option<crate::laws::LawBinding>,
    #[serde(default)]
    pub law_position: Option<i32>,
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
    Infrastructure { operation: crate::infrastructure::InfrastructureOperation },
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
    ReadRecord { record: String },
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
// The tag is created afresh for every invocation, never retained by a cached engine.
#[derive(Clone)]
struct ScopedLawCall {
    faults: Rc<RefCell<Vec<crate::laws::LawFault>>>,
    calls: Rc<std::cell::Cell<u32>>,
}
thread_local! { static CACHE: RefCell<BTreeMap<String, Rc<Compiled>>> = RefCell::new(BTreeMap::new()); }

// Exact semantic inputs, not revision IDs or addresses. Most actor hooks use
// the same law repeatedly; comparing immutable source bytes avoids allocating,
// JSON-encoding and hashing the entire source for every cache hit. All runtime
// faults and invocation budgets remain outside the compiled-artifact cache.
struct CachedLaw {
    law: Definition,
    layers: Vec<(crate::laws::LawRef, crate::laws::LawArtifact)>,
    disabled: Vec<crate::laws::LawDisabled>,
    compiled: Rc<Compiled>,
    source_bytes: usize,
}
thread_local! { static LAW_FAST_CACHE: RefCell<Vec<CachedLaw>> = const { RefCell::new(Vec::new()) }; }
fn remember_law(law: &Definition, layers: &[(crate::laws::LawRef, crate::laws::LawArtifact)],
    disabled: &[crate::laws::LawDisabled], compiled: &Rc<Compiled>) {
    const SOURCE_BUDGET: usize = 2 * MAX_CONTENT;
    let source_bytes = law.source.len() + law.description.len()
        + layers.iter().map(|(_, a)| a.source.len()).sum::<usize>();
    if source_bytes > SOURCE_BUDGET { return; }
    LAW_FAST_CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        while cache.len() >= 8 || cache.iter().map(|c| c.source_bytes).sum::<usize>() + source_bytes > SOURCE_BUDGET {
            cache.remove(0);
        }
        cache.push(CachedLaw { law: law.clone(), layers: layers.to_vec(), disabled: disabled.to_vec(),
            compiled: compiled.clone(), source_bytes });
    });
}

struct CachedScript {
    definition: Definition,
    law: Definition,
    dependencies: BTreeMap<String, Definition>,
    compiled: Rc<Compiled>,
    source_bytes: usize,
}
thread_local! { static SCRIPT_FAST_CACHE: RefCell<Vec<CachedScript>> = const { RefCell::new(Vec::new()) }; }
fn remember_script(definition: &Definition, law: &Definition, dependencies: &BTreeMap<String, &Definition>,
    compiled: &Rc<Compiled>) {
    const SOURCE_BUDGET: usize = 2 * MAX_CONTENT;
    let source_bytes = definition.source.len() + definition.description.len() + law.source.len() + law.description.len()
        + dependencies.values().map(|d| d.source.len() + d.description.len()).sum::<usize>();
    if source_bytes > SOURCE_BUDGET { return; }
    SCRIPT_FAST_CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        while cache.len() >= 8 || cache.iter().map(|c| c.source_bytes).sum::<usize>() + source_bytes > SOURCE_BUDGET {
            cache.remove(0);
        }
        cache.push(CachedScript { definition: definition.clone(), law: law.clone(),
            dependencies: dependencies.iter().map(|(k, d)| (k.clone(), (*d).clone())).collect(),
            compiled: compiled.clone(), source_bytes });
    });
}

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
        if let Some(compiled) = SCRIPT_FAST_CACHE.with(|cache| cache.borrow().iter().rev()
            .find(|c| c.definition == *definition && c.law == *law && c.dependencies.len() == dependencies.len()
                && c.dependencies.iter().all(|(key, value)| dependencies.get(key).is_some_and(|current| value == *current)))
            .map(|c| c.compiled.clone())) {
            return Ok(compiled);
        }
        let key = format!(
            "{:x}",
            Sha256::digest(
                serde_json::to_vec(&(API_VERSION, definition, law, &dependencies))
                    .map_err(|e| e.to_string())?
            )
        );
        if let Some(value) = CACHE.with(|cache| cache.borrow().get(&key).cloned()) {
            remember_script(definition, law, &dependencies, &value);
            return Ok(value);
        }
        let mut e = engine();
        let law_ast = compile(&e, &law.source)?;
        let module =
            rhai::Module::eval_ast_as_new(Scope::new(), &law_ast, &e).map_err(|e| e.to_string())?;
        e.register_static_module("law", module.into());
        for (id, dep) in &dependencies {
            let ast = compile(&e, &dep.source)?;
            let module =
                rhai::Module::eval_ast_as_new(Scope::new(), &ast, &e).map_err(|e| e.to_string())?;
            e.register_static_module(id.clone(), module.into());
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
        remember_script(definition, law, &dependencies, &compiled);
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
    "authorize_law_edit",
    "food_renewal",
    "action_interval_ms",
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
    "research_authoring",
    "research_use",
];

pub fn facts(p: &Player) -> Value {
    json!({"id":p.id,"position":p.position,"health":p.health,"hunger":p.hunger,"energy":p.energy,"food":p.food,"caution":p.caution,"empathy":p.empathy,"introspection":p.introspection,"fear":p.fear,"failures":p.failures})
}

pub fn subjective(p: &Player) -> Value {
    let mut value = facts(p);
    value["charge"] = json!(0);
    value["beliefs"] = json!(p.beliefs);
    // Policy guards need personal record IDs and observed resource quantities.
    // Full reports/catalogs remain in private model and human context, but cannot
    // expand this bounded interpreter input with every physical archive copy.
    let guard_percept = |m: &crate::Percept| {
        let mut v = json!(m);
        if m.kind == "program_inspected" || m.kind == "law_inspected" {
            v["content"] = json!({"record":m.content["record"],"program_hash":m.content["program"]["source_hash"],"law_hash":m.content["law_program"]["source_hash"]});
        } else if m.kind == "knowledge_report" {
            v["content"] = json!({"record":{"id":m.content["record"]["id"]}});
        } else if m.kind == "site" {
            if let Some(content) = v["content"].as_object_mut() { content.remove("archives"); content.remove("lifecycle"); content.remove("infrastructure"); }
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

/// Strict participant law compiler. Unlike operator content, unused top-level
/// statements are rejected rather than silently stripped.
pub(crate) fn compile_participant_law(source: &str) -> Result<AST, String> {
    let mut e = engine();
    e.set_strict_variables(true);
    e.set_optimization_level(rhai::OptimizationLevel::None);
    e.set_allow_anonymous_fn(false);
    for symbol in ["export", "Fn", "call", "curry"] {
        e.disable_symbol(symbol);
    }
    let ast = e.compile(source).map_err(|e| format!("law compile: {e}"))?;
    fn statements<T>(ast: &impl AsRef<[T]>) -> bool {
        !ast.as_ref().is_empty()
    }
    if statements(&ast) {
        return Err(
            "law source must contain only hook functions; top-level statements are forbidden"
                .into(),
        );
    }
    Ok(ast.clone_functions_only())
}
impl Registry {
    fn compiled_laws(
        &self,
        base: &DefinitionRef,
        layers: &[(crate::laws::LawRef, crate::laws::LawArtifact)],
        faults: &[crate::laws::LawDisabled],
    ) -> Result<Rc<Compiled>, String> {
        let law = self.definition(base)?;
        if let Some(compiled) = LAW_FAST_CACHE.with(|cache| cache.borrow().iter().rev()
            .find(|c| c.law == *law && c.layers == layers && c.disabled == faults)
            .map(|c| c.compiled.clone())) {
            return Ok(compiled);
        }
        let excluded: Vec<_> = faults.iter().map(|f| (&f.reference, &f.hook)).collect();
        let key = format!(
            "layered:{:x}",
            Sha256::digest(
                serde_json::to_vec(&(API_VERSION, law, layers, excluded))
                    .map_err(|e| e.to_string())?
            )
        );
        if let Some(c) = CACHE.with(|c| c.borrow().get(&key).cloned()) {
            remember_law(law, layers, faults, &c);
            return Ok(c);
        }
        let mut e = engine();
        e.set_allow_anonymous_fn(false);
        for symbol in ["export", "Fn", "call", "curry"] {
            e.disable_symbol(symbol);
        }
        let mut ast = compile(&e, &law.source)?;
        for (reference, artifact) in layers {
            crate::laws::validate(artifact)?;
            let mut patch = compile_participant_law(&artifact.source)?;
            patch.retain_functions(|_, _, name, _| {
                !faults
                    .iter()
                    .any(|f| f.reference == *reference && f.hook == name)
            });
            ast.combine(patch);
        }
        let c = Rc::new(Compiled { engine: e, ast });
        CACHE.with(|cache| {
            let mut cache = cache.borrow_mut();
            if cache.len() >= 64 {
                cache.clear();
            }
            cache.insert(key, c.clone());
        });
        remember_law(law, layers, faults, &c);
        Ok(c)
    }
    pub(crate) fn evaluate_law_candidate(
        &self,
        base: &DefinitionRef,
        layers: &[(crate::laws::LawRef, crate::laws::LawArtifact)],
        faults: &[crate::laws::LawDisabled],
        hook: &str,
        input: Value,
    ) -> Result<Value, String> {
        let compiled = self.compiled_laws(base, layers, faults)?;
        Self::call_compiled(&compiled, hook, input)
    }
    fn call_compiled(compiled: &Compiled, hook: &str, input: Value) -> Result<Value, String> {
        if serde_json::to_vec(&input).map_err(|e| e.to_string())?.len() > MAX_VALUE {
            return Err("script input budget exceeded".into());
        }
        let original_input = input.clone();
        let result = compiled
            .engine
            .call_fn_with_options::<Dynamic>(
                rhai::CallFnOptions::new().eval_ast(false),
                &mut Scope::new(),
                &compiled.ast,
                hook,
                (input_value(input)?,),
            )
            .map_err(|e| e.to_string().chars().take(512).collect::<String>())?;
        let v = output_value(result, 0, &mut 4096)?;
        if serde_json::to_vec(&v).map_err(|e| e.to_string())?.len() > MAX_VALUE {
            return Err("script output budget exceeded".into());
        }
        crate::laws::validate_output(hook, &v)?;
        if hook == "food_renewal"
            && original_input["food"]
                .as_i64()
                .zip(v.as_i64())
                .is_some_and(|(food, growth)| {
                    food.checked_add(growth).is_none_or(|n| n > 1_000_000)
                })
        {
            return Err("food production exceeds physical storage budget".into());
        }
        Ok(v)
    }
    pub(crate) fn call_law_layers(
        &self,
        base: &DefinitionRef,
        layers: &[(crate::laws::LawRef, crate::laws::LawArtifact)],
        faults: &mut Vec<crate::laws::LawFault>,
        hook: &str,
        input: Value,
    ) -> Result<Value, String> {
        for _ in 0..=layers.len() {
            let winner = layers
                .iter()
                .rev()
                .find(|(r, a)| {
                    a.hooks.iter().any(|h| h == hook)
                        && !faults.iter().any(|f| f.reference == *r && f.hook == hook)
                })
                .map(|(r, _)| r.clone());
            let disabled = faults
                .iter()
                .map(|f| crate::laws::LawDisabled {
                    reference: f.reference.clone(),
                    hook: f.hook.clone(),
                })
                .collect::<Vec<_>>();
            let outcome = self
                .compiled_laws(base, layers, &disabled)
                .and_then(|compiled| Self::call_compiled(&compiled, hook, input.clone()));
            match outcome {
                Ok(v) => return Ok(v),
                Err(error) => {
                    if let Some(reference) = winner {
                        faults.push(crate::laws::LawFault {
                            reference,
                            hook: hook.into(),
                            error,
                        });
                    } else {
                        return Err(error);
                    }
                }
            }
        }
        Err("law fallback depth exceeded".into())
    }
    fn compiled_scoped_skill(
        &self,
        reference: &DefinitionRef,
        base: &DefinitionRef,
        layers: &[(crate::laws::LawRef, crate::laws::LawArtifact)],
    ) -> Result<Rc<Compiled>, String> {
        if self.api_version != API_VERSION {
            return Err("unsupported scripting API".into());
        }
        let definition = self.definition(reference)?;
        let law = self.definition(base)?;
        let mut dependencies = BTreeMap::new();
        self.dependencies(definition, &mut BTreeSet::new(), &mut dependencies)?;
        // References alone are insufficient across independently restored worlds.
        // Include exact source and dependency contents, as in the unscoped cache.
        let key = format!(
            "scoped:{:x}",
            Sha256::digest(
                serde_json::to_vec(&(API_VERSION, definition, law, &dependencies, layers))
                    .map_err(|e| e.to_string())?
            )
        );
        if let Some(compiled) = CACHE.with(|cache| cache.borrow().get(&key).cloned()) {
            return Ok(compiled);
        }
        // Dispatch needs only the pinned base definition, not registry history or
        // any world state. Layers and this minimal registry are immutable.
        let mut registry = Registry {
            api_version: API_VERSION,
            revision: 0,
            active: BTreeMap::new(),
            history: BTreeMap::new(),
            pending: None,
        };
        registry.insert(law.clone());
        let base_ref = base.clone();
        let layers = layers.to_vec();
        let mut e = engine();
        e.register_fn(
            "scoped_law_dispatch",
            move |context: rhai::NativeCallContext,
                  hook: rhai::ImmutableString,
                  arg: Dynamic|
                  -> Result<Dynamic, Box<rhai::EvalAltResult>> {
                let state = context
                    .tag()
                    .and_then(|tag| tag.clone().try_cast::<ScopedLawCall>())
                    .ok_or_else(|| {
                        Box::<rhai::EvalAltResult>::from("missing scoped law invocation")
                    })?;
                state.calls.set(state.calls.get() + 1);
                if state.calls.get() > 128 {
                    return Err("law call budget exceeded".into());
                }
                let v = output_value(arg, 0, &mut 4096)
                    .map_err(|e| Box::<rhai::EvalAltResult>::from(e))?;
                let result = registry
                    .call_law_layers(
                        &base_ref,
                        &layers,
                        &mut state.faults.borrow_mut(),
                        hook.as_str(),
                        v,
                    )
                    .map_err(|e| Box::<rhai::EvalAltResult>::from(e))?;
                input_value(result).map_err(|e| e.into())
            },
        );
        let mut law_ast = self.compiled_laws(base, &[], &[])?.ast.clone();
        let wrappers = crate::laws::HOOKS
            .iter()
            .map(|h| format!("fn {h}(c) {{ scoped_law_dispatch(\"{h}\",c) }}"))
            .collect::<Vec<_>>()
            .join("\n");
        law_ast.combine(compile(&e, &wrappers)?);
        let module =
            rhai::Module::eval_ast_as_new(Scope::new(), &law_ast, &e).map_err(|e| e.to_string())?;
        e.register_static_module("law", module.into());
        for (id, dep) in dependencies {
            let ast = compile(&e, &dep.source)?;
            let module =
                rhai::Module::eval_ast_as_new(Scope::new(), &ast, &e).map_err(|e| e.to_string())?;
            e.register_static_module(id, module.into());
        }
        let ast = compile(&e, &definition.source)?;
        let compiled = Rc::new(Compiled { engine: e, ast });
        CACHE.with(|cache| {
            let mut cache = cache.borrow_mut();
            if cache.len() >= 64 {
                cache.clear();
            }
            cache.insert(key, compiled.clone());
        });
        Ok(compiled)
    }

    /// Cached engines contain only immutable definitions. Faults and native-call
    /// budgets travel in an invocation-local tag, including on error paths.
    pub(crate) fn call_scoped_skill<T: DeserializeOwned>(
        &self,
        reference: &DefinitionRef,
        base: &DefinitionRef,
        layers: &[(crate::laws::LawRef, crate::laws::LawArtifact)],
        faults: &mut Vec<crate::laws::LawFault>,
        function: &str,
        input: Value,
    ) -> Result<T, String> {
        if serde_json::to_vec(&input).map_err(|e| e.to_string())?.len() > MAX_VALUE {
            return Err("script input budget exceeded".into());
        }
        if layers.is_empty() && self.resolve("law")? == *base {
            return self.call(reference, function, input);
        }
        let compiled = self.compiled_scoped_skill(reference, base, layers)?;
        let collected = Rc::new(RefCell::new(faults.clone()));
        let state = ScopedLawCall {
            faults: collected.clone(),
            calls: Rc::new(std::cell::Cell::new(0)),
        };
        let outcome = compiled
            .engine
            .call_fn_with_options::<Dynamic>(
                rhai::CallFnOptions::new().eval_ast(false).with_tag(state),
                &mut Scope::new(),
                &compiled.ast,
                function,
                (input_value(input)?,),
            )
            .map_err(|e| e.to_string());
        *faults = collected.borrow().clone();
        let value = output_value(outcome?, 0, &mut 4096)?;
        if serde_json::to_vec(&value).map_err(|e| e.to_string())?.len() > MAX_VALUE {
            return Err("script output budget exceeded".into());
        }
        serde_json::from_value(value).map_err(|e| format!("script result contract: {e}"))
    }
}

#[cfg(test)]
mod scoped_cache_tests {
    use super::*;
    use crate::laws::{LawArtifact, LawDraft, LawFault, LawRef, LawScope};

    fn fixture() -> (
        Registry,
        DefinitionRef,
        DefinitionRef,
        Vec<(LawRef, LawArtifact)>,
    ) {
        let mut registry = Registry::default();
        registry.insert(Definition {
            id: "cache_probe".into(),
            revision: 1,
            source: "fn run(x) { law::cost(x) }".into(),
            description: String::new(),
            dependencies: vec![],
        });
        let skill = registry.resolve("cache_probe").unwrap();
        let base = registry.resolve("law").unwrap();
        let layers = vec![(
            LawRef {
                scope: LawScope::Universal,
                revision: 1,
            },
            crate::laws::compile(&LawDraft {
                interface_version: 1,
                source: "fn cost(x) { 17 }".into(),
            })
            .unwrap(),
        )];
        (registry, skill, base, layers)
    }

    fn run(
        registry: &Registry,
        skill: &DefinitionRef,
        base: &DefinitionRef,
        layers: &[(LawRef, LawArtifact)],
        faults: &mut Vec<LawFault>,
    ) -> Result<i64, String> {
        registry.call_scoped_skill(skill, base, layers, faults, "run", json!("gather"))
    }

    #[test]
    fn scoped_cache_uses_exact_sources_and_dependencies() {
        let (mut registry, skill, base, mut layers) = fixture();
        let mut faults = vec![];
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            17
        );
        layers[0].1 = crate::laws::compile(&LawDraft {
            interface_version: 1,
            source: "fn cost(x) { 19 }".into(),
        })
        .unwrap();
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            19
        );
        registry
            .history
            .get_mut("cache_probe")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = "fn run(x) { law::cost(x) + 1 }".into();
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            20
        );
        registry.insert(Definition {
            id: "helper".into(),
            revision: 1,
            source: "fn number() { 3 }".into(),
            description: String::new(),
            dependencies: vec![],
        });
        let probe = registry
            .history
            .get_mut("cache_probe")
            .unwrap()
            .get_mut(&1)
            .unwrap();
        probe.dependencies = vec![DefinitionRef {
            id: "helper".into(),
            revision: 1,
        }];
        probe.source = "fn run(x) { law::cost(x) + helper::number() }".into();
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            22
        );
        registry
            .history
            .get_mut("helper")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = "fn number() { 5 }".into();
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            24
        );
        // Base source must matter even if an overlay is present but does not implement cost.
        layers[0].1 = crate::laws::compile(&LawDraft {
            interface_version: 1,
            source: "fn action_interval_ms(x) { 1000 }".into(),
        })
        .unwrap();
        registry
            .history
            .get_mut("law")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = "fn cost(x) { 7 }".into();
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            12
        );
        registry
            .history
            .get_mut("law")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = "fn cost(x) { 8 }".into();
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut faults).unwrap(),
            13
        );
    }

    #[test]
    fn unscoped_fast_cache_tracks_exact_sources_dependencies_and_bounds() {
        let (mut registry, skill, base, _) = fixture();
        let mut faults = vec![];
        registry.history.get_mut("cache_probe").unwrap().get_mut(&1).unwrap().source = "fn run(x) { 3 }".into();
        assert_eq!(run(&registry, &skill, &base, &[], &mut faults).unwrap(), 3);
        registry.history.get_mut("cache_probe").unwrap().get_mut(&1).unwrap().source = "fn run(x) { 4 }".into();
        assert_eq!(run(&registry, &skill, &base, &[], &mut faults).unwrap(), 4);
        registry.insert(Definition { id: "helper".into(), revision: 1, source: "fn number() { 5 }".into(),
            description: String::new(), dependencies: vec![] });
        let probe = registry.history.get_mut("cache_probe").unwrap().get_mut(&1).unwrap();
        probe.source = "fn run(x) { helper::number() }".into();
        probe.dependencies = vec![DefinitionRef { id: "helper".into(), revision: 1 }];
        assert_eq!(run(&registry, &skill, &base, &[], &mut faults).unwrap(), 5);
        registry.history.get_mut("helper").unwrap().get_mut(&1).unwrap().source = "fn number() { 6 }".into();
        assert_eq!(run(&registry, &skill, &base, &[], &mut faults).unwrap(), 6);
        for n in 0..12 {
            registry.history.get_mut("helper").unwrap().get_mut(&1).unwrap().source = format!("fn number() {{ {n} }}");
            assert_eq!(run(&registry, &skill, &base, &[], &mut faults).unwrap(), n);
        }
        SCRIPT_FAST_CACHE.with(|c| {
            assert!(c.borrow().len() <= 8);
            assert!(c.borrow().iter().map(|e| e.source_bytes).sum::<usize>() <= 2 * MAX_CONTENT);
        });
    }

    #[test]
    fn scoped_cache_keeps_faults_and_call_budget_per_invocation() {
        let (mut registry, skill, base, layers) = fixture();
        let mut quarantined = vec![LawFault {
            reference: layers[0].0.clone(),
            hook: "cost".into(),
            error: "earlier fault".into(),
        }];
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut quarantined).unwrap(),
            4
        );
        let mut fresh = vec![];
        assert_eq!(
            run(&registry, &skill, &base, &layers, &mut fresh).unwrap(),
            17
        );
        assert!(fresh.is_empty());
        registry
            .history
            .get_mut("cache_probe")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source =
            "fn run(x) { let result = 0; for n in 0..128 { result = law::cost(x); } result }"
                .into();
        for _ in 0..2 {
            assert_eq!(
                run(&registry, &skill, &base, &layers, &mut fresh).unwrap(),
                17
            );
        }
        registry
            .history
            .get_mut("cache_probe")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = "fn run(x) { for n in 0..129 { law::cost(x); } 0 }".into();
        assert!(run(&registry, &skill, &base, &layers, &mut fresh)
            .unwrap_err()
            .contains("law call budget exceeded"));
        let mut broken = layers.clone();
        broken[0].1 = crate::laws::compile(&LawDraft {
            interface_version: 1,
            source: "fn cost(x) { 1 / 0 }".into(),
        })
        .unwrap();
        registry
            .history
            .get_mut("cache_probe")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = "fn run(x) { law::cost(x) }".into();
        for _ in 0..2 {
            let mut independent = vec![];
            assert_eq!(
                run(&registry, &skill, &base, &broken, &mut independent).unwrap(),
                4
            );
            assert_eq!(independent.len(), 1);
        }
        assert!(fresh.is_empty());
    }

    #[test]
    #[ignore = "manual scoped invocation performance comparison"]
    fn scoped_invocation_benchmark() {
        let (registry, skill, base, layers) = fixture();
        for (name, active) in [
            ("no_overlay", &[][..]),
            ("active_overlay", layers.as_slice()),
        ] {
            let mut faults = vec![];
            run(&registry, &skill, &base, active, &mut faults).unwrap();
            let start = std::time::Instant::now();
            for _ in 0..1000 {
                std::hint::black_box(run(&registry, &skill, &base, active, &mut faults).unwrap());
            }
            eprintln!(
                "scoped_invocation_benchmark {name}: {} us / 1000 calls",
                start.elapsed().as_micros()
            );
        }
    }
}
