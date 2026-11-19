"""Run with Blender -b --factory-startup -P. One local client, one request at a time."""
import datetime
import json
import os
from pathlib import Path
import socket
import traceback

root = Path.cwd()
os.umask(0o077)
endpoint = root / "live.sock"
scope = {"ROOT": root, "__name__": "__main__"}
with socket.socket(socket.AF_UNIX) as server:
    server.bind("live.sock")
    server.listen(1)
    try:
        while True:
            connection, _ = server.accept()
            with connection, connection.makefile("rb") as stream:
                request = json.loads(stream.readline())
                if request == "close":
                    break
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                record = dict(timestamp=now, **request)
                with (root / "session.jsonl").open("a") as journal:
                    journal.write(json.dumps(record) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
                try:
                    exec(compile(record["code"], record["stage"], "exec"), scope)
                    reply = "ok"
                except Exception:
                    reply = traceback.format_exc()
                connection.sendall(reply.encode())
    finally:
        endpoint.unlink(missing_ok=True)
