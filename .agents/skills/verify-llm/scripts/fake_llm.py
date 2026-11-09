#!/usr/bin/env python3
"""Local OpenAI-compatible scripted server. See references/fake-llm.md."""
import argparse
import copy
import json
import re
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PURPOSES = ('think', 'deliberate', 'consolidate', 'talk', 'internalize')
SPEECH = 'verify fake: I will wait here.'
REPLIES = {
    'think': {'thought': 'I can wait here.', 'intend': ['wait briefly'],
              'say': {'text': SPEECH, 'to': None}, 'judgments': [], 'places': []},
    'deliberate': {'thought': 'I can wait here.', 'plan': 'verify fake wait',
                   'graph': {'wait': 2}, 'say': {'text': SPEECH, 'to': None}, 'acts': []},
    'consolidate': {'summary': 'I remember this moment.', 'remember': [],
                    'nodes': [], 'edges': [], 'retract': [], 'merge': [], 'identity': None,
                    'relations': [], 'judgments': [], 'places': [],
                    'narrative': 'I live here and watch what happens.', 'values': [],
                    'goals': [], 'traits': {'curiosity': 50, 'sociability': 50}, 'mood': 'settled'},
    'talk': {'thought': 'I heard you.', 'say': 'verify fake: I heard you.',
             'to': 0, 'acts': [], 'end': True, 'settled': 'We have spoken.'},
    'internalize': {'summary': 'I lived through this.', 'remember': [], 'nodes': [], 'edges': [],
                    'retract': [], 'merge': [], 'relations': [], 'judgments': [], 'places': []},
}


def cite(value, body):
    """Fill `$EXP:<word>` and `$PERSON` placeholders from the experience lines the request
    carried (`- [id] time text {Name=#id}`): `$EXP:<word>` becomes the id of the first line
    whose text contains <word> (0 if none), `$EXPS` all ids, `$PERSON` `person:<id>` of the
    first person tagged, `$PERSON_ID` that id."""
    user = '\n'.join(m.get('content', '') for m in body.get('messages', []) if m.get('role') == 'user')
    lines = re.findall(r'^- \[(\d+)\] (.*)$', user, re.M)
    people = re.findall(r'=#(\d+)', user)

    def fill(v):
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fill(x) for x in v]
        if v == '$EXPS':
            return [int(i) for i, _ in lines]
        if v == '$PERSON':
            return f'person:{people[0]}' if people else 'person:0'
        if v == '$PERSON_ID':
            return int(people[0]) if people else 0
        if isinstance(v, str) and v.startswith('$EXP:'):
            word = v[5:].lower()
            return next((int(i) for i, t in lines if word in t.lower()), 0)
        return v
    return fill(value)


def purpose_of(body):
    effort = body.get('reasoning_effort')
    if effort in PURPOSES:
        return effort
    system = '\n'.join(m.get('content', '') for m in body.get('messages', []) if m.get('role') == 'system')
    if 'This is your turn in a conversation' in system:
        return 'talk'
    if 'someone you cannot see' in system:
        return 'internalize'
    if 'already decided what to do' in system or 'what the impulse makes it do' in system:
        return 'deliberate'
    if 'starting identity' in system or '"remember"' in system or '"merge"' in system or '"summary"' in system:
        return 'consolidate'
    return 'think'


def valid_reply(purpose, body):
    value = copy.deepcopy(REPLIES[purpose])
    system = '\n'.join(m.get('content', '') for m in body.get('messages', []) if m.get('role') == 'system')
    if purpose == 'talk':
        match = re.search(r'face to face with .*?\(#(\d+)\)', system)
        if match:
            value['to'] = int(match[1])
    if purpose == 'think':
        value.update(feeling='calm', impulse='wait')
    return value


