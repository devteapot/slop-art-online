//! Observer presentation over canonical typed components. No observer view is
//! an authority or participant permission boundary: every view checks the grant.
//! The participant path retains its existing personally scoped projection.
use super::{client_access::*,native_storage::*};
use serde_json::json;
use spacetimedb::{SpacetimeType,ViewContext};

fn observer(ctx:&ViewContext)->Option<SimClientAccess> {
    ctx.db.sim_client_access().identity().find(ctx.sender()).filter(|a|a.observer)
}

#[spacetimedb::view(accessor = sim_my_render_header, public)]
pub fn sim_my_render_header(ctx:&ViewContext)->Option<SimClientSnapshot> {
    let access=ctx.db.sim_client_access().identity().find(ctx.sender())?;
    if !access.observer {return super::client_access::render_snapshot(ctx,false);}
    let Some(head)=render_timing(ctx,&access.run) else {return super::client_access::render_snapshot(ctx,false);};
    let inspected=ctx.db.sim_client_inspector().identity().find(ctx.sender())
        .filter(|row|row.run==access.run).and_then(|row|row.actor);
    // Open inspection reads the selected actor and its local public dependencies.
    // Do not construct/serialize a whole observer snapshot to extract one player.
    // Closed inspection reads no actor mind/controller/experience rows whatsoever.
    let selected=if let Some(actor)=inspected {
        let world=super::measured("view.inspector.load",||super::storage::inspector_for_view(ctx,&access.run,actor))?;
        super::measured("view.inspector.projection",||simulation::client_view::inspected_player(&world,actor))
    } else {None};
    let pending:Vec<simulation::Pending>=serde_json::from_str(&head.pending).ok()?;
    let mut body=json!({"incremental_observer":true,"run":access.run,"tick":head.tick,
        "time_ms":head.time_ms,"updates":head.updates,"projection_revision":head.next_event,
        "clock_unit_ms":simulation::timing::LEGACY_UNIT_MS,"stopped":head.stopped,"rules":head.version,
        "observer":true,"actor":null,"inspected_actor":inspected,"inspected_player":selected,
        "pending":pending.iter().map(|p|json!({"id":p.id,"actor":p.actor,"tick":p.tick})).collect::<Vec<_>>()});
    if let Some(clock)=ctx.db.sim_client_clock().run().find(&access.run) {
        body["paused"]=json!(clock.paused);body["evidence_mode"]=json!(clock.evidence_mode);
    }
    Some(SimClientSnapshot {run:access.run,tick:head.tick,body:body.to_string()})
}

#[spacetimedb::view(accessor = sim_my_render_actors, public)]
pub fn sim_my_render_actors(ctx:&ViewContext)->Vec<SimNativeActor> {
    let Some(access)=observer(ctx) else {return vec![];};
    ctx.db.sim_native_actor().run().filter(access.run.as_str()).collect()
}

#[derive(SpacetimeType)]
pub struct SimRenderBodySupport {
    pub run:String,
    pub actor:u32,
    pub arena:Option<String>,
    pub body:Option<String>,
}
#[spacetimedb::view(accessor = sim_my_render_bodies, public)]
pub fn sim_my_render_bodies(ctx:&ViewContext)->Vec<SimRenderBodySupport> {
    let Some(access)=observer(ctx) else {return vec![];};
    ctx.db.sim_render_actor_support().run().filter(access.run.as_str())
        .map(|row|SimRenderBodySupport {run:row.run,actor:row.actor,arena:row.arena,body:row.body}).collect()
}

#[spacetimedb::view(accessor = sim_my_render_sites, public)]
pub fn sim_my_render_sites(ctx:&ViewContext)->Vec<SimNativeSite> {
    let Some(access)=observer(ctx) else {return vec![];};
    ctx.db.sim_native_site().run().filter(access.run.as_str()).collect()
}

#[derive(SpacetimeType)]
pub struct SimRenderScene {
    pub run:String,
    pub body:String,
}
#[spacetimedb::view(accessor = sim_my_render_scene, public)]
pub fn sim_my_render_scene(ctx:&ViewContext)->Option<SimRenderScene> {
    let access=observer(ctx)?;
    let initial=render_initial(ctx,&access.run).ok()?;
    let mut archives:Vec<_>=ctx.db.sim_native_archive().run().filter(access.run.as_str()).collect();
    archives.sort_by_key(|row|row.ordinal);
    let archives=archives.into_iter().map(SimNativeArchive::archive).collect::<Result<Vec<_>,_>>().ok()?;
    let body=simulation::client_view::observer_scene(&initial,&archives);
    Some(SimRenderScene {run:access.run,body:body.to_string()})
}
