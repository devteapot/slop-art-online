//! Host-only identity enrollment. Authority creates characters; this module supplies
//! explicitly configured controller connections, never bodies, goals or knowledge.
use super::*;
use std::collections::{BTreeMap, BTreeSet};

pub const PROTOCOL: &str = "sao-enrollment-v1";

#[derive(Clone, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NewcomerController {
    pub role: String,
    pub config: Config,
}
impl NewcomerController {
    pub fn validate(&self) -> Result<(), String> {
        if !matches!(self.role.as_str(), "builtin" | "external") {
            return Err("newcomer role must be builtin or external".into());
        }
        Reasoner::new(self.config.clone()).map(|_| ())
    }
}

#[derive(Default)]
pub(super) struct Registry {
    links: HashMap<String, BTreeMap<u32, Value>>,
    failed: BTreeSet<(String, u32)>,
    errors: Vec<Value>,
    stopped: bool,
}

pub(super) fn atomic_json(path: &std::path::Path, value: &Value) -> Result<(), String> {
    let temporary = path.with_extension("json.tmp");
    std::fs::write(
        &temporary,
        serde_json::to_vec(value).map_err(|_| "artifact serialization failed")?,
    )
    .map_err(|_| "artifact write failed")?;
    std::fs::rename(temporary, path).map_err(|_| "artifact commit failed".into())
}

fn stop_requested() -> bool {
    std::env::var("BEVY_DEV_ENROLLMENT_STOP_FILE")
        .ok()
        .is_some_and(|path| std::path::Path::new(&path).exists())
}

pub(super) fn roster_limit(world: &simulation::World) -> Result<usize, String> {
    // Read the serialized lifecycle seed so old seeds without lifecycle metadata
    // retain their immutable initial population limit.
    let initial = serde_json::to_value(&world.initial).map_err(|_| "invalid scenario metadata")?;
    let limit = match initial.get("lifecycle").filter(|v| !v.is_null()) {
        Some(seed) => seed.get("max_total").and_then(Value::as_u64).unwrap_or(64) as usize,
        None => world.initial.players.len(),
    };
    if limit < world.initial.players.len() || limit > 256 || world.players.len() > limit {
        return Err("authority roster exceeds its configured lifecycle identity bound".into());
    }
    Ok(limit)
}

fn pending_actors(
    world: &simulation::World,
    registered: &BTreeSet<u32>,
    limit: usize,
) -> Result<Vec<u32>, String> {
    let ids: BTreeSet<_> = world.players.iter().map(|p| p.id).collect();
    if ids.len() != world.players.len() || ids.len() > limit {
        return Err("invalid or excessive authority actor roster".into());
    }
    let initial: BTreeSet<_> = world.initial.players.iter().map(|p| p.id).collect();
    Ok(world
        .players
        .iter()
        .filter(|p| {
            p.health > 0
                && p.controller == simulation::Controller::Ai
                && !initial.contains(&p.id)
                && !registered.contains(&p.id)
        })
        .map(|p| p.id)
        .collect())
}

