//! Bounded actual-authority privacy/reconnect check, after the timed workload.
use super::*;
use shared::module_bindings::SimMyCombatEventsTableAccess;
use spacetimedb_sdk::SubscriptionHandle as _;

fn rows(person:&ParticipantService,run:&str,actor:u32)->Result<Vec<Value>,String> {
    let mut result=Vec::new();
    for row in person.connection.db.sim_my_combat_events().iter() {
        if row.run!=run || row.actor!=actor {return Err("combat view leaked another participant's row".into());}
        let data:Value=serde_json::from_str(&row.data).map_err(|e|e.to_string())?;
        if !simulation::combat::is_combat_event(&row.kind,&data) {return Err("non-combat fact in combat view".into());}
        result.push(json!({"cursor":row.cursor,"source":row.source,"tick":row.tick,"location":row.location,
            "kind":row.kind,"parents":row.parents,"data":data}));
    }
    result.sort_by_key(|row|row["cursor"].as_u64().unwrap());
    Ok(result)
}

pub async fn verify(c:&Value,people:&[ParticipantService],scenario:&simulation::Scenario)->Result<(),String> {
    let run=c["run"].as_str().unwrap();
    let mut captured=Vec::new();
    for (person,actor) in people.iter().zip(&scenario.players) {
        let handle=person.subscribe_combat_events().await?;
        let events=rows(person,run,actor.id)?;
        captured.push(json!({"actor":actor.id,"events":events}));
        handle.unsubscribe().map_err(|e|e.to_string())?;
    }
    if captured.iter().all(|row|row["events"].as_array().unwrap().is_empty()) {
        return Err("combat verification requires actual combat evidence".into());
    }
    // A separate real connection reuses only its privately stored identity.
    let actor=scenario.players[0].id;
    let path=PathBuf::from(c["credentials"].as_str().unwrap()).join(format!("actor-{actor}.json"));
    let reopened=ParticipantService::from_file(&path).await?;
    let handle=reopened.subscribe_combat_events().await?;
    let recovered=rows(&reopened,run,actor)?;
    if json!(recovered)!=captured[0]["events"] {return Err("combat reconnect changed retained evidence".into());}
    handle.unsubscribe().map_err(|e|e.to_string())?;
    let _=reopened.connection.disconnect();
    let path=PathBuf::from(c["credentials"].as_str().unwrap()).join("combat-outsider.json");
    let (outsider,identity)=new_session(c["server"].as_str().unwrap().into(),c["database"].as_str().unwrap().into(),&path).await?;
    let handle=outsider.subscribe_combat_events().await?;
    if outsider.connection.db.sim_my_combat_events().count()!=0 {return Err("ungranted combat view was not empty".into());}
    handle.unsubscribe().map_err(|e|e.to_string())?;
    call(c,"sim_grant_client",vec![json!(run),json!(identity),json!(true),json!(actor)]).await?;
    let handle=outsider.subscribe_combat_events().await?;
    if outsider.connection.db.sim_my_combat_events().count()!=0 {return Err("observer received participant combat channel".into());}
    handle.unsubscribe().map_err(|e|e.to_string())?;
    call(c,"sim_revoke_client",vec![json!(identity)]).await?;
    let handle=outsider.subscribe_combat_events().await?;
    if outsider.connection.db.sim_my_combat_events().count()!=0 {return Err("revoked combat view was not empty".into());}
    handle.unsubscribe().map_err(|e|e.to_string())?;
    let _=outsider.connection.disconnect();
    std::fs::write(PathBuf::from(c["output_dir"].as_str().unwrap()).join("combat-feed-verification.json"),
        serde_json::to_vec_pretty(&json!({"ok":true,"scope":"post-pause verification; excluded from timed workload",
            "reconnect_equal":true,"ungranted_empty":true,"observer_empty":true,"revoked_empty":true,"participants":captured})).unwrap()).map_err(|e|e.to_string())?;
    Ok(())
}
