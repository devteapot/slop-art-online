//! Local CPU diagnostic; never a live-controller or simulation-outcome trial.
use std::time::Instant;
fn main() {
    let path=std::env::args().nth(1).expect("authority snapshot JSON");
    let snapshot:serde_json::Value=serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let state=serde_json::to_string(&snapshot["world"]).unwrap();
    let world:simulation::World=serde_json::from_str(&state).unwrap();
    let mut results=vec![];
    for (name,count) in [("deserialize",10),("clone",100),("serialize",10),("participant_publication",10),("advance_50ms",10)] {
        let start=Instant::now();
        for _ in 0..count {match name {
            "deserialize"=>{std::hint::black_box(serde_json::from_str::<simulation::World>(&state).unwrap());},
            "clone"=>{std::hint::black_box(world.clone());},
            "serialize"=>{std::hint::black_box(serde_json::to_string(&world).unwrap());},
            "participant_publication"=>{for actor in world.participants.keys(){std::hint::black_box(world.participant_status_json(*actor).unwrap());}},
            _=>{let mut w=world.clone();w.advance_ms(50);std::hint::black_box(w);},
        }}
        results.push(serde_json::json!({"operation":name,"iterations":count,"mean_ms":start.elapsed().as_secs_f64()*1000./count as f64}));
    }
    let mut continuous=world.clone();
    let mut durations=vec![];
    for _ in 0..100 {let start=Instant::now();continuous.advance_ms(50);durations.push(start.elapsed().as_secs_f64()*1000.);continuous.events.clear();}
    results.push(serde_json::json!({"operation":"continuous_50ms_steps","iterations":100,"mean_ms":durations.iter().sum::<f64>()/100.,"max_ms":durations.iter().cloned().fold(0.,f64::max)}));
    println!("{}",serde_json::json!({"actors":world.players.len(),"serialized_bytes":state.len(),"native_profile":if cfg!(debug_assertions){"debug"}else{"release"},"results":results}));
}
