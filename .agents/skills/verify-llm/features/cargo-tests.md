# Model-client cargo tests

## Sub-features

- Unreachable providers hold subsequent calls.
- Group ancestry is bounded and searches parent_a first.
- Group, stage, assignment, rotation and missing-key precedence.
- Repair of stray closers and trailing commas.
- Explicit-clock pacing, token reservations, one decrease per 429 burst, relative rate floors and 100-second recovery after halving.
- Unconfigured profiles start at 600 requests/minute, header ceilings can exceed the start, and Interactive precedes queued Background under saturation.
- Cancellation of queued requests and outage probes.
- Fake HTTP recovery, cache keys, usage breakdown and omitted usage fields.

## How to get to it (user POV)

Run the existing model-client tests after editing `llm.rs`.

## Driving it with cargo

```bash
cargo test --manifest-path living/Cargo.toml -p living-mind llm::tests -- --nocapture
```

Expect every non-ignored `llm::tests` check to pass. `verify_llm.py` runs this command and keeps `cargo-tests.log` in the suite directory before launching scratch worlds.

## Gotchas

The unreachable-provider test uses localhost port 9 and a temporary journal. It makes no paid call. Unit tests complement the real-mind cases. They do not prove a mind subscription or accepted authority update by themselves. Source: `living/mind/src/llm.rs`, module `tests`.
