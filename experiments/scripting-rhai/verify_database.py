"""Verify a published, disposable probe module; never targets a gameplay database."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:3197")
    parser.add_argument("--database", default="sao-rhai-decision")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.database.startswith("sao-rhai-decision"):
        parser.error("use a disposable sao-rhai-decision database")
    base = f"{args.server.rstrip('/')}/v1/database/{args.database}"
    prefix = uuid.uuid4().hex[:12]

    def post(path, body):
        req = urllib.request.Request(base + path, data=body.encode(), method="POST",
            headers={"Content-Type": "application/json" if path.startswith("/call/") else "text/plain"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    def rows():
        status, body = post("/sql", "SELECT * FROM probe_result")
        assert status == 200, (status, body)
        return dict(json.loads(body)[0]["rows"])

    movement = (Path(__file__).parent / "scripts/movement.rhai").read_text()
    normal = "fn step_size() { 1 } fn move_cost() { 2 }\n" + movement
    changed = "fn step_size() { 2 } fn move_cost() { 1 }\n" + movement
    results = {}
    for name, source, x, energy, expected in [
        ("normal", normal, 0, 10, "1,8"),
        ("changed", changed, 1, 8, "3,7"),
        ("failed", 'let moved = x + 1; throw "failure"; [moved, energy]', 0, 10, None),
        ("budget", "loop { } [x, energy]", 0, 10, None),
        ("hidden", "[hidden_other_actor, energy]", 0, 10, None),
    ]:
        key = f"{prefix}-{name}"
        status, body = post("/call/evaluate_source", json.dumps([key, source, x, energy, 4]))
        saved = rows()
        if expected is None:
            cause = {"failed": "Runtime error: failure", "budget": "Too many operations",
                     "hidden": "Variable not found"}[name]
            assert status == 530 and cause in body and key not in saved, (name, status, body, saved)
        else:
            assert status == 200 and saved.get(key) == expected, (name, status, body, saved)
        results[name] = {"status": status, "stored_result": saved.get(key)}
    assert rows().get("contracts", "").startswith("11 checks passed"), rows()
    report = {"runtime": "SpacetimeDB 2.1.0 / Rhai 1.26.0",
              "embedded_contracts": rows()["contracts"], "runtime_source_checks": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
