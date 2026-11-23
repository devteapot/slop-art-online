# Shared harness: the first CLI login, once (`launch-login-lock`)

Validated on the dev-box on branch `launch-login-lock`, from `origin/main` `a76dfc3f3` with `launch-login-note` (`2d0728c32`) merged in, before its commit. Harness and tools: `living/tools/cli_login.py` (new), `cli_login_selftest.py` (new), `verify.py` `admin_token(initialize=True)`, `trials.py up`, and SKILL.md's Launch paragraph. Server: private `clockworklabs/spacetime:v2.14.1` containers `ll-stdb` on `127.0.0.1:3343`, created fresh for each step below in their own systemd scope and removed with their volumes afterwards. No mind service, no Neo4j.

## SpacetimeDB documentation

The [CLI reference](https://spacetimedb.com/docs/cli-reference) (`#spacetime-login`, `#spacetime-login-show`) lists `--auth-host`, `--token` and `--no-browser` and does not document `--server-issued-login`. In the pinned image the flag writes `~/.config/spacetime/cli.toml` ("Saving config to …cli.toml") and calls `POST /v1/identity`, which issues a new identity ([HTTP API](https://spacetimedb.com/docs/http/identity/)). `cli.toml` is in the container, not the data volume: a recreated container has a fresh CLI.

## Runs

- **Fake tier** (`python3 living/tools/cli_login_selftest.py`): 8 parallel first logins through `ensure()`: 1 login, 1 identity, the CLI's own; with `--parallel 16`: passed. Control, the old check-then-login: 8 at once made 8 logins and 4 distinct identities read; 16 at once, 16 and 7.
- **Control on a fresh server** (the old pattern by hand, 4 shells at once): one of the four read a token other than the CLI's final one.
- **Server tier** on another fresh `ll-stdb` (`--server ll-stdb --url http://127.0.0.1:3343 --parallel 4`): no error, one token across the four, equal to the CLI's own: passed.
- **End to end:** four `verify.py launch --run ll-par-{1..4} --target-dir .local/ll/target` at once on a third fresh `ll-stdb` (its CLI "not logged in"): all four exit 0, published and installed `skills.rhai`; cleanup deleted all four, and the server listed no databases.
- Evidence: `.local/ll/launch-*.log` and `.local/living/verify/ll-par-*`, archived in `~/archive/worktree-evidence-20261121/launch-login-lock-local.tar.gz`.

## Not covered

`trials.py up` on a fresh container (the same `ensure()`, not run). macOS (fcntl locks work there; not run). A CLI logged out while launches run.
