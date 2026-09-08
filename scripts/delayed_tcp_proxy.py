#!/usr/bin/env python3
"""Local diagnostic delay: preserve TCP bytes/order, add delay in each direction.

This models propagation delay, not packet loss or a bandwidth limit. No payloads,
headers, credentials or tokens are logged. Each read is scheduled independently
so many consecutive chunks do not acquire an extra delay per chunk.
"""
import argparse
import asyncio
import json
from pathlib import Path
import signal
import time


async def forward(reader, writer, delay, samples):
    queue=asyncio.Queue(maxsize=512)
    async def read():
        while data:=await reader.read(65536):
            await queue.put((asyncio.get_running_loop().time()+delay,data))
        await queue.put(None)
    async def send():
        while (item:=await queue.get()) is not None:
            deadline,data=item
            await asyncio.sleep(max(0,deadline-asyncio.get_running_loop().time()))
            writer.write(data)
            await writer.drain()
            samples.append(dict(bytes=len(data),extra_delay_ms=max(0,(asyncio.get_running_loop().time()-deadline)*1000)))
        if writer.can_write_eof():writer.write_eof()
    tasks=[asyncio.create_task(read()),asyncio.create_task(send())]
    try:await asyncio.gather(*tasks)
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)


async def serve(args):
    stats=dict(start_wall_ms=time.time_ns()//10**6,one_way_delay_ms=args.delay_ms,
        upstream=f'{args.upstream_host}:{args.upstream_port}',connections=0,errors=0,
        directions={'client_to_server':[],'server_to_client':[]})
    clients=set()
    async def connect(reader,writer):
        task=asyncio.current_task();clients.add(task);upstream=None;transfers=[]
        try:
            remote,upstream=await asyncio.open_connection(args.upstream_host,args.upstream_port)
            stats['connections']+=1
            transfers=[asyncio.create_task(forward(reader,upstream,args.delay_ms/1000,stats['directions']['client_to_server'])),
                asyncio.create_task(forward(remote,writer,args.delay_ms/1000,stats['directions']['server_to_client']))]
            await asyncio.gather(*transfers)
        except (ConnectionError,OSError):stats['errors']+=1
        finally:
            for transfer in transfers:transfer.cancel()
            await asyncio.gather(*transfers,return_exceptions=True)
            writer.close()
            if upstream:upstream.close()
            clients.discard(task)
    stop=asyncio.Event()
    for sig in [signal.SIGINT,signal.SIGTERM]:asyncio.get_running_loop().add_signal_handler(sig,stop.set)
    server=await asyncio.start_server(connect,'127.0.0.1',args.port)
    print(f'Local delay proxy ready on 127.0.0.1:{args.port}',flush=True)
    try:
        async with server:await stop.wait()
    finally:
        pending=list(clients)
        for task in pending:task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
        stats['end_wall_ms']=time.time_ns()//10**6
        args.output.write_text(json.dumps(stats,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--upstream-host',default='127.0.0.1')
    parser.add_argument('--upstream-port',type=int,required=True)
    parser.add_argument('--delay-ms',type=float,default=40)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.delay_ms<0:parser.error('delay must be nonnegative')
    asyncio.run(serve(args))
