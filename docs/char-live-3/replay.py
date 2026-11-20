"""Run the live journal from the approved char-live-2 editable scene."""
import json
import os
from pathlib import Path

SESSION = Path(__file__).resolve().parent
PREVIOUS = SESSION.parent/'char-live-2'
APPROVED = PREVIOUS/'final'
ROOT = Path(os.environ.get('CHAR_LIVE_OUTPUT', SESSION/'rebuilt')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
for record in map(json.loads, (SESSION/'session.jsonl').read_text().splitlines()):
    if record.get('archived'):
        continue
    source = SESSION/record['block']
    exec(compile(source.read_text(), str(source), 'exec'), globals())
