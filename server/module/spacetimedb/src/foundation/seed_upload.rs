//! Private, bounded seed transport. A World exists only after atomic finalization.
use sha2::{Digest, Sha256};
use spacetimedb::{Identity, ReducerContext, Table, ViewContext};

pub(super) const MAX_SEED_BYTES: usize = 8 * 1024 * 1024;
const MAX_CHUNK_BYTES: usize = 128 * 1024;
const MAX_CHUNKS: u32 = 128;

#[spacetimedb::table(accessor = sim_world_upload)]
pub struct SimWorldUpload {
    #[primary_key]
    pub run: String,
    #[unique]
    pub owner: Identity,
    pub mode: String,
    pub total_bytes: u32,
    pub sha256: String,
    pub received_bytes: u32,
    pub next_index: u32,
}

#[spacetimedb::table(accessor = sim_world_upload_chunk)]
pub struct SimWorldUploadChunk {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub index: u32,
    pub body: String,
}

fn constructor(mode: &str) -> Result<fn(String, simulation::Scenario) -> Result<simulation::World,String>,String> {
    match mode {
        "world"=>Ok(simulation::World::new),
        "participant"=>Ok(simulation::World::new_participant),
        "client"=>Ok(simulation::World::new_client),
        _=>Err("seed mode must be world, participant or client".into()),
    }
}

fn validate_manifest(mode: &str, total_bytes: u32, sha256: &str) -> Result<(),String> {
    constructor(mode)?;
    if total_bytes == 0 || total_bytes as usize > MAX_SEED_BYTES {
        return Err("seed upload requires 1..8388608 UTF-8 bytes".into());
    }
    if sha256.len()!=64 || !sha256.bytes().all(|b|b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("seed digest must be lowercase SHA-256 hex".into());
    }
    Ok(())
}

pub(super) fn reserved(ctx: &ReducerContext, run: &str) -> bool {
    ctx.db.sim_world_upload().run().find(run.to_owned()).is_some()
}

pub(super) fn owned(ctx: &ReducerContext, run: &str) -> Result<SimWorldUpload,String> {
    ctx.db.sim_world_upload().run().find(run.to_owned())
        .filter(|row|row.owner==ctx.sender()).ok_or("seed upload unavailable".into())
}

/// At most one incomplete upload per authenticated identity. Identical retries
/// preserve its progress; a different manifest requires explicit cancellation.
#[spacetimedb::reducer]
pub fn sim_begin_world_upload(ctx: &ReducerContext, run: String, mode: String,
    total_bytes: u32, sha256: String) -> Result<(),String> {
    super::validate_run_id(&run)?;
    validate_manifest(&mode,total_bytes,&sha256)?;
    if super::storage::exists(ctx,&run) {return Err("run already exists; never overwrite".into());}
    if reserved(ctx,&run) {
        let row=owned(ctx,&run)?;
        if row.mode==mode && row.total_bytes==total_bytes && row.sha256==sha256 {return Ok(());}
        return Err("seed manifest differs from the pending upload".into());
    }
    if ctx.db.sim_world_upload().owner().find(ctx.sender()).is_some() {
        return Err("cancel or finish the existing seed upload first".into());
    }
    ctx.db.sim_world_upload().insert(SimWorldUpload{run,owner:ctx.sender(),mode,total_bytes,sha256,
        received_bytes:0,next_index:0});
    Ok(())
}

