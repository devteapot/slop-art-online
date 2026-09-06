//! Paid, private experiments on actual law source, carried as physical records.
use crate::*;
use infrastructure::{ComputeJob, InfrastructureOperation as Op, Module};
use knowledge::Record;
use laws::{LawArtifact, LawBinding, LawRef, LawRevision, LawScope, PendingLaw};
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LawCase {
    pub hook: String,
    pub input: Value,
    pub expected: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LawEvidence {
    pub operator: u32,
    pub station: u32,
    pub job: u64,
    pub scope: LawScope,
    pub binding: LawBinding,
    pub program_hash: String,
    pub input_hash: String,
    pub cases: Vec<LawCase>,
    pub results: Vec<Result<Value, String>>,
    pub successful: bool,
    pub paid_quanta: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LawWork {
    pub scope: LawScope,
    pub binding: LawBinding,
    pub program_record: Record,
    pub cases: Vec<LawCase>,
}
impl World {
    fn held_law(&self, i: usize, id: &str, interpreted: bool) -> Result<&Record, String> {
        let h = self.players[i]
            .knowledge
            .iter()
            .find(|h| h.record.id == id && h.record.law_program.is_some())
            .ok_or("law program is not personally held")?;
        if interpreted && (h.interpretation.is_none() || h.interpreted_source.is_none()) {
            return Err("law program requires personal interpretation".into());
        }
        laws::validate(h.record.law_program.as_ref().unwrap())?;
        Ok(&h.record)
    }
    fn law_cases(
        &self,
        i: usize,
        artifact: &LawArtifact,
        cases: &[LawCase],
        sources: &[String],
    ) -> Result<(), String> {
        self.validate_numeric_inputs(i, &[], sources, None)?;
        if cases.is_empty()
            || cases.len() > 16
            || serde_json::to_vec(cases).map_err(|e| e.to_string())?.len() > 32_768
        {
            return Err("law experiment requires 1..16 cases within 32 KiB".into());
        }
        for case in cases {
            if !artifact.hooks.contains(&case.hook)
                || serde_json::to_vec(&case.input)
                    .map_err(|e| e.to_string())?
                    .len()
                    > 4096
                || serde_json::to_vec(&case.expected)
                    .map_err(|e| e.to_string())?
                    .len()
                    > 4096
            {
                return Err(
                    "case needs an authored hook and bounded private input/prediction".into(),
                );
            }
            if ["cost", "action_interval_ms"].contains(&case.hook.as_str()) {
                if !case
                    .input
                    .as_str()
                    .is_some_and(|s| !s.is_empty() && s.len() <= 48)
                {
                    return Err("cost and action_interval_ms receive a skill name".into());
                }
            } else if case.hook != "observation" && !case.input.is_object() {
                return Err("law hook receives an explicit case object".into());
            }
            laws::validate_output(&case.hook, &case.expected)?;
        }
        if artifact
            .hooks
            .iter()
            .any(|hook| !cases.iter().any(|c| &c.hook == hook))
        {
            return Err("each authored hook needs a submitted prediction".into());
        }
        Ok(())
    }
    fn matching_law_proof(
        &self,
        i: usize,
        scope: &LawScope,
        artifact: &LawArtifact,
        binding: &LawBinding,
        record: Option<&str>,
    ) -> bool {
        self.players[i].knowledge.iter().any(|h| {
            record.is_none_or(|id| h.record.id == id)
                && h.interpretation.is_some()
                && h.interpreted_source.is_some()
                && h.record.author == self.players[i].id
                && h.record.law_experiment.as_ref().is_some_and(|e| {
                    e.operator == self.players[i].id
                        && e.scope == *scope
                        && e.binding == *binding
                        && e.program_hash == artifact.source_hash
                        && e.paid_quanta > 0
                        && e.successful
                })
        })
    }
    fn law_install_allowed(
        &self,
        i: usize,
        scope: &LawScope,
        artifact: &LawArtifact,
        binding: &LawBinding,
        experiment: Option<&str>,
    ) -> Result<bool, String> {
        let auth = if matches!(scope, LawScope::Universal) {
            self.law_binding_at(None)
        } else {
            binding.clone()
        };
        self.bound_law(&auth,"authorize_law_edit",json!({"actor":scripting::facts(&self.players[i]),"scope":if matches!(scope,LawScope::Universal){"universal"}else{"territory"},"local_grant":self.local_law_grant(self.players[i].id,scope),"own_matching_assessed_experiment":self.matching_law_proof(i,scope,artifact,binding,experiment)}))
    }
    pub(super) fn validate_law_operation(
        &self,
        i: usize,
        n: usize,
        op: &Op,
    ) -> Result<bool, String> {
        if !matches!(
            op,
            Op::PrototypeLaw { .. }
                | Op::PracticeLaw { .. }
                | Op::InspectLaw { .. }
                | Op::InspectInstalledLaw { .. }
                | Op::InstallLaw { .. }
        ) {
            return Ok(false);
        }
        if self.initial.society.is_none() {
            return Err(
                "law research requires configured society scopes (regions may be empty)".into(),
            );
        }
        let s = &self.infrastructure.stations[n];
        if !s.enabled || s.integrity <= 0 || !s.seed.modules.contains(&Module::Terminal) {
            return Err("law work requires a working local terminal".into());
        }
        match op {
            Op::PrototypeLaw {
                scope,
                draft,
                cases,
                sources,
                ..
            } => {
                self.binding_for_scope(i, scope)?;
                if !self.local_law_grant(self.players[i].id, scope)
                    && !self.can_author_program(i)?
                {
                    return Err("law authorship requires personally interpreted paid terminal competence or a local initial grant".into());
                }
                let artifact = laws::compile(draft)?;
                self.law_cases(i, &artifact, cases, sources)?;
            }
            Op::PracticeLaw {
                scope,
                record,
                cases,
                sources,
                ..
            } => {
                self.binding_for_scope(i, scope)?;
                let r = self.held_law(i, record, true)?;
                self.law_cases(i, r.law_program.as_ref().unwrap(), cases, sources)?;
            }
            Op::InspectLaw { record, .. } => {
                self.held_law(i, record, false)?;
            }
            Op::InspectInstalledLaw { scope, .. } => {
                self.binding_for_scope(i, scope)?;
                if self.law_scope_revision(scope) == 0 {
                    return Err("no installed law in this accessible scope".into());
                }
            }
            Op::InstallLaw {
                scope,
                record,
                experiment_record,
                expected_revision,
                expected_binding,
                ..
            } => {
                let binding = self.binding_for_scope(i, scope)?;
                if self.law_scope_revision(scope) != *expected_revision
                    || binding.digest != *expected_binding
                    || self
                        .laws
                        .pending
                        .iter()
                        .any(|p| p.revision.reference.scope == *scope)
                {
                    return Err("stale law revision/binding or competing pending edit".into());
                }
                let held = self.held_law(i, record, false)?;
                let artifact = held.law_program.as_ref().unwrap();
                if !self.law_install_allowed(
                    i,
                    scope,
                    artifact,
                    &binding,
                    experiment_record.as_deref(),
                )? {
                    return Err("current law denies installation: matching personally assessed law experiment or local grant required".into());
                }
                if self.laws.history.values().map(|h| h.len()).sum::<usize>()
                    + self.laws.pending.len()
                    >= 128
                {
                    return Err("installed law revision storage budget reached".into());
                }
                let mut prospective = self.laws.clone();
                prospective.pending.push(PendingLaw {
                    update: self.timing.updates + 1,
                    expected_binding: binding.clone(),
                    location: self.players[i].position,
                    revision: LawRevision {
                        reference: LawRef {
                            scope: scope.clone(),
                            revision: expected_revision
                                .checked_add(1)
                                .ok_or("law revision overflow")?,
                        },
                        artifact: artifact.clone(),
                        author: self.players[i].id,
                        origin: self.next_event,
                        installed_ms: self.timing.time_ms,
                    },
                });
                if serde_json::to_vec(&prospective)
                    .map_err(|e| e.to_string())?
                    .len()
                    > 2_097_152
                {
                    return Err("installed law byte storage budget reached".into());
                }
            }
            _ => unreachable!(),
        }
        if matches!(op, Op::PrototypeLaw { .. } | Op::PracticeLaw { .. })
            && (s.jobs.len() >= infrastructure::MAX_JOBS
                || self.infrastructure.next_job == u64::MAX)
        {
            return Err("retained terminal job capacity is full".into());
        }
        Ok(true)
    }
    pub(super) fn apply_law_operation(
        &mut self,
        i: usize,
        n: usize,
        parent: u64,
        op: &Op,
    ) -> Result<Option<u64>, String> {
        let actor = self.players[i].id;
        let position = self.players[i].position;
        let station = self.infrastructure.stations[n].seed.id;
        let (scope, record, cases, sources) = match op {
            Op::PrototypeLaw {
                scope,
                draft,
                cases,
                sources,
                ..
            } => {
                let artifact = laws::compile(draft)?;
                let origin = self.next_event;
                let job = self.infrastructure.next_job;
                let record=Record{law_program:Some(artifact),law_experiment:None,program:None,experiment:None,id:self.fresh_material_record_id("law",job,origin),topic:"Authored physical law".into(),text:"Executable law-hook source. This code record carries no private experiment cases or proof of general correctness.".into(),location:None,author:actor,origin,confidence:50};
                (scope.clone(), record, cases.clone(), sources.clone())
            }
            Op::PracticeLaw {
                scope,
                record,
                cases,
                sources,
                ..
            } => (
                scope.clone(),
                self.held_law(i, record, true)?.clone(),
                cases.clone(),
                sources.clone(),
            ),
            Op::InspectLaw { record, .. } => {
                let artifact = self.held_law(i, record, false)?.law_program.clone();
                let event = self.event(
                    Some(actor),
                    "law_inspected",
                    vec![parent],
                    json!({"record":record,"location":position}),
                );
                self.perceive(
                    i,
                    event,
                    "law_inspected",
                    None,
                    position,
                    json!({"record":record,"law_program":artifact}),
                )?;
                return Ok(Some(event));
            }
            Op::InspectInstalledLaw { scope, .. } => {
                let revision = self.law_scope_revision(scope);
                let law = self.laws.history[&scope.key()][&revision].clone();
                let event = self.event(
                    Some(actor),
                    "law_inspected",
                    vec![parent, law.origin],
                    json!({"reference":law.reference,"location":position}),
                );
                self.perceive(i,event,"law_inspected",None,position,json!({"installed":law.reference,"law_program":law.artifact,"meaning":"Installed law is an operative source copy, accessible only from an affected scope at a working terminal."}))?;
                return Ok(Some(event));
            }
            Op::InstallLaw {
                scope,
                record,
                experiment_record,
                expected_revision,
                ..
            } => {
                let artifact = self
                    .held_law(i, record, false)?
                    .law_program
                    .clone()
                    .unwrap();
                let binding = self.binding_for_scope(i, scope)?;
                let origin = self.next_event;
                let reference = LawRef {
                    scope: scope.clone(),
                    revision: expected_revision
                        .checked_add(1)
                        .ok_or("law revision overflow")?,
                };
                let event=self.event(Some(actor),"law_edit_staged",vec![parent],json!({"reference":reference,"source_hash":artifact.source_hash,"hooks":artifact.hooks,"activate_update":self.timing.updates+1,"binding":binding.digest,"expected_binding":binding,"expected_revision":expected_revision,"record":record,"experiment_record":experiment_record,"location":position}));
                self.laws.pending.push(PendingLaw {
                    update: self.timing.updates + 1,
                    expected_binding: binding,
                    location: position,
                    revision: LawRevision {
                        reference,
                        artifact,
                        author: actor,
                        origin,
                        installed_ms: self.timing.time_ms,
                    },
                });
                return Ok(Some(event));
            }
            _ => return Ok(None),
        };
        let binding = self.binding_for_scope(i, &scope)?;
        let id = self.infrastructure.next_job;
        self.infrastructure.next_job += 1;
        let source_records = sources
            .iter()
            .map(|id| {
                self.players[i]
                    .knowledge
                    .iter()
                    .find(|h| h.record.id == *id)
                    .unwrap()
                    .record
                    .clone()
            })
            .collect::<Vec<_>>();
        let hash = laws::digest(&(&scope, &binding, &record, &cases, &source_records));
        let required = self.infrastructure.balance.compute_quanta;
        let event=self.event(Some(actor),"compute_submitted",vec![parent],json!({"station":station,"job":id,"experiment_kind":"law","scope":scope,"program_record":record,"binding":binding,"cases":cases,"source_records":source_records,"new_program":matches!(op,Op::PrototypeLaw{..}),"input_hash":hash,"required_quanta":required,"quantum_ms":self.infrastructure.balance.compute_quantum_ms,"location":position}));
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
            source: event,
            input: None,
            program_work: None,
            law_work: Some(LawWork {
                scope,
                binding,
                program_record: record,
                cases,
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
        Ok(Some(event))
    }
    pub(super) fn finish_law_job(
        &mut self,
        n: usize,
        j: usize,
        cause: u64,
        at: u64,
    ) -> Result<u64, String> {
        let job = self.infrastructure.stations[n].jobs[j].clone();
        let work = job.law_work.as_ref().ok_or("law job missing work")?;
        let artifact = work
            .program_record
            .law_program
            .as_ref()
            .ok_or("law job missing physical code")?;
        let results = match self.candidate_layers(&work.binding, &work.scope, artifact) {
            Ok(layers) => work
                .cases
                .iter()
                .map(|c| {
                    self.scripts.evaluate_law_candidate(
                        &work.binding.base,
                        &layers,
                        &work.binding.disabled,
                        &c.hook,
                        c.input.clone(),
                    )
                })
                .collect::<Vec<_>>(),
            Err(error) => work.cases.iter().map(|_| Err(error.clone())).collect(),
        };
        let successful = results
            .iter()
            .zip(&work.cases)
            .all(|(r, c)| r.as_ref().is_ok_and(|v| v == &c.expected));
        let station = self.infrastructure.stations[n].seed.id;
        let position = self.infrastructure.stations[n].seed.position;
        let evidence = LawEvidence {
            operator: job.owner,
            station,
            job: job.id,
            scope: work.scope.clone(),
            binding: work.binding.clone(),
            program_hash: artifact.source_hash.clone(),
            input_hash: job.input_hash.clone(),
            cases: work.cases.clone(),
            results,
            successful,
            paid_quanta: job.progress,
        };
        let origin = self.next_event;
        let record=Record{law_program:None,law_experiment:Some(evidence),program:None,experiment:None,id:self.fresh_compute_record_id(job.id,origin),topic:"Private physical-law experiment".into(),text:format!("Paid law experiment. Submitted predictions {}. Evidence concerns only the exact source, binding and cases; it does not establish arbitrary future correctness.",if successful{"matched"}else{"failed"}),location:None,author:job.owner,origin,confidence:50};
        self.event(Some(job.owner),"compute_completed",vec![cause,job.source],json!({"station":station,"job":job.id,"experiment_kind":"law","program_hash":artifact.source_hash,"input_hash":job.input_hash,"successful":successful,"record":record,"program_record":work.program_record,"location":position,"quantum_at_ms":at}));
        self.infrastructure.stations[n].jobs[j].report = Some(record);
        Ok(origin)
    }
    pub(super) fn law_research_facts(&self, actor: u32) -> Value {
        if self.initial.society.is_none() {
            return Value::Null;
        }
        let Ok(i) = self.idx(actor) else {
            return Value::Null;
        };
        let position = self.players[i].position;
        let mut scopes = vec![LawScope::Universal];
        if let Some(s) = &self.initial.society {
            scopes.extend(
                s.regions
                    .iter()
                    .filter(|r| self.region_contains(r, position))
                    .map(|r| LawScope::Territory {
                        region: r.id.clone(),
                    }),
            );
        }
        json!({"effective_binding":self.law_binding_at(Some(position)),"scopes":scopes.iter().map(|s|json!({"scope":s,"revision":self.law_scope_revision(s),"binding":self.binding_for_scope(i,s).ok().map(|b|b.digest),"local_grant":self.local_law_grant(actor,s)})).collect::<Vec<_>>(),
            "programs":self.players[i].knowledge.iter().filter_map(|h|h.record.law_program.as_ref().map(|p|json!({"record":h.record.id,"source_hash":p.source_hash,"hooks":p.hooks,"interpreted":h.interpreted_source.is_some()}))).collect::<Vec<_>>(),
            "experiments":self.players[i].knowledge.iter().filter_map(|h|h.record.law_experiment.as_ref().map(|e|json!({"record":h.record.id,"operator":e.operator,"scope":e.scope,"binding":e.binding.digest,"source_hash":e.program_hash,"successful":e.successful,"interpreted":h.interpreted_source.is_some()}))).collect::<Vec<_>>(),
            "editable_hooks":laws::hook_contracts(),"interface":"Set LawDraft.interface_version to 1. Functions only, 1..8 listed hooks with one argument, source <=8192 bytes. Declare each as fn hook_name(argument), substituting its listed hook name, followed by its body. Rhai functions are public by default; there is no pub keyword. Local bindings use let x = ... and are mutable without a mut keyword. Helpers from the base law may be called; no new helper declarations. cost/action_interval_ms receive a skill name; other hooks receive documented facts. Clock periods and behavior/guard validation are not editable. Each hook needs a case with input and a typed expected output. Private cases <=16 total and 32 KiB; each input/prediction <=4096 bytes.",
            "learning":"Author through personally assessed paid numeric terminal work or an initial grant for this territory. Law practice establishes evidence for the tested candidate; it does not itself grant numeric authoring competence. Reflecting on your InspectLaw perception assesses the exact currently held law code, with or without an additional assertion. Assessed taught code can be practiced directly; reading alone supplies no paid experiment proof. Universal installation needs your own paid, successful, interpreted experiment for the exact candidate and universal binding under current authorization. An initial local grant permits installing retrieved held code without a successful experiment or code assessment. No office, name, role or intelligence score grants power.",
            "scope_contract":"Universal hooks override applicable regional hooks; regional priority wins, then smaller area, then lexicographically smaller ID. Laws activate next update. Stationary actions pin formulas; effects obey current law. Movement rebinds after a cell crossing. Periodic physiology and production use their current cell. Installed laws remain operative after death or loss of other copies.",
            "inspection":"InspectLaw reads personally held code. InspectInstalledLaw reads an operative installed copy from a working terminal in the affected scope; this does not acquire or assess a personal code record. Neither lists remote territorial source. Teach code separately from private experiment evidence."})
    }
}
