# Model-client cargo tests

## Sub-features

- Unreachable providers hold subsequent calls.
- Group ancestry is bounded and searches parent_a first.
- Group, stage, assignment, rotation and missing-key precedence.
- Repair of stray closers and trailing commas.

## How to get to it (user POV)

Run the existing model-client tests after editing `llm.rs`.

## Driving it with cargo

```bash
cargo test --manifest-path living/Cargo.toml -p living-mind llm::tests -- --nocapture
```

Expect four passed tests. `verify_llm.py` runs this command and keeps `cargo-tests.log` in the suite directory before launching scratch worlds.

## Gotchas

The unreachable-provider test uses localhost port 9 and a temporary journal. It makes no paid call. Unit tests complement the real-mind cases. They do not prove a mind subscription or accepted authority update by themselves. Source: `living/mind/src/llm.rs:522-602`.