fn validate_chunk(row: &SimWorldUpload, index: u32, body: &str) -> Result<(),String> {
    if index!=row.next_index || index>=MAX_CHUNKS {
        return Err("seed chunk index must be the next index below 128".into());
    }
    if body.is_empty() || body.len()>MAX_CHUNK_BYTES {
        return Err("seed chunk requires 1..131072 UTF-8 bytes".into());
    }
    if body.len()>row.total_bytes.saturating_sub(row.received_bytes) as usize {
        return Err("seed chunk exceeds declared byte count".into());
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn sim_append_world_upload(ctx: &ReducerContext, run: String, index: u32, body: String) -> Result<(),String> {
    let mut row=owned(ctx,&run)?;
    let key=format!("{run}:{index}");
    if index<row.next_index {
        let previous=ctx.db.sim_world_upload_chunk().key().find(&key).ok_or("stored seed chunk missing")?;
        if previous.run==run && previous.index==index && previous.body==body {return Ok(());}
        return Err("seed chunk retry differs from stored bytes".into());
    }
    validate_chunk(&row,index,&body)?;
    row.received_bytes+=body.len() as u32;
    row.next_index+=1;
    ctx.db.sim_world_upload_chunk().insert(SimWorldUploadChunk{key,run,index,body});
    ctx.db.sim_world_upload().run().update(row);
    Ok(())
}

#[spacetimedb::view(accessor = sim_my_world_upload, public)]
pub fn sim_my_world_upload(ctx: &ViewContext) -> Option<SimWorldUpload> {
    ctx.db.sim_world_upload().owner().find(ctx.sender())
}

pub(super) fn remove(ctx: &ReducerContext, row: &SimWorldUpload) {
    // The validated ordinal range is bounded by MAX_CHUNKS. Point operations
    // cannot remove another upload's chunks or scan unrelated pending seeds.
    for index in 0..row.next_index {
        ctx.db.sim_world_upload_chunk().key().delete(format!("{}:{index}",row.run));
    }
    ctx.db.sim_world_upload().run().delete(&row.run);
}

#[spacetimedb::reducer]
pub fn sim_cancel_world_upload(ctx: &ReducerContext, run: String) -> Result<(),String> {
    let row=owned(ctx,&run)?;
    if super::world_build::cancel(ctx, &run)? { remove(ctx,&row); }
    Ok(())
}

#[spacetimedb::reducer]
pub fn sim_finish_world_upload(ctx: &ReducerContext, run: String) -> Result<(),String> {
    let row=owned(ctx,&run)?;
    if super::world_build::finish(ctx, &row)? { return Ok(()); }
    let scenario = verified_seed(ctx, &row)?;
    super::create_world(ctx,run,scenario,constructor(&row.mode)?,MAX_SEED_BYTES,true)?;
    remove(ctx,&row);
    Ok(())
}

pub(super) fn verified_seed(ctx: &ReducerContext, row: &SimWorldUpload) -> Result<String,String> {
    if row.received_bytes!=row.total_bytes {return Err("seed upload is incomplete".into());}
    let run=&row.run;
    let mut scenario=String::with_capacity(row.total_bytes as usize);
    for index in 0..row.next_index {
        let chunk=ctx.db.sim_world_upload_chunk().key().find(format!("{run}:{index}")).ok_or("stored seed chunk missing")?;
        if chunk.run!=*run || chunk.index!=index {return Err("stored seed chunk scope mismatch".into());}
        scenario.push_str(&chunk.body);
    }
    if scenario.len()!=row.total_bytes as usize || format!("{:x}",Sha256::digest(scenario.as_bytes()))!=row.sha256 {
        return Err("seed upload digest or length mismatch".into());
    }
    Ok(scenario)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn upload_manifest_and_chunk_limits_count_bytes_and_bound_rows() {
        let digest="0".repeat(64);
        for mode in ["world","participant","client"] {assert!(validate_manifest(mode,MAX_SEED_BYTES as u32,&digest).is_ok());}
        for (mode,size,sha) in [("unknown",1,digest.as_str()),("client",0,digest.as_str()),
            ("client",MAX_SEED_BYTES as u32+1,digest.as_str()),("client",1,"not-a-digest")] {
            assert!(validate_manifest(mode,size,sha).is_err());
        }
        let mut row=SimWorldUpload{run:"sim-test".into(),owner:Identity::ZERO,mode:"client".into(),
            total_bytes:4,sha256:digest,received_bytes:0,next_index:0};
        assert!(validate_chunk(&row,0,"éé").is_ok());
        assert!(validate_chunk(&row,0,"ééé").is_err());
        assert!(validate_chunk(&row,0,"").is_err());
        assert!(validate_chunk(&row,1,"a").is_err());
        row.total_bytes=MAX_SEED_BYTES as u32;
        assert!(validate_chunk(&row,0,&"a".repeat(MAX_CHUNK_BYTES+1)).is_err());
        row.next_index=MAX_CHUNKS;
        assert!(validate_chunk(&row,MAX_CHUNKS,"a").is_err());
    }
}
