"""python3 drive.py STAGE source.py (or: python3 drive.py close)."""
import json
import socket
import sys
from pathlib import Path

stage = sys.argv[1]
request = "close" if stage == "close" else dict(stage=stage, code=Path(sys.argv[2]).read_text())
with socket.socket(socket.AF_UNIX) as client:
    client.connect(str(Path("live.sock").resolve()))
    client.sendall(json.dumps(request).encode() + b"\n")
    reply = client.makefile("rb").read().decode()
    if reply and reply != "ok":
        sys.exit(reply)