class Script:
    def __init__(self, data, log):
        self.data = data
        self.rules = copy.deepcopy(data.get('rules', []))
        self.lock = threading.Lock()
        self.log = log
        self.sequence = 0

    def receive(self, body, batch_job=None):
        purpose = purpose_of(body)
        with self.lock:
            self.sequence += 1
            action = dict(self.data.get('defaults', {}))
            for rule in self.rules:
                if (rule.get('purpose', purpose) == purpose
                        and rule.get('model', body.get('model')) == body.get('model')
                        and rule.get('times', 1) != 0):
                    action.update(rule)
                    if rule.get('times', 1) > 0:
                        rule['times'] = rule.get('times', 1) - 1
                    break
            reply = action.get('reply', self.data.get('replies', {}).get(purpose, valid_reply(purpose, body)))
            if action.get('cite'):
                reply = cite(reply, body)
            content = action.get('content', json.dumps(reply))
            if action.get('repair'):
                content = '```json\n' + json.dumps(reply)[:-1] + ',}\n```'
            if action.get('content_parts'):
                content = [{'type': 'thinking', 'text': 'ignored'}, {'type': 'text', 'text': content}]
            record = {'at_ms': int(time.time() * 1000), 'sequence': self.sequence,
                      'purpose': purpose, 'model': body.get('model'),
                      'reasoning_effort': body.get('reasoning_effort'),
                      'body_excerpt': json.dumps(body)[:2000], 'body': body,
                      'status': action.get('status', 200), 'delay_s': action.get('delay_s', 0),
                      'close_port': action.get('close_port', False), 'content': content,
                      'batch_job': batch_job}
            with self.log.open('a') as stream:
                stream.write(json.dumps(record) + '\n')
        return action, content


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        jobs = self.server.jobs
        m = re.fullmatch(r'/v1/batch/jobs/([\w-]+)', self.path)
        if m and m[1] in jobs:
            job = jobs[m[1]]
            # A job is QUEUED for its first poll, then RUNNING, then SUCCESS.
            job['polls'] += 1
            status = 'QUEUED' if job['polls'] == 1 else 'RUNNING' if job['polls'] == 2 else 'SUCCESS'
            view = {'id': m[1], 'object': 'batch', 'status': status, 'model': job['model'],
                    'endpoint': job['endpoint'], 'total_requests': len(job['lines']),
                    'output_file': m[1] + '-out' if status == 'SUCCESS' else None, 'error_file': None}
            return self.respond(200, json.dumps(view).encode())
        m = re.fullmatch(r'/v1/files/([\w-]+)-out/content', self.path)
        if m and m[1] in jobs:
            return self.respond(200, '\n'.join(json.dumps(x) for x in jobs[m[1]]['lines']).encode())
        self.respond(200 if self.path == '/health' else 404, b'{"ready":true}')

    def respond(self, status, data, headers=None):
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, str(value))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def batch(self, body):
        """Mistral-shaped batch job with inline `requests`: each is answered like a direct
        request (same script, same log, `batch_job` recorded) and kept for the output file."""
        jid = f'job-{len(self.server.jobs) + 1}'
        lines = []
        for r in body.get('requests', []):
            req = dict(r.get('body', {}))
            req.setdefault('model', body.get('model'))
            action, content = self.server.script.receive(req, batch_job=jid)
            usage = action.get('usage', {'total_tokens': int(action.get('tokens', 17)), 'prompt_tokens': 12,
                                         'completion_tokens': 5, 'prompt_tokens_details': {'cached_tokens': 8}})
            lines.append({'id': f'{jid}-{len(lines)}', 'custom_id': r.get('custom_id'),
                          'response': {'status_code': 200, 'body': {'id': 'verify-local', 'object': 'chat.completion',
                                       'choices': [{'message': {'role': 'assistant', 'content': content}}], 'usage': usage}},
                          'error': None})
        self.server.jobs[jid] = {'model': body.get('model'), 'endpoint': body.get('endpoint'), 'lines': lines, 'polls': 0}
        self.respond(200, json.dumps({'id': jid, 'object': 'batch', 'status': 'QUEUED'}).encode())

    def do_POST(self):
        if self.path in ('/v1/batch/jobs',) or re.fullmatch(r'/v1/batch/jobs/[\w-]+/cancel', self.path):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            except ValueError:
                return self.respond(400, b'{"error":"invalid JSON body"}')
            if self.path == '/v1/batch/jobs':
                return self.batch(body)
            return self.respond(200, b'{"status":"CANCELLATION_REQUESTED"}')
        if self.path != '/v1/chat/completions':
            return self.respond(404, b'{}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if not isinstance(body, dict):
                raise ValueError('request must be an object')
        except (ValueError, TypeError):
            return self.respond(400, b'{"error":"invalid JSON body"}')
        action, content = self.server.script.receive(body)
        if action.get('close_port'):
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        time.sleep(max(0, float(action.get('delay_s', 0))))
        status = int(action.get('status', 200))
        envelope = {'id': 'verify-local', 'object': 'chat.completion',
                    'choices': [{'message': {'role': 'assistant', 'content': content}}],
                    'usage': action.get('usage', {'total_tokens': int(action.get('tokens', 17)),
                              'prompt_tokens': 12, 'completion_tokens': 5,
                              'prompt_tokens_details': {'cached_tokens': 8}})}
        payload = action.get('raw_http_body', json.dumps(envelope) if status == 200 else json.dumps({'error': 'scripted failure'}))
        self.respond(status, payload.encode(), action.get('headers'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--script', type=Path)
    parser.add_argument('--scenario', choices=['valid', '429', '500', 'malformed', 'repair', 'delay', 'timeout', 'outage'], default='valid')
    parser.add_argument('--delay-s', type=float, default=1)
    args = parser.parse_args()
    scenarios = {'valid': {}, '429': {'status': 429}, '500': {'status': 500},
                 'malformed': {'content': 'not JSON'}, 'repair': {'repair': True},
                 'delay': {'delay_s': args.delay_s}, 'timeout': {'delay_s': 185},
                 'outage': {'close_port': True}}
    data = json.loads(args.script.read_text()) if args.script else {'defaults': scenarios[args.scenario]}
    args.log.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.script = Script(data, args.log)
    server.jobs = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f'READY http://127.0.0.1:{server.server_port}/v1 pid={__import__("os").getpid()}', flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
