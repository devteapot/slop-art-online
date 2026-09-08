//! Actor-scoped pages and immutable evidence bodies. Refcounts have a separate
//! table so retaining a shared body does not invalidate its other readers.
use super::*;
mod append;

pub(super) const MARKER: &str = "sao-native-trace-pages-v4";
const PAGE_CURSORS: u64 = 32;

#[derive(Clone, PartialEq, spacetimedb::SpacetimeType)]
pub struct SimNativePagedTraceEntry {
    pub metadata: SimNativeTraceEntry,
    pub body: u64,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_trace_head)]
pub struct SimNativeTraceHead {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub pages: Vec<u64>,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_trace_page,
    index(accessor = participant, btree(columns = [run, actor])))]
pub struct SimNativeTracePage {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub first: u64,
    pub entries: Vec<SimNativePagedTraceEntry>,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_evidence_body)]
pub struct SimNativeEvidenceBody {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[unique]
    pub digest: String,
    #[index(btree)]
    pub run: String,
    pub data: String,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_evidence_retention)]
pub struct SimNativeEvidenceRetention {
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub run: String,
    pub references: u64,
}

fn page_key(run: &str, actor: u32, first: u64) -> String { key(run,format!("{actor}:{first}")) }
fn digest(run: &str, body: &str) -> String {
    super::super::storage_codec::blob_key(run,None,"personal-evidence-v4",body)
}
pub(super) fn body_data(run: &str, id: u64, row: SimNativeEvidenceBody) -> Result<String,String> {
    if id == 0 || row.id != id || row.run != run || row.digest != digest(run,&row.data) {
        return Err("native evidence body identity mismatch".into());
    }
    serde_json::from_str::<&serde_json::value::RawValue>(&row.data).map_err(|e|e.to_string())?;
    Ok(row.data)
}

type BodyReader = dyn Fn(&str,u64) -> Result<String,String> + Send + Sync;
/// One reader/transaction owns these handles. Actor-scoped pages must be
/// validated before calling this; sharing a body never grants a trace entry.
pub(super) struct Payloads {
    read: Arc<BodyReader>,
    values: std::sync::Mutex<PayloadValues>,
}
#[derive(Default)]
struct PayloadValues {
    runs: BTreeMap<String,BTreeMap<u64,simulation::participant::ExperienceData>>,
    #[cfg(feature="clock-profile")]
    references: usize,
}
impl Payloads {
    pub(super) fn new(read: impl Fn(&str,u64) -> Result<String,String> + Send + Sync + 'static) -> Self {
        Self {read:Arc::new(read),values:std::sync::Mutex::new(PayloadValues::default())}
    }
    pub(super) fn experiences(&self,run:&str,entries:Vec<SimNativePagedTraceEntry>) -> Vec<Experience> {
        let mut values=self.values.lock().expect("trace payload handles");
        #[cfg(feature="clock-profile")]
        {values.references+=entries.len();}
        if !values.runs.contains_key(run) {values.runs.insert(run.into(),BTreeMap::new());}
        let bodies=values.runs.get_mut(run).unwrap();
        entries.into_iter().map(|entry| {
            let data=bodies.entry(entry.body).or_insert_with(|| {
                // Capture only the body reader, never this cache or ColdReader:
                // the resulting ownership graph must end with the transaction.
                let (read,run,id)=(self.read.clone(),run.to_owned(),entry.body);
                simulation::participant::ExperienceData::load_with(move || {
                    serde_json::value::RawValue::from_string(read(&run,id)?).map_err(|e|e.to_string())
                })
            }).clone();
            let m=entry.metadata;
            ExperienceRecord {cursor:m.cursor,source:m.source,tick:m.tick,location:m.location,
                kind:m.kind,parents:m.parents,data}.into()
        }).collect()
    }
}
#[cfg(feature="clock-profile")]
impl Drop for Payloads {
    fn drop(&mut self) {
        let values=self.values.get_mut().expect("trace payload handles");
        if values.references>0 {
            let distinct:usize=values.runs.values().map(BTreeMap::len).sum();
            log::info!("trace-body-handles {}",json(&[values.references,distinct]));
        }
    }
}

