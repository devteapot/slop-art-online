use living_bindings::*;
use serde::Deserialize;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Table, TableWithPrimaryKey};
use std::io::{self, Read, Write};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[derive(Deserialize)]
struct Request {
    uri: String,
    db: String,
    token: Option<String>,
    queries: Vec<String>,
    seconds: u64,
    drop_file: Option<String>,
    credential_fd: Option<u32>,
    until_actor: Option<u32>,
    #[serde(default)]
    stream: bool,
}

#[derive(Default)]
struct Signals {
    identity: String,
    applied: bool,
    error: Option<String>,
    disconnected: Option<String>,
    body_updates: u64,
    stats_updates: u64,
    stream_live: bool,
}

macro_rules! primary_tables {
    ($action:ident, $($arg:expr),*) => {
        $action!($($arg),*; world, terrain_chunk, character, body, vitals, activity,
            inventory, resource_node, structure, brain, mind_state, persona, relation,
            belief, judgment, place, thought, chronicle, stats, bond_offer, expecting,
            mind_cursor, know_how, artifact, trade_offer, background, gate, experience,
            routine, routine_stat, script, community, membership, join_request, genome,
            practice);
    };
}

fn row_json(row: &impl spacetimedb_sats::ser::Serialize) -> Value {
    row.serialize(spacetimedb_sats::ser::serde::SerdeSerializer::new(
        serde_json::value::Serializer,
    ))
    .unwrap_or_else(|_| panic!("row JSON serialization failed"))
}

fn emit(value: &Value) {
    println!("{value}");
    io::stdout().flush().expect("probe stdout");
}

fn stream_change(signals: &Mutex<Signals>, value: Value) {
    if signals.lock().unwrap().stream_live {
        emit(&value);
    }
}

fn stream_callbacks(c: &DbConnection, signals: Arc<Mutex<Signals>>) {
    macro_rules! insert_delete {
        ($c:expr, $signals:expr; $($table:ident),*) => { $(
            let inserted = $signals.clone();
            $c.db.$table().on_insert(move |_, row| stream_change(&inserted,
                json!({"event":"insert","table":stringify!($table),"row":row_json(row)})));
            let deleted = $signals.clone();
            $c.db.$table().on_delete(move |_, row| stream_change(&deleted,
                json!({"event":"delete","table":stringify!($table),"row":row_json(row)})));
        )* };
    }
    macro_rules! updates {
        ($c:expr, $signals:expr; $($table:ident),*) => { $(
            let changed = $signals.clone();
            $c.db.$table().on_update(move |_, old, row| stream_change(&changed,
                json!({"event":"update","table":stringify!($table),
                    "old":row_json(old),"row":row_json(row)})));
        )* };
    }
    primary_tables!(insert_delete, c, signals);
    primary_tables!(updates, c, signals);
    insert_delete!(c, signals; my_deliberations);
}

fn stream_initial(c: &DbConnection, r: &Request, identity: &str) {
    let mut tables = serde_json::Map::new();
    macro_rules! rows {
        ($c:expr, $tables:expr; $($table:ident),*) => { $(
            let received: Vec<_> = $c.db.$table().iter().map(|row| row_json(&row)).collect();
            if !received.is_empty() {
                $tables.insert(stringify!($table).into(), json!(received));
            }
        )* };
    }
    primary_tables!(rows, c, tables);
    rows!(c, tables; my_deliberations);
    emit(&json!({"event":"initial","identity":identity,"db":r.db,
        "queries":r.queries,"seconds":r.seconds,"tables":tables}));
}

