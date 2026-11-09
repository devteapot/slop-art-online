#!/usr/bin/env python3
"""Bytes the server sent to clients of one database, by transaction kind, from the server's
Prometheus metrics (`spacetime_num_bytes_sent_to_clients_total`). Prints JSON; run twice and
subtract for a window. `client_bytes.py DB [--url http://127.0.0.1:3300]`."""
import json, re, sys, urllib.request

db = sys.argv[1]
url = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--url" else "http://127.0.0.1:3300"
ident = json.load(urllib.request.urlopen(f"{url}/v1/database/{db}"))["database_identity"]["__identity__"].removeprefix("0x")
text = urllib.request.urlopen(f"{url}/v1/metrics").read().decode()
out = {}
for m in re.finditer(r'^spacetime_num_bytes_sent_to_clients_total\{db="([0-9a-f]+)",txn_type="(\w+)"\} (\d+)', text, re.M):
    if m.group(1) == ident:
        out[m.group(2)] = int(m.group(3))
print(json.dumps(out))
