# Run the project journal in the same namespace the live bridge will use.
from pathlib import Path
import json
path=Path.cwd()
code=(path/'bridge.py').read_text()
before,server=code.split('with socket.socket(socket.AF_UNIX) as server:',1)
exec(before)
for row in (path/'session.jsonl').read_text().splitlines():
    step=json.loads(row)
    exec(compile(step['code'],step['stage'],'exec'),scope)
exec('with socket.socket(socket.AF_UNIX) as server:'+server)
