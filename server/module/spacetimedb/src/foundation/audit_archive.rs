//! Lossless owner-readable audit blocks. The recent indexed tail is independent
//! of participant memory; compaction never changes simulation events or cursors.
use super::{sim_audit, storage, SimAudit};
use sha2::{Digest, Sha256};
use spacetimedb::{ReducerContext, Table};

const BLOCK_EVENTS: u64 = 128;
const LIVE_EVENTS: u64 = 2048;
const MAX_BLOCK_BYTES: usize = 32 * 1024 * 1024;
const PAGE_EVENTS: u64 = 4096;

#[spacetimedb::table(accessor = sim_audit_wake, scheduled(sim_audit_maintenance))]
pub struct SimAuditWake {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[unique]
    pub run: String,
    pub scheduled_at: spacetimedb::ScheduleAt,
}

fn arm(ctx: &ReducerContext, state: &SimAuditRetention) {
    if !state.enabled || state.blocked.is_some()
        || state.next_event.saturating_sub(state.archived_through+1) < LIVE_EVENTS+BLOCK_EVENTS {
        return;
    }
    if ctx.db.sim_audit_wake().run().find(&state.run).is_none() {
        ctx.db.sim_audit_wake().insert(SimAuditWake {
            id:0,run:state.run.clone(),scheduled_at:(ctx.timestamp+std::time::Duration::from_millis(1)).into(),
        });
    }
}

#[spacetimedb::reducer]
pub fn sim_audit_maintenance(ctx: &ReducerContext, wake: SimAuditWake) -> Result<(),String> {
    if ctx.sender()!=ctx.identity() {return Err("scheduled audit maintenance only".into());}
    if !ctx.db.sim_audit_wake().run().find(&wake.run).is_some_and(|row|row.id==wake.id) {return Ok(());}
    ctx.db.sim_audit_wake().id().delete(wake.id);
    let Some(mut state)=ctx.db.sim_audit_retention().run().find(&wake.run) else {return Ok(());};
    // One existing 128-event block per transaction. Facts and recipient delivery
    // have already committed; archive creation and tail deletion remain atomic.
    compact(ctx,&mut state,1);
    arm(ctx,&state);
    ctx.db.sim_audit_retention().run().update(state);
    Ok(())
}

#[spacetimedb::table(accessor = sim_audit_block)]
pub struct SimAuditBlock {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub first: u64,
    pub last: u64,
    pub plain_bytes: u64,
    pub digest: String,
    pub zlib: Vec<u8>,
}
#[spacetimedb::table(accessor = sim_audit_retention)]
pub struct SimAuditRetention {
    #[primary_key]
    pub run: String,
    pub enabled: bool,
    pub archived_through: u64,
    pub next_event: u64,
    pub archived_plain_bytes: u64,
    pub archived_compressed_bytes: u64,
    pub blocked: Option<String>,
}
fn key(run: &str, first: u64) -> String {
    format!("{run}:{first}")
}
fn block_first(event: u64) -> u64 {
    (event - 1) / BLOCK_EVENTS * BLOCK_EVENTS + 1
}

