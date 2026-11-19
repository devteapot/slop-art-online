"""Rebuild Cora with the journal's edits to the inherited head construction."""
import json
import os
from pathlib import Path

SESSION = Path(__file__).resolve().parent
baseline = SESSION.parent / "char-live-1" / "restart" / "replay.py"
os.environ.setdefault("CHAR_LIVE_OUTPUT", str(SESSION / "rebuilt"))
entries = [json.loads(line) for line in (SESSION / "session.jsonl").read_text().splitlines()]
source = baseline.read_text()
for entry in entries:
    if "replace_baseline" in entry:
        original = entry["replace_baseline"]
        if source.count(original) != 1:
            raise ValueError(f"Expected one match for {entry['stage']}")
        source = source.replace(original, entry["code"])
exec(compile(source, str(baseline), "exec"), globals())
for entry in entries:
    if "replace_baseline" not in entry:
        exec(compile(entry["code"], entry["stage"], "exec"), globals())