fn snapshot(c: &DbConnection) -> Value {
    let mut counts = serde_json::Map::new();
    macro_rules! count {
        ($($table:ident),*) => { $(counts.insert(stringify!($table).into(), json!(c.db.$table().count()));)* };
    }
    count!(
        world,
        terrain_chunk,
        character,
        body,
        vitals,
        activity,
        inventory,
        resource_node,
        structure,
        brain,
        mind_state,
        persona,
        relation,
        belief,
        judgment,
        place,
        thought,
        chronicle,
        stats,
        bond_offer,
        expecting,
        mind_cursor,
        know_how,
        artifact,
        trade_offer,
        background,
        gate,
        experience,
        routine,
        routine_stat,
        my_deliberations,
        script,
        community,
        membership,
        join_request,
        genome,
        practice
    );
    let characters: Vec<_> = c.db.character().iter().map(|r| json!({
        "id":r.id,"name":r.name,"kind":r.kind,"controller":r.controller.to_hex().to_string(),
        "ai":r.ai,"alive":r.alive,"stage":r.stage
    })).collect();
    let experiences: Vec<_> =
        c.db.experience()
            .iter()
            .map(|r| {
                json!({
                    "id":r.id,"observer":r.observer,"controller":r.controller.to_hex().to_string(),
                    "kind":r.kind,"text":r.text
                })
            })
            .collect();
    let thoughts: Vec<_> = c
        .db
        .thought()
        .iter()
        .map(|r| {
            json!({
                "id":r.id,"actor":r.actor,"detail":r.detail,"reference":r.reference,"model":r.model
            })
        })
        .collect();
    let deliberations: Vec<_> =
        c.db.my_deliberations()
            .iter()
            .map(|r| {
                json!({
                    "actor":r.actor,"controller":r.controller.to_hex().to_string(),
                    "reason":r.reason,"revision":r.revision,"updated_ms":r.updated_ms
                })
            })
            .collect();
    let routines: Vec<_> =
        c.db.routine()
            .iter()
            .map(|r| json!({"id":r.id,"actor":r.actor,"name":r.name}))
            .collect();
    let routine_stats: Vec<_> =
        c.db.routine_stat()
            .iter()
            .map(|r| json!({"id":r.id,"ok":r.ok,"failed":r.failed}))
            .collect();
    let brains: Vec<_> =
        c.db.brain()
            .iter()
            .map(|r| json!({"id":r.id,"plan":r.plan,"source":r.source,"revision":r.revision}))
            .collect();
    let bodies: Vec<_> =
        c.db.body()
            .iter()
            .map(|r| json!({"id":r.id,"x":r.x,"y":r.y,"vx":r.vx,"vy":r.vy,"t_ms":r.t_ms}))
            .collect();
    let chronicle: Vec<_> =
        c.db.chronicle()
            .iter()
            .map(|r| json!({"kind":r.kind,"a":r.a,"text":r.text}))
            .collect();
    let cursors: Vec<_> =
        c.db.mind_cursor()
            .iter()
            .map(|r| json!({"actor":r.actor,"upto":r.upto}))
            .collect();
    json!({"counts":counts,"ticks":c.db.stats().iter().next().map(|r|r.ticks),
        "characters":characters,"experiences":experiences,"thoughts":thoughts,
        "deliberations":deliberations,"routines":routines,"routine_stats":routine_stats,
        "brains":brains,"bodies":bodies,"chronicle":chronicle,"cursors":cursors})
}

fn connect(r: &Request, signals: Arc<Mutex<Signals>>) -> Result<DbConnection, String> {
    let ready = signals.clone();
    let gone = signals.clone();
    let failed = signals.clone();
    let queries = r.queries.clone();
    let credential_fd = r.credential_fd;
    let stream = r.stream;
    DbConnection::builder()
        .with_uri(&r.uri)
        .with_database_name(&r.db)
        .with_token(r.token.clone())
        .on_connect(move |c, identity, token| {
            if let Some(fd) = credential_fd {
                std::fs::write(format!("/proc/self/fd/{fd}"), token).expect("credential pipe");
            }
            ready.lock().unwrap().identity = identity.to_hex().to_string();
            if stream {
                stream_callbacks(c, ready.clone());
            }
            let updates = ready.clone();
            c.db.body()
                .on_update(move |_, _, _| updates.lock().unwrap().body_updates += 1);
            let updates = ready.clone();
            c.db.stats()
                .on_update(move |_, _, _| updates.lock().unwrap().stats_updates += 1);
            let applied = ready.clone();
            let error = ready.clone();
            c.subscription_builder()
                .on_applied(move |_| applied.lock().unwrap().applied = true)
                .on_error(move |_, e| error.lock().unwrap().error = Some(e.to_string()))
                .subscribe(queries);
        })
        .on_disconnect(move |_, e| {
            gone.lock().unwrap().disconnected = Some(
                e.map(|e| e.to_string())
                    .unwrap_or_else(|| "connection closed".into()),
            );
        })
        .on_connect_error(move |_, e| failed.lock().unwrap().error = Some(e.to_string()))
        .build()
        .map_err(|e| e.to_string())
}