async fn enroll_locked(
    app: &App,
    registry: &mut Registry,
    run: &str,
    actor: u32,
    role: &str,
    config: Option<&Config>,
    newcomer: bool,
) -> Result<(), String> {
    if registry.stopped || stop_requested() {
        return Err("controller enrollment has stopped".into());
    }
    if registry
        .links
        .get(run)
        .is_some_and(|links| links.contains_key(&actor))
    {
        return Ok(());
    }
    if registry.failed.contains(&(run.into(), actor)) {
        return Err("earlier controller enrollment failed; explicit recovery required".into());
    }
    let dir = app.out.join(run);
    let private = std::env::var("BEVY_DEV_CREDENTIAL_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| app.root.join(".local/credentials"));
    std::fs::create_dir_all(&private).map_err(|_| "private session directory unavailable")?;
    let path = private.join(format!("{run}-actor-{actor}-{role}.json"));
    let (service, identity) = new_session(app.server.clone(), app.db.clone(), &path).await?;
    let admitted = async {
        call(
            app,
            "sim_grant_client",
            vec![json!(run), json!(identity), json!(false), json!(actor)],
        )
        .await?;
        let view = service.observe(0, 256).await?;
        let config_file = dir.join(format!("actor-{actor}-config.json"));
        if let Some(config) = config {
            atomic_json(&config_file, &json!(config))?;
        }
        let link = json!({"actor":actor,"role":role,"identity":identity,"session_file":path,
            "config_file":if config.is_some(){json!(config_file)}else{Value::Null},
            "enrollment":if newcomer{"newcomer"}else{"initial"},"enrolled_at_ms":now()});
        // Publish a complete descriptor before dispatching its controller. An
        // external supervisor may now start it; the grant and config already exist.
        let links = registry.links.entry(run.into()).or_default();
        links.insert(actor, link);
        if let Err(error) = atomic_json(
            &dir.join("participants.json"),
            &json!(links.values().collect::<Vec<_>>()),
        ) {
            links.remove(&actor);
            return Err(error);
        }
        if stop_requested() {
            let _ = service.connection.disconnect();
            return Ok(());
        }
        if role == "builtin" {
            if let Some(config) = config {
                if std::env::var("SAO_HARNESS_MANUAL").as_deref() == Ok("1") {
                    let _ = service.connection.disconnect();
                    return Ok(());
                }
                let (tx, rx) = tokio::sync::watch::channel(None);
                app.harness_cancellations.lock().unwrap().push(tx);
                tokio::spawn(agent_harness::run(
                    service.clone(),
                    config.clone(),
                    if app.controllers.is_empty() && !newcomer {
                        dir.join("reasoning")
                    } else {
                        dir.join("reasoning").join(format!("actor-{actor}"))
                    },
                    rx,
                ));
            } else {
                let fixture: simulation::Decision = serde_json::from_slice(
                    &std::fs::read(app.root.join("scenarios/reactive-client-fixture.json"))
                        .map_err(|_| "fixture missing")?,
                )
                .map_err(|_| "fixture invalid")?;
                let receipt = service
                    .command(simulation::participant::Request {
                        api_version: simulation::participant::API_VERSION.into(),
                        request_id: format!("fixture-{run}"),
                        control_epoch: view["control_epoch"]
                            .as_u64()
                            .ok_or("missing control epoch")?,
                        command: simulation::participant::Command::ReplaceTree {
                            expected_revision: view["policy_revision"]
                                .as_u64()
                                .ok_or("missing policy revision")?,
                            reason: "explicit test-authored developer fixture; no model inference"
                                .into(),
                            tree: fixture.policy.ok_or("fixture tree missing")?,
                        },
                    })
                    .await?;
                if !receipt.ok {
                    return Err(format!("fixture rejected: {:?}", receipt.error));
                }
                let _ = service.connection.disconnect();
            }
        } else {
            let _ = service.connection.disconnect();
        }
        Ok(())
    }
    .await;
    if admitted.is_err() {
        let _ = call(app, "sim_revoke_client", vec![json!(identity)]).await;
        let _ = service.connection.disconnect();
    }
    admitted
}

pub(super) async fn enroll_initial(
    app: &App,
    run: &str,
    actor: u32,
    role: &str,
    config: Option<&Config>,
) -> Result<(), String> {
    let mut registry = app.enrollments.lock().await;
    enroll_locked(app, &mut registry, run, actor, role, config, false).await
}

pub(super) async fn acknowledge_stop(app: &App) -> Result<bool, String> {
    if !stop_requested() {
        return Ok(false);
    }
    // The same lock covers identity grant, descriptor publication and harness
    // dispatch. Its acknowledgement therefore excludes any later enrollment.
    let mut registry = app.enrollments.lock().await;
    registry.stopped = true;
    for cancel in app.harness_cancellations.lock().unwrap().drain(..) {
        let _ = cancel.send(Some("experiment ending; enrollment stopped".into()));
    }
    atomic_json(
        &app.out.join("enrollment-stopped.json"),
        &json!({
            "protocol":PROTOCOL,"phase":"stopped","stopped_at_ms":now(),
            "enrolled":registry.links.values().map(BTreeMap::len).sum::<usize>(),
        }),
    )?;
    Ok(true)
}

pub(super) async fn discover(
    app: &App,
    run: &str,
    world: &simulation::World,
) -> Result<(), String> {
    let Some(template) = &app.newcomer else {
        return Ok(());
    };
    if world.stopped || stop_requested() {
        return Ok(());
    }
    let limit = roster_limit(world)?;
    let mut registry = app.enrollments.lock().await;
    if registry.stopped {
        return Ok(());
    }
    let registered = registry
        .links
        .get(run)
        .map(|links| links.keys().copied().collect())
        .unwrap_or_default();
    for actor in pending_actors(world, &registered, limit)? {
        if stop_requested() {
            break;
        }
        if registry.failed.contains(&(run.into(), actor)) {
            continue;
        }
        if let Err(error) = enroll_locked(
            app,
            &mut registry,
            run,
            actor,
            &template.role,
            Some(&template.config),
            true,
        )
        .await
        {
            registry.failed.insert((run.into(), actor));
            registry.errors.push(json!({"run":run,"actor":actor,"error":error,"at_ms":now(),"retry":"none; explicit recovery required"}));
            atomic_json(
                &app.out.join("enrollment-errors.json"),
                &json!({"errors":registry.errors}),
            )?;
            return Err(error);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn world() -> simulation::World {
        let scenario: simulation::Scenario =
            serde_json::from_str(include_str!("../../../../../scenarios/survival.json")).unwrap();
        simulation::World::new("enrollment-fixture".into(), scenario).unwrap()
    }

    #[test]
    fn discovers_only_new_living_ai_identities_once_with_bound() {
        let mut w = world();
        let mut child = w.players[0].clone();
        child.id = 100;
        w.players.push(child.clone());
        child.id = 101;
        child.health = 0;
        w.players.push(child.clone());
        child.id = 102;
        child.health = 100;
        child.controller = simulation::Controller::Human;
        w.players.push(child);
        assert_eq!(pending_actors(&w, &BTreeSet::new(), 8).unwrap(), vec![100]);
        assert!(pending_actors(&w, &BTreeSet::from([100]), 8)
            .unwrap()
            .is_empty());
        assert!(pending_actors(&w, &BTreeSet::new(), 3).is_err());
        w.players.push(w.players[0].clone());
        assert!(pending_actors(&w, &BTreeSet::new(), 8).is_err());
    }

    #[test]
    fn template_is_explicit_and_rejects_behavior_fields() {
        let mut config: Value = serde_json::from_str(include_str!(
            "../../../../../configs/reasoning/codex-carlid-luna-streaming-proof.json"
        ))
        .unwrap();
        config["backend"]["auth"] = json!({"kind":"none"});
        config["backend"]["base_url"] = json!("http://127.0.0.1:1/v1");
        let template: NewcomerController =
            serde_json::from_value(json!({"role":"builtin","config":config})).unwrap();
        template.validate().unwrap();
        assert!(serde_json::from_value::<NewcomerController>(
            json!({"role":"builtin","config":config,"tree":{}})
        )
        .is_err());
        let invalid: NewcomerController =
            serde_json::from_value(json!({"role":"invented","config":config})).unwrap();
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn descriptor_replacement_is_complete_and_leaves_no_temporary_artifact() {
        let root = std::env::temp_dir().join(format!(
            "sao-enrollment-{}-{}",
            std::process::id(),
            rand::random::<u64>()
        ));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("participants.json");
        atomic_json(&path, &json!([{"actor":1}])).unwrap();
        atomic_json(&path, &json!([{"actor":1},{"actor":4}])).unwrap();
        let value: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        assert_eq!(value.as_array().unwrap().len(), 2);
        assert!(!root.join("participants.json.tmp").exists());
        std::fs::remove_dir_all(root).unwrap();
    }
}
