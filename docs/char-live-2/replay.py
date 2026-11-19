"""Rebuild char-live-1, then run each char-live-2 modelling block in order."""
import json
import os
from pathlib import Path

SESSION = Path(__file__).resolve().parent
baseline = SESSION.parent / "char-live-1" / "restart" / "replay.py"
os.environ.setdefault("CHAR_LIVE_OUTPUT", str(SESSION / "rebuilt"))
exec(compile(baseline.read_text(), str(baseline), "exec"), globals())
for entry in (SESSION / "session.jsonl").read_text().splitlines():
    block = json.loads(entry)
    exec(compile(block["code"], block["stage"], "exec"), globals())
