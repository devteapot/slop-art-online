#!/usr/bin/env python3
"""Exercise the reusable fake's HTTP contract without any external endpoint."""
import argparse
import http.client
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
FAKE = Path(__file__).with_name('fake_llm.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'llm-[A-Za-z0-9-]+', args.run):
        parser.error('use a new llm- run name')
    directory = ROOT / '.local/living/verify' / args.run
    directory.mkdir(parents=True, exist_ok=False)
    results = []
    for scenario in ('valid', '429', '500', 'malformed', 'repair', 'delay', 'timeout', 'outage', 'script'):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        log = directory / f'{scenario}.jsonl'
        server_log = directory / f'{scenario}-server.log'
        command = [sys.executable, str(FAKE), '--port', str(port), '--log', str(log)]
        if scenario == 'script':
            script = directory / 'script.json'
            script.write_text(json.dumps({'rules': [{'purpose': 'think', 'status': 429, 'headers': {'Retry-After': '2', 'x-ratelimit-limit-req-minute': '60'}},
                       {'purpose': 'talk', 'reply': {'say': 'scripted', 'to': 3}, 'usage': {'total_tokens': 100, 'prompt_tokens': 80, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 64}}},
                       {'purpose': 'consolidate', 'raw_http_body': 'broken envelope'}]}))
            command += ['--script', str(script)]
        else:
            command += ['--scenario', scenario, '--delay-s', '0.3']
        process = None
        with server_log.open('w') as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 5
                while 'READY ' not in server_log.read_text():
                    assert process.poll() is None, 'fake exited before readiness'
                    assert time.monotonic() < deadline, 'fake readiness timed out'
                    time.sleep(0.02)
                def post(purpose, timeout=2):
                    request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                          json.dumps({'model': 'contract', 'reasoning_effort': purpose,
                                      'messages': [{'role': 'user', 'content': 'hello'}]}).encode(),
                          {'Content-Type': 'application/json', 'Authorization': 'Bearer dummy-local-only'})
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        return response.status, response.read().decode()
                if scenario in ('429', '500'):
                    try:
                        post('think')
                        raise AssertionError('status injection did not fail')
                    except urllib.error.HTTPError as error:
                        assert error.code == int(scenario)
                elif scenario in ('delay', 'timeout'):
                    started = time.monotonic()
                    try:
                        post('think', 0.1)
                        raise AssertionError('delay did not exceed caller timeout')
                    except TimeoutError:
                        assert time.monotonic() - started >= 0.09
                elif scenario == 'outage':
                    try:
                        post('think')
                        raise AssertionError('outage returned a response')
                    except (http.client.RemoteDisconnected, urllib.error.URLError):
                        pass
                    process.wait(timeout=3)
                    with socket.socket() as sock:
                        assert sock.connect_ex(('127.0.0.1', port)) != 0, 'outage left port listening'
                elif scenario == 'script':
                    try:
                        post('think')
                        raise AssertionError('first script action did not inject 429')
                    except urllib.error.HTTPError as error:
                        assert error.code == 429
                        assert error.headers['Retry-After'] == '2'
                        assert error.headers['x-ratelimit-limit-req-minute'] == '60'
                    assert json.loads(json.loads(post('think')[1])['choices'][0]['message']['content'])['intend']
                    talk = json.loads(post('talk')[1])
                    assert json.loads(talk['choices'][0]['message']['content'])['say'] == 'scripted'
                    assert talk['usage']['prompt_tokens_details']['cached_tokens'] == 64
                    assert talk['usage']['prompt_tokens'] + talk['usage']['completion_tokens'] == talk['usage']['total_tokens']
                    assert post('consolidate')[1] == 'broken envelope'
                else:
                    for purpose in ('think', 'deliberate', 'consolidate', 'talk'):
                        envelope = json.loads(post(purpose)[1])
                        assert envelope['usage']['total_tokens'] == 17
                        content = envelope['choices'][0]['message']['content']
                        if scenario == 'malformed':
                            assert content == 'not JSON'
                        elif scenario == 'repair':
                            assert content.startswith('```json') and ',}' in content
                        else:
                            assert isinstance(json.loads(content), dict)
                entries = [json.loads(line) for line in log.read_text().splitlines()]
                assert entries and all(e['model'] == 'contract' and e['body_excerpt'] for e in entries)
                assert 'dummy-local-only' not in log.read_text(), 'authorization leaked into log'
                results.append({'scenario': scenario, 'pass': True, 'requests': len(entries), 'pid': process.pid})
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
                assert process.poll() is not None
    (directory / 'results.json').write_text(json.dumps(results, indent=2))
    print(f'{len(results)} fake scenarios passed; evidence kept in {directory}')


if __name__ == '__main__':
    main()
