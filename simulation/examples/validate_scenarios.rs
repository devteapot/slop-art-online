//! Validate generated experiment inputs through the actual authority, without
//! creating database worlds, participant grants or model calls.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let paths: Vec<_> = std::env::args().skip(1).collect();
    if paths.is_empty() {
        return Err("supply one or more scenario JSON paths".into());
    }
    for path in paths {
        let scenario: simulation::Scenario = serde_json::from_slice(&std::fs::read(&path)?)?;
        let mut world = simulation::World::new("sim-seed-validation".into(), scenario)
            .map_err(std::io::Error::other)?;
        world.enable_participants();
        world.advance_ms(50);
        if let Some(event) = world.events.iter().find(|e| e.kind == "script_tick_failed") {
            return Err(format!("{path}: initial clock update failed: {}", event.data).into());
        }
        println!("{}", serde_json::json!({"scenario":path,"rules":world.version,
            "actors":world.players.len(),"initialization_and_first_update":"passed","model_calls":0}));
    }
    Ok(())
}
