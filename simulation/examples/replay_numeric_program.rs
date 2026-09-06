//! Observer-only replay of a retained artifact. No world, participant, or proof is created.
use serde::Deserialize;
use serde_json::json;
use simulation::research_programs::{run, validate, ProgramArtifact};

#[derive(Deserialize)]
struct Case {
    label: String,
    inputs: Vec<i64>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 {
        return Err("usage: replay_numeric_program ARTIFACT.json CASES.json".into());
    }
    let artifact: ProgramArtifact = serde_json::from_slice(&std::fs::read(&args[1])?)?;
    validate(&artifact)?;
    let cases: Vec<Case> = serde_json::from_slice(&std::fs::read(&args[2])?)?;
    let results: Vec<_> = cases.into_iter().map(|case| {
        let (output, error) = match run(&artifact, &case.inputs) {
            Ok(output) => (Some(output), None),
            Err(error) => (None, Some(error)),
        };
        json!({"label":case.label,"inputs":case.inputs,"output":output,"error":error})
    }).collect();
    println!("{}", serde_json::to_string_pretty(&json!({
        "mode":"offline observer replay; no character action or competence proof",
        "source_hash":artifact.source_hash,
        "results":results,
    }))?);
    Ok(())
}
