//! Isolated interpreter for participant-authored numeric techniques.
//!
//! This module has no world, effect, storage, or capability APIs. Its caller must
//! authorize the actor and account for physical compute before invoking `run`.
//! Artifacts are self-contained data to carry in personal/physical knowledge
//! copies; a hash is an integrity check, not a globally resolvable code address.
//!
//! Interface 1 accepts and returns at most 64 signed 64-bit integers. Contract
//! descriptions explain their meaning; they are not executable validators.
//! Source contains function definitions only. Top-level statements are rejected,
//! including constants, so no uncharged initialization or captured globals run.
use rhai::packages::Package;
use rhai::{
    CallFnOptions, Dynamic, Engine, EvalAltResult, FnAccess, OptimizationLevel, Scope, AST,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const INTERFACE_VERSION: u32 = 1;
pub const MAX_SOURCE_BYTES: usize = 8_192;
pub const MAX_CONTRACT_BYTES: usize = 512;
pub const MAX_VECTOR_LEN: usize = 64;
pub const MAX_OPERATIONS: u64 = 20_000;
const MAX_ERROR_CHARS: usize = 512;

#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProgramDraft {
    /// Numeric interface version: must be 1.
    pub interface_version: u32,
    /// Rhai function definitions only. Declare fn technique(input) followed by its body;
    /// functions are public by default and Rhai has no pub keyword. No top-level statements.
    /// Local bindings use let x = ... and are mutable without a mut keyword.
    pub source: String,
    pub input_contract: String,
    pub output_contract: String,
}

#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProgramArtifact {
    pub interface_version: u32,
    pub source: String,
    /// Lowercase SHA-256 of the domain-separated, length-framed interface,
    /// exact source bytes, and both contract descriptions. Whitespace matters.
    pub source_hash: String,
    pub input_contract: String,
    pub output_contract: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", content = "detail", rename_all = "snake_case")]
pub enum ProgramError {
    InterfaceVersion,
    SourceSize,
    ContractSize,
    InvalidSource(String),
    TopLevelStatements,
    EntryPoint,
    HashMismatch,
    InputSize,
    OperationBudget,
    RecursionLimit,
    Runtime(String),
    OutputType,
    OutputSize,
    OutputElement(usize),
}
impl std::fmt::Display for ProgramError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InterfaceVersion => f.write_str("numeric technique interface version must be 1"),
            Self::SourceSize => f.write_str("technique source must contain 1..8192 bytes"),
            Self::ContractSize => f.write_str("each technique contract must contain 1..512 bytes"),
            Self::InvalidSource(detail) => write!(f, "invalid technique source: {detail}"),
            Self::TopLevelStatements => f.write_str("techniques permit function definitions only; top-level statements and globals are forbidden"),
            Self::EntryPoint => f.write_str("technique requires public function technique(input) with exactly one parameter"),
            Self::HashMismatch => f.write_str("technique artifact hash does not match its exact payload"),
            Self::InputSize => f.write_str("technique input exceeds 64 integers"),
            Self::OperationBudget => f.write_str("technique exceeded its interpreter operation budget"),
            Self::RecursionLimit => f.write_str("technique exceeded its call-depth limit"),
            Self::Runtime(detail) => write!(f, "technique execution failed: {detail}"),
            Self::OutputType => f.write_str("technique must return an array of integers"),
            Self::OutputSize => f.write_str("technique output exceeds 64 integers"),
            Self::OutputElement(index) => write!(f, "technique output element {index} is not an integer"),
        }
    }
}
impl std::error::Error for ProgramError {}

fn engine() -> Engine {
    let mut engine = Engine::new_raw();
    rhai::packages::StandardPackage::new().register_into_engine(&mut engine);
    engine.set_max_operations(MAX_OPERATIONS);
    engine.set_max_call_levels(16);
    engine.set_max_expr_depths(32, 24);
    engine.set_max_array_size(128);
    engine.set_max_map_size(64);
    engine.set_max_string_size(1024);
    engine.set_max_variables(128);
    engine.set_max_strings_interned(256);
    engine.set_strict_variables(true);
    // Preserve the actual top-level AST for rejection, rather than optimizing
    // away an expression or propagating a global constant into a function.
    engine.set_optimization_level(OptimizationLevel::None);
    engine.set_allow_anonymous_fn(false);
    for symbol in [
        "eval", "import", "export", "print", "debug", "Fn", "call", "curry",
    ] {
        engine.disable_symbol(symbol);
    }
    engine
}

fn validate_payload(
    version: u32,
    source: &str,
    input: &str,
    output: &str,
) -> Result<(), ProgramError> {
    if version != INTERFACE_VERSION {
        return Err(ProgramError::InterfaceVersion);
    }
    if source.trim().is_empty() || source.len() > MAX_SOURCE_BYTES {
        return Err(ProgramError::SourceSize);
    }
    if [input, output]
        .iter()
        .any(|s| s.trim().is_empty() || s.len() > MAX_CONTRACT_BYTES)
    {
        return Err(ProgramError::ContractSize);
    }
    Ok(())
}

