//! Exact projection equivalence on real subscriptions, outside the timed window.
use super::*;
use shared::module_bindings::{
    sim_select_inspector, SimMyRenderActorsTableAccess, SimMyRenderBodiesTableAccess,
    SimMyRenderHeaderTableAccess, SimMyRenderSceneTableAccess, SimMyRenderSitesTableAccess,
    SimMyRenderSnapshotTableAccess,
};
use spacetimedb_sdk::SubscriptionHandle as _;

async fn subscribe(
    person: &ParticipantService,
) -> Result<shared::module_bindings::SubscriptionHandle, String> {
    let (send, receive) = tokio::sync::oneshot::channel();
    let mut queries = shared::render_projection::SUBSCRIPTIONS.to_vec();
    queries.push("SELECT * FROM sim_my_render_snapshot");
    let handle = person
        .connection
        .subscription_builder()
        .on_applied(move |_| {
            let _ = send.send(());
        })
        .subscribe(queries);
    tokio::time::timeout(Duration::from_secs(10), receive)
        .await
        .map_err(|_| "render subscription timeout")?
        .map_err(|_| "render subscription disconnected")?;
    Ok(handle)
}
fn empty(person: &ParticipantService) -> bool {
    let db = &person.connection.db;
    db.sim_my_render_actors().count() == 0
        && db.sim_my_render_bodies().count() == 0
        && db.sim_my_render_sites().count() == 0
        && db.sim_my_render_scene().count() == 0
}
fn equal(person: &ParticipantService, c: &Value, label: &str) -> Result<(), String> {
    let mut actual = shared::render_projection::from_tables(&person.connection.db)?
        .ok_or("component snapshot missing")?;
    let mut cache = shared::render_projection::Cache::default();
    let mut cached = Value::Null;
    cache.refresh(
        &person.connection.db,
        &mut cached,
        shared::render_projection::ALL,
    )?;
    if cached != actual {
        return Err(format!("initial render cache mismatch: {label}"));
    }
    cache.refresh(&person.connection.db, &mut cached, 0)?;
    if cached != actual {
        return Err(format!("retained render cache mismatch: {label}"));
    }
    actual.as_object_mut().unwrap().remove("events");
    let legacy = person
        .connection
        .db
        .sim_my_render_snapshot()
        .iter()
        .next()
        .ok_or("comparison snapshot missing")?;
    let expected: Value = serde_json::from_str(&legacy.body).map_err(|e| e.to_string())?;
    if actual != expected {
        std::fs::write(
            PathBuf::from(c["output_dir"].as_str().unwrap())
                .join(format!("render-mismatch-{label}.json")),
            serde_json::to_vec_pretty(&json!({"expected":expected,"actual":actual})).unwrap(),
        )
        .map_err(|e| e.to_string())?;
        return Err(format!("render component mismatch: {label}"));
    }
    Ok(())
}
pub async fn verify(
    c: &Value,
    people: &[ParticipantService],
    scenario: &simulation::Scenario,
) -> Result<(), String> {
    let actor = scenario.players[0].id;
    let handle = subscribe(&people[0]).await?;
    if !empty(&people[0]) {
        return Err("participant received observer components".into());
    }
    equal(&people[0], c, "participant")?;
    handle.unsubscribe().map_err(|e| e.to_string())?;
    let path = PathBuf::from(c["credentials"].as_str().unwrap()).join("render-observer.json");
    let (observer, identity) = new_session(
        c["server"].as_str().unwrap().into(),
        c["database"].as_str().unwrap().into(),
        &path,
    )
    .await?;
    let handle = subscribe(&observer).await?;
    if !empty(&observer) || observer.connection.db.sim_my_render_header().count() != 0 {
        return Err("ungranted render was not empty".into());
    }
    handle.unsubscribe().map_err(|e| e.to_string())?;
    call(
        c,
        "sim_grant_client",
        vec![c["run"].clone(), json!(identity), json!(true), json!(actor)],
    )
    .await?;
    let handle = subscribe(&observer).await?;
    equal(&observer, c, "observer-closed")?;
    let mut cache = shared::render_projection::Cache::default();
    let mut cached = Value::Null;
    cache.refresh(
        &observer.connection.db,
        &mut cached,
        shared::render_projection::ALL,
    )?;
    let (send, receive) = tokio::sync::oneshot::channel();
    observer
        .connection
        .reducers
        .sim_select_inspector_then(Some(actor), move |_, result| {
            let _ = send.send(result);
        })
        .map_err(|e| e.to_string())?;
    tokio::time::timeout(Duration::from_secs(10), receive)
        .await
        .map_err(|_| "inspector timeout")?
        .map_err(|_| "inspector disconnected")?
        .map_err(|e| format!("inspector transport: {e:?}"))??;
    equal(&observer, c, "observer-open")?;
    cache.refresh(&observer.connection.db, &mut cached, 0)?;
    if Some(cached) != shared::render_projection::from_tables(&observer.connection.db)? {
        return Err("inspector cache transition mismatch".into());
    }
    handle.unsubscribe().map_err(|e| e.to_string())?;
    let _ = observer.connection.disconnect();
    let reopened = ParticipantService::from_file(&path).await?;
    let handle = subscribe(&reopened).await?;
    equal(&reopened, c, "reconnect")?;
    call(c, "sim_revoke_client", vec![json!(identity)]).await?;
    tokio::time::timeout(Duration::from_secs(10), async {
        while !empty(&reopened) || reopened.connection.db.sim_my_render_header().count() != 0 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .map_err(|_| "revoked render retained data")?;
    handle.unsubscribe().map_err(|e| e.to_string())?;
    let _ = reopened.connection.disconnect();
    std::fs::write(PathBuf::from(c["output_dir"].as_str().unwrap()).join("render-parts-verification.json"),
        serde_json::to_vec_pretty(&json!({"ok":true,"scope":"post-pause actual subscriptions; compatibility view deliberately active here",
            "cache_initial_and_unchanged_equal":true,"cache_inspector_transition_equal":true,"participant_equal":true,"observer_closed_equal":true,"observer_open_equal":true,"reconnect_equal":true,
            "ungranted_empty":true,"participant_cannot_read_observer_rows":true,"revoked_empty":true})).unwrap()).map_err(|e|e.to_string())?;
    Ok(())
}
