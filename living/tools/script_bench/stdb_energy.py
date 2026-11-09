#!/usr/bin/env python3
"""Call the calibration module's `bench` reducer over the v1 JSON websocket protocol and
report the energy (wasmtime fuel = WASM instructions) and host duration SpacetimeDB 2.14.1
returns in the caller's TransactionUpdate (crates/core/src/client/messages.rs:455; the v2/v3
protocols, the SDK and the CLI do not carry it).

usage: stdb_energy.py URL DB TOKEN_FILE ENGINE LAW N [REPEATS]
Prints one JSON line per call; the first call per (engine, n) also has n=0 as a baseline.
Needs `websockets` (python -m venv ...; pip install websockets).
"""
import asyncio
import json
import sys

import websockets


def num(v):
    # EnergyQuanta / TimeDuration serialize as {"quanta": n} / {"__time_duration_micros__": n}
    # or plain numbers depending on version; accept any.
    if isinstance(v, dict):
        return next(iter(v.values()))
    return v


async def main():
    url, db, token_file, engine, law, n = sys.argv[1:7]
    repeats = int(sys.argv[7]) if len(sys.argv) > 7 else 5
    token = open(token_file).read().strip()
    ws_url = f"{url.replace('http', 'ws')}/v1/database/{db}/subscribe"
    async with websockets.connect(ws_url, subprotocols=["v1.json.spacetimedb"], additional_headers={"Authorization": f"Bearer {token}"}, max_size=None) as ws:
        first = json.loads(await ws.recv())
        assert "IdentityToken" in first, first
        rid = 0
        for count in [0] + [int(n)] * repeats:
            rid += 1
            args = json.dumps([int(engine), int(law), count])
            await ws.send(json.dumps({"CallReducer": {"reducer": "bench", "args": args, "request_id": rid, "flags": 0}}))
            while True:
                msg = json.loads(await ws.recv())
                if "TransactionUpdate" in msg:
                    tu = msg["TransactionUpdate"]
                    status = tu["status"]
                    if "Failed" in status:
                        print(json.dumps({"error": status}))
                        return
                    print(json.dumps({"engine": int(engine), "law": int(law), "n": count, "energy": num(tu["energy_quanta_used"]), "host_us": num(tu["total_host_execution_duration"])}))
                    break


asyncio.run(main())