/// Cursor buckets keep ordinary append/prune changes at the two ends. A custom
/// retained order starts a new page at every bucket transition; it is never
/// sorted or approximated as a contiguous interval.
#[cfg(test)]
fn pack(run: &str, actor: u32, entries: Vec<SimNativePagedTraceEntry>) -> (SimNativeTraceHead,Vec<SimNativeTracePage>) {
    let mut pages: Vec<SimNativeTracePage> = vec![];
    for entry in entries {
        if pages.last().is_none_or(|p| p.first / PAGE_CURSORS != entry.metadata.cursor / PAGE_CURSORS) {
            let first=entry.metadata.cursor;
            pages.push(SimNativeTracePage {key:page_key(run,actor,first),run:run.into(),actor,first,entries:vec![]});
        }
        pages.last_mut().unwrap().entries.push(entry);
    }
    (SimNativeTraceHead {key:key(run,actor),run:run.into(),actor,pages:pages.iter().map(|p|p.first).collect()},pages)
}
/// Validate the same format for owned reads and borrowed save comparisons.
/// Borrowing does not clone every page's historical strings and parent vectors.
fn walk_pages<P: std::borrow::Borrow<SimNativeTracePage>>(run: &str, actor: u32,
    head: &SimNativeTraceHead, pages: impl IntoIterator<Item=P>, mut visit: impl FnMut(P)) -> Result<(),String> {
    if head.key != key(run,actor) || head.run != run || head.actor != actor {
        return Err("native trace head scope mismatch".into());
    }
    let mut stored=BTreeMap::new();
    for page in pages {
        if stored.insert(page.borrow().first,page).is_some() {return Err("native trace page count mismatch".into());}
    }
    if head.pages.len()!=stored.len() {return Err("native trace page count mismatch".into());}
    let mut cursors=BTreeSet::new();
    for &first in &head.pages {
        let value=stored.remove(&first).ok_or("native trace page missing or repeated")?;
        let page=value.borrow();
        if page.run!=run || page.actor!=actor || page.key!=page_key(run,actor,first)
            || page.entries.first().is_none_or(|e|e.metadata.cursor!=first)
            || page.entries.len()>PAGE_CURSORS as usize {
            return Err("native trace page scope or shape mismatch".into());
        }
        for entry in &page.entries {
            if entry.metadata.cursor/PAGE_CURSORS!=first/PAGE_CURSORS || entry.body==0
                || !cursors.insert(entry.metadata.cursor) {
                return Err("native trace page cursor or body mismatch".into());
            }
        }
        visit(value);
    }
    Ok(())
}
pub(super) fn unpack(run: &str, actor: u32, head: SimNativeTraceHead,
    pages: Vec<SimNativeTracePage>) -> Result<Vec<SimNativePagedTraceEntry>,String> {
    let mut entries=vec![];
    walk_pages(run,actor,&head,pages,|page|entries.extend(page.entries))?;
    Ok(entries)
}

