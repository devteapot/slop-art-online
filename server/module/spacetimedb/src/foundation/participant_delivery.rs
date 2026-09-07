//! Native incremental participant delivery. Fast-changing headers, command
//! receipts and immutable read responses have independent subscription rows.
//! No subscribed function loads World or expands the normalized storage graph.
use super::client_access::{sim_client_access__view, SimClientSnapshot};
use simulation::{
    participant::{ParticipantState, Receipt},
    Player, World,
};
use spacetimedb::{ReducerContext, Table, ViewContext};
use std::collections::{BTreeMap, BTreeSet};

#[spacetimedb::table(accessor = sim_participant_head)]
pub struct SimParticipantHead {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub tick: u64,
    pub stopped: bool,
    pub latest_cursor: u64,
    pub oldest_cursor: u64,
    pub control_epoch: u64,
    pub policy_revision: u64,
    pub learning_revision: u64,
    pub health: i32,
}

#[spacetimedb::table(accessor = sim_participant_receipt,
    index(accessor = participant, btree(columns = [run, actor])))]
pub struct SimParticipantReceipt {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub request_id: String,
    pub fingerprint: String,
    pub ok: bool,
    pub error: Option<String>,
    pub event: u64,
}

#[spacetimedb::table(accessor = sim_participant_read,
    index(accessor = participant, btree(columns = [run, actor])))]
pub struct SimParticipantRead {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub lease_id: u64,
    pub request_id: String,
    pub control_epoch: u64,
    pub sequence: u64,
    pub expires_ms: u64,
    pub observation: String,
}

fn head(
    run: &str,
    tick: u64,
    stopped: bool,
    player: &Player,
    state: &ParticipantState,
) -> SimParticipantHead {
    let actor = player.id;
    SimParticipantHead {
        key: format!("{run}:{actor}"),
        run: run.into(),
        actor,
        tick,
        stopped,
        latest_cursor: state.cursor,
        oldest_cursor: state.experiences.first().map_or(1, |e| e.cursor),
        control_epoch: state.control_epoch,
        policy_revision: player.generation,
        learning_revision: state.learning_revision,
        health: player.health,
    }
}

fn same_head(a: &SimParticipantHead, b: &SimParticipantHead) -> bool {
    a.run == b.run
        && a.actor == b.actor
        && a.tick == b.tick
        && a.stopped == b.stopped
        && a.latest_cursor == b.latest_cursor
        && a.oldest_cursor == b.oldest_cursor
        && a.control_epoch == b.control_epoch
        && a.policy_revision == b.policy_revision
        && a.learning_revision == b.learning_revision
        && a.health == b.health
}

pub(super) fn publish(
    ctx: &ReducerContext,
    world: &World,
    lease_ids: &BTreeMap<u32, Vec<u64>>,
    previous: &BTreeMap<u32, ParticipantState>,
    previous_time_ms: u64,
) {
    if !world.participant_mode {
        return;
    }
    for player in &world.players {
        let actor = player.id;
        let Some(state) = world.participants.get(&actor) else {
            continue;
        };
        publish_actor(
            ctx,
            &world.run,
            world.tick,
            world.timing.time_ms,
            world.stopped,
            player,
            state,
            lease_ids.get(&actor).expect("participant lease references"),
            previous.get(&actor),
            previous_time_ms,
        );
    }
}

