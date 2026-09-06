//! Explicit no-model authority diagnostic. Never used by autonomous controllers.
//! The Python runner creates one fresh owned run and captures/revokes it afterward.
use bridge::participant::{new_session, ParticipantService};
use serde::Deserialize;
use serde_json::{json, Value};
use simulation::participant::{Command, Request, API_VERSION};
use spacetimedb_sdk::DbContext;
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const PREFIX: &str = "sim-universal-persistence-probe-";
const SOURCE: &str = "// EXPLICIT_UNIVERSAL_PERSISTENCE_PROBE\nfn cost(skill) { 1 }";
#[derive(Deserialize)]
struct Config {
    server: String,
    database: String,
    run: String,
    output: PathBuf,
    credential_dir: PathBuf,
    cli: PathBuf,
    cli_config: PathBuf,
    setup_deadline_ms: u64,
    death_ms: u64,
    finish_ms: u64,
    wall_timeout_seconds: u64,
}
struct Person {
    actor: u32,
    service: ParticipantService,
}
fn wall_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis()
}
fn write(path: &Path, value: &Value) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    std::fs::write(
        &temporary,
        serde_json::to_vec(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    std::fs::rename(temporary, path).map_err(|e| e.to_string())
}
async fn cli(c: &Config, name: &str, values: Vec<Value>) -> Result<(), String> {
    let mut command = tokio::process::Command::new(&c.cli);
    command
        .arg("--config-path")
        .arg(&c.cli_config)
        .args(["call", &c.database, name]);
    for value in values {
        command.arg(value.to_string());
    }
    let output = tokio::time::timeout(
        Duration::from_secs(20),
        command
            .args(["--server", &c.server, "--no-config", "-y"])
            .output(),
    )
    .await
    .map_err(|_| "operator CLI timeout")?
    .map_err(|_| "operator CLI unavailable")?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "own-run operator {name} failed (output suppressed)"
        ))
    }
}
async fn own(p: &Person) -> Result<Value, String> {
    let cursor = p
        .service
        .current()
        .ok()
        .and_then(|v| v["latest_cursor"].as_u64())
        .unwrap_or(0);
    tokio::time::timeout(
        Duration::from_secs(15),
        p.service.observe(cursor.saturating_sub(128), 128),
    )
    .await
    .map_err(|_| "participant observation timeout")?
}
fn time(v: &Value) -> u64 {
    v["time_ms"].as_u64().unwrap_or(0)
}
fn held<'a>(v: &'a Value, id: &str) -> Option<&'a Value> {
    v["context"]["player"]["knowledge"]
        .as_array()?
        .iter()
        .find(|h| h["record"]["id"] == id)
}
fn scope<'a>(v: &'a Value, kind: &str) -> Option<&'a Value> {
    v["context"]["research"]["law_research"]["scopes"]
        .as_array()?
        .iter()
        .find(|s| {
            if kind == "west" {
                s["scope"]["kind"] == "territory" && s["scope"]["region"] == "west"
            } else {
                s["scope"]["kind"] == kind
            }
        })
}
fn idle() -> Value {
    json!({"kind":"priority","children":[
        {"kind":"guard","condition":{"kind":"all","conditions":[
            {"kind":"resource","resource":"hunger","comparison":"at_least","value":35},
            {"kind":"resource","resource":"food","comparison":"at_least","value":1}]},
            "child":{"kind":"action","action":{"skill":"eat","duration":1}}},
        {"kind":"guard","condition":{"kind":"resource","resource":"energy","comparison":"below","value":30},
            "child":{"kind":"action","action":{"skill":"rest","duration":1}}},
        {"kind":"action","action":{"skill":"wait","duration":1}}
    ]})
}
async fn replace(
    p: &Person,
    c: &Config,
    action: Option<Value>,
    tag: &str,
    log: &mut Vec<Value>,
) -> Result<u64, String> {
    let observed = own(p).await?;
    if action.is_some() && tag != "east-after-death" && time(&observed) >= c.setup_deadline_ms {
        return Err("prospective setup deadline reached; no further setup commands allowed".into());
    }
    if tag == "east-after-death" && time(&observed) >= c.finish_ms {
        return Err("prospective final ceiling reached".into());
    }
    if observed["context"]["player"]["health"] == 0 {
        return Err("actor is dead; no command attempted".into());
    }
    let mut tree = idle();
    if let Some(action) = action {
        tree["children"].as_array_mut().unwrap().insert(
            0,
            json!({"kind":"once","child":{"kind":"action","action":action}}),
        );
    }
    let receipt = p
        .service
        .command(Request {
            api_version: API_VERSION.into(),
            request_id: format!("universal-probe-{tag}-{}", wall_ms()),
            control_epoch: observed["control_epoch"]
                .as_u64()
                .ok_or("control epoch missing")?,
            command: Command::ReplaceTree {
                expected_revision: observed["policy_revision"]
                    .as_u64()
                    .ok_or("policy revision missing")?,
                reason: format!("Declared no-model capability diagnostic: {tag}"),
                tree: serde_json::from_value(tree).map_err(|e| e.to_string())?,
            },
        })
        .await?;
    log.push(
        json!({"phase":tag,"actor":p.actor,"observed_time_ms":time(&observed),"receipt":receipt}),
    );
    write(&c.output.join("receipts.json"), &json!(log))?;
    if !receipt.ok {
        return Err(format!("{tag} rejected: {:?}", receipt.error));
    }
    Ok(receipt.event)
}
async fn operation(
    p: &Person,
    c: &Config,
    op: Value,
    tag: &str,
    log: &mut Vec<Value>,
) -> Result<u64, String> {
    replace(
        p,
        c,
        Some(json!({"skill":"infrastructure","duration":1,"infrastructure":op})),
        tag,
        log,
    )
    .await
}
async fn wait_for(
    p: &Person,
    c: &Config,
    what: &str,
    until_ms: u64,
    predicate: impl Fn(&Value) -> bool,
) -> Result<Value, String> {
    let deadline = Instant::now() + Duration::from_secs(c.wall_timeout_seconds);
    loop {
        let observed = own(p).await?;
        if predicate(&observed) && time(&observed) <= until_ms {
            return Ok(observed);
        }
        if time(&observed) >= until_ms || Instant::now() > deadline {
            return Err(format!("deadline waiting for {what}"));
        }
        if observed["context"]["player"]["health"] == 0 {
            return Err(format!("actor died waiting for {what}"));
        }
        tokio::time::sleep(Duration::from_millis(300)).await;
    }
}
fn event<'a>(v: &'a Value, after: u64, predicate: impl Fn(&Value) -> bool) -> Option<&'a Value> {
    v["experiences"]
        .as_array()?
        .iter()
        .rev()
        .find(|e| e["source"].as_u64().unwrap_or(0) > after && predicate(e))
}
async fn assess(
    p: &Person,
    c: &Config,
    id: &str,
    inspect: bool,
    log: &mut Vec<Value>,
) -> Result<Value, String> {
    let mut observed = own(p).await?;
    let source = if inspect {
        let floor = operation(
            p,
            c,
            json!({"op":"inspect_law","station":1,"record":id}),
            "inspect-held-code",
            log,
        )
        .await?;
        observed = wait_for(
            p,
            c,
            "exact personally held code inspection",
            c.setup_deadline_ms,
            |v| {
                event(v, floor, |e| {
                    e["kind"] == "perception"
                        && e["data"]["kind"] == "law_inspected"
                        && e["data"]["content"]["record"] == id
                })
                .is_some()
            },
        )
        .await?;
        let e = event(&observed, floor, |e| {
            e["kind"] == "perception"
                && e["data"]["kind"] == "law_inspected"
                && e["data"]["content"]["record"] == id
        })
        .unwrap();
        if e["data"]["content"]["law_program"]["source"] != SOURCE {
            return Err("inspection source differs from declared artifact".into());
        }
        e["source"].as_u64().ok_or("inspection source missing")?
    } else {
        held(&observed, id).ok_or("own proof not held")?["source"]
            .as_u64()
            .ok_or("own acquisition source missing")?
    };
    if time(&observed) >= c.setup_deadline_ms {
        return Err("setup deadline before assessment".into());
    }
    let receipt=p.service.command(Request{api_version:API_VERSION.into(),request_id:format!("universal-probe-assess-{}-{}",p.actor,wall_ms()),
        control_epoch:observed["control_epoch"].as_u64().ok_or("epoch missing")?,
        command:Command::Reflect{expected_revision:observed["learning_revision"].as_u64().ok_or("learning revision missing")?,
            observed_cursor:observed["latest_cursor"].as_u64().ok_or("cursor missing")?,goal:None,
            reflections:vec![simulation::Reflection{source,interpretation:if inspect {"I assessed the exact code I physically hold; reading supplies no paid universal proof."}else{"I assessed my own retrieved paid universal experiment, limited to its exact source, binding and submitted cases."}.into(),knowledge:None,caution_delta:0,trust_delta:0,belief:None}]}}).await?;
    log.push(
        json!({"phase":"assess","actor":p.actor,"record":id,"source":source,"receipt":receipt}),
    );
    write(&c.output.join("receipts.json"), &json!(log))?;
    if !receipt.ok {
        return Err(format!("assessment rejected: {:?}", receipt.error));
    }
    wait_for(p, c, "personal interpretation", c.setup_deadline_ms, |v| {
        held(v, id).is_some_and(|h| h["interpreted_source"] == source)
    })
    .await
}
fn own_job<'a>(v: &'a Value, old_jobs: &[u64]) -> Option<&'a Value> {
    v["context"]["infrastructure"]["stations"]
        .as_array()?
        .iter()
        .find(|s| s["id"] == 1)?["own_jobs"]
        .as_array()?
        .iter()
        .find(|j| {
            j["id"].as_u64().is_some_and(|id| !old_jobs.contains(&id))
                && j["law"].is_object()
                && j["report"].is_string()
                && j["retrieved"] == false
        })
}
async fn paid_job(
    p: &Person,
    c: &Config,
    op: Value,
    tag: &str,
    log: &mut Vec<Value>,
) -> Result<Value, String> {
    let before = own(p).await?;
    let old_jobs = before["context"]["infrastructure"]["stations"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|s| s["id"] == 1)
        .flat_map(|s| s["own_jobs"].as_array().into_iter().flatten())
        .filter_map(|j| j["id"].as_u64())
        .collect::<Vec<_>>();
    operation(p, c, op, tag, log).await?;
    let completed = wait_for(p, c, "own paid law job", c.setup_deadline_ms, |v| {
        own_job(v, &old_jobs).is_some()
    })
    .await?;
    let job = own_job(&completed, &old_jobs).unwrap().clone();
    let record = job["law"]["record"]
        .as_str()
        .ok_or("law record missing")?
        .to_owned();
    let report = job["report"]
        .as_str()
        .ok_or("law report missing")?
        .to_owned();
    operation(
        p,
        c,
        json!({"op":"retrieve_job","station":1,"job":job["id"]}),
        "retrieve-own-law-job",
        log,
    )
    .await?;
    let retrieved = wait_for(p, c, "physical job retrieval", c.setup_deadline_ms, |v| {
        held(v, &record).is_some() && held(v, &report).is_some()
    })
    .await?;
    Ok(
        json!({"job":job,"code":held(&retrieved,&record).unwrap(),"proof":held(&retrieved,&report).unwrap(),"retrieved_observation":retrieved}),
    )
}
async fn install(
    p: &Person,
    c: &Config,
    kind: &str,
    code: &str,
    proof: Option<&str>,
    log: &mut Vec<Value>,
) -> Result<Value, String> {
    let observed = own(p).await?;
    let s = scope(&observed, kind).ok_or("scope unavailable")?.clone();
    operation(p,c,json!({"op":"install_law","station":1,"scope":s["scope"],"record":code,
        "experiment_record":proof,"expected_revision":s["revision"],"expected_binding":s["binding"]}),"install-law",log).await?;
    wait_for(p, c, "law activation", c.setup_deadline_ms, |v| {
        scope(v, kind).is_some_and(|s| s["revision"] == 1)
    })
    .await
}
async fn gather_cost(
    p: &Person,
    c: &Config,
    tag: &str,
    expected: i64,
    after_death: bool,
    log: &mut Vec<Value>,
) -> Result<Value, String> {
    let floor = replace(p, c, Some(json!({"skill":"gather","duration":1})), tag, log).await?;
    let end = if after_death {
        c.finish_ms
    } else {
        c.setup_deadline_ms
    };
    let observed = wait_for(p, c, tag, end, |v| {
        event(v, floor, |e| {
            e["kind"] == "skill_result"
                && e["data"]["skill"] == "gather"
                && e["data"]["status"] == "completed"
        })
        .is_some()
    })
    .await?;
    let result = event(&observed, floor, |e| {
        e["kind"] == "skill_result"
            && e["data"]["skill"] == "gather"
            && e["data"]["status"] == "completed"
    })
    .unwrap()
    .clone();
    let attempt = event(&observed, floor, |e| {
        e["kind"] == "skill_attempt" && e["data"]["action"]["skill"] == "gather"
    })
    .ok_or("gather attempt absent from same retained read")?
    .clone();
    let cost = attempt["data"]["before"]["energy"]
        .as_i64()
        .ok_or("before energy missing")?
        - result["data"]["after"]["energy"]
            .as_i64()
            .ok_or("after energy missing")?;
    if attempt["data"]["before"]["position"] != 88
        || result["data"]["after"]["position"] != 88
        || cost != expected
    {
        return Err(format!(
            "east gather cost mismatch: expected{expected}, actual{cost}"
        ));
    }
    Ok(
        json!({"expected_cost":expected,"actual_cost":cost,"attempt":attempt,"result":result,"observation":observed}),
    )
}
async fn exercise(c: &Config, people: &[Person], log: &mut Vec<Value>) -> Result<Value, String> {
    let teacher = &people[0];
    let learner = &people[1];
    let east = &people[2];
    let initial = own(teacher).await?;
    if scope(&initial, "west").is_none_or(|s| s["local_grant"] != true || s["revision"] != 0) {
        return Err("fixture lacks pristine teacher west grant".into());
    }
    let baseline = gather_cost(east, c, "east-baseline", 4, false, log).await?;
    let author=paid_job(teacher,c,json!({"op":"prototype_law","station":1,"scope":{"kind":"territory","region":"west"},
        "draft":{"interface_version":1,"source":SOURCE},"cases":[{"hook":"cost","input":"AUTHOR_PRIVATE_CASE","expected":1}],"sources":[]}),"teacher-paid-prototype",log).await?;
    let code = author["code"]["record"]["id"]
        .as_str()
        .ok_or("teacher code ID missing")?
        .to_owned();
    let teacher_proof = author["proof"]["record"]["id"]
        .as_str()
        .ok_or("teacher proof ID missing")?
        .to_owned();
    // The held-record catalog intentionally omits source. Read through the real
    // terminal inspection action, then personally assess that observation.
    let teacher_inspected = assess(teacher, c, &code, true, log).await?;
    let artifact = event(&teacher_inspected, 0, |e| {
        e["kind"] == "perception"
            && e["data"]["kind"] == "law_inspected"
            && e["data"]["content"]["record"] == code
    })
    .ok_or("teacher inspection observation missing")?["data"]["content"]["law_program"]
        .clone();
    if artifact["source"] != SOURCE {
        return Err("prototype source mismatch".into());
    }
    let local = install(teacher, c, "west", &code, None, log).await?;
    let east_after_local = gather_cost(east, c, "east-after-local-only", 4, false, log).await?;
    replace(
        teacher,
        c,
        Some(json!({"skill":"teach","target":2,"record":code,"duration":1})),
        "physically-teach-code-only",
        log,
    )
    .await?;
    let taught = wait_for(
        learner,
        c,
        "physically taught code",
        c.setup_deadline_ms,
        |v| held(v, &code).is_some(),
    )
    .await?;
    if held(&taught, &code).unwrap()["record"]["law_program"]["source_hash"]
        != artifact["source_hash"]
        || held(&taught, &teacher_proof).is_some()
        || taught.to_string().contains("AUTHOR_PRIVATE_CASE")
    {
        return Err("taught code/source or author-private-proof separation failed".into());
    }
    let interpreted = assess(learner, c, &code, true, log).await?;
    let learner_artifact = &event(&interpreted, 0, |e| {
        e["kind"] == "perception"
            && e["data"]["kind"] == "law_inspected"
            && e["data"]["content"]["record"] == code
    })
    .ok_or("learner inspection observation missing")?["data"]["content"]["law_program"];
    if learner_artifact != &artifact {
        return Err("learner inspected source differs from teacher artifact".into());
    }
    let universal_before = scope(&interpreted, "universal")
        .ok_or("universal scope missing")?
        .clone();
    if universal_before["revision"] != 0 || universal_before["local_grant"] != false {
        return Err("learner unexpectedly has universal grant/revision".into());
    }
    // Check the real action gate before obtaining personal universal proof.
    let floor=operation(learner,c,json!({"op":"install_law","station":1,"scope":{"kind":"universal"},"record":code,
        "experiment_record":null,"expected_revision":0,"expected_binding":universal_before["binding"]}),"universal-denied-before-own-proof",log).await?;
    let denied = wait_for(
        learner,
        c,
        "universal denial without own proof",
        c.setup_deadline_ms,
        |v| {
            event(v, floor, |e| {
                e["kind"] == "skill_result"
                    && e["data"]["status"] == "failed"
                    && e["data"]["reason"]
                        .as_str()
                        .is_some_and(|s| s.contains("matching personally assessed law experiment"))
            })
            .is_some()
        },
    )
    .await?;
    let practice = paid_job(
        learner,
        c,
        json!({"op":"practice_law","station":1,"scope":{"kind":"universal"},"record":code,
        "cases":[{"hook":"cost","input":"gather","expected":1}],"sources":[]}),
        "learner-paid-universal-practice",
        log,
    )
    .await?;
    let proof_id = practice["proof"]["record"]["id"]
        .as_str()
        .ok_or("learner proof ID missing")?
        .to_owned();
    let proof = &practice["proof"]["record"]["law_experiment"];
    if proof["operator"] != 2
        || proof["scope"]["kind"] != "universal"
        || proof["binding"]["digest"] != universal_before["binding"]
        || proof["program_hash"] != artifact["source_hash"]
        || proof["paid_quanta"] != 3
        || proof["successful"] != true
    {
        return Err(
            "learner exact-source/current-universal-binding/paid proof contract failed".into(),
        );
    }
    let assessed = assess(learner, c, &proof_id, false, log).await?;
    if scope(&assessed, "universal").unwrap()["binding"] != universal_before["binding"] {
        return Err("universal binding changed after practice".into());
    }
    let activated = install(learner, c, "universal", &code, Some(&proof_id), log).await?;
    let east_after_universal = gather_cost(east, c, "east-after-universal", 1, false, log).await?;
    Ok(
        json!({"source":SOURCE,"artifact":artifact,"code":code,"teacher_proof":teacher_proof,"learner_proof":proof_id,
        "baseline_east":baseline,"teacher_paid_job":author,"local_activation":local,"east_after_local_only":east_after_local,
        "physical_teaching_observation":taught,"learner_code_interpretation":interpreted,"denial_without_own_proof":denied,
        "universal_binding_tested":universal_before["binding"],"learner_paid_practice":practice,"learner_proof_assessment":assessed,
        "universal_activation":activated,"east_after_universal":east_after_universal}),
    )
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    if std::env::args().nth(1).as_deref() == Some("--check-fixture") {
        let scenario: simulation::Scenario = serde_json::from_slice(&std::fs::read(
            std::env::args().nth(2).ok_or("fixture path required")?,
        )?)?;
        let world = simulation::World::new("offline-universal-probe-preflight".into(), scenario)?;
        if !world.laws.active.is_empty() || world.players.iter().any(|p| !p.knowledge.is_empty()) {
            return Err("fixture unexpectedly seeds knowledge or active laws".into());
        }
        println!("fixture parses and initializes locally; no authority connection opened");
        return Ok(());
    }
    let c: Config = serde_json::from_slice(&std::fs::read(
        std::env::args().nth(1).ok_or("config JSON required")?,
    )?)?;
    if !c.run.starts_with(PREFIX)
        || !c.run.chars().all(|x| x.is_ascii_alphanumeric() || x == '-')
        || !c.server.starts_with("http://127.0.0.1:")
        || !(120_000..=240_000).contains(&c.death_ms)
        || c.setup_deadline_ms + 30_000 > c.death_ms
        || c.finish_ms != c.death_ms + 20_000
        || c.wall_timeout_seconds > 360
    {
        return Err("explicit fresh local bounded fixture config required".into());
    }
    let mut people = Vec::new();
    let mut identities = Vec::new();
    let mut log = Vec::new();
    let setup: Result<Value, String> = async {
        for actor in 1..=4 {
            let path = c
                .credential_dir
                .join(format!("{}-actor-{actor}.json", c.run));
            let (service, identity) =
                new_session(c.server.clone(), c.database.clone(), &path).await?;
            identities.push(identity.clone());
            write(&c.output.join("identities.json"), &json!(identities))?;
            cli(
                &c,
                "sim_grant_client",
                vec![json!(c.run), json!(identity), json!(false), json!(actor)],
            )
            .await?;
            people.push(Person { actor, service });
            replace(
                people.last().unwrap(),
                &c,
                None,
                "declared-idle-survival",
                &mut log,
            )
            .await?;
        }
        cli(
            &c,
            "sim_operator_clock",
            vec![json!(c.run), json!(50), json!(false)],
        )
        .await?;
        tokio::time::timeout(
            Duration::from_secs(c.wall_timeout_seconds),
            exercise(&c, &people, &mut log),
        )
        .await
        .map_err(|_| "wall deadline during setup".to_owned())?
    }
    .await;
    write(
        &c.output.join("capability-result.json"),
        &match &setup {
            Ok(v) => json!({"setup_completed":true,"evidence":v}),
            Err(e) => json!({"setup_completed":false,"error":e}),
        },
    )?;
    let mut persistence = Err("witness session unavailable".to_owned());
    if let Some(east) = people.iter().find(|p| p.actor == 3) {
        let after = wait_for(
            east,
            &c,
            "prospective learner death boundary",
            c.finish_ms,
            |v| time(v) >= c.death_ms + 1000,
        )
        .await;
        persistence = match after {
            Ok(observed) => {
                if setup.is_ok() {
                    gather_cost(east,&c,"east-after-death",1,true,&mut log).await.map(|effect|json!({"post_death_boundary_observation":observed,"east_effect":effect}))
                } else {
                    Ok(
                        json!({"setup_noncompletion_capture":observed,"persistence_not_claimed":true}),
                    )
                }
            }
            Err(e) => Err(e),
        };
    }
    let pause = cli(&c, "sim_operator_pause", vec![json!(c.run)]).await;
    let final_status = people
        .iter()
        .map(|p| json!({"actor":p.actor,"status":p.service.current().ok()}))
        .collect::<Vec<_>>();
    let report = json!({"run":c.run,"model_calls":0,"explicit_tooling_fixture":true,"autonomous_evidence":false,
        "setup_completed":setup.is_ok(),"setup_error":setup.as_ref().err(),"persistence_evidence":persistence.as_ref().ok(),
        "persistence_error":persistence.as_ref().err(),"pause_error":pause.as_ref().err(),"final_participants":final_status,
        "candidate_source":SOURCE,"scheduled_learner_death_ms":c.death_ms,"receipts":log,
        "participant_checks_pass":setup.is_ok()&&persistence.is_ok()&&pause.is_ok(),
        "final_authority_audit_required":"Python must verify actual learner death, own paid proof, activation author/scope/binding and east physical effects before declaring pass."});
    write(&c.output.join("participant-result.json"), &report)?;
    for p in people {
        let _ = p.service.connection.disconnect();
    }
    if report["participant_checks_pass"] != true {
        return Err("probe did not complete; preserve capability and final evidence".into());
    }
    Ok(())
}