struct ResolvedEntry<'a> { experience: &'a Experience, body: u64 }
impl ResolvedEntry<'_> {
    fn matches(&self, stored: &SimNativePagedTraceEntry) -> bool {
        let SimNativeTraceEntry { cursor,source,tick,location,kind,parents }=&stored.metadata;
        self.body==stored.body && self.experience.cursor==*cursor && self.experience.source==*source
            && self.experience.tick==*tick && self.experience.location==*location
            && self.experience.kind==*kind && self.experience.parents==*parents
    }
    fn materialize(&self) -> SimNativePagedTraceEntry {
        let e=self.experience;
        SimNativePagedTraceEntry {metadata:SimNativeTraceEntry {cursor:e.cursor,source:e.source,tick:e.tick,
            location:e.location,kind:e.kind.clone(),parents:e.parents.clone()},body:self.body}
    }
}
struct PagePlan {
    head: SimNativeTraceHead,
    // Whether the primary key already exists, then its changed/new value.
    writes: Vec<(bool,SimNativeTracePage)>,
    removed: Vec<String>,
    reused: usize,
}
/// Old pages have passed walk_pages. Current entries are still borrowed from
/// the kernel; materialize metadata only for pages that will actually be written.
fn plan_pages(run:&str,actor:u32,current:&[ResolvedEntry<'_>],old:&[SimNativeTracePage]) -> Result<PagePlan,String> {
    let mut cursors=BTreeSet::new();
    for entry in current {
        if entry.body==0 || !cursors.insert(entry.experience.cursor) {return Err("invalid current trace cursor or body".into());}
    }
    let mut old:BTreeMap<_,_>=old.iter().map(|page|(page.first,page)).collect();
    let mut plan=PagePlan {head:SimNativeTraceHead {key:key(run,actor),run:run.into(),actor,pages:vec![]},
        writes:vec![],removed:vec![],reused:0};
    let mut start=0;
    while start<current.len() {
        let first=current[start].experience.cursor;
        let mut end=start+1;
        while end<current.len() && current[end].experience.cursor/PAGE_CURSORS==first/PAGE_CURSORS {end+=1;}
        let entries=&current[start..end];
        let previous=old.remove(&first);
        plan.head.pages.push(first);
        if previous.is_some_and(|page|page.entries.len()==entries.len()
            && entries.iter().zip(&page.entries).all(|(new,old)|new.matches(old))) {
            plan.reused+=1;
        } else {
            plan.writes.push((previous.is_some(),SimNativeTracePage {key:page_key(run,actor,first),run:run.into(),actor,first,
                entries:entries.iter().map(ResolvedEntry::materialize).collect()}));
        }
        start=end;
    }
    plan.removed=old.into_values().map(|page|page.key.clone()).collect();
    Ok(plan)
}
fn reference_change(changes:&mut BTreeMap<u64,i64>,old:Option<u64>,new:Option<u64>) {
    if old==new {return;}
    if let Some(id)=old {*changes.entry(id).or_default()-=1;}
    if let Some(id)=new {*changes.entry(id).or_default()+=1;}
}
macro_rules! read_entries {
    ($db:expr,$run:expr,$actor:expr) => {{
        let (run,actor)=($run,$actor);
        let head=$db.sim_native_trace_head().key().find(key(run,actor)).ok_or("native trace head missing")?;
        unpack(run,actor,head,$db.sim_native_trace_page().participant().filter((run,actor)).collect())
    }};
}
pub(super) fn reducer_entries(ctx: &ReducerContext,run:&str,actor:u32) -> Result<Vec<SimNativePagedTraceEntry>,String> {
    read_entries!(ctx.db,run,actor)
}
fn unread_head(mut head:SimNativeTraceHead,after:u64) -> SimNativeTraceHead {
    head.pages.retain(|first| (first/PAGE_CURSORS*PAGE_CURSORS).saturating_add(PAGE_CURSORS-1)>after);
    head
}
pub(super) fn view_entries(ctx: &ViewContext,run:&str,actor:u32,after:u64) -> Result<Vec<SimNativePagedTraceEntry>,String> {
    if after==0 {return read_entries!(ctx.db,run,actor);}
    let head=ctx.db.sim_native_trace_head().key().find(key(run,actor)).ok_or("native trace head missing")?;
    // Every entry in a validated page belongs to its declared cursor bucket.
    // Skip fully acknowledged buckets without reading their bodies or metadata.
    let head=unread_head(head,after);
    let pages=head.pages.iter().map(|first|ctx.db.sim_native_trace_page().key()
        .find(page_key(run,actor,*first)).ok_or("native trace page missing"))
        .collect::<Result<Vec<_>,_>>()?;
    unpack(run,actor,head,pages)
}
pub(super) fn to_row(run:&str,actor:u32,entry:SimNativePagedTraceEntry,data:String) -> SimNativeExperience {
    let m=entry.metadata;
    SimNativeExperience {key:key(run,format!("{actor}:{}",m.cursor)),run:run.into(),actor,
        cursor:m.cursor,source:m.source,tick:m.tick,location:m.location,kind:m.kind,parents:m.parents,data}
}

#[derive(Default)]
pub(super) struct Writes {
    // This cache is owned by one save transaction. Exact bytes are the key;
    // repeated witness payloads need one digest/lookup, without pointer tokens.
    bodies: BTreeMap<String,u64>,
    new: BTreeSet<u64>,
    changes: BTreeMap<u64,i64>,
    run: Option<String>,
}
impl Writes {
    fn body(&mut self,ctx:&ReducerContext,run:&str,data:String) -> u64 {
        assert_eq!(self.run.get_or_insert_with(||run.to_owned()),run,"one run per trace save");
        if let Some(id)=self.bodies.get(&data) {return *id;}
        let hash=digest(run,&data);
        let id=if let Some(row)=ctx.db.sim_native_evidence_body().digest().find(hash.clone()) {
            assert_eq!(row.run,run,"evidence body run");
            assert_eq!(row.data,data,"evidence body digest collision");
            row.id
        } else {
            let id=ctx.db.sim_native_evidence_body().insert(SimNativeEvidenceBody {
                id:0,digest:hash,run:run.into(),data:data.clone(),
            }).id;
            self.new.insert(id);id
        };
        self.bodies.insert(data,id);id
    }
    /// Called only when evidence changed. Old pages provide storage identities;
    /// the retained kernel snapshot proves which payloads remain unchanged.
    pub(super) fn save(&mut self,ctx:&ReducerContext,run:&str,actor:u32,state:&ParticipantState,
        previous:Option<&ParticipantState>,old:Option<&SimNativeParticipant>,sampled:bool) {
        let mut profile=super::super::evidence_profile::SaveScope::new(sampled,"participant.save.diff");
        assert_eq!(self.run.get_or_insert_with(||run.to_owned()),run,"one run per trace save");
        let paged=old.is_some_and(|r|r.experiences==MARKER);
        if paged && self.append_delta(ctx, run, actor, state, previous, sampled, &mut profile) { return; }
        let old_pages:Vec<_>=if paged {ctx.db.sim_native_trace_page().participant().filter((run,actor)).collect()} else {vec![]};
        let mut old_entries=BTreeMap::new();
        if paged {
            walk_pages(run,actor,&ctx.db.sim_native_trace_head().key().find(key(run,actor))
                .expect("native trace head exists"),&old_pages,|page| {
                    for entry in &page.entries {old_entries.insert(entry.metadata.cursor,entry);}
                }).expect("validated trace pages");
        }
        let previous:BTreeMap<_,_>=previous.into_iter().flat_map(|p|p.experiences.iter()).map(|e|(e.cursor,e)).collect();
        let mut current=Vec::with_capacity(state.experiences.len());
        profile.phase(sampled,"participant.save.rows");
        for e in state.experiences.iter() {
            let prior=old_entries.remove(&e.cursor);
            let retained=prior.filter(|_|previous.get(&e.cursor).is_some_and(|p|e.can_reuse_encoding(p)));
            let body=retained.map_or_else(||self.body(ctx,run,json(&e.data)),|entry|entry.body);
            current.push(ResolvedEntry {experience:e,body});
            reference_change(&mut self.changes,prior.map(|entry|entry.body),Some(body));
        }
        for e in old_entries.into_values() {reference_change(&mut self.changes,Some(e.body),None);}
        profile.phase(sampled,"participant.save.index");
        let plan=plan_pages(run,actor,&current,&old_pages).expect("valid current trace pages");
        #[cfg(feature="clock-profile")]
        if sampled {log::info!("trace-page-plan {}",json(&[actor as usize,current.len(),plan.reused,
            plan.writes.len(),plan.removed.len(),plan.writes.iter().map(|(_,page)|page.entries.len()).sum()]));}
        for (exists,page) in plan.writes {
            if exists {ctx.db.sim_native_trace_page().key().update(page);}
            else {ctx.db.sim_native_trace_page().insert(page);}
        }
        for key in plan.removed {ctx.db.sim_native_trace_page().key().delete(key);}
        upsert!(ctx,sim_native_trace_head,key,plan.head);
        if !paged {
            // Existing inline/v1/v2/v3 actors upgrade atomically on trace change.
            let keys:Vec<_>=ctx.db.sim_native_experience().controller_scope().filter((run,actor)).map(|r|r.key).collect();
            for key in keys {ctx.db.sim_native_experience().key().delete(key);}
            ctx.db.sim_native_trace_index().key().delete(key(run,actor));
        }
    }
    pub(super) fn finish(self,ctx:&ReducerContext,run:&str) {
        let _profile=super::super::evidence_profile::SaveScope::new(true,"native.evidence.retention");
        if let Some(scope)=self.run {assert_eq!(scope,run,"trace save scope");}
        for (id,delta) in self.changes {
            if delta==0 {continue;}
            let old=ctx.db.sim_native_evidence_retention().id().find(id);
            let references=balance(run,id,old.as_ref(),self.new.contains(&id),delta).expect("evidence reference balance");
            if references==0 {
                ctx.db.sim_native_evidence_retention().id().delete(id);
                ctx.db.sim_native_evidence_body().id().delete(id);
            } else {
                let row=SimNativeEvidenceRetention {id,run:run.into(),references};
                if old.is_some() {ctx.db.sim_native_evidence_retention().id().update(row);}
                else {ctx.db.sim_native_evidence_retention().insert(row);}
            }
        }
    }
}

fn balance(run:&str,id:u64,old:Option<&SimNativeEvidenceRetention>,new:bool,delta:i64) -> Result<u64,String> {
    let previous=match old {
        Some(row) if row.id==id && row.run==run && row.references>0 && !new=>row.references,
        None if new=>0,
        _=>return Err("native evidence retention identity mismatch".into()),
    };
    previous.checked_add_signed(delta).ok_or("native evidence retention underflow or overflow".into())
}

#[cfg(test)]
pub(super) fn fixture(w:&World) -> (Vec<SimNativeTraceHead>,Vec<SimNativeTracePage>,Vec<SimNativeEvidenceBody>) {
    let mut by_data=BTreeMap::new();let mut bodies=vec![];let mut heads=vec![];let mut pages=vec![];
    for (&actor,state) in &w.participants {
        let entries=state.experiences.iter().map(|e| {
            let data=json(&e.data);
            let id=*by_data.entry(data.clone()).or_insert_with(|| {
                let id=bodies.len() as u64+1;
                bodies.push(SimNativeEvidenceBody{id,digest:digest(&w.run,&data),run:w.run.clone(),data});id
            });
            SimNativePagedTraceEntry {metadata:SimNativeTraceEntry {cursor:e.cursor,source:e.source,tick:e.tick,
                location:e.location,kind:e.kind.clone(),parents:e.parents.clone()},body:id}
        }).collect();
        let (head,mut actor_pages)=pack(&w.run,actor,entries);heads.push(head);pages.append(&mut actor_pages);
    }
    (heads,pages,bodies)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn entry(cursor:u64) -> SimNativePagedTraceEntry {
        SimNativePagedTraceEntry {metadata:SimNativeTraceEntry {cursor,source:cursor+700,tick:2,location:9,
            kind:"perception".into(),parents:vec![1]},body:3}
    }
    #[test]
    fn payload_handles_share_only_scoped_identities_and_keep_records_independent() {
        use std::sync::atomic::{AtomicUsize,Ordering};
        let reads=Arc::new(AtomicUsize::new(0));let seen=reads.clone();
        let cache=Payloads::new(move |run,id| {
            seen.fetch_add(1,Ordering::SeqCst);
            if run!="run" {return Err("foreign body".into());}
            Ok(format!("{{\"body\":{id}}}"))
        });
        let first=cache.experiences("run",vec![entry(1),entry(2)]);
        let mut other=cache.experiences("run",vec![entry(99)]);
        assert_eq!(reads.load(Ordering::SeqCst),0,"metadata assembly never fetches payloads");
        assert!(first[0].data.same_snapshot(&first[1].data));
        assert!(first[0].data.same_snapshot(&other[0].data));
        assert_eq!(json(&first[0].data),"{\"body\":3}");
        assert_eq!(json(&other[0].data),"{\"body\":3}");
        assert_eq!(reads.load(Ordering::SeqCst),1);
        other[0].kind="changed".into();
        other[0].data=serde_json::json!({"edited":true}).into();
        assert_eq!(first[0].kind,"perception");assert_eq!(first[0].cursor,1);
        assert_eq!(first[1].cursor,2);assert_eq!(other[0].cursor,99);
        assert_eq!(json(&first[0].data),"{\"body\":3}");
        let foreign=cache.experiences("foreign",vec![entry(1)]);
        assert!(!foreign[0].data.same_snapshot(&first[0].data));
        assert!(serde_json::to_string(&foreign[0].data).is_err());
        let again=cache.experiences("foreign",vec![entry(12)]);
        assert!(serde_json::to_string(&again[0].data).is_err());
        assert_eq!(reads.load(Ordering::SeqCst),2,"failures are shared only within their scope");
        let mut different=entry(1);different.body=4;
        let different=cache.experiences("run",vec![different]);
        assert!(!different[0].data.same_snapshot(&first[0].data));
        assert_eq!(json(&different[0].data),"{\"body\":4}");
        assert_eq!(reads.load(Ordering::SeqCst),3);
    }
    #[test]
    fn payload_handles_release_the_reader_without_an_ownership_cycle() {
        let owner=Arc::new(());let weak=Arc::downgrade(&owner);
        let cache=Payloads::new(move |_,_| {let _=&owner;Ok("null".into())});
        let records=cache.experiences("run",vec![entry(1)]);
        drop(cache);
        assert!(weak.upgrade().is_some(),"unresolved records retain their reader");
        assert_eq!(json(&records[0].data),"null");
        drop(records);
        assert!(weak.upgrade().is_none(),"no cache-to-payload-to-cache cycle survives the transaction");
    }
    fn experiences(entries:&[SimNativePagedTraceEntry]) -> Vec<Experience> {
        entries.iter().map(|e| {
            let m=&e.metadata;
            ExperienceRecord {cursor:m.cursor,source:m.source,tick:m.tick,location:m.location,kind:m.kind.clone(),parents:m.parents.clone(),
                data:simulation::participant::ExperienceData::load_with(|| Err("page planning must not load a payload".into()))}.into()
        }).collect()
    }
    fn compare_plan(old:&[SimNativePagedTraceEntry],new:&[SimNativePagedTraceEntry]) -> PagePlan {
        let (old_head,old_pages)=pack("run",4,old.to_vec());
        walk_pages("run",4,&old_head,&old_pages,|_|{}).unwrap();
        let records=experiences(new);
        let resolved:Vec<_>=records.iter().zip(new).map(|(experience,e)|ResolvedEntry{experience,body:e.body}).collect();
        let plan=plan_pages("run",4,&resolved,&old_pages).unwrap();
        let (expected_head,expected_pages)=pack("run",4,new.to_vec());
        let mut rows:BTreeMap<_,_>=old_pages.into_iter().map(|p|(p.key.clone(),p)).collect();
        for key in &plan.removed {assert!(rows.remove(key).is_some());}
        for (exists,page) in &plan.writes {
            assert_eq!(*exists,rows.contains_key(&page.key));
            assert!(rows.get(&page.key)!=Some(page),"never write an unchanged page");
            rows.insert(page.key.clone(),page.clone());
        }
        assert!(plan.head==expected_head);
        assert_eq!(plan.reused+plan.writes.len(),expected_pages.len());
        assert!(rows==expected_pages.into_iter().map(|p|(p.key.clone(),p)).collect());
        assert!(unpack("run",4,plan.head.clone(),rows.into_values().collect()).unwrap()==new);
        plan
    }
    #[test]
    fn selective_plans_match_full_materialization_for_edits_order_gaps_and_empty_traces() {
        let old:Vec<_>=(1..=256).map(entry).collect();
        let unchanged=compare_plan(&old,&old);
        assert_eq!(unchanged.reused,9);assert!(unchanged.writes.is_empty());
        let mut next=old[1..].to_vec();next.push(entry(257));
        let edge=compare_plan(&old,&next);
        assert_eq!(edge.reused,7);assert_eq!(edge.writes.len(),2);assert_eq!(edge.removed.len(),1);
        assert_eq!(edge.writes.iter().map(|(_,p)|p.entries.len()).sum::<usize>(),32,"materialize changed edges, not all 256 entries");
        for field in ["source","tick","location","kind","parents","body"] {
            let mut changed=old.clone();
            let e=&mut changed[145];
            match field {
                "source"=>e.metadata.source=2,"tick"=>e.metadata.tick=10,"location"=>e.metadata.location=-3,
                "kind"=>e.metadata.kind="death".into(),"parents"=>e.metadata.parents=vec![7,7,2],"body"=>e.body=9,_=>unreachable!(),
            }
            assert_eq!(compare_plan(&old,&changed).writes.len(),1,"{field}");
        }
        let mut moved=old.clone();moved.rotate_left(31);
        let reordered=compare_plan(&old,&moved);
        assert_eq!(reordered.reused,9);assert!(reordered.writes.is_empty(),"whole-page reordering changes only the head");
        for seed in 0..32usize {
            let mut changed=old.clone();
            changed.swap(seed,255-seed);changed.remove(80+seed);changed.rotate_left(seed*3);
            changed.push(entry(1000+seed as u64*37));
            changed[120].body=11;
            compare_plan(&old,&changed);
        }
        assert_eq!(compare_plan(&old,&[]).removed.len(),9);
        assert_eq!(compare_plan(&[],&old).writes.len(),9);
        assert!(compare_plan(&[],&[]).writes.is_empty());
    }
    #[test]
    fn selective_plans_reject_duplicate_cursors_and_zero_body_ids() {
        for mut entries in [vec![entry(1),entry(1)],vec![entry(1),entry(2)]] {
            if entries[0].metadata.cursor!=entries[1].metadata.cursor {entries[1].body=0;}
            let records=experiences(&entries);
            let resolved:Vec<_>=records.iter().zip(&entries).map(|(experience,e)|ResolvedEntry{experience,body:e.body}).collect();
            assert!(plan_pages("run",4,&resolved,&[]).is_err());
        }
    }
    #[test]
    fn reference_deltas_match_full_multisets_without_touching_unchanged_entries() {
        let old:Vec<_>=(1..=256u64).map(|cursor|(cursor,cursor%7+1)).collect();
        let mut stable=BTreeMap::new();
        for &(_,body) in &old {reference_change(&mut stable,Some(body),Some(body));}
        assert!(stable.is_empty());
        for seed in 0..32u64 {
            let mut new=old.clone();new.rotate_left(seed as usize);new.retain(|(cursor,_)|cursor%11!=seed%11);
            new.push((300+seed,17));new[19].1=19;
            let mut remaining:BTreeMap<_,_>=old.iter().copied().collect();
            let mut actual=BTreeMap::new();
            for &(cursor,body) in &new {reference_change(&mut actual,remaining.remove(&cursor),Some(body));}
            for body in remaining.into_values() {reference_change(&mut actual,Some(body),None);}
            let mut expected=BTreeMap::new();
            for &(_,body) in &old {*expected.entry(body).or_insert(0i64)-=1;}
            for &(_,body) in &new {*expected.entry(body).or_insert(0i64)+=1;}
            actual.retain(|_,count|*count!=0);expected.retain(|_,count|*count!=0);
            assert_eq!(actual,expected);
        }
        reference_change(&mut stable,Some(1),Some(2));
        reference_change(&mut stable,Some(2),Some(1));
        assert!(stable.values().all(|count|*count==0),"transfers across participants cancel atomically");
    }
    #[test]
    fn append_prune_rewrites_only_edge_pages_and_preserves_arbitrary_order() {
        let values:Vec<_>=(1..=256).map(entry).collect();
        let (head,pages)=pack("run",4,values.clone());
        assert!(unpack("run",4,head,pages.clone()).unwrap()==values);
        let mut next=values.clone();next.remove(0);next.push(entry(257));
        let (head,changed)=pack("run",4,next.clone());
        assert_eq!(pages.len(),9);
        assert_eq!(changed.iter().filter(|page|pages.contains(page)).count(),7);
        assert!(unpack("run",4,head,changed).unwrap()==next);
        next.swap(3,173);next.swap(5,250);next.remove(80);
        let (head,pages)=pack("run",4,next.clone());
        assert!(unpack("run",4,head,pages).unwrap()==next);
    }
    #[test]
    fn pages_reject_missing_foreign_duplicate_and_invalid_entries() {
        for fault in ["head run","head key","head actor","missing page","extra page","page key","page run","page actor","duplicate cursor","zero body","bucket","empty"] {
            let (mut head,mut pages)=pack("run",4,(1..=90).map(entry).collect());
            match fault {
                "head run"=>head.run="foreign".into(),"head key"=>head.key="foreign".into(),"head actor"=>head.actor=5,
                "missing page"=>{pages.pop();},"extra page"=>pages.push(pages[0].clone()),
                "page key"=>pages[0].key="foreign".into(),"page run"=>pages[0].run="foreign".into(),"page actor"=>pages[0].actor=5,
                "duplicate cursor"=>pages[0].entries[1].metadata.cursor=1,"zero body"=>pages[0].entries[0].body=0,
                "bucket"=>pages[0].entries[1].metadata.cursor=1000,"empty"=>pages[0].entries.clear(),_=>unreachable!(),
            }
            assert!(walk_pages("run",4,&head,&pages,|_|{}).is_err(),"borrowed {fault}");
            assert!(unpack("run",4,head,pages).is_err(),"{fault}");
        }
    }
    #[test]
    fn acknowledged_page_selection_preserves_exact_unread_order_and_gaps() {
        let mut entries:Vec<_>=(1..=257).map(entry).collect();
        entries.swap(0,190);entries.swap(64,255);entries.remove(125);
        let (head,pages)=pack("run",4,entries.clone());
        for after in [0,1,31,32,64,200,255,256,257,u64::MAX] {
            let selected=unread_head(head.clone(),after);
            let loaded=pages.iter().filter(|p|selected.pages.contains(&p.first)).cloned().collect();
            let actual:Vec<_>=unpack("run",4,selected,loaded).unwrap().into_iter().filter(|e|e.metadata.cursor>after).collect();
            let expected:Vec<_>=entries.iter().filter(|e|e.metadata.cursor>after).cloned().collect();
            assert!(actual==expected,"cursor {after}");
        }
    }
    #[test]
    fn bodies_and_reference_balances_reject_corruption_and_preserve_last_owner() {
        let data="{\"kind\":\"death\"}".to_owned();
        let row=SimNativeEvidenceBody {id:5,digest:digest("run",&data),run:"run".into(),data:data.clone()};
        assert_eq!(body_data("run",5,row.clone()).unwrap(),data);
        for fault in ["id","run","digest","data","malformed"] {
            let mut changed=row.clone();
            match fault {"id"=>changed.id=6,"run"=>changed.run="other".into(),"digest"=>changed.digest="bad".into(),
                "data"=>changed.data.push(' '),"malformed"=>{changed.data="{".into();changed.digest=digest("run","{");},_=>unreachable!()}
            assert!(body_data("run",5,changed).is_err(),"{fault}");
        }
        let mut refs=SimNativeEvidenceRetention {id:5,run:"run".into(),references:200};
        assert_eq!(balance("run",5,Some(&refs),false,-199).unwrap(),1);
        assert_eq!(balance("run",5,Some(&refs),false,-200).unwrap(),0);
        assert!(balance("run",5,Some(&refs),false,-201).is_err());
        assert!(balance("foreign",5,Some(&refs),false,-1).is_err());
        assert!(balance("run",6,Some(&refs),false,-1).is_err());
        assert!(balance("run",5,None,false,1).is_err());
        assert_eq!(balance("run",5,None,true,200).unwrap(),200);
        refs.references=u64::MAX;assert!(balance("run",5,Some(&refs),false,1).is_err());
    }
}