#[derive(serde::Deserialize)]
struct Header {
    run: String,
    id: u64,
}
fn validate(run: &str, first: u64, bodies: &[String]) -> Result<(), String> {
    for (n, body) in bodies.iter().enumerate() {
        let h: Header = serde_json::from_str(body).map_err(|_| "invalid audit event")?;
        if h.run != run || h.id != first + n as u64 {
            return Err("audit identity or sequence mismatch".into());
        }
    }
    Ok(())
}
fn encode(run: &str, first: u64, rows: &[SimAudit]) -> Result<SimAuditBlock, String> {
    if first == 0 || block_first(first) != first || rows.len() != BLOCK_EVENTS as usize {
        return Err("invalid audit block boundary".into());
    }
    if rows.iter().map(|r| r.json.len()).sum::<usize>() > MAX_BLOCK_BYTES {
        return Err("audit block exceeds compression budget".into());
    }
    let mut bodies = Vec::with_capacity(rows.len());
    for (n, row) in rows.iter().enumerate() {
        if row.run != run || row.event_id != first + n as u64 || row.key != key(run, row.event_id) {
            return Err("audit row gap or scope mismatch".into());
        }
        bodies.push(row.json.clone());
    }
    validate(run, first, &bodies)?;
    struct BoundedBytes(Vec<u8>);
    impl std::io::Write for BoundedBytes {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            if self.0.len().saturating_add(buf.len()) > MAX_BLOCK_BYTES {
                return Err(std::io::Error::other("audit compression budget"));
            }
            self.0.extend_from_slice(buf);
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut encoded = BoundedBytes(Vec::new());
    serde_json::to_writer(&mut encoded, &bodies)
        .map_err(|_| "audit block exceeds compression budget")?;
    let bytes = encoded.0;
    Ok(SimAuditBlock {
        key: key(run, first),
        run: run.into(),
        first,
        last: first + BLOCK_EVENTS - 1,
        plain_bytes: bytes.len() as u64,
        digest: format!("{:x}", Sha256::digest(&bytes)),
        zlib: miniz_oxide::deflate::compress_to_vec_zlib(&bytes, 1),
    })
}
fn decode(run: &str, first: u64, block: SimAuditBlock) -> Result<Vec<String>, String> {
    if block.run != run
        || block.first != first
        || block.key != key(run, first)
        || block.last != first + BLOCK_EVENTS - 1
        || block.plain_bytes > MAX_BLOCK_BYTES as u64
    {
        return Err("invalid audit block metadata".into());
    }
    let bytes = miniz_oxide::inflate::decompress_to_vec_zlib_with_limit(
        &block.zlib,
        block.plain_bytes as usize,
    )
    .map_err(|_| "invalid compressed audit")?;
    if bytes.len() as u64 != block.plain_bytes
        || format!("{:x}", Sha256::digest(&bytes)) != block.digest
    {
        return Err("audit block integrity failure".into());
    }
    let bodies: Vec<String> =
        serde_json::from_slice(&bytes).map_err(|_| "invalid archived audit")?;
    if bodies.len() != BLOCK_EVENTS as usize {
        return Err("audit block count mismatch".into());
    }
    validate(run, first, &bodies)?;
    Ok(bodies)
}
fn compact(ctx: &ReducerContext, state: &mut SimAuditRetention, budget: u64) {
    if !state.enabled || state.blocked.is_some() {
        return;
    }
    for _ in 0..budget {
        let first = state.archived_through + 1;
        if state.next_event.saturating_sub(first) < LIVE_EVENTS + BLOCK_EVENTS {
            break;
        }
        let mut rows: Vec<_> = ctx
            .db
            .sim_audit()
            .run_and_event()
            .filter((state.run.as_str(), first..first + BLOCK_EVENTS))
            .collect();
        rows.sort_by_key(|r| r.event_id);
        let block = match super::measured("audit.compress", || encode(&state.run, first, &rows)) {
            Ok(block) => block,
            Err(error) => {
                state.blocked = Some(error);
                break;
            }
        };
        state.archived_plain_bytes += block.plain_bytes;
        state.archived_compressed_bytes += block.zlib.len() as u64;
        state.archived_through = block.last;
        // The archive and deletion commit atomically. A failed transaction
        // retains the original rows; a failed encoder does not delete anything.
        ctx.db.sim_audit_block().insert(block);
        for row in rows {
            ctx.db.sim_audit().key().delete(row.key);
        }
    }
}
pub(super) fn appended(ctx: &ReducerContext, run: &str, first: u64, count: u64) {
    if count == 0 {
        return;
    }
    let Some(mut state) = ctx.db.sim_audit_retention().run().find(run.to_owned()) else {
        return;
    };
    assert_eq!(state.next_event, first, "audit retention cursor continuity");
    state.next_event = first + count;
    // Physical transactions only retain original facts and advance this cursor.
    // Compression executes separately, with one pending callback per run.
    arm(ctx, &state);
    ctx.db.sim_audit_retention().run().update(state);
}
#[spacetimedb::reducer]
pub fn sim_configure_audit_archive(
    ctx: &ReducerContext,
    run: String,
    enabled: bool,
) -> Result<(), String> {
    let (_, world) = super::load(ctx, &run)?; // owner check precedes all audit reads
    let mut state = ctx
        .db
        .sim_audit_retention()
        .run()
        .find(&run)
        .unwrap_or(SimAuditRetention {
            run,
            enabled,
            archived_through: 0,
            next_event: world.next_event,
            archived_plain_bytes: 0,
            archived_compressed_bytes: 0,
            blocked: None,
        });
    state.enabled = enabled;
    state.blocked = None;
    if !enabled {
        if let Some(wake)=ctx.db.sim_audit_wake().run().find(&state.run) {ctx.db.sim_audit_wake().id().delete(wake.id);}
    }
    arm(ctx, &state);
    if ctx
        .db
        .sim_audit_retention()
        .run()
        .find(&state.run)
        .is_some()
    {
        ctx.db.sim_audit_retention().run().update(state);
    } else {
        ctx.db.sim_audit_retention().insert(state);
    }
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_compact_audit(ctx: &ReducerContext, run: String) -> Result<(), String> {
    storage::require_owner(ctx, &run)?;
    let mut state = ctx
        .db
        .sim_audit_retention()
        .run()
        .find(&run)
        .ok_or("audit retention not configured")?;
    compact(ctx, &mut state, 8);
    arm(ctx, &state);
    ctx.db.sim_audit_retention().run().update(state);
    Ok(())
}

#[spacetimedb::procedure]
pub fn sim_export_owned_audit(
    ctx: &mut spacetimedb::ProcedureContext,
    run: String,
    start: u64,
    end: u64,
    limit: u32,
) -> Result<Vec<String>, String> {
    if start == 0 || end < start || limit == 0 || limit as u64 > PAGE_EVENTS {
        return Err("invalid audit page range".into());
    }
    let until = end.min(start.saturating_add(limit as u64));
    let (blocks, mut live) = ctx.try_with_tx(|tx| {
        storage::require_owner(tx, &run)?;
        let archived = tx
            .db
            .sim_audit_retention()
            .run()
            .find(&run)
            .map_or(0, |s| s.archived_through);
        let mut blocks = vec![];
        if start < until && start <= archived {
            let mut first = block_first(start);
            while first < until && first <= archived {
                blocks.push(
                    tx.db
                        .sim_audit_block()
                        .key()
                        .find(key(&run, first))
                        .ok_or("audit block missing")?,
                );
                first += BLOCK_EVENTS;
            }
        }
        let live_start = start.max(archived + 1);
        let live = if live_start < until {
            tx.db
                .sim_audit()
                .run_and_event()
                .filter((run.as_str(), live_start..until))
                .collect::<Vec<_>>()
        } else {
            vec![]
        };
        Ok::<_, String>((blocks, live))
    })?;
    // Decompression uses the owned coherent page after leaving the transaction.
    // No database/network access is hidden in serialization or validation.
    let mut bodies = Vec::with_capacity((until - start) as usize);
    for block in blocks {
        let first = block.first;
        for (n, body) in decode(&run, first, block)?.into_iter().enumerate() {
            if (start..until).contains(&(first + n as u64)) {
                bodies.push(body);
            }
        }
    }
    live.sort_by_key(|row| row.event_id);
    for row in live {
        if row.run != run || row.key != key(&run, row.event_id) {
            return Err("invalid live audit row".into());
        }
        bodies.push(row.json);
    }
    if bodies.len() as u64 != until - start {
        return Err("audit page incomplete".into());
    }
    validate(&run, start, &bodies)?;
    Ok(bodies)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Vec<SimAudit> {
        (1..=BLOCK_EVENTS).map(|id| SimAudit { key:key("r",id), run:"r".into(),event_id:id,
            kind:"fixture".into(), actor:1,
            json:format!("{{ \"run\":\"r\", \"id\":{id}, \"data\":{{\"text\":\"λ \\\" \\\\ \\n\",\"number\":1.00}} }}") }).collect()
    }
    #[test]
    fn archival_recovers_exact_bytes_and_rejects_corruption_scope_and_gaps() {
        let rows = fixture();
        let expected = rows.iter().map(|r| r.json.clone()).collect::<Vec<_>>();
        assert_eq!(
            decode("r", 1, encode("r", 1, &rows).unwrap()).unwrap(),
            expected
        );
        assert!(decode("other", 1, encode("r", 1, &rows).unwrap()).is_err());
        let mut corrupted = encode("r", 1, &rows).unwrap();
        corrupted.zlib[2] ^= 1;
        assert!(decode("r", 1, corrupted).is_err());
        let mut wrong = fixture();
        wrong[17].event_id = 20;
        assert!(encode("r", 1, &wrong).is_err());
        let mut wrong = fixture();
        wrong[17].json = wrong[18].json.clone();
        assert!(encode("r", 1, &wrong).is_err());
        assert!(encode("r", 1, &rows[..127]).is_err());
        assert!(encode("r", 2, &rows).is_err());
    }
}
