#!/usr/bin/env python3
"""Opt-in: one minimal POST per keyed base URL in the real model configuration."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
from models_config import ROOT, models_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true', help='required after authorization for this paid run')
    parser.add_argument('--run', required=True, help='evidence name starting with llm-live-')
    parser.add_argument('--models', type=Path, default=None)
    args = parser.parse_args()
    if not args.allow_live:
        parser.error('live calls are disabled; authorization and --allow-live are required')
    if not re.fullmatch(r'llm-live-[A-Za-z0-9-]+', args.run):
        parser.error('--run must start with llm-live-')
    selected_models = models_path(args.models)
    config = json.loads(selected_models.read_text())
    directory = ROOT / '.local/living/verify' / args.run
    directory.mkdir(parents=True, exist_ok=False)
    seen = set()
    failures = 0
    for name, profile in sorted(config['profiles'].items()):
        base = profile['base_url'].rstrip('/')
        key = os.environ.get(profile['key_env'], '').strip()
        if not key or base in seen:
            continue
        seen.add(base)
        body = {'model': profile['model'], 'max_tokens': 64,
                'messages': [{'role': 'system', 'content': 'Return only a JSON object.'},
                             {'role': 'user', 'content': 'Reply with {"ok":true}.'}]}
        if profile.get('json_mode', True):
            body['response_format'] = {'type': 'json_object'}
        if profile.get('reasoning_effort', {}).get('think'):
            body['reasoning_effort'] = profile['reasoning_effort']['think']
        request = urllib.request.Request(base + '/chat/completions', json.dumps(body).encode(),
                          {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        started = time.monotonic()
        record = {'profile': name, 'base_url': base, 'model': profile['model'], 'request': body}
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.loads(response.read())
                record.update(status=response.status, reply=payload['choices'][0]['message']['content'],
                              tokens=payload.get('usage', {}).get('total_tokens'))
                content = record['reply']
                if isinstance(content, list):
                    content = ''.join(part.get('text', '') for part in content if part.get('type') == 'text')
                record['accepted'] = json.loads(content).get('ok') is True
                if not record['accepted']:
                    failures += 1
        except urllib.error.HTTPError as error:
            record.update(status=error.code, error='HTTP error')
            failures += 1
        except Exception as error:
            # Exception messages can contain credential-bearing URLs. Store the class only.
            record['error'] = type(error).__name__
            failures += 1
        record['latency_ms'] = int((time.monotonic() - started) * 1000)
        with (directory / 'live.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        print(f'{name}: {record.get("status", record.get("error"))}', flush=True)
    (directory / 'summary.json').write_text(json.dumps({'provider_endpoints_called': len(seen), 'failures': failures,
                         'max_tokens': 64, 'retries': 0, 'models': str(selected_models)}, indent=2))
    if not seen:
        sys.exit('no configured provider has an environment key')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