fn hash_payload(version: u32, source: &str, input: &str, output: &str) -> String {
    let mut hash = Sha256::new();
    hash.update(b"slop-art-online/numeric-technique\0");
    hash.update(version.to_be_bytes());
    for field in [source, input, output] {
        hash.update((field.len() as u64).to_be_bytes());
        hash.update(field.as_bytes());
    }
    format!("{:x}", hash.finalize())
}

// Rhai 1.26 exposes AST's top-level statement slice through this public AsRef
// implementation even when the statement type is not re-exported by `internals`.
// Keeping T inferred avoids any dependency on Rhai's private AST representation.
fn has_top_level_statements<T>(ast: &impl AsRef<[T]>) -> bool {
    !ast.as_ref().is_empty()
}
fn compile_source(engine: &Engine, source: &str) -> Result<AST, ProgramError> {
    let ast = engine
        .compile(source)
        .map_err(|error| ProgramError::InvalidSource(bounded(error)))?;
    if has_top_level_statements(&ast) {
        return Err(ProgramError::TopLevelStatements);
    }
    if !ast.iter_functions().any(|f| {
        f.name == "technique"
            && f.params.len() == 1
            && f.access == FnAccess::Public
            && f.this_type.is_none()
    }) {
        return Err(ProgramError::EntryPoint);
    }
    // Defense in depth: neither compilation nor invocation executes statements.
    Ok(ast.clone_functions_only())
}
fn bounded(error: impl std::fmt::Display) -> String {
    error.to_string().chars().take(MAX_ERROR_CHARS).collect()
}
fn runtime_error(error: Box<EvalAltResult>) -> ProgramError {
    match error.unwrap_inner() {
        EvalAltResult::ErrorTooManyOperations(_) => ProgramError::OperationBudget,
        EvalAltResult::ErrorStackOverflow(_) => ProgramError::RecursionLimit,
        _ => ProgramError::Runtime(bounded(error)),
    }
}

/// Validate syntax and the entry point without running the submitted technique.
/// The returned artifact is suitable for a physical paid job, not an authority grant.
pub fn compile(draft: &ProgramDraft) -> Result<ProgramArtifact, ProgramError> {
    validate_payload(
        draft.interface_version,
        &draft.source,
        &draft.input_contract,
        &draft.output_contract,
    )?;
    compile_source(&engine(), &draft.source)?;
    Ok(ProgramArtifact {
        interface_version: draft.interface_version,
        source: draft.source.clone(),
        source_hash: hash_payload(
            draft.interface_version,
            &draft.source,
            &draft.input_contract,
            &draft.output_contract,
        ),
        input_contract: draft.input_contract.clone(),
        output_contract: draft.output_contract.clone(),
    })
}
fn validated(artifact: &ProgramArtifact) -> Result<(Engine, AST), ProgramError> {
    validate_payload(
        artifact.interface_version,
        &artifact.source,
        &artifact.input_contract,
        &artifact.output_contract,
    )?;
    if artifact.source_hash.len() != 64
        || artifact.source_hash
            != hash_payload(
                artifact.interface_version,
                &artifact.source,
                &artifact.input_contract,
                &artifact.output_contract,
            )
    {
        return Err(ProgramError::HashMismatch);
    }
    let engine = engine();
    let ast = compile_source(&engine, &artifact.source)?;
    Ok((engine, ast))
}

/// Revalidate a received or deserialized artifact before admitting a paid job.
pub fn validate(artifact: &ProgramArtifact) -> Result<(), ProgramError> {
    validated(artifact).map(|_| ())
}

