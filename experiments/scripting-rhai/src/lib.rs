//! Embedding probe for ADR 016. No production simulation rules live here.
use rhai::{Array, Engine, EvalAltResult, Scope, INT};

pub const MOVEMENT: &str = include_str!("../scripts/movement.rhai");
pub const NORMAL_LAW: &str = "fn step_size() { 1 } fn move_cost() { 2 }";
pub const CHANGED_LAW: &str = "fn step_size() { 2 } fn move_cost() { 1 }";

pub fn engine() -> Engine {
    let mut engine = Engine::new_raw();
    engine.set_max_operations(2_000);
    engine.set_max_call_levels(16);
    engine.set_max_expr_depths(32, 16);
    engine.set_max_string_size(1_024);
    engine.set_max_array_size(64);
    engine.set_max_map_size(32);
    engine.set_max_variables(64);
    engine.disable_symbol("eval");
    engine.disable_symbol("import");
    engine
}

pub fn evaluate(source: &str, x: i64, energy: i64, destination: i64) -> Result<(i64, i64), String> {
    if source.len() > 16_384 {
        return Err("source limit".into());
    }
    let engine = engine();
    let ast = engine.compile(source).map_err(|e| e.to_string())?;
    let mut scope = Scope::new();
    scope.push_constant("x", x);
    scope.push_constant("energy", energy);
    scope.push_constant("destination", destination);
    let output: Array = engine
        .eval_ast_with_scope(&mut scope, &ast)
        .map_err(|e| e.to_string())?;
    if output.len() != 2 {
        return Err("expected two state fields".into());
    }
    let new_x = output[0].as_int().map_err(|_| "position must be integer")?;
    let new_energy = output[1].as_int().map_err(|_| "energy must be integer")?;
    Ok((new_x, new_energy))
}

pub fn check_contracts() -> Result<String, String> {
    let normal = format!("{NORMAL_LAW}\n{MOVEMENT}");
    let changed = format!("{CHANGED_LAW}\n{MOVEMENT}");
    if evaluate(&normal, 0, 10, 4)? != (1, 8) {
        return Err("scripted movement failed".into());
    }
    // State outlives the evaluator. A later tick uses the same skill and a new law.
    let (x, energy) = evaluate(&normal, 0, 10, 4)?;
    if evaluate(&changed, x, energy, 4)? != (3, 7) {
        return Err("active law change failed".into());
    }
    if evaluate(&normal, 0, 1, 4)? != (0, 1) {
        return Err("scripted prerequisite failed".into());
    }
    // This law changes the cost without changing Rust or the skill source.
    let free = format!("fn step_size() {{ 1 }} fn move_cost() {{ 0 }}\n{MOVEMENT}");
    if evaluate(&free, 0, 0, 4)? != (1, 0) {
        return Err("editable cost failed".into());
    }
    // Composing two scripted action steps introduces no Rust action variant.
    let composed = normal.replace(
        "step(x, energy, destination)",
        "let first = step(x, energy, destination); step(first[0], first[1], destination)",
    );
    if evaluate(&composed, 0, 10, 4)? != (2, 6) {
        return Err("composition failed".into());
    }
    let engine = engine();
    let error = engine.eval::<INT>("loop { }").expect_err("loop must stop");
    if !matches!(*error, EvalAltResult::ErrorTooManyOperations(_)) {
        return Err(format!("unexpected budget error: {error}"));
    }
    for (name, source) in [
        ("host access", "read_file(\"unavailable\"); [x, energy]"),
        ("hidden observation", "[hidden_other_actor, energy]"),
        (
            "recursive execution",
            "fn recurse() { recurse() } recurse(); [x, energy]",
        ),
        ("invalid effect", "[true, energy]"),
        (
            "partial execution",
            "let moved = x + 1; throw \"failure\"; [moved, energy]",
        ),
    ] {
        if evaluate(source, 0, 10, 4).is_ok() {
            return Err(format!("{name} was not rejected"));
        }
    }
    Ok("11 checks passed: movement, law change, prerequisite, editable cost, composition, operation budget, host access, hidden observation, recursion, invalid effect, partial execution".into())
}

#[cfg(feature = "database")]
mod database {
    use spacetimedb::{ReducerContext, Table};

    #[spacetimedb::table(accessor = probe_result, public)]
    pub struct ProbeResult {
        #[primary_key]
        pub name: String,
        pub result: String,
    }

    #[spacetimedb::reducer]
    pub fn check(ctx: &ReducerContext) -> Result<(), String> {
        let result = super::check_contracts()?;
        ctx.db.probe_result().insert(ProbeResult {
            name: "contracts".into(),
            result,
        });
        Ok(())
    }

    // Source arrives at runtime: it is not compiled into the WASM artifact.
    #[spacetimedb::reducer]
    pub fn evaluate_source(
        ctx: &ReducerContext,
        name: String,
        source: String,
        x: i64,
        energy: i64,
        destination: i64,
    ) -> Result<(), String> {
        let (x, energy) = super::evaluate(&source, x, energy, destination)?;
        ctx.db.probe_result().insert(ProbeResult {
            name,
            result: format!("{x},{energy}"),
        });
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn embedding_contracts() {
        println!("{}", super::check_contracts().unwrap());
    }
}
