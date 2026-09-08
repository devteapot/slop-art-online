#!/usr/bin/env python3
"""Upload an exact seed in private chunks, then atomically create its World.

Interrupted uploads remain resumable by rerunning with the same run, mode and
bytes. A failed finalization retains the upload; it never deletes an existing run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import urllib.error
import urllib.request

CHUNK_BYTES = 128 * 1024
MAX_SEED_BYTES = 8 * 1024 * 1024
MAX_CHUNKS = 128


def seed_chunks(text):
    data = text.encode('utf-8')
    if not 0 < len(data) <= MAX_SEED_BYTES:
        raise ValueError('seed must contain 1..8388608 UTF-8 bytes')
    offset = 0
    while offset < len(data):
        end = min(offset + CHUNK_BYTES, len(data))
        if end < len(data):
            while data[end] & 0xc0 == 0x80:
                end -= 1
        yield data[offset:end].decode('utf-8')
        offset = end


def upload_world(call, run, text, mode='client', build_progress=None):
    """Use an authenticated reducer callable; never substitute controller identity."""
    if mode not in ('world', 'participant', 'client'):
        raise ValueError('invalid initialization mode')
    parts = list(seed_chunks(text))
    if len(parts) > MAX_CHUNKS:
        raise ValueError('seed requires too many chunks')
    data = text.encode('utf-8')
    digest = hashlib.sha256(data).hexdigest()
    call('sim_begin_world_upload', run, mode, len(data), digest)
    for index, part in enumerate(parts):
        call('sim_append_world_upload', run, index, part)
    if build_progress is not None:
        call('sim_prepare_world_build', run)
        while True:
            progress = build_progress()
            if progress is None:
                raise RuntimeError('private world build progress is unavailable')
            if progress['phase'] == 'ready':
                break
            if progress['phase'] == 'cancelling':
                raise RuntimeError('world build is being cancelled')
            call('sim_advance_world_build', run, progress['step'])
    call('sim_finish_world_upload', run)
    return dict(run=run, mode=mode, bytes=len(data), chunks=len(parts), sha256=digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--config', type=Path, required=True, help='existing private CLI credential file')
    parser.add_argument('--run', required=True)
    parser.add_argument('--mode', choices=['world', 'participant', 'client'], default='client')
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--staged', action='store_true', help='initialize in resumable private batches before activation')
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    token = config['spacetimedb_token']

    def call(reducer, *values):
        request = urllib.request.Request(
            args.server.rstrip('/') + '/v1/database/' + args.database + '/call/' + reducer,
            data=json.dumps(values).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'{reducer}: HTTP {error.code}: {error.read().decode(errors="replace")}') from None

    # Read bytes directly so newline conversion cannot change the committed digest.
    def build_progress():
        request = urllib.request.Request(
            args.server.rstrip('/') + '/v1/database/' + args.database + '/sql',
            data=b'SELECT phase, step FROM sim_my_world_build', method='POST',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'text/plain'})
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            rows = json.load(response)[0]['rows']
        return dict(zip(['phase', 'step'], rows[0])) if rows else None

    result = upload_world(call, args.run, args.scenario.read_bytes().decode('utf-8'), args.mode,
        build_progress=build_progress if args.staged else None)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