/// Run only against caller-provided integers, in a fresh engine and empty scope.
/// No AST, scope, mutable globals or function pointers survive this invocation.
pub fn run(artifact: &ProgramArtifact, input: &[i64]) -> Result<Vec<i64>, ProgramError> {
    if input.len() > MAX_VECTOR_LEN {
        return Err(ProgramError::InputSize);
    }
    let (engine, ast) = validated(artifact)?;
    let values: rhai::Array = input
        .iter()
        .map(|&value| Dynamic::from_int(value))
        .collect();
    let result: Dynamic = engine
        .call_fn_with_options(
            CallFnOptions::new().eval_ast(false),
            &mut Scope::new(),
            &ast,
            "technique",
            (values,),
        )
        .map_err(runtime_error)?;
    let output = result
        .try_cast::<rhai::Array>()
        .ok_or(ProgramError::OutputType)?;
    if output.len() > MAX_VECTOR_LEN {
        return Err(ProgramError::OutputSize);
    }
    output
        .into_iter()
        .enumerate()
        .map(|(index, value)| {
            value
                .as_int()
                .map_err(|_| ProgramError::OutputElement(index))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn draft(source: &str) -> ProgramDraft {
        ProgramDraft {
            interface_version: 1,
            source: source.into(),
            input_contract: "An array of signed integers, as documented by the technique".into(),
            output_contract: "Derived signed integer results".into(),
        }
    }
    fn program(source: &str) -> ProgramArtifact {
        compile(&draft(source)).unwrap()
    }

    // Tooling fixture only, not evidence that an in-world participant invented it.
    // A capped battery loses surplus generation and accumulates unmet demand.
    // Ordering changes the answer even when total inflow and demand are equal.
    const RESERVE: &str = r#"
        fn positive(n) { if n > 0 { n } else { 0 } }
        fn technique(input) {
            let charge = input[0];
            let capacity = input[1];
            let unmet = 0;
            let spilled = 0;
            for index in range(2, input.len(), 2) {
                let available = charge + input[index];
                spilled += positive(available-capacity);
                charge = if available > capacity { capacity } else { available };
                unmet += positive(input[index+1]-charge);
                charge = positive(charge-input[index+1]);
            }
            [charge, unmet, spilled]
        }
    "#;

    #[test]
    fn nonlinear_multi_interval_algorithm_uses_only_explicit_input_and_helpers() {
        let artifact = program(RESERVE);
        assert_eq!(run(&artifact, &[2, 5, 8, 2, 0, 7]).unwrap(), vec![0, 4, 5]);
        assert_eq!(run(&artifact, &[2, 5, 0, 7, 8, 2]).unwrap(), vec![3, 5, 3]);
        assert_eq!(run(&artifact, &[2, 20, 8, 2, 0, 7]).unwrap(), vec![1, 0, 0]);
        assert_eq!(run(&artifact, &[2, 5, 8, 2, 0, 7]).unwrap(), vec![0, 4, 5]);
        let roundtrip: ProgramArtifact =
            serde_json::from_slice(&serde_json::to_vec(&artifact).unwrap()).unwrap();
        assert_eq!(artifact, roundtrip);
        assert_eq!(run(&roundtrip, &[2, 5, 8, 2, 0, 7]).unwrap(), vec![0, 4, 5]);
    }
    #[test]
    fn parser_checks_syntax_and_public_entry_arity_without_executing() {
        assert!(matches!(
            compile(&draft("fn technique(input) { [ }")),
            Err(ProgramError::InvalidSource(_))
        ));
        for source in [
            "fn other(input) { input }",
            "fn technique() { [] }",
            "fn technique(a,b) { [] }",
            "private fn technique(input) { input }",
        ] {
            assert_eq!(compile(&draft(source)), Err(ProgramError::EntryPoint));
        }
        // Admission must not evaluate code that consumes budget or throws.
        validate(&program("fn technique(input) { throw \"only when run\"; }")).unwrap();
        validate(&program("fn technique(input) { loop {} }")).unwrap();
    }
    #[test]
    fn top_level_execution_and_globals_are_rejected_by_real_ast() {
        assert_eq!(
            compile(&draft("42; fn technique(input) { input }")),
            Err(ProgramError::TopLevelStatements)
        );
        for source in [
            "42; fn technique(input) { input }",
            "let global_number = 7; fn technique(input) { input }",
            "const global_number = 7; fn technique(input) { [global_number] }",
            "loop {} fn technique(input) { input }",
            "throw \"uncharged\"; fn technique(input) { input }",
        ] {
            assert!(
                matches!(
                    compile(&draft(source)),
                    Err(ProgramError::TopLevelStatements) | Err(ProgramError::InvalidSource(_))
                ),
                "{source}"
            );
        }
        assert!(compile(&draft(
            "// let global_number=8;\n fn technique(input) { let global_number=8; [global_number] }"
        ))
        .is_ok());
        assert!(compile(&draft("fn technique(input) { [unprovided_global] }")).is_err());
    }
    #[test]
    fn operation_budget_and_recursion_are_recoverable_typed_failures() {
        assert_eq!(
            run(&program("fn technique(input) { loop {} }"), &[]),
            Err(ProgramError::OperationBudget)
        );
        let recursive = program("fn again(n) { again(n+1) } fn technique(input) { [again(0)] }");
        assert_eq!(run(&recursive, &[]), Err(ProgramError::RecursionLimit));
        assert_eq!(
            run(&program("fn technique(input) { input }"), &[7]),
            Ok(vec![7]),
            "failed work leaves no execution state"
        );
    }
    #[test]
    fn result_shape_and_numeric_limits_are_checked_without_coercion() {
        for source in [
            "fn technique(input) { 1 }",
            "fn technique(input) { #{effects: []} }",
            "fn technique(input) { \"result\" }",
        ] {
            assert_eq!(run(&program(source), &[]), Err(ProgramError::OutputType));
        }
        assert_eq!(
            run(&program("fn technique(input) { [1,true] }"), &[]),
            Err(ProgramError::OutputElement(1))
        );
        assert_eq!(
            run(&program("fn technique(input) { [[1]] }"), &[]),
            Err(ProgramError::OutputElement(0))
        );
        assert_eq!(run(&program("fn technique(input) { let result=[]; for x in 0..65 {result.push(x);} result }"),&[]),Err(ProgramError::OutputSize));
        let identity = program("fn technique(input) { input }");
        assert_eq!(run(&identity, &vec![0; 65]), Err(ProgramError::InputSize));
        assert_eq!(
            run(&identity, &[i64::MIN, 0, i64::MAX]),
            Ok(vec![i64::MIN, 0, i64::MAX])
        );
        assert!(matches!(
            run(
                &program("fn technique(input) { [input[0]+1] }"),
                &[i64::MAX]
            ),
            Err(ProgramError::Runtime(_))
        ));
        assert!(matches!(
            run(&program("fn technique(input) { [1/input[0]] }"), &[0]),
            Err(ProgramError::Runtime(_))
        ));
    }
    #[test]
    fn artifact_hash_binds_exact_source_interface_and_contracts() {
        let good = program("fn technique(input) { input }");
        assert_eq!(good.source_hash.len(), 64);
        assert!(good
            .source_hash
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)));
        for change in 0..4 {
            let mut bad = good.clone();
            match change {
                0 => bad.source.push(' '),
                1 => bad.input_contract.push('!'),
                2 => bad.output_contract.push('!'),
                _ => bad.source_hash = "0".repeat(64),
            };
            assert_eq!(validate(&bad), Err(ProgramError::HashMismatch));
            assert_eq!(run(&bad, &[]), Err(ProgramError::HashMismatch));
        }
        let mut bad = good;
        bad.interface_version = 2;
        assert_eq!(validate(&bad), Err(ProgramError::InterfaceVersion));
        assert_ne!(
            program("fn technique(input) { input }").source_hash,
            program("fn technique(input) { input } ").source_hash
        );
    }
    #[test]
    fn no_world_host_dynamic_evaluation_or_global_state_is_available() {
        for source in [
            "fn technique(input) { print(\"hello\"); [] }",
            "fn technique(input) { debug(input); [] }",
            "fn technique(input) { eval(\"[42]\") }",
            "fn technique(input) { import \"secrets\" as secrets; [] }",
            "fn technique(input) { let f=Fn(\"print\"); f.call(\"hello\"); [] }",
            "fn technique(input) { let f=|x| x; [f.call(1)] }",
            "fn technique(input) { [World.players[0].food] }",
        ] {
            assert!(compile(&draft(source)).is_err(), "{source}");
        }
        for source in [
            "fn technique(input) { [read_file(\"/etc/passwd\")] }",
            "fn technique(input) { [http_get(\"https://example.com\")] }",
            "fn technique(input) { [world_food(0)] }",
            "fn technique(input) { [random()] }",
            "fn technique(input) { [timestamp()] }",
        ] {
            assert!(
                matches!(run(&program(source), &[]), Err(ProgramError::Runtime(_))),
                "{source}"
            );
        }
        let local = program("fn technique(input) { let count=0; count+=1; [count] }");
        assert_eq!(run(&local, &[]), Ok(vec![1]));
        assert_eq!(run(&local, &[]), Ok(vec![1]));
    }
    #[test]
    fn source_contract_and_working_collection_bounds_apply() {
        let mut bad = draft(&" ".repeat(8193));
        assert_eq!(compile(&bad), Err(ProgramError::SourceSize));
        bad = draft("fn technique(input) { input }");
        bad.input_contract = "é".repeat(257);
        assert_eq!(compile(&bad), Err(ProgramError::ContractSize));
        bad.input_contract = " ".into();
        assert_eq!(compile(&bad), Err(ProgramError::ContractSize));
        assert!(matches!(
            run(
                &program(
                    "fn technique(input) { let data=[]; for i in 0..129 { data.push(i); } [] }"
                ),
                &[]
            ),
            Err(ProgramError::Runtime(_))
        ));
        assert!(matches!(
            run(
                &program("fn technique(input) { let data=\"x\"; for i in 0..11 {data+=data;} [] }"),
                &[]
            ),
            Err(ProgramError::Runtime(_))
        ));
        let map_limit=run(&program("fn technique(input) { let data=#{}; for i in 0..65 { data[i.to_string()]=i; } [data.len()] }"),&[]);
        assert!(
            matches!(map_limit, Err(ProgramError::Runtime(_))),
            "{map_limit:?}"
        );
    }
}