fn drive(r: &Request, drop_connection: bool) -> Result<Value, String> {
    let signals = Arc::new(Mutex::new(Signals::default()));
    let c = connect(r, signals.clone())?;
    let start = Instant::now();
    loop {
        c.frame_tick().map_err(|e| e.to_string())?;
        let s = signals.lock().unwrap();
        if let Some(error) = &s.error {
            return Ok(
                json!({"status":"rejected","identity":s.identity,"error":error,"queries":r.queries}),
            );
        }
        if s.applied {
            break;
        }
        if start.elapsed() > Duration::from_secs(20) {
            return Err("subscription timed out".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let initial = if r.stream { Value::Null } else { snapshot(&c) };
    if r.stream {
        let mut s = signals.lock().unwrap();
        stream_initial(&c, r, &s.identity);
        s.stream_live = true;
    }
    let start = Instant::now();
    let mut requested_drop = false;
    loop {
        if let Err(e) = c.frame_tick() {
            signals
                .lock()
                .unwrap()
                .disconnected
                .get_or_insert(e.to_string());
        }
        let s = signals.lock().unwrap();
        if s.error.is_some() {
            return Err(format!("live subscription failed: {:?}", s.error));
        }
        if s.disconnected.is_some() {
            if r.stream {
                return Err(format!("connection lost: {:?}", s.disconnected));
            }
            break;
        }
        if r.until_actor
            .is_some_and(|actor| c.db.my_deliberations().iter().any(|d| d.actor == actor))
        {
            break;
        }
        if !drop_connection && start.elapsed() >= Duration::from_secs(r.seconds) {
            break;
        }
        drop(s);
        if drop_connection && !requested_drop && start.elapsed() >= Duration::from_secs(2) {
            std::fs::write(r.drop_file.as_ref().unwrap(), b"drop").map_err(|e| e.to_string())?;
            requested_drop = true;
        }
        if start.elapsed() > Duration::from_secs(15) && drop_connection {
            return Err("proxy did not drop connection".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let final_state = if r.stream { Value::Null } else { snapshot(&c) };
    let s = signals.lock().unwrap();
    let result = if r.stream {
        json!({"event":"complete","status":"applied","live_ms":start.elapsed().as_millis()})
    } else {
        json!({"status":"applied","identity":s.identity,"queries":r.queries,
        "initial":initial,"final":final_state,"body_updates":s.body_updates,
        "stats_updates":s.stats_updates,"disconnect":s.disconnected,
        "live_ms":start.elapsed().as_millis()})
    };
    drop(s);
    let _ = c.disconnect();
    Ok(result)
}

fn main() {
    let result = (|| -> Result<Value, String> {
        let mut input = String::new();
        io::stdin()
            .read_to_string(&mut input)
            .map_err(|e| e.to_string())?;
        let r: Request = serde_json::from_str(&input).map_err(|e| e.to_string())?;
        if !r.db.starts_with("verify-client-") {
            return Err("database must start with verify-client-".into());
        }
        let first = drive(&r, r.drop_file.is_some())?;
        if r.drop_file.is_some() {
            std::thread::sleep(Duration::from_secs(3));
            let second = drive(&r, false)?;
            Ok(json!({"rounds":[first,second],"retry_delay_ms":3000}))
        } else {
            Ok(first)
        }
    })();
    match result {
        Ok(value) => emit(&value),
        Err(error) => {
            println!("{}", json!({"status":"error","error":error}));
            std::process::exit(1);
        }
    }
}