pub(super) fn clear_actor(ctx: &ReducerContext, run: &str, actor: u32) {
    ctx.db
        .sim_participant_head()
        .key()
        .delete(format!("{run}:{actor}"));
    for row in ctx
        .db
        .sim_participant_receipt()
        .participant()
        .filter((run, actor))
    {
        ctx.db.sim_participant_receipt().key().delete(row.key);
    }
    for row in ctx
        .db
        .sim_participant_read()
        .participant()
        .filter((run, actor))
    {
        ctx.db.sim_participant_read().key().delete(row.key);
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn publish_actor(
    ctx: &ReducerContext,
    run: &str,
    tick: u64,
    time_ms: u64,
    stopped: bool,
    player: &Player,
    state: &ParticipantState,
    ids: &[u64],
    previous: Option<&ParticipantState>,
    previous_time_ms: u64,
) {
    let actor = player.id;
    let row = head(run, tick, stopped, player, state);
    let old = ctx.db.sim_participant_head().key().find(&row.key);
    let existing = old.is_some();
    match old {
        Some(old) if same_head(&old, &row) => (),
        Some(_) => {
            ctx.db.sim_participant_head().key().update(row);
        }
        None => {
            ctx.db.sim_participant_head().insert(row);
        }
    }
    let expired = state
        .evidence_leases
        .iter()
        .any(|l| l.expires_ms >= previous_time_ms && l.expires_ms < time_ms);
    if existing && !expired && previous.is_some_and(|old| state.same_snapshot(old)) {
        return;
    }
    let receipt_ids: BTreeSet<_> = state
        .receipts
        .iter()
        .map(|r| r.request_id.as_str())
        .collect();
    for old in ctx
        .db
        .sim_participant_receipt()
        .participant()
        .filter((run, actor))
    {
        if !receipt_ids.contains(old.request_id.as_str()) {
            ctx.db.sim_participant_receipt().key().delete(old.key);
        }
    }
    for receipt in &state.receipts {
        let key = format!("{}:{actor}:{}", run, receipt.request_id);
        let old = ctx.db.sim_participant_receipt().key().find(&key);
        if old.as_ref().is_none_or(|r| r.event != receipt.event) {
            let row = SimParticipantReceipt {
                key,
                run: run.into(),
                actor,
                request_id: receipt.request_id.clone(),
                fingerprint: receipt.fingerprint.clone(),
                ok: receipt.ok,
                error: receipt.error.clone(),
                event: receipt.event,
            };
            if old.is_some() {
                ctx.db.sim_participant_receipt().key().update(row);
            } else {
                ctx.db.sim_participant_receipt().insert(row);
            }
        }
    }
    assert_eq!(ids.len(), state.evidence_leases.len());
    let leases: Vec<_> = state
        .evidence_leases
        .iter()
        .zip(ids)
        .filter(|(l, _)| l.expires_ms >= time_ms && l.observation.is_capture())
        .collect();
    let read_ids: BTreeSet<_> = leases.iter().map(|(_, id)| **id).collect();
    let mut sequence = 0;
    for old in ctx
        .db
        .sim_participant_read()
        .participant()
        .filter((run, actor))
    {
        sequence = sequence.max(old.sequence);
        if old.control_epoch != state.control_epoch || !read_ids.contains(&old.lease_id) {
            ctx.db.sim_participant_read().key().delete(old.key);
        }
    }
    for (lease, &lease_id) in leases {
        let key = format!("{}:{actor}:{lease_id}", run);
        if ctx.db.sim_participant_read().key().find(&key).is_none() {
            sequence += 1;
            ctx.db.sim_participant_read().insert(SimParticipantRead {
                key,
                run: run.into(),
                actor,
                lease_id,
                request_id: lease.request_id.clone(),
                control_epoch: state.control_epoch,
                sequence,
                expires_ms: lease.expires_ms,
                observation: lease.response_json().expect("valid captured read"),
            });
        }
    }
}

#[spacetimedb::view(accessor = sim_my_participant_head, public)]
pub fn sim_my_participant_head(ctx: &ViewContext) -> Option<SimParticipantHead> {
    let access = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    if access.observer {
        return None;
    }
    ctx.db
        .sim_participant_head()
        .key()
        .find(format!("{}:{}", access.run, access.actor))
}

#[spacetimedb::view(accessor = sim_my_participant_receipts, public)]
pub fn sim_my_participant_receipts(ctx: &ViewContext) -> Vec<SimParticipantReceipt> {
    let Some(access) = ctx.db.sim_client_access().identity().find(ctx.sender()) else {
        return vec![];
    };
    if access.observer {
        return vec![];
    }
    ctx.db
        .sim_participant_receipt()
        .participant()
        .filter((access.run.as_str(), access.actor))
        .collect()
}

#[spacetimedb::view(accessor = sim_my_participant_reads, public)]
pub fn sim_my_participant_reads(ctx: &ViewContext) -> Vec<SimParticipantRead> {
    let Some(access) = ctx.db.sim_client_access().identity().find(ctx.sender()) else {
        return vec![];
    };
    if access.observer {
        return vec![];
    }
    ctx.db
        .sim_participant_read()
        .participant()
        .filter((access.run.as_str(), access.actor))
        .collect()
}

/// Compatibility for old clients. New clients subscribe to the three native
/// views above, so a header change cannot retransmit every retained response.
pub(super) fn legacy_status(ctx: &ViewContext) -> Option<SimClientSnapshot> {
    let h = sim_my_participant_head(ctx)?;
    let mut receipts = sim_my_participant_receipts(ctx);
    receipts.sort_by_key(|r| r.event);
    let receipts: Vec<_> = receipts
        .into_iter()
        .map(|r| Receipt {
            request_id: r.request_id,
            fingerprint: r.fingerprint,
            ok: r.ok,
            error: r.error,
            event: r.event,
        })
        .collect();
    let mut reads = sim_my_participant_reads(ctx);
    reads.sort_by_key(|r| r.sequence);
    let reads: Vec<_> = reads.into_iter().map(|r| serde_json::json!({
        "request_id":r.request_id,
        "observation":serde_json::from_str::<serde_json::Value>(&r.observation).expect("valid captured read")
    })).collect();
    let body = serde_json::json!({
        "api_version":simulation::participant::API_VERSION,
        "projection":"status; use read_observation for fresh subjective state",
        "run":h.run,"actor":h.actor,"tick":h.tick,"stopped":h.stopped,
        "latest_cursor":h.latest_cursor,"oldest_cursor":h.oldest_cursor,
        "control_epoch":h.control_epoch,"policy_revision":h.policy_revision,
        "learning_revision":h.learning_revision,"context":{"player":{"health":h.health}},
        "receipts":receipts,"read_observations":reads,
        "capabilities":["read_observation","replace_tree","patch_subtree","speak","reflect","pin_observation"]
    }).to_string();
    Some(SimClientSnapshot {
        run: h.run,
        tick: h.tick,
        body,
    })
}
