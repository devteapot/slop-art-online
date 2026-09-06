//! Participant techniques are executable knowledge copies, not entries in the
//! operator's rule registry. Authority derives only from personally owned,
//! interpreted evidence of paid work; program output remains inert numeric data.
use crate::*;
use infrastructure::{ComputeJob, InfrastructureOperation as Op, Module};
use knowledge::Record;
use research_programs::ProgramError;
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExperimentKind {
    BuiltinForecast,
    Prototype,
    Practice,
    Run,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ExperimentEvidence {
    pub kind: ExperimentKind,
    pub operator: u32,
    pub station: u32,
    pub job: u64,
    pub program_hash: Option<String>,
    pub input_hash: String,
    pub inputs: Vec<i64>,
    pub expected_results: Option<Vec<i64>>,
    pub output: Option<Vec<i64>>,
    pub runtime_error: Option<ProgramError>,
    pub predictions_matched: Option<bool>,
    pub successful: bool,
    pub paid_quanta: u32,
    pub rules_revision: u64,
}
impl ExperimentEvidence {
    pub(super) fn forecast(
        operator: u32,
        station: u32,
        job: u64,
        input_hash: String,
        paid_quanta: u32,
        rules_revision: u64,
    ) -> Self {
        Self {
            kind: ExperimentKind::BuiltinForecast,
            operator,
            station,
            job,
            program_hash: None,
            input_hash,
            inputs: vec![],
            expected_results: None,
            output: None,
            runtime_error: None,
            predictions_matched: None,
            successful: true,
            paid_quanta,
            rules_revision,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProgramWork {
    pub kind: ExperimentKind,
    // The executable's sole persistent representation is a physical Record copy.
    pub program_record: Record,
    pub inputs: Vec<i64>,
    pub expected_results: Option<Vec<i64>>,
}

/// Default catalogs and experience feeds do not replicate every program body.
/// An explicit own-program inspection is the sole unredacted reading response.
pub fn redact_program_sources(value: &mut Value) {
    match value {
        Value::Object(map) => {
            if map.get("kind").and_then(Value::as_str) == Some("program_inspected") {
                return;
            }
            if map.contains_key("interface_version")
                && map.contains_key("input_contract")
                && map.contains_key("output_contract")
                && map.remove("source").is_some()
            {
                map.insert("source_omitted".into(), json!(true));
            }
            for value in map.values_mut() {
                redact_program_sources(value)
            }
        }
        Value::Array(values) => {
            for value in values {
                redact_program_sources(value)
            }
        }
        _ => {}
    }
}
pub fn redacted(mut value: Value) -> Value {
    redact_program_sources(&mut value);
    value
}
pub fn record_view(record: &Record) -> Value {
    redacted(json!(record))
}

impl World {
    fn assessed_own_experiments(
        &self,
        i: usize,
    ) -> impl Iterator<Item = (&knowledge::Holding, &ExperimentEvidence)> {
        let actor = self.players[i].id;
        self.players[i].knowledge.iter().filter_map(move |holding| {
            let e = holding.record.experiment.as_ref()?;
            (holding.interpretation.is_some()
                && holding.interpreted_source.is_some()
                && e.operator == actor
                && holding.record.author == actor
                && e.paid_quanta > 0
                && e.successful)
                .then_some((holding, e))
        })
    }
    fn authoring_evidence(&self, i: usize) -> Value {
        let evidence: Vec<_> = self.assessed_own_experiments(i).collect();
        json!({
            "own_forecast_assessed":evidence.iter().any(|(_,e)|e.kind==ExperimentKind::BuiltinForecast),
            "own_practice_assessed":evidence.iter().any(|(_,e)|e.kind==ExperimentKind::Practice),
            "own_prototype_assessed":evidence.iter().any(|(_,e)|e.kind==ExperimentKind::Prototype),
            "proofs":evidence.iter().filter(|(_,e)|e.kind!=ExperimentKind::Run).map(|(h,e)|json!({"record":h.record.id,"kind":e.kind,"program_hash":e.program_hash,"assessment":h.interpreted_source})).collect::<Vec<_>>()
        })
    }
    fn can_author_program(&self, i: usize) -> Result<bool, String> {
        self.scripts
            .law("research_authoring", self.authoring_evidence(i))
    }
    fn personally_held_program(
        &self,
        i: usize,
        id: &str,
        assessed: bool,
    ) -> Result<&Record, String> {
        let held = self.players[i]
            .knowledge
            .iter()
            .find(|h| h.record.id == id && h.record.program.is_some())
            .ok_or("program record is not personally held")?;
        if assessed && (held.interpretation.is_none() || held.interpreted_source.is_none()) {
            return Err(
                "program record requires personal interpretation before practice or use".into(),
            );
        }
        Ok(&held.record)
    }
    fn can_use_program(&self, i: usize, record: &Record) -> Result<bool, String> {
        let hash = &record
            .program
            .as_ref()
            .ok_or("record has no program")?
            .source_hash;
        let held = self.players[i]
            .knowledge
            .iter()
            .find(|h| h.record.id == record.id);
        let proof = self.assessed_own_experiments(i).any(|(_, e)| {
            matches!(e.kind, ExperimentKind::Prototype | ExperimentKind::Practice)
                && e.program_hash.as_ref() == Some(hash)
        });
        self.scripts.law("research_use",json!({"held_interpreted":held.is_some_and(|h|h.interpretation.is_some() && h.interpreted_source.is_some()),"own_matching_practice_assessed":proof}))
    }
    /// Trusted skill evaluation receives only its selected physical capability.
    /// Private experiment vectors and source catalogs never inflate unrelated guards/actions.
    pub(super) fn infrastructure_script_facts(&self, actor: u32, op: Option<&Op>) -> Value {
        let selected = op.map(Op::station);
        let position = self.idx(actor).ok().map(|i| self.players[i].position);
        let stations:Vec<_>=self.infrastructure.stations.iter().filter(|s|Some(s.seed.id)==selected && Some(s.seed.position)==position && self.same_arena(actor,s.seed.owner)).map(|s| {
            let rights=s.seed.access.get(&actor).cloned().unwrap_or_default();
            let selected_job=s.jobs.iter().find(|j| match op {
                Some(Op::RetrieveReady {..})=>j.owner==actor && !j.retrieved && j.report.is_some(),
                Some(Op::RetrieveJob {job,..})=>j.id==*job && j.owner==actor,
                Some(Op::CancelJob {job,..}|Op::EraseJob {job,..})=>j.id==*job && (j.owner==actor || rights.admin),
                _=>false,
            });
            json!({"id":s.seed.id,"owner":s.seed.owner,"position":s.seed.position,"enabled":s.enabled,"integrity":s.integrity,"modules":s.seed.modules,"electricity":s.seed.electricity,"electricity_capacity":s.seed.electricity_capacity,"materials":s.seed.materials,"rights":rights,"retained_jobs":s.jobs.len(),"queue_length":s.jobs.iter().filter(|j|j.report.is_none()&&!j.cancelled).count(),"selected_job":selected_job.map(|j|json!({"id":j.id,"owner":j.owner,"progress":j.progress,"required":j.required,"complete":j.report.is_some(),"retrieved":j.retrieved,"cancelled":j.cancelled,"blocked_reason":j.blocked_reason}))})
        }).collect();
        json!({"enabled":self.initial.infrastructure.is_some(),"body":self.body_support_context(actor),"materials":self.infrastructure.actor_materials.get(&actor).cloned().unwrap_or_default(),"balance":self.infrastructure.balance,"stations":stations})
    }
    pub(super) fn research_facts(&self, actor: u32) -> Value {
        let Ok(i) = self.idx(actor) else {
            return Value::Null;
        };
        let programs:Vec<_>=self.players[i].knowledge.iter().filter_map(|h|h.record.program.as_ref().map(|p|json!({"record":h.record.id,"source_hash":p.source_hash,"interface_version":p.interface_version,"interpreted":h.interpreted_source.is_some(),"can_run":self.can_use_program(i,&h.record).unwrap_or(false),"input_contract":p.input_contract,"output_contract":p.output_contract}))).collect();
        json!({"can_author":self.players[i].health>0 && self.can_author_program(i).unwrap_or(false),"evidence":self.authoring_evidence(i),"programs":programs,
            "interface":"Set interface_version to 1. Rhai declaration: fn technique(input), followed by its function body. Functions are public by default; there is no pub keyword. Local bindings use let x = ... and are mutable without a mut keyword. The function receives only the supplied integer array (at most 64) and returns at most 64 integers. Helpers are permitted. No top-level statements, globals, imports, eval, I/O, effects, or dynamic function pointers. Source at most 8192 bytes; each input/output contract 1..512 bytes; 20000 interpreter operations and 16 call levels.",
            "learning":"First personally complete, retrieve and interpret a paid built-in forecast, or learn an interpreted communicated program through your own paid successful practice. Prototype and practice compare outputs against predictions submitted before work. Reflect on your own program_inspected perception to assess the exact code you still hold, or assess its received knowledge_report. Inspection alone grants no practice proof. Interpret your own successful experiment and the code record to run that exact source hash. Communicated experiment reports do not grant their author's personal practice.",
            "privacy":"Code and private experiment reports are separate records. Teach the program record to share code without experiment inputs. InspectProgram reads only your held source. Terminal jobs retain physical copies until explicitly erased; erase never refunds past work."})
    }
    fn validate_numeric_inputs(
        &self,
        i: usize,
        inputs: &[i64],
        sources: &[String],
        expected: Option<&[i64]>,
    ) -> Result<(), String> {
        if inputs.len() > research_programs::MAX_VECTOR_LEN
            || expected.is_some_and(|v| v.len() > research_programs::MAX_VECTOR_LEN)
            || sources.len() > 8
            || sources
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != sources.len()
            || sources
                .iter()
                .any(|id| !self.players[i].knowledge.iter().any(|h| &h.record.id == id))
        {
            return Err("research requires at most 64 numeric inputs/predictions and 8 unique personally held source IDs".into());
        }
        Ok(())
    }
    pub(super) fn validate_research_operation(
        &self,
        i: usize,
        n: usize,
        op: &Op,
    ) -> Result<bool, String> {
        let actor = self.players[i].id;
        let station = &self.infrastructure.stations[n];
        if matches!(
            op,
            Op::Prototype { .. }
                | Op::PracticeProgram { .. }
                | Op::RunProgram { .. }
                | Op::InspectProgram { .. }
        ) {
            if !station.enabled
                || station.integrity <= 0
                || !station.seed.modules.contains(&Module::Terminal)
            {
                return Err("working local terminal is required".into());
            }
        }
        if matches!(
            op,
            Op::Prototype { .. } | Op::PracticeProgram { .. } | Op::RunProgram { .. }
        ) && (station.jobs.len() >= infrastructure::MAX_JOBS
            || self.infrastructure.next_job == u64::MAX)
        {
            return Err("retained terminal job capacity is full".into());
        }
        match op {
            Op::Prototype {
                draft,
                inputs,
                sources,
                expected_results,
                ..
            } => {
                if !self.can_author_program(i)? {
                    return Err("authorship requires personally paid, retrieved and interpreted terminal practice".into());
                }
                self.validate_numeric_inputs(i, inputs, sources, Some(expected_results))?;
                research_programs::compile(draft).map_err(|e| e.to_string())?;
            }
            Op::PracticeProgram {
                record,
                inputs,
                sources,
                expected_results,
                ..
            } => {
                let record = self.personally_held_program(i, record, true)?;
                research_programs::validate(record.program.as_ref().unwrap())
                    .map_err(|e| e.to_string())?;
                self.validate_numeric_inputs(i, inputs, sources, Some(expected_results))?;
            }
            Op::RunProgram {
                record,
                inputs,
                sources,
                ..
            } => {
                let record = self.personally_held_program(i, record, true)?;
                if !self.can_use_program(i, record)? {
                    return Err("ordinary use requires own assessed successful prototype or practice for this exact source hash".into());
                }
                research_programs::validate(record.program.as_ref().unwrap())
                    .map_err(|e| e.to_string())?;
                self.validate_numeric_inputs(i, inputs, sources, None)?;
            }
            Op::InspectProgram { record, .. } => {
                self.personally_held_program(i, record, false)?;
            }
            Op::EraseJob { job, .. } => {
                let admin = station.seed.access.get(&actor).is_some_and(|r| r.admin);
                if !station
                    .jobs
                    .iter()
                    .any(|j| j.id == *job && (j.owner == actor || admin))
                {
                    return Err(
                        "only job owner or local administrator may erase an accessible job".into(),
                    );
                }
            }
            _ => return Ok(false),
        }
        Ok(true)
    }
    pub(super) fn apply_research_operation(
        &mut self,
        i: usize,
        n: usize,
        parent: u64,
        op: &Op,
    ) -> Result<Option<u64>, String> {
        let actor = self.players[i].id;
        let location = self.players[i].position;
        let (kind, record, inputs, sources, expected) = match op {
            Op::Prototype {
                draft,
                inputs,
                sources,
                expected_results,
                ..
            } => {
                let program = research_programs::compile(draft).map_err(|e| e.to_string())?;
                let origin = self.next_event;
                let job = self.infrastructure.next_job;
                let record=Record {id:self.fresh_material_record_id("technique",job,origin),topic:format!("Numeric technique {}",&program.source_hash[..12]),text:format!("Participant-authored technique. Input contract: {} Output contract: {} Compilation and tests do not establish that its assumptions match future reality.",program.input_contract,program.output_contract),location:None,author:actor,origin,confidence:50,program:Some(program),experiment:None};
                (
                    ExperimentKind::Prototype,
                    record,
                    inputs.clone(),
                    sources.clone(),
                    Some(expected_results.clone()),
                )
            }
            Op::PracticeProgram {
                record,
                inputs,
                sources,
                expected_results,
                ..
            } => (
                ExperimentKind::Practice,
                self.personally_held_program(i, record, true)?.clone(),
                inputs.clone(),
                sources.clone(),
                Some(expected_results.clone()),
            ),
            Op::RunProgram {
                record,
                inputs,
                sources,
                ..
            } => (
                ExperimentKind::Run,
                self.personally_held_program(i, record, true)?.clone(),
                inputs.clone(),
                sources.clone(),
                None,
            ),
            Op::InspectProgram { station, record } => {
                let held = self.personally_held_program(i, record, false)?.clone();
                let event=self.event(Some(actor),"program_inspected",vec![parent],json!({"station":station,"record":record,"program_hash":held.program.as_ref().map(|p|&p.source_hash),"location":location}));
                self.perceive(
                    i,
                    event,
                    "program_inspected",
                    None,
                    location,
                    json!({"record":record,"program":held.program}),
                )?;
                return Ok(Some(event));
            }
            Op::EraseJob { station, job } => {
                let at = self.infrastructure.stations[n]
                    .jobs
                    .iter()
                    .position(|j| j.id == *job)
                    .ok_or("job disappeared")?;
                let erased = self.infrastructure.stations[n].jobs.remove(at);
                let mut copies = erased.sources;
                copies.extend(erased.report);
                if let Some(work) = erased.program_work {
                    copies.push(work.program_record);
                }
                let ids: std::collections::BTreeSet<_> =
                    copies.iter().map(|r| r.id.clone()).collect();
                let hashes: std::collections::BTreeSet<_> = copies
                    .iter()
                    .filter_map(|r| r.program.as_ref().map(|p| p.source_hash.clone()))
                    .collect();
                return Ok(Some(self.event(Some(actor),"compute_erased",vec![parent],json!({"station":station,"job":job,"owner":erased.owner,"progress":erased.progress,"record_ids":ids,"program_hashes":hashes,"refund":false,"location":location,"meaning":"This terminal job's input, source and output copies were removed. Surviving personal and archive copies are unaffected."}))));
            }
            _ => return Ok(None),
        };
        let id = self.infrastructure.next_job;
        self.infrastructure.next_job += 1;
        let source_records: Vec<_> = sources
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
        let hash=format!("{:x}",Sha256::digest(serde_json::to_vec(&json!({"kind":kind,"program_record":record,"inputs":inputs,"expected_results":expected,"sources":source_records})).map_err(|e|e.to_string())?));
        let station = self.infrastructure.stations[n].seed.id;
        let b = &self.infrastructure.balance;
        let source=self.event(Some(actor),"compute_submitted",vec![parent],json!({"station":station,"job":id,"experiment_kind":kind,"program_record":record,"new_program":kind==ExperimentKind::Prototype,"input":inputs,"expected_results":expected,"source_records":source_records,"input_hash":hash,"required_quanta":b.compute_quanta,"quantum_ms":b.compute_quantum_ms,"location":location,"capability_evidence":self.authoring_evidence(i)}));
        let required = self.infrastructure.balance.compute_quanta;
        let station = &mut self.infrastructure.stations[n];
        if station
            .jobs
            .iter()
            .all(|j| j.report.is_some() || j.cancelled)
        {
            station.compute_remainder_ms = 0;
        }
        station.jobs.push(ComputeJob {
            id,
            owner: actor,
            submitted_ms: self.timing.time_ms,
            source,
            input: None,
            program_work: Some(ProgramWork {
                kind,
                program_record: record,
                inputs,
                expected_results: expected,
            }),
            input_hash: hash,
            sources: source_records,
            progress: 0,
            required,
            last_quantum_ms: None,
            report: None,
            retrieved: false,
            blocked_reason: None,
            cancelled: false,
        });
        Ok(Some(source))
    }
    pub(super) fn finish_program_job(
        &mut self,
        n: usize,
        j: usize,
        cause: u64,
        at: u64,
    ) -> Result<u64, String> {
        let job = self.infrastructure.stations[n].jobs[j].clone();
        let work = job
            .program_work
            .as_ref()
            .ok_or("missing numeric experiment")?;
        let artifact = work
            .program_record
            .program
            .as_ref()
            .ok_or("physical program record lacks executable")?;
        // A bounded runtime failure is a paid experiment result. It cannot escape
        // as a world-update error that refunds already completed physical work.
        let (output, runtime_error) = match research_programs::run(artifact, &work.inputs) {
            Ok(result) => (Some(result), None),
            Err(error) => (None, Some(error)),
        };
        let matched = work
            .expected_results
            .as_ref()
            .map(|expected| output.as_ref() == Some(expected));
        let successful = runtime_error.is_none() && matched.unwrap_or(true);
        let station = self.infrastructure.stations[n].seed.id;
        let location = self.infrastructure.stations[n].seed.position;
        let evidence = ExperimentEvidence {
            kind: work.kind,
            operator: job.owner,
            station,
            job: job.id,
            program_hash: Some(artifact.source_hash.clone()),
            input_hash: job.input_hash.clone(),
            inputs: work.inputs.clone(),
            expected_results: work.expected_results.clone(),
            output: output.clone(),
            runtime_error: runtime_error.clone(),
            predictions_matched: matched,
            successful,
            paid_quanta: job.progress,
            rules_revision: self.scripts.revision,
        };
        let origin = self.next_event;
        let record=Record {id:self.fresh_compute_record_id(job.id,origin),topic:"Numeric technique experiment".into(),text:format!("Paid {:?} experiment for source {}. {} The evidence contains supplied inputs, predictions and actual numeric output; it establishes only this experiment, not general correctness or verified future conditions.",work.kind,artifact.source_hash,if runtime_error.is_some(){"The bounded program failed during execution."}else if matched==Some(false){"The output did not match the submitted prediction."}else{"The execution succeeded and any submitted prediction matched."}),location:None,author:job.owner,origin,confidence:50,program:None,experiment:Some(evidence)};
        self.event(Some(job.owner),"compute_completed",vec![cause,job.source],json!({"station":station,"job":job.id,"experiment_kind":work.kind,"input_hash":job.input_hash,"program_hash":artifact.source_hash,"output":output,"runtime_error":runtime_error,"successful":successful,"record":record,"program_record":work.program_record,"location":location,"quantum_at_ms":at,"delivery":"Separate private experiment and portable program records require explicit local retrieval."}));
        self.infrastructure.stations[n].jobs[j].report = Some(record);
        Ok(origin)
    }
    fn compute_output_records<'a>(&self, job: &'a ComputeJob) -> Result<Vec<&'a Record>, String> {
        let mut records = vec![job.report.as_ref().ok_or("job has no completed report")?];
        if let Some(work) = &job.program_work {
            records.push(&work.program_record)
        }
        Ok(records)
    }
    pub(super) fn validate_compute_retrieval(
        &self,
        i: usize,
        job: &ComputeJob,
    ) -> Result<(), String> {
        let records = self.compute_output_records(job)?;
        let mut added = std::collections::BTreeSet::new();
        for record in records {
            if let Some(held) = self.players[i]
                .knowledge
                .iter()
                .find(|h| h.record.id == record.id)
            {
                if held.record != *record {
                    return Err("immutable computed record conflicts with held copy".into());
                }
            } else {
                added.insert(&record.id);
            }
        }
        if self.players[i].knowledge.len() + added.len() > knowledge::MAX_HOLDINGS {
            return Err(
                "personal knowledge storage cannot receive all ready output records atomically"
                    .into(),
            );
        }
        Ok(())
    }
    pub(super) fn retrieve_compute_outputs(
        &mut self,
        i: usize,
        n: usize,
        parent: u64,
        station: u32,
        job: u64,
    ) -> Result<u64, String> {
        let index = self.infrastructure.stations[n]
            .jobs
            .iter()
            .position(|j| j.id == job)
            .ok_or("job disappeared")?;
        self.validate_compute_retrieval(i, &self.infrastructure.stations[n].jobs[index])?;
        let records: Vec<_> = self
            .compute_output_records(&self.infrastructure.stations[n].jobs[index])?
            .into_iter()
            .cloned()
            .collect();
        let actor = self.players[i].id;
        let location = self.players[i].position;
        let mut latest = parent;
        for record in records {
            let event=self.event(Some(actor),"compute_retrieved",vec![parent,record.origin],json!({"station":station,"job":job,"record":record.id,"record_kind":if record.program.is_some(){"program"}else{"experiment"},"location":location,"new_copy":!self.players[i].knowledge.iter().any(|h|h.record.id==record.id)}));
            self.receive_record(i, event, None, &record, "compute_terminal")?;
            latest = event;
        }
        self.infrastructure.stations[n].jobs[index].retrieved = true;
        Ok(latest)
    }
}
