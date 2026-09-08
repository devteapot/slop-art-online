//! Export the shared kernel's exact initial state for authority comparisons.
//! This does not create a database, advance a world or establish server capacity.
use std::{fs::{self, File}, io::{BufWriter, Write}, path::Path, time::Instant};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args:Vec<_>=std::env::args().skip(1).collect();
    if args.len()!=4 {return Err("usage: initialize_world SCENARIO RUN MODE OUTPUT; MODE is world, participant or client".into());}
    let scenario:simulation::Scenario=serde_json::from_slice(&fs::read(&args[0])?)?;
    let construct=match args[2].as_str() {
        "world"=>simulation::World::new,
        "participant"=>simulation::World::new_participant,
        "client"=>simulation::World::new_client,
        _=>return Err("unknown initialization mode".into()),
    };
    let started=Instant::now();
    let world=construct(args[1].clone(),scenario).map_err(std::io::Error::other)?;
    let initialization_ms=started.elapsed().as_secs_f64()*1000.;
    let out=Path::new(&args[3]);fs::create_dir(out)?;
    let mut state=BufWriter::new(File::create(out.join("world.json"))?);
    serde_json::to_writer(&mut state,&world)?;state.write_all(b"\n")?;state.flush()?;
    let mut audit=BufWriter::new(File::create(out.join("audit.jsonl"))?);
    for event in &world.events {serde_json::to_writer(&mut audit,event)?;audit.write_all(b"\n")?;}
    audit.flush()?;
    let result=serde_json::json!({"run":world.run,"mode":args[2],"population":world.players.len(),
        "events":world.events.len(),"rules":world.version,"initialization_ms":initialization_ms,
        "native_profile":if cfg!(debug_assertions){"debug"}else{"release"},
        "scope":"Shared kernel initialization only; excludes input parsing, export and database work. No inference, connections or physical advancement."});
    fs::write(out.join("result.json"),serde_json::to_vec_pretty(&result)?)?;
    println!("{result}");
    Ok(())
}
