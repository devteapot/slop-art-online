//! Material infrastructure. Public local equipment is distinct from private queued inputs/results.
//! Pure computation can transform supplied assertions, never inspect the world or apply effects.
use crate::*;
use rhai::packages::Package;
use scripting::Effect;
use sha2::{Digest, Sha256};

const MAX_STATIONS: usize = 32;
const MAX_JOBS: usize = 64;
const MAX_STOCK: i32 = 1_000_000;
const FORECAST_PROGRAM: &str = "fn forecast(c) { let net = c.inflow_per_min - c.demand_per_min; let projected = c.stock + net * c.horizon_ms / 60000; #{ projected_stock: projected, residual: if projected > 0 { projected } else { 0 }, shortfall: if projected < 0 { -projected } else { 0 } } }";

#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum Material {
    Parts,
    Water,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum Module {
    Generator,
    Charger,
    Terminal,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default, deny_unknown_fields)]
pub struct Materials {
    pub parts: i32,
    pub water: i32,
}
impl Materials {
    fn get(&self, m: Material) -> i32 {
        match m {
            Material::Parts => self.parts,
            Material::Water => self.water,
        }
    }
    fn add(&mut self, m: Material, amount: i32) {
        match m {
            Material::Parts => self.parts += amount,
            Material::Water => self.water += amount,
        }
    }
    fn valid(&self) -> bool {
        (0..=MAX_STOCK).contains(&self.parts) && (0..=MAX_STOCK).contains(&self.water)
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default, deny_unknown_fields)]
pub struct Rights {
    pub use_allowed: bool,
    pub maintain: bool,
    pub admin: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Support {
    Nutrient,
    Electric,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BodyProfile {
    pub version: u32,
    pub support: Support,
    pub capacity: i32,
    pub initial_charge: i32,
    pub drain_per_pulse: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BodyState {
    pub profile: BodyProfile,
    pub charge: i32,
    #[serde(default)]
    pub unpaid_support_pulses_since_hazard: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct InfrastructureBalance {
    pub version: u32,
    pub build_parts: BTreeMap<Module, i32>,
    pub repair_per_part: i32,
    pub electricity_per_charge: i32,
    pub compute_electricity: i32,
    pub compute_water: i32,
    pub compute_quanta: u32,
    pub compute_quantum_ms: u64,
    pub wear_per_quantum: i32,
    pub support_care_min_charge: i32,
}
impl Default for InfrastructureBalance {
    fn default() -> Self {
        Self {
            version: 1,
            build_parts: [
                (Module::Generator, 6),
                (Module::Charger, 3),
                (Module::Terminal, 5),
            ]
            .into(),
            repair_per_part: 20,
            electricity_per_charge: 1,
            compute_electricity: 2,
            compute_water: 1,
            compute_quanta: 3,
            compute_quantum_ms: 1000,
            wear_per_quantum: 1,
            support_care_min_charge: 20,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StationSeed {
    pub id: u32,
    pub owner: u32,
    pub position: i32,
    pub label: String,
    pub electricity: i32,
    pub electricity_capacity: i32,
    #[serde(default)]
    pub materials: Materials,
    #[serde(default)]
    pub modules: Vec<Module>,
    #[serde(default)]
    pub access: BTreeMap<u32, Rights>,
    pub generation_period_ms: u64,
    pub generation_amount: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InfrastructureSeed {
    pub version: u32,
    #[serde(default)]
    pub balance: InfrastructureBalance,
    #[serde(default)]
    pub bodies: BTreeMap<u32, BodyProfile>,
    #[serde(default)]
    pub actor_materials: BTreeMap<u32, Materials>,
    #[serde(default)]
    pub stations: Vec<StationSeed>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Station {
    pub seed: StationSeed,
    pub enabled: bool,
    pub integrity: i32,
    pub embodied_parts: i32,
    pub repair_parts_consumed: i32,
    pub generation_remainder_ms: u64,
    pub compute_remainder_ms: u64,
    pub jobs: Vec<ComputeJob>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct InfrastructureState {
    pub balance: InfrastructureBalance,
    pub bodies: BTreeMap<u32, BodyState>,
    pub actor_materials: BTreeMap<u32, Materials>,
    pub stations: Vec<Station>,
    pub next_job: u64,
}
impl Default for InfrastructureState {
    fn default() -> Self {
        Self {
            balance: InfrastructureBalance::default(),
            bodies: BTreeMap::new(),
            actor_materials: BTreeMap::new(),
            stations: vec![],
            next_job: 1,
        }
    }
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ForecastInput {
    pub stock: i32,
    pub inflow_per_min: i32,
    pub demand_per_min: i32,
    pub horizon_ms: u64,
    #[serde(default)]
    pub sources: Vec<String>,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum InfrastructureOperation {
    TakeMaterial {
        station: u32,
        material: Material,
        amount: i32,
    },
    DepositMaterial {
        station: u32,
        material: Material,
        amount: i32,
    },
    Build {
        station: u32,
        module: Module,
    },
    Repair {
        station: u32,
        parts: i32,
    },
    Charge {
        station: u32,
        amount: i32,
    },
    SupportCharge {
        station: u32,
        target: u32,
        amount: i32,
    },
    SetAccess {
        station: u32,
        actor: u32,
        use_allowed: bool,
        maintain: bool,
        admin: bool,
    },
    SetEnabled {
        station: u32,
        enabled: bool,
    },
    SubmitJob {
        station: u32,
        input: ForecastInput,
    },
    CancelJob {
        station: u32,
        job: u64,
    },
    RetrieveJob {
        station: u32,
        job: u64,
    },
    RetrieveReady {
        station: u32,
    },
}
impl InfrastructureOperation {
    pub fn station(&self) -> u32 {
        match self {
            Self::TakeMaterial { station, .. }
            | Self::DepositMaterial { station, .. }
            | Self::Build { station, .. }
            | Self::Repair { station, .. }
            | Self::Charge { station, .. }
            | Self::SupportCharge { station, .. }
            | Self::SetAccess { station, .. }
            | Self::SetEnabled { station, .. }
            | Self::SubmitJob { station, .. }
            | Self::CancelJob { station, .. }
            | Self::RetrieveJob { station, .. } => *station,
            Self::RetrieveReady { station } => *station,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComputeJob {
    pub id: u64,
    pub owner: u32,
    pub submitted_ms: u64,
    pub source: u64,
    pub input: ForecastInput,
    pub input_hash: String,
    pub sources: Vec<knowledge::Record>,
    pub progress: u32,
    pub required: u32,
    pub last_quantum_ms: Option<u64>,
    pub report: Option<knowledge::Record>,
    pub retrieved: bool,
    #[serde(default)]
    pub blocked_reason: Option<String>,
    #[serde(default)]
    pub cancelled: bool,
}

impl World {
    pub(super) fn initialize_infrastructure(&mut self, cause: u64) -> Result<(), String> {
        let Some(seed) = self.initial.infrastructure.clone() else {
            return Ok(());
        };
        let b = &seed.balance;
        if seed.version != 1
            || b.version != 1
            || seed.stations.len() > MAX_STATIONS
            || b.build_parts.len() != 3
            || [Module::Generator, Module::Charger, Module::Terminal]
                .iter()
                .any(|m| {
                    !b.build_parts
                        .get(m)
                        .is_some_and(|v| (1..=10000).contains(v))
                })
            || !(1..=100).contains(&b.repair_per_part)
            || !(1..=100).contains(&b.electricity_per_charge)
            || !(1..=10000).contains(&b.compute_electricity)
            || !(1..=10000).contains(&b.compute_water)
            || !(1..=100).contains(&b.compute_quanta)
            || !(50..=60000).contains(&b.compute_quantum_ms)
            || !(0..=100).contains(&b.wear_per_quantum)
            || !(1..=10000).contains(&b.support_care_min_charge)
        {
            return Err("invalid infrastructure version, limits, or balance".into());
        }
        for (&actor, profile) in &seed.bodies {
            self.idx(actor)?;
            if profile.version != 1
                || !(1..=10000).contains(&profile.capacity)
                || !(0..=profile.capacity).contains(&profile.initial_charge)
                || !(1..=100).contains(&profile.drain_per_pulse)
            {
                return Err("invalid versioned body support profile".into());
            }
        }
        for (&actor, materials) in &seed.actor_materials {
            self.idx(actor)?;
            if !materials.valid() {
                return Err("invalid initial carried materials".into());
            }
        }
        let mut ids = std::collections::BTreeSet::new();
        for s in &seed.stations {
            self.idx(s.owner)?;
            if !ids.insert(s.id)
                || s.id == 0
                || s.label.trim().is_empty()
                || s.label.chars().count() > 100
                || !spatial::walkable(self.map_for_actor(s.owner).as_ref(), s.position)
                || !(1..=MAX_STOCK).contains(&s.electricity_capacity)
                || !(0..=s.electricity_capacity).contains(&s.electricity)
                || !s.materials.valid()
                || !(50..=3_600_000).contains(&s.generation_period_ms)
                || !(1..=10000).contains(&s.generation_amount)
                || s.modules.len() > 3
                || s.modules
                    .iter()
                    .collect::<std::collections::BTreeSet<_>>()
                    .len()
                    != s.modules.len()
            {
                return Err("invalid infrastructure station seed".into());
            }
            for actor in s.access.keys() {
                self.idx(*actor)?;
                if !self.same_arena(s.owner, *actor) {
                    return Err("station rights cross arena boundary".into());
                }
            }
        }
        self.infrastructure.balance = seed.balance;
        self.infrastructure.actor_materials = seed.actor_materials;
        for (actor, profile) in seed.bodies {
            let charge = profile.initial_charge;
            if profile.support == Support::Electric {
                let i = self.idx(actor)?;
                self.players[i].hunger = 0;
                if let Some(life) = self.lifecycle.get_mut(&actor) {
                    life.body = lifecycle::BodyKind::Artificial;
                }
            }
            self.infrastructure.bodies.insert(
                actor,
                BodyState {
                    profile,
                    charge,
                    unpaid_support_pulses_since_hazard: 0,
                },
            );
        }
        self.infrastructure.stations = seed
            .stations
            .into_iter()
            .map(|mut seed| {
                seed.access.insert(
                    seed.owner,
                    Rights {
                        use_allowed: true,
                        maintain: true,
                        admin: true,
                    },
                );
                Station {
                    enabled: true,
                    integrity: 100,
                    embodied_parts: seed
                        .modules
                        .iter()
                        .map(|m| self.infrastructure.balance.build_parts[m])
                        .sum(),
                    repair_parts_consumed: 0,
                    generation_remainder_ms: 0,
                    compute_remainder_ms: 0,
                    jobs: vec![],
                    seed,
                }
            })
            .collect();
        self.event(None, "infrastructure_initialized", vec![cause], json!({"version":1,"balance":self.infrastructure.balance,"bodies":self.infrastructure.bodies,"stations":self.infrastructure.stations,"actor_materials":self.infrastructure.actor_materials,"meaning":"Initial endowed stocks and equipment; generation and consumption are separately recorded"}));
        Ok(())
    }
    pub(super) fn body_support_context(&self, actor: u32) -> Value {
        self.infrastructure.bodies.get(&actor).map(|body| json!({"support":body.profile.support,"version":body.profile.version,"charge":body.charge,"capacity":body.profile.capacity,"drain_per_pulse":body.profile.drain_per_pulse,"unpaid_support_pulses":body.unpaid_support_pulses_since_hazard})).unwrap_or_else(|| json!({"support":"nutrient","version":1}))
    }
    pub(super) fn consume_body_charge(
        &mut self,
        actor: u32,
        pulses: u64,
        parent: u64,
    ) -> Result<(), String> {
        if pulses == 0 {
            return Ok(());
        }
        let Some(body) = self.infrastructure.bodies.get_mut(&actor) else {
            return Ok(());
        };
        if body.profile.support != Support::Electric {
            return Ok(());
        }
        let funded = if body.profile.drain_per_pulse <= 0 {
            pulses
        } else {
            pulses.min(body.charge as u64 / body.profile.drain_per_pulse as u64)
        };
        let unpaid = pulses - funded;
        body.unpaid_support_pulses_since_hazard = body
            .unpaid_support_pulses_since_hazard
            .saturating_add(unpaid);
        let required = pulses.saturating_mul(body.profile.drain_per_pulse as u64);
        let spent = (body.charge as u64).min(required) as i32;
        body.charge -= spent;
        let remaining = body.charge;
        self.event(Some(actor), "electricity_consumed", vec![parent], json!({"amount":spent,"required":required,"deficit":required-spent as u64,"reason":"body_support","remaining_charge":remaining,"unpaid_support_pulses":unpaid}));
        Ok(())
    }
    pub(super) fn clear_body_support_deficit(&mut self, actor: u32) {
        if let Some(body) = self.infrastructure.bodies.get_mut(&actor) {
            body.unpaid_support_pulses_since_hazard = 0;
        }
    }
    fn local_station(&self, i: usize, station: u32) -> Result<usize, String> {
        if self.initial.infrastructure.is_none() {
            return Err("material infrastructure is not configured".into());
        }
        if self.players[i].health <= 0 {
            return Err("dead characters cannot operate infrastructure".into());
        }
        self.infrastructure
            .stations
            .iter()
            .position(|s| {
                s.seed.id == station
                    && s.seed.position == self.players[i].position
                    && self.same_arena(self.players[i].id, s.seed.owner)
            })
            .ok_or_else(|| "station is not locally accessible".into())
    }
    fn validate_infrastructure_operation(
        &self,
        i: usize,
        op: &InfrastructureOperation,
    ) -> Result<usize, String> {
        use InfrastructureOperation::*;
        let actor = self.players[i].id;
        let n = self.local_station(i, op.station())?;
        let s = &self.infrastructure.stations[n];
        let rights = s.seed.access.get(&actor).cloned().unwrap_or_default();
        let permitted = match op {
            SetAccess { .. } | SetEnabled { .. } => rights.admin,
            Build { .. } | Repair { .. } => rights.maintain,
            CancelJob { .. } => rights.admin || rights.use_allowed,
            _ => rights.use_allowed,
        };
        if !permitted {
            return Err("station permission denied".into());
        }
        let own = self
            .infrastructure
            .actor_materials
            .get(&actor)
            .cloned()
            .unwrap_or_default();
        let b = &self.infrastructure.balance;
        match op {
            TakeMaterial {
                material, amount, ..
            } => {
                if *amount <= 0
                    || *amount > s.seed.materials.get(*material)
                    || own.get(*material) > MAX_STOCK - *amount
                {
                    return Err("insufficient station material or carried capacity".into());
                }
            }
            DepositMaterial {
                material, amount, ..
            } => {
                if *amount <= 0
                    || *amount > own.get(*material)
                    || s.seed.materials.get(*material) > MAX_STOCK - *amount
                {
                    return Err("insufficient carried material or station capacity".into());
                }
            }
            Build { module, .. } => {
                if s.seed.modules.contains(module) || own.parts < b.build_parts[module] {
                    return Err("module already exists or construction lacks carried parts".into());
                }
            }
            Repair { parts, .. } => {
                if *parts <= 0
                    || *parts > own.parts
                    || s.integrity >= 100
                    || *parts > (100 - s.integrity + b.repair_per_part - 1) / b.repair_per_part
                {
                    return Err("repair requires useful carried parts and damaged equipment".into());
                }
            }
            Charge { amount, .. } | SupportCharge { amount, .. } => {
                let target = if let SupportCharge { target, .. } = op {
                    *target
                } else {
                    actor
                };
                if target != actor && !self.target_perceived(i, target, &self.players[i].memories) {
                    return Err("supported target has not been perceived".into());
                }
                let j = self.idx(target)?;
                if target != actor
                    && (self.players[j].health <= 0
                        || self.players[j].position != self.players[i].position
                        || !self.same_arena(actor, target)
                        || !self.lifecycle.get(&target).is_some_and(|l| l.dependent))
                {
                    return Err("supported charging requires a living local dependent".into());
                }
                let body = self
                    .infrastructure
                    .bodies
                    .get(&target)
                    .ok_or("target has no electric body profile")?;
                if body.profile.support != Support::Electric
                    || *amount <= 0
                    || *amount > body.profile.capacity - body.charge
                    || (*amount as i64) * b.electricity_per_charge as i64
                        > s.seed.electricity as i64
                    || !s.enabled
                    || s.integrity <= 0
                    || !s.seed.modules.contains(&Module::Charger)
                {
                    return Err(
                        "charging requires working charger, electricity, and battery capacity"
                            .into(),
                    );
                }
                if target != actor && self.lifecycle.get(&actor).is_some_and(|l| l.dependent) {
                    return Err("a dependent cannot supply developmental care".into());
                }
            }
            SetAccess { actor: target, .. } => {
                if *target != actor
                    && !s.seed.access.contains_key(target)
                    && !self.target_perceived(i, *target, &self.players[i].memories)
                {
                    return Err("access target has not been perceived".into());
                }
                self.idx(*target)?;
                if !self.same_arena(actor, *target) {
                    return Err("rights cannot cross actor scope".into());
                }
            }
            SetEnabled { .. } => {}
            SubmitJob { input, .. } => {
                if !s.enabled
                    || s.integrity <= 0
                    || !s.seed.modules.contains(&Module::Terminal)
                    || s.jobs.len() >= MAX_JOBS
                    || self.infrastructure.next_job == u64::MAX
                {
                    return Err("terminal unavailable or retained job capacity full".into());
                }
                if !(0..=MAX_STOCK).contains(&input.stock)
                    || !(0..=10000).contains(&input.inflow_per_min)
                    || !(0..=10000).contains(&input.demand_per_min)
                    || !(1..=3_600_000).contains(&input.horizon_ms)
                    || input.sources.len() > 8
                    || input
                        .sources
                        .iter()
                        .collect::<std::collections::BTreeSet<_>>()
                        .len()
                        != input.sources.len()
                    || input
                        .sources
                        .iter()
                        .any(|id| !self.players[i].knowledge.iter().any(|h| &h.record.id == id))
                {
                    return Err("forecast requires bounded explicit assumptions and personally held source IDs".into());
                }
            }
            CancelJob { job, .. } => {
                let job = s
                    .jobs
                    .iter()
                    .find(|j| j.id == *job)
                    .ok_or("no such queued job")?;
                if job.cancelled || job.report.is_some() || (job.owner != actor && !rights.admin) {
                    return Err("only owner or administrator may cancel unfinished job".into());
                }
            }
            RetrieveJob { .. } | RetrieveReady { .. } => {
                let report = s
                    .jobs
                    .iter()
                    .find(|j| j.owner == actor && match op {
                        RetrieveJob {job,..} => j.id==*job,
                        _ => !j.retrieved && j.report.is_some(),
                    })
                    .and_then(|j| j.report.as_ref())
                    .ok_or("no own completed report at this terminal")?;
                if !s.enabled || s.integrity <= 0 || !s.seed.modules.contains(&Module::Terminal) {
                    return Err("terminal unavailable for retrieval".into());
                }
                if let Some(held) = self.players[i]
                    .knowledge
                    .iter()
                    .find(|h| h.record.id == report.id)
                {
                    if held.record != *report {
                        return Err("computed report identity conflicts with held record".into());
                    }
                } else if self.players[i].knowledge.len() >= knowledge::MAX_HOLDINGS {
                    return Err("personal knowledge storage is full".into());
                }
            }
        }
        Ok(n)
    }
    pub(super) fn validate_infrastructure_effect(
        &self,
        i: usize,
        a: &Action,
        effect: &Effect,
    ) -> Result<(), String> {
        let Effect::Infrastructure { operation } = effect else {
            return Err("not an infrastructure effect".into());
        };
        if a.skill.id() != "infrastructure" || a.infrastructure.as_ref() != Some(operation) {
            return Err("infrastructure effect exceeds selected operation capability".into());
        }
        self.validate_infrastructure_operation(i, operation)
            .map(|_| ())
    }
    pub(super) fn apply_infrastructure_effect(
        &mut self,
        i: usize,
        parent: u64,
        effect: &Effect,
    ) -> Result<(), String> {
        let Effect::Infrastructure { operation } = effect else {
            return Err("not an infrastructure effect".into());
        };
        let n = self.validate_infrastructure_operation(i, operation)?;
        if let InfrastructureOperation::RetrieveReady {station} = operation {
            let job=self.infrastructure.stations[n].jobs.iter()
                .find(|j|j.owner==self.players[i].id && !j.retrieved && j.report.is_some())
                .ok_or("no own completed report at this terminal")?.id;
            return self.apply_infrastructure_effect(i,parent,&Effect::Infrastructure {
                operation:InfrastructureOperation::RetrieveJob {station:*station,job}
            });
        }
        use InfrastructureOperation::*;
        let actor = self.players[i].id;
        let location = self.players[i].position;
        let b = self.infrastructure.balance.clone();
        let event = match operation {
            RetrieveReady { .. } => unreachable!("ready report resolved above"),
            TakeMaterial {
                station,
                material,
                amount,
            }
            | DepositMaterial {
                station,
                material,
                amount,
            } => {
                let take = matches!(operation, TakeMaterial { .. });
                let delta = if take { *amount } else { -*amount };
                self.infrastructure
                    .actor_materials
                    .entry(actor)
                    .or_default()
                    .add(*material, delta);
                self.infrastructure.stations[n]
                    .seed
                    .materials
                    .add(*material, -delta);
                self.event(Some(actor),"material_transferred",vec![parent],json!({"station":station,"location":location,"material":material,"amount":amount,"direction":if take {"to_actor"} else {"to_station"}}))
            }
            Build { station, module } => {
                let parts = b.build_parts[module];
                self.infrastructure
                    .actor_materials
                    .entry(actor)
                    .or_default()
                    .parts -= parts;
                let s = &mut self.infrastructure.stations[n];
                s.seed.modules.push(*module);
                s.embodied_parts += parts;
                self.event(Some(actor),"infrastructure_built",vec![parent],json!({"station":station,"location":location,"module":module,"parts":parts,"balance_version":b.version}))
            }
            Repair { station, parts } => {
                self.infrastructure
                    .actor_materials
                    .entry(actor)
                    .or_default()
                    .parts -= parts;
                let s = &mut self.infrastructure.stations[n];
                s.integrity = (s.integrity + parts * b.repair_per_part).min(100);
                s.repair_parts_consumed += parts;
                let integrity = s.integrity;
                self.event(Some(actor),"infrastructure_repaired",vec![parent],json!({"station":station,"location":location,"parts":parts,"integrity":integrity,"balance_version":b.version}))
            }
            Charge { station, amount }
            | SupportCharge {
                station, amount, ..
            } => {
                let target = if let SupportCharge { target, .. } = operation {
                    *target
                } else {
                    actor
                };
                let spent = amount * b.electricity_per_charge;
                self.infrastructure.stations[n].seed.electricity -= spent;
                self.infrastructure.bodies.get_mut(&target).unwrap().charge += amount;
                let event = self.event(Some(actor),"body_charged",vec![parent],json!({"station":station,"location":location,"target":target,"electricity":spent,"charge":amount,"conversion_loss":spent-amount,"support":target!=actor}));
                if target != actor && *amount >= b.support_care_min_charge {
                    let j = self.idx(target)?;
                    let source = self.perceive(
                        j,
                        event,
                        "charge_care_received",
                        Some(actor),
                        location,
                        json!({"station":station,"charge":amount}),
                    )?;
                    if let Some(l) = self.lifecycle.get_mut(&target) {
                        l.care_meals = l.care_meals.saturating_add(1);
                        if let Some(c) = l.care.iter_mut().find(|c| c.caregiver == actor) {
                            c.meals = c.meals.saturating_add(1);
                            c.source = source;
                        } else {
                            l.care.push(lifecycle::CareEvidence {
                                caregiver: actor,
                                source,
                                meals: 1,
                            });
                        }
                    }
                }
                event
            }
            SetAccess {
                station,
                actor: target,
                use_allowed,
                maintain,
                admin,
            } => {
                self.infrastructure.stations[n].seed.access.insert(
                    *target,
                    Rights {
                        use_allowed: *use_allowed,
                        maintain: *maintain,
                        admin: *admin,
                    },
                );
                self.event(Some(actor),"infrastructure_access_changed",vec![parent],json!({"station":station,"target":target,"use_allowed":use_allowed,"maintain":maintain,"admin":admin,"location":location}))
            }
            SetEnabled { station, enabled } => {
                self.infrastructure.stations[n].enabled = *enabled;
                self.event(
                    Some(actor),
                    "infrastructure_enabled_changed",
                    vec![parent],
                    json!({"station":station,"enabled":enabled,"location":location}),
                )
            }
            SubmitJob { station, input } => {
                let id = self.infrastructure.next_job;
                self.infrastructure.next_job += 1;
                let sources: Vec<_> = input
                    .sources
                    .iter()
                    .map(|id| {
                        self.players[i]
                            .knowledge
                            .iter()
                            .find(|h| &h.record.id == id)
                            .unwrap()
                            .record
                            .clone()
                    })
                    .collect();
                let hash=format!("{:x}",Sha256::digest(serde_json::to_vec(&json!({"input":input,"sources":sources,"program":FORECAST_PROGRAM,"program_version":1})).map_err(|e|e.to_string())?));
                let source=self.event(Some(actor),"compute_submitted",vec![parent],json!({"station":station,"job":id,"input":input,"input_hash":hash,"program":"resource_forecast_v1","required_quanta":b.compute_quanta,"quantum_ms":b.compute_quantum_ms,"location":location}));
                let s = &mut self.infrastructure.stations[n];
                if s.jobs.iter().all(|j| j.report.is_some() || j.cancelled) {
                    s.compute_remainder_ms = 0;
                }
                s.jobs.push(ComputeJob {
                    id,
                    owner: actor,
                    submitted_ms: self.timing.time_ms,
                    source,
                    input: input.clone(),
                    input_hash: hash,
                    sources,
                    progress: 0,
                    required: b.compute_quanta,
                    last_quantum_ms: None,
                    report: None,
                    retrieved: false,
                    blocked_reason: None,
                    cancelled: false,
                });
                source
            }
            CancelJob { station, job } => {
                let queued = self.infrastructure.stations[n]
                    .jobs
                    .iter_mut()
                    .find(|j| j.id == *job)
                    .unwrap();
                queued.cancelled = true;
                let progress = queued.progress;
                self.event(Some(actor),"compute_cancelled",vec![parent],json!({"station":station,"job":job,"progress":progress,"refund":false,"location":location}))
            }
            RetrieveJob { station, job } => {
                let n_job = self.infrastructure.stations[n]
                    .jobs
                    .iter()
                    .position(|j| j.id == *job)
                    .unwrap();
                let record = self.infrastructure.stations[n].jobs[n_job]
                    .report
                    .clone()
                    .unwrap();
                let event=self.event(Some(actor),"compute_retrieved",vec![parent,record.origin],json!({"station":station,"job":job,"record":record.id,"location":location,"new_copy":!self.players[i].knowledge.iter().any(|h|h.record.id==record.id)}));
                self.receive_record(i, event, None, &record, "compute_terminal")?;
                self.infrastructure.stations[n].jobs[n_job].retrieved = true;
                event
            }
        };
        self.perceive(
            i,
            event,
            "infrastructure_action",
            None,
            location,
            json!({"operation":operation,"result":"completed"}),
        )?;
        Ok(())
    }
    fn fresh_compute_record_id(&self, job: u64, origin: u64) -> String {
        let mut suffix = 0u32;
        loop {
            let id = format!("compute-{job}-{origin}-{suffix}");
            let taken = self
                .players
                .iter()
                .any(|p| p.knowledge.iter().any(|h| h.record.id == id))
                || self
                    .archives
                    .iter()
                    .any(|a| a.records.iter().any(|r| r.id == id))
                || self.infrastructure.stations.iter().any(|s| {
                    s.jobs
                        .iter()
                        .any(|j| j.report.as_ref().is_some_and(|r| r.id == id))
                });
            if !taken {
                return id;
            }
            suffix += 1;
        }
    }
    pub(super) fn infrastructure_facts(&self, actor: u32) -> Value {
        let Ok(i) = self.idx(actor) else {
            return json!({"enabled":false});
        };
        let own = self
            .infrastructure
            .actor_materials
            .get(&actor)
            .cloned()
            .unwrap_or_default();
        let stations:Vec<_>=self.infrastructure.stations.iter().filter(|s|s.seed.position==self.players[i].position && self.same_arena(actor,s.seed.owner)).map(|s| {
            let rights=s.seed.access.get(&actor).cloned().unwrap_or_default();
            let jobs:Vec<_>=s.jobs.iter().filter(|j|j.owner==actor).map(|j|json!({"id":j.id,"progress":j.progress,"required":j.required,"input":j.input,"input_hash":j.input_hash,"report":j.report.as_ref().map(|r|&r.id),"retrieved":j.retrieved,"blocked_reason":j.blocked_reason,"cancelled":j.cancelled})).collect();
            json!({"id":s.seed.id,"owner":s.seed.owner,"position":s.seed.position,"label":s.seed.label,"enabled":s.enabled,"integrity":s.integrity,"modules":s.seed.modules,"electricity":s.seed.electricity,"electricity_capacity":s.seed.electricity_capacity,"materials":s.seed.materials,"generation_period_ms":s.seed.generation_period_ms,"generation_amount":s.seed.generation_amount,"rights":rights,"access":if rights.admin {json!(s.seed.access)} else {Value::Null},"queue_length":s.jobs.iter().filter(|j|j.report.is_none() && !j.cancelled).count(),"own_jobs":jobs,"admin_queue":if rights.admin {json!(s.jobs.iter().map(|j|json!({"id":j.id,"owner":j.owner,"progress":j.progress,"required":j.required,"complete":j.report.is_some(),"cancelled":j.cancelled,"blocked_reason":j.blocked_reason})).collect::<Vec<_>>())} else {Value::Null}})
        }).collect();
        json!({"enabled":self.initial.infrastructure.is_some(),"body":self.body_support_context(actor),"materials":own,"balance":self.infrastructure.balance,"stations":stations})
    }
    pub(super) fn advance_infrastructure(&mut self, delta_ms: u64) -> Result<(), String> {
        if self.initial.infrastructure.is_none() || delta_ms == 0 {
            return Ok(());
        }
        let b = self.infrastructure.balance.clone();
        for n in 0..self.infrastructure.stations.len() {
            let mut remaining = delta_ms;
            let mut at = self.timing.time_ms.saturating_sub(delta_ms);
            while remaining > 0 {
                let s = &self.infrastructure.stations[n];
                let to_generation = s.seed.generation_period_ms - s.generation_remainder_ms;
                let to_compute = b.compute_quantum_ms - s.compute_remainder_ms;
                let step = remaining.min(to_generation).min(to_compute);
                at += step;
                remaining -= step;
                let s = &mut self.infrastructure.stations[n];
                s.generation_remainder_ms += step;
                s.compute_remainder_ms += step;
                if s.generation_remainder_ms == s.seed.generation_period_ms {
                    s.generation_remainder_ms = 0;
                    if s.enabled && s.integrity > 0 && s.seed.modules.contains(&Module::Generator) {
                        let generated = s
                            .seed
                            .generation_amount
                            .min(s.seed.electricity_capacity - s.seed.electricity);
                        s.seed.electricity += generated;
                        let (station, position, spill) = (
                            s.seed.id,
                            s.seed.position,
                            s.seed.generation_amount - generated,
                        );
                        self.event(None,"electricity_generated",vec![],json!({"station":station,"location":position,"amount":generated,"potential":generated+spill,"spilled":spill,"quantum_at_ms":at,"source":"seeded_renewable_generator"}));
                    }
                }
                if self.infrastructure.stations[n].compute_remainder_ms == b.compute_quantum_ms {
                    self.infrastructure.stations[n].compute_remainder_ms = 0;
                    self.advance_compute_quantum(n, at)?;
                }
            }
        }
        Ok(())
    }
    fn advance_compute_quantum(&mut self, n: usize, at: u64) -> Result<(), String> {
        let b = self.infrastructure.balance.clone();
        let s = &self.infrastructure.stations[n];
        let Some(j) = s
            .jobs
            .iter()
            .position(|j| j.report.is_none() && !j.cancelled)
        else {
            return Ok(());
        };
        let job = &s.jobs[j];
        if at < job.submitted_ms.saturating_add(b.compute_quantum_ms) {
            return Ok(());
        }
        let permitted = s.seed.access.get(&job.owner).is_some_and(|r| r.use_allowed);
        let blocked = if !permitted {
            Some("access_revoked")
        } else if !s.enabled {
            Some("disabled")
        } else if s.integrity <= 0 {
            Some("damaged")
        } else if !s.seed.modules.contains(&Module::Terminal) {
            Some("terminal_absent")
        } else if s.seed.electricity < b.compute_electricity {
            Some("electricity")
        } else if s.seed.materials.water < b.compute_water {
            Some("cooling_water")
        } else {
            None
        };
        let blocked = blocked.map(str::to_owned);
        if job.blocked_reason != blocked {
            let (owner, station, id, source) = (job.owner, s.seed.id, job.id, job.source);
            self.infrastructure.stations[n].jobs[j].blocked_reason = blocked.clone();
            self.event(
                Some(owner),
                "compute_availability_changed",
                vec![source],
                json!({"station":station,"job":id,"blocked_reason":blocked,"quantum_at_ms":at}),
            );
        }
        if blocked.is_some() {
            return Ok(());
        }
        // Submitted work is physical: death does not cancel an authorized job or disclose its output.
        let s = &mut self.infrastructure.stations[n];
        s.seed.electricity -= b.compute_electricity;
        s.seed.materials.water -= b.compute_water;
        s.integrity = (s.integrity - b.wear_per_quantum).max(0);
        s.jobs[j].progress += 1;
        s.jobs[j].last_quantum_ms = Some(at);
        let (station, position, owner, id, source, progress, required) = (
            s.seed.id,
            s.seed.position,
            s.jobs[j].owner,
            s.jobs[j].id,
            s.jobs[j].source,
            s.jobs[j].progress,
            s.jobs[j].required,
        );
        let event=self.event(Some(owner),"compute_quantum",vec![source],json!({"station":station,"job":id,"progress":progress,"required":required,"electricity":b.compute_electricity,"water":b.compute_water,"water_consumed":b.compute_water,"wear":b.wear_per_quantum,"quantum_at_ms":at,"location":position,"balance_version":b.version}));
        if progress == required {
            let job = self.infrastructure.stations[n].jobs[j].clone();
            let output = forecast(&job.input)?;
            let text=format!("Conditional resource forecast v1. Assumed stock {}, inflow {}/min, demand {}/min, horizon {} ms. Projected stock {}; residual {}; shortfall {}. Input SHA-256 {}. Sources: {}. Arithmetic uses supplied assumptions; it does not verify geography, future production, access, or others' intentions.",job.input.stock,job.input.inflow_per_min,job.input.demand_per_min,job.input.horizon_ms,output["projected_stock"],output["residual"],output["shortfall"],job.input_hash,if job.input.sources.is_empty(){"none".into()}else{job.input.sources.join(",")});
            let origin = self.next_event;
            let record = knowledge::Record {
                id: self.fresh_compute_record_id(id, origin),
                topic: "Conditional resource forecast".into(),
                text,
                location: None,
                author: owner,
                origin,
                confidence: 50,
            };
            self.event(Some(owner),"compute_completed",vec![event,source],json!({"station":station,"job":id,"input_hash":job.input_hash,"program":"resource_forecast_v1","program_source":FORECAST_PROGRAM,"program_hash":format!("{:x}",Sha256::digest(FORECAST_PROGRAM.as_bytes())),"output":output,"record":record,"location":position,"quantum_at_ms":at,"delivery":"private physical terminal report; explicit local retrieval required"}));
            self.infrastructure.stations[n].jobs[j].report = Some(record);
            if let Ok(i) = self.idx(owner) {
                if self.players[i].health > 0
                    && self.players[i].position == position
                    && self.same_arena(owner, self.infrastructure.stations[n].seed.owner)
                {
                    self.perceive(
                        i,
                        origin,
                        "compute_ready",
                        None,
                        position,
                        json!({"station":station,"job":id,"retrieval_required":true}),
                    )?;
                }
            }
        }
        Ok(())
    }
}
fn forecast(input: &ForecastInput) -> Result<Value, String> {
    let mut engine = rhai::Engine::new_raw();
    rhai::packages::StandardPackage::new().register_into_engine(&mut engine);
    engine.set_max_operations(2000);
    engine.set_max_call_levels(8);
    engine.set_max_expr_depths(16, 16);
    engine.set_max_array_size(16);
    engine.set_max_map_size(16);
    engine.set_max_string_size(256);
    for symbol in ["eval", "import", "print", "debug"] {
        engine.disable_symbol(symbol);
    }
    let ast = engine
        .compile(FORECAST_PROGRAM)
        .map_err(|e| e.to_string())?
        .clone_functions_only();
    let mut data = rhai::Map::new();
    data.insert("stock".into(), (input.stock as rhai::INT).into());
    data.insert(
        "inflow_per_min".into(),
        (input.inflow_per_min as rhai::INT).into(),
    );
    data.insert(
        "demand_per_min".into(),
        (input.demand_per_min as rhai::INT).into(),
    );
    data.insert("horizon_ms".into(), (input.horizon_ms as rhai::INT).into());
    let result: rhai::Map = engine
        .call_fn(&mut rhai::Scope::new(), &ast, "forecast", (data,))
        .map_err(|e| e.to_string())?;
    let mut output = serde_json::Map::new();
    for (key, value) in result {
        output.insert(
            key.to_string(),
            json!(value.as_int().map_err(|e| e.to_string())?),
        );
    }
    Ok(Value::Object(output))
}
