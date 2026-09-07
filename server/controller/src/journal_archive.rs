//! Lossless private journal retention. Runtime interpretation never reads this
//! archive; explicit journal inspection reconstructs the original ordered rows.
use super::*;

const BLOCK: u64 = 128;
const TAIL: u64 = 256;
const MAX_BYTES: usize = 32 * 1024 * 1024;

#[spacetimedb::table(accessor = brain_journal_block,
    index(accessor = personal, btree(columns = [owner, first])))]
pub struct BrainJournalBlock {
    #[primary_key]
    pub key: String,
    pub owner: Identity,
    pub first: u64,
    pub last: u64,
    pub plain_bytes: u64,
    pub digest: String,
    pub zlib: Vec<u8>,
}
#[spacetimedb::table(accessor = brain_journal_retention)]
pub struct BrainJournalRetention {
    #[primary_key]
    pub owner: Identity,
    pub archived_through: u64,
    pub next_sequence: u64,
    pub plain_bytes: u64,
    pub compressed_bytes: u64,
    pub blocked: Option<String>,
}
fn pack(owner: Identity, first: u64, rows: &[BrainJournal]) -> Result<BrainJournalBlock, String> {
    if first == 0 || (first - 1) % BLOCK != 0 || rows.len() != BLOCK as usize {
        return Err("invalid journal block boundary".into());
    }
    if rows.iter().map(|r| r.kind.len() + r.data.len()).sum::<usize>() > MAX_BYTES / 2 {
        return Err("journal block exceeds compression budget".into());
    }
    let mut records = Vec::with_capacity(rows.len());
    for (i, row) in rows.iter().enumerate() {
        if row.owner != owner || row.sequence != first + i as u64 || row.key != key(owner, row.sequence) {
            return Err("journal row gap or scope mismatch".into());
        }
        records.push((row.sequence, &row.kind, &row.data));
    }
    let bytes = serde_json::to_vec(&records).map_err(|e| e.to_string())?;
    if bytes.len() > MAX_BYTES { return Err("journal block exceeds compression budget".into()); }
    Ok(BrainJournalBlock { key:key(owner,first), owner, first, last:first+BLOCK-1,
        plain_bytes:bytes.len() as u64, digest:format!("{:x}",Sha256::digest(&bytes)),
        zlib:miniz_oxide::deflate::compress_to_vec_zlib(&bytes,1) })
}
fn unpack(owner: Identity, block: BrainJournalBlock) -> Result<Vec<BrainJournal>, String> {
    if block.owner != owner || block.first == 0 || (block.first-1)%BLOCK != 0
        || block.key != key(owner,block.first) || block.last != block.first+BLOCK-1
        || block.plain_bytes > MAX_BYTES as u64 {
        return Err("invalid journal archive metadata".into());
    }
    let bytes = miniz_oxide::inflate::decompress_to_vec_zlib_with_limit(&block.zlib,block.plain_bytes as usize)
        .map_err(|_| "invalid compressed journal")?;
    if bytes.len() as u64 != block.plain_bytes || format!("{:x}",Sha256::digest(&bytes)) != block.digest {
        return Err("journal archive integrity failure".into());
    }
    let records: Vec<(u64,String,String)> = decode(std::str::from_utf8(&bytes).map_err(|_| "invalid journal encoding")?)?;
    if records.len() != BLOCK as usize { return Err("journal archive count mismatch".into()); }
    records.into_iter().enumerate().map(|(i,(sequence,kind,data))| {
        if sequence != block.first+i as u64 { return Err("journal archive sequence mismatch".into()); }
        Ok(BrainJournal {key:key(owner,sequence),owner,sequence,kind,data})
    }).collect()
}
fn compact(ctx: &ReducerContext, state: &mut BrainJournalRetention, budget: u64) {
    if state.blocked.is_some() { return; }
    for _ in 0..budget {
        let first = state.archived_through+1;
        if state.next_sequence.saturating_sub(first) < TAIL+BLOCK { break; }
        let mut rows: Vec<_> = ctx.db.brain_journal().personal().filter((state.owner,first..first+BLOCK)).collect();
        rows.sort_by_key(|r| r.sequence);
        let block = match pack(state.owner,first,&rows) {
            Ok(block) => block,
            Err(error) => { state.blocked=Some(error); break; }
        };
        state.archived_through=block.last;
        state.plain_bytes+=block.plain_bytes;
        state.compressed_bytes+=block.zlib.len() as u64;
        // Archive insertion and removal of original rows are one transaction.
        ctx.db.brain_journal_block().insert(block);
        for row in rows { ctx.db.brain_journal().key().delete(row.key); }
    }
}
pub(super) fn appended(ctx: &ReducerContext, owner: Identity, first: u64, count: u64) {
    if count == 0 { return; }
    let mut state = ctx.db.brain_journal_retention().owner().find(owner).unwrap_or(BrainJournalRetention {
        owner,archived_through:0,next_sequence:first,plain_bytes:0,compressed_bytes:0,blocked:None,
    });
    assert_eq!(state.next_sequence,first,"journal append continuity");
    state.next_sequence=first+count;
    compact(ctx,&mut state,count.div_ceil(BLOCK)+1);
    if ctx.db.brain_journal_retention().owner().find(owner).is_some() { ctx.db.brain_journal_retention().owner().update(state); }
    else { ctx.db.brain_journal_retention().insert(state); }
}
pub(super) fn journal(ctx: &ViewContext) -> Vec<BrainJournal> {
    let owner=ctx.sender();
    let mut result=Vec::new();
    let mut blocks:Vec<_>=ctx.db.brain_journal_block().personal().filter((owner,)).collect();
    blocks.sort_by_key(|b| b.first);
    let mut next=1;
    for block in blocks {
        assert_eq!(block.first,next,"journal archive continuity");
        next=block.last+1;
        result.extend(unpack(owner,block).expect("valid private journal archive"));
    }
    let mut tail:Vec<_>=ctx.db.brain_journal().personal().filter((owner,)).collect();
    tail.sort_by_key(|r|r.sequence);
    for row in tail { assert_eq!(row.sequence,next,"journal tail continuity"); next+=1; result.push(row); }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    fn rows(owner: Identity) -> Vec<BrainJournal> {
        (1..=BLOCK).map(|sequence| BrainJournal {key:key(owner,sequence),owner,sequence,
            kind:"model_result".into(),data:format!(" {{\"text\":\"line\\n{} 🐈\"}} ",sequence)}).collect()
    }
    #[test]
    fn archive_restores_exact_ordered_rows_and_rejects_damage_or_wrong_owner() {
        let owner=Identity::from_byte_array([1;32]);
        let input=rows(owner);
        let output=unpack(owner,pack(owner,1,&input).unwrap()).unwrap();
        for (a,b) in input.iter().zip(output) {
            assert_eq!((&a.key,a.owner,a.sequence,&a.kind,&a.data),(&b.key,b.owner,b.sequence,&b.kind,&b.data));
        }
        assert!(unpack(Identity::from_byte_array([2;32]),pack(owner,1,&input).unwrap()).is_err());
        let mut bad=pack(owner,1,&input).unwrap(); bad.digest.push('0');
        assert!(unpack(owner,bad).is_err());
        let mut bad=pack(owner,1,&input).unwrap(); bad.plain_bytes=1;
        assert!(unpack(owner,bad).is_err());
        let mut input=rows(owner); input[1].sequence=99;
        assert!(pack(owner,1,&input).is_err());
    }
}
