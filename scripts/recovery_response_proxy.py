#!/usr/bin/env python3
"""Local recovery probe: forward requests, hold responses while a marker exists.

Does not record payloads or credentials. Backpressure bounds held data to one
64 KiB chunk per connection; closing the process closes every owned socket.
"""
import argparse
import asyncio
from pathlib import Path
import signal


async def main(args):
    jobs = set()
    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopping.set)

    async def connection(reader, writer):
        task = asyncio.current_task()
        jobs.add(task)
        upstream = None
        pumps = []
        try:
            remote, upstream = await asyncio.open_connection("127.0.0.1", args.target)

            async def pump(source, destination, hold):
                while data := await source.read(65536):
                    if hold and args.hold.exists():
                        print("response held", flush=True)
                        while args.hold.exists():
                            await asyncio.sleep(0.02)
                    destination.write(data)
                    await destination.drain()

            pumps = [asyncio.create_task(pump(reader, upstream, False)),
                     asyncio.create_task(pump(remote, writer, True))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pump_task in pumps:
                pump_task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            writer.close()
            if upstream:
                upstream.close()
            jobs.discard(task)

    server = await asyncio.start_server(connection, "127.0.0.1", args.listen)
    print(f"listening on 127.0.0.1:{args.listen}", flush=True)
    async with server:
        await stopping.wait()
    for task in list(jobs):
        task.cancel()
    await asyncio.gather(*jobs, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", type=int, default=3113)
    parser.add_argument("--target", type=int, default=3103)
    parser.add_argument("--hold", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
