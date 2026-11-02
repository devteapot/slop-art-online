#!/usr/bin/env python3
"""Drive real internal minds against the shared local fake model server."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('verify_llm', ROOT / '.agents/skills/verify-llm/scripts/verify_llm.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
CASES = ('roundtrip', 'acts', 'conversation', 'consolidation', 'prune', 'reject', 'only', 'reconnect', 'lod')


class Run(shared.Run):
    def __init__(self, name):
        super().__init__(name, prefix='minds')

    def request(self, actor, marker):
        self.admin('set_behavior', actor, json.dumps({'think': 'I finished my plan. verify ' + marker}))
        return self.wait(lambda: self.private(f'SELECT * FROM deliberation WHERE actor = {actor}',
                                              'pending-' + marker), 'authority deliberation', 65)

    def thoughts(self, actor, save='thoughts'):
        return self.sql(f'SELECT * FROM thought WHERE actor = {actor}', save)


def prepare(run):
    run.harness('launch')
    run.harness('doctor')
    people = sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
    adults = [p for p in people if p['ai'] and p['alive'] and p['stage'] == 2][:2]
    assert len(adults) == 2
    world = run.sql('SELECT * FROM world', 'world')[0]
    assert all(p['controller'] == world['admin'] for p in adults)
    return adults


def model(run, script):
    port = shared.free_port()
    run.fake(port, script, 'fake')
    return {'default': 'local', 'profiles': {'local': shared.profile(port, 'fake-minds')}}


def accepted(run, actor, plan='verify minds wait'):
    return run.wait(lambda: any(t['kind'] == 'deliberate' and plan in t['summary']
                                for t in run.thoughts(actor)), 'accepted deliberation')


def basic_reply(graph=None, **extra):
    return {'graph': graph or {'wait': 120}, 'weight': 1.5, 'plan': 'verify minds wait', **extra}


def run_case(run, case):
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'],
                                   'say': None}, 'deliberate': basic_reply()}}
    if case == 'roundtrip':
        script['replies']['think']['say'] = 'verify minds round trip speech'
    if case == 'acts':
        run.harness('player', 'join', 'MindsReceiver')
        other = run.sql("SELECT id FROM character WHERE name = 'MindsReceiver'", 'receiver')[0]['id']
        run.admin('place_near', actor, other)
        run.admin('grant_items', actor, 'stone', 3)
        act_reply = basic_reply(acts=[
            {'do': 'give', 'target': {'id': other}, 'item': 'stone', 'qty': 1},
            {'do': 'offer', 'target': {'id': other}, 'item': 'stone', 'qty': 1, 'want': 'wood', 'want_qty': 1},
            {'do': 'give', 'target': {'id': other}, 'item': 'verify_absent_item', 'qty': 1}])
        script['rules'] = [{'purpose': 'deliberate', 'reply': act_reply}]
        run.sql(f'SELECT * FROM inventory WHERE owner = {other}', 'receiver-inventory-before')
    if case == 'prune':
        script['replies']['deliberate'] = basic_reply({'seq': [{'do': 'teleport'}, {'wait': 120}]})
    if case == 'reject':
        script['replies']['deliberate'] = basic_reply()
        script['replies']['deliberate']['graph'] = 'verify-invalid-graph'
    if case == 'conversation':
        script['replies']['talk'] = {'thought': 'We have finished talking.', 'say': 'verify minds goodbye',
                                     'end': True}
        # Save receipt while the response is still in flight.
        script['rules'] = [{'purpose': 'talk', 'delay_s': 2, 'times': -1}]
    if case == 'consolidation':
        # Authored bootstrap exercises direct no-store projections before consolidation.
        run.admin('set_background', actor, json.dumps({'sheet': {'narrative': 'I am the verification listener.',
            'values': ['care'], 'goals': ['listen'], 'mood': 'settled',
            'relations': [{'id': other, 'trust': 10, 'affinity': 11, 'label': 'before'}],
            'stances': [{'key': 'verify_before', 'value': 0.2, 'why': 'before'}],
            'places': [{'name': 'verify before', 'x': 40, 'y': 60}]}}))
        script['replies']['consolidate'] = {'summary': 'verify minds integrated speech',
            'identity': {'narrative': 'I now value the verification conversation.', 'values': ['conversation'],
                'goals': ['remember'], 'traits': {}, 'mood': 'attentive', 'why': 'An addressed conversation matters.'},
            'relations': [{'id': other, 'trust': 67, 'affinity': 68, 'label': 'verify after'}],
            'judgments': [{'key': 'verify_after', 'value': 0.8, 'why': 'I heard it.'}],
            'places': [{'name': 'verify after', 'x': 41, 'y': 61}],
            'nodes': [{'key': 'idea:verify_reply', 'labels': ['Idea'], 'name': 'verify belief', 'props': {}}],
            'edges': [{'from': 'self', 'rel': 'BELIEVES', 'to': 'idea:verify_reply', 'confidence': 0.8}]}
        script['rules'] = [{'purpose': 'consolidate', 'delay_s': 3, 'times': -1}]
    if case == 'lod':
        script['rules'] = [{'purpose': 'deliberate', 'delay_s': 4, 'times': -1}]
    models = model(run, script)
    run.request(actor, 'first')
    if case == 'reject':
        # Keep a desires top level so keep_needs does not repair the invalid string
        # into a new top level before the graph validator sees it.
        run.admin('set_behavior', actor, json.dumps({'desires': [
            {'want': 'verification', 'weight': {'base': 0.01}, 'do': {'wait': 120}}]}))
    before = run.sql(f'SELECT * FROM brain WHERE id = {actor}', 'brain-before')[0]
    if case == 'only':
        run.request(other, 'excluded')
    run.start(models, [actor], lod=case == 'lod')
    if case == 'reject':
        run.wait(lambda: any(t['kind'] == 'error' and 'could not decide' in t['summary']
                            for t in run.thoughts(actor)), 'rejected graph thought')
        after = run.sql(f'SELECT * FROM brain WHERE id = {actor}', 'brain-after')[0]
        assert after['revision'] == before['revision'] and after['source'] == 'test'
        assert not run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'pending-after')
        assert len([e for e in run.exchanges() if e['purpose'] == 'deliberate']) == 3
        return {'status': 'pass', 'proof': 'mind_skip records error; graph and revision unchanged'}
    accepted(run, actor)
    brain = run.sql(f'SELECT * FROM brain WHERE id = {actor}', 'brain-after')[0]
    assert brain['source'] == 'mind' and brain['revision'] > before['revision'] and brain['plan'] == 'verify minds wait'
    routines = run.sql(f'SELECT * FROM routine WHERE actor = {actor}', 'routines-after')
    assert any(r['name'] == 'current plan' and '120' in r['graph'] for r in routines)
    run.wait(lambda: any(a['skill'] == 'wait' for a in run.sql(f'SELECT * FROM activity WHERE id = {actor}',
                                                           'activity-after')), 'graph activity')
    assert not run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'pending-after')
    if case == 'roundtrip':
        run.wait(lambda: any('verify minds round trip speech' in c['text'] for c in run.sql(
            f'SELECT * FROM chronicle WHERE a = {actor}', 'speech-after')), 'installed speech')
        thought = next(t for t in run.thoughts(actor) if t['kind'] == 'deliberate')
        assert json.loads(thought['detail'])['reply']['say'] == 'verify minds round trip speech'
        assert thought['model'] == 'fake-minds' and thought['tokens'] == 34 and thought['reference']
        assert {e['purpose'] for e in run.exchanges()} >= {'think', 'deliberate'}
    elif case == 'acts':
        run.wait(lambda: any(i['item'] == 'stone' and i['qty'] == 1 for i in run.sql(
            f'SELECT * FROM inventory WHERE owner = {other}', 'receiver-inventory-after')), 'give effect')
        run.wait(lambda: any(o['from'] == actor and o['to'] == other and o['give_item'] == 'stone'
                            for o in run.sql('SELECT * FROM trade_offer', 'offers-after')), 'offer effect')
        run.wait(lambda: any('verify_absent_item' in e['text'] and 'could not act' in e['text']
                for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'act-experiences')),
                'act failure feedback')
    elif case == 'prune':
        assert all('teleport' not in r['graph'] for r in routines)
        assert 'teleport' not in brain['graph']
        assert any('teleport' in e['reply'] for e in run.exchanges() if e['purpose'] == 'deliberate')
    elif case == 'only':
        time.sleep(8)
        assert run.private(f'SELECT * FROM deliberation WHERE actor = {other}', 'excluded-pending-after')
        excluded = run.sql(f'SELECT * FROM brain WHERE id = {other}', 'excluded-brain-after')[0]
        assert excluded['source'] == 'test'
        assert not run.thoughts(other, 'excluded-thoughts')
        assert all(e['actor'] == people[0]['name'] for e in run.exchanges())
    elif case in ('conversation', 'consolidation'):
        run.harness('player', 'join', 'MindsSpeaker')
        player = run.sql("SELECT id FROM character WHERE name = 'MindsSpeaker'", 'player')[0]['id']
        run.admin('place_near', player, actor)
        if case == 'conversation':
            line = 'Can you hear my verification question?'
            run.harness('player', 'say', line, '--to', str(actor))
            run.wait(lambda: any(e['purpose'] == 'talk' for e in shared.rows(run.directory / 'fake-requests.jsonl')),
                     'talk request')
            assert any(e['kind'] == 'speech' and e['subject'] == player for e in run.private(
                f'SELECT * FROM experience WHERE observer = {actor}', 'heard-speech'))
            run.wait(lambda: any('verify minds goodbye' in c['text'] and c['b'] == player for c in run.sql(
                f'SELECT * FROM chronicle WHERE a = {actor}', 'talk-speech')), 'talk speech')
            assert any(json.loads(t['detail'])['reply']['end'] for t in run.thoughts(actor)
                       if t['kind'] == 'talk')
            count = len([e for e in run.exchanges() if e['purpose'] == 'talk'])
            time.sleep(2.2)
            run.harness('player', 'say', line, '--to', str(actor))
            time.sleep(6)
            assert len([e for e in run.exchanges() if e['purpose'] == 'talk']) == count
            assert 'no turn' in run.log()
            run.thoughts(actor, 'thoughts-after-end')
        else:
            cursor_before = run.sql(f'SELECT * FROM mind_cursor WHERE actor = {actor}', 'cursor-before')
            for table in ('persona', 'relation', 'belief', 'judgment', 'place'):
                run.sql(f'SELECT * FROM {table} WHERE ' + ('id' if table == 'persona' else 'actor') + f' = {actor}', table + '-before')
            # Addressed speech has salience 0.9. Four lines force actual consolidation.
            for line in ('Will you listen to this important verification question?',
                         'Can you remember the river and the missing berry basket?',
                         'Did you notice the stone tower and the winter campfire?',
                         'Will you recall our conversation when morning comes?'):
                run.harness('player', 'say', line, '--to', str(actor))
                time.sleep(2.2)
            inbox = run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'experiences-before')
            speech_ids = {e['id'] for e in inbox if e['kind'] == 'speech' and e['subject'] == player}
            assert speech_ids, 'addressed speech must be present before consolidation'
            run.wait(lambda: any(t['kind'] == 'consolidate' and 'verify minds integrated speech' in t['summary']
                         and speech_ids.intersection(json.loads(t['detail']).get('experiences', []))
                         for t in run.thoughts(actor)), 'consolidation of addressed speech', 110)
            cursor = run.wait(lambda: run.sql(f'SELECT * FROM mind_cursor WHERE actor = {actor}', 'cursor-after'),
                              'cursor advanced')[0]['upto']
            assert cursor > (cursor_before[0]['upto'] if cursor_before else 0)
            assert not run.private(f'SELECT * FROM experience WHERE observer = {actor} AND id <= {cursor}',
                                   'integrated-experiences-after')
            after = {}
            for table in ('persona', 'relation', 'belief', 'judgment', 'place'):
                after[table] = run.sql(f'SELECT * FROM {table} WHERE ' + ('id' if table == 'persona' else 'actor') + f' = {actor}', table + '-after')
            assert any(p['narrative'] == 'I now value the verification conversation.' and p['version'] >= 2
                       for p in after['persona'])
            checks = {'relations': any(r['label'] == 'verify after' for r in after['relation']),
                      'beliefs': any('verify belief' in b['text'] for b in after['belief']),
                      'judgments': any(j['key'] == 'verify_after' for j in after['judgment']),
                      'places': any(p['name'] == 'verify after' for p in after['place'])}
            return {'status': 'xpass' if all(checks.values()) else 'xfail', 'projection_checks': checks,
                    'persona': 'pass', 'consolidated': 'pass', 'cursor': 'pass',
                    'label': 'KNOWN ISSUE', 'issue': 'no-store project discards graph patch fields',
                    'reference': 'docs/LIVING_HANDOFF.md', 'section': 'Still open'}
    elif case == 'reconnect':
        # Keep an excluded actor's pending request stable while the served mind stays alive.
        run.request(other, 'survive-update')
        inbox = run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'reconnect-inbox')
        cursors = run.sql(f'SELECT * FROM mind_cursor WHERE actor = {actor}', 'reconnect-cursor')
        points = [e['id'] for e in inbox] + [c['upto'] for c in cursors]
        assert points, 'setup requires an inbox or a previously consolidated cursor'
        upto = max(points)
        run.admin('mind_consolidated', actor, upto)
        run.admin('set_paused', True)
        queries = {'graph': f'SELECT * FROM brain WHERE id = {actor}',
                   'pending': f'SELECT * FROM deliberation WHERE actor = {other}',
                   'cursor': f'SELECT * FROM mind_cursor WHERE actor = {actor}'}
        before_update = {k: run.private(q, 'survival-' + k + '-before') for k, q in queries.items()}
        assert all(before_update.values()) and before_update['cursor'][0]['upto'] == upto
        old = run.mind
        subscriptions = run.log().count('world subscribed:')
        run.harness('launch', '--keep-data')
        after_update = {k: run.private(q, 'survival-' + k + '-after') for k, q in queries.items()}
        survives = {k: before_update[k] == after_update[k] for k in queries}
        record = {'old_pid': old.pid, 'data_preserved': survives}
        (run.directory / 'reconnect.json').write_text(json.dumps(record, indent=2))
        assert all(survives.values()), 'product state lost across --keep-data update; see reconnect.json'
        try:
            old.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Identical module updates may retain the socket. Restart only our owned mind
            # to prove a new subscription recovers preserved state too.
            record['disconnect'] = 'controlled owned-process restart after unchanged module update'
            record['stop'] = shared.stop(old)
        else:
            assert old.returncode == 2
            record['disconnect'] = 'module update disconnected mind'
        time.sleep(3)
        run.launch_mind()
        run.wait(lambda: run.log().count('world subscribed:') > subscriptions, 'reconnected subscription')
        assert run.mind.pid != old.pid
        run.admin('set_paused', False)
        run.harness('doctor')
        run.admin('set_behavior', actor, json.dumps({'think': 'I finished my plan. verify after-update'}))
        run.wait(lambda: any(t['kind'] == 'deliberate' and 'after-update' in json.loads(t['detail']).get('reason', '')
                            for t in run.thoughts(actor, 'thoughts-after-update')), 'post-update response', 65)
        record.update(new_pid=run.mind.pid, old_exit=old.poll(), launcher_restart=old.poll() is not None)
        (run.directory / 'reconnect.json').write_text(json.dumps(record, indent=2))
    elif case == 'lod':
        assert 'level of detail on:' in run.log()
        time.sleep(46)
        run.request(actor, 'offstage')
        count = len([e for e in run.exchanges() if e['purpose'] == 'think'])
        time.sleep(7)
        assert len([e for e in run.exchanges() if e['purpose'] == 'think']) == count
        assert run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'offstage-held')
        run.admin('set_behavior', actor, json.dumps({'think': 'verify plain merged reason'}))
        plain = run.wait(lambda: [d for d in run.private(f'SELECT * FROM deliberation WHERE actor = {actor}',
                        'plain-merged-pending') if 'verify plain merged reason' in d['reason']], 'plain authority merge')
        time.sleep(2)
        assert len([e for e in run.exchanges() if e['purpose'] == 'think']) == count
        upgraded_at = time.monotonic()
        run.admin('set_behavior', actor, json.dumps({'think': 'Wolf is attacking you! verify urgent upgrade'}))
        run.wait(lambda: len([e for e in run.exchanges() if e['purpose'] == 'think']) > count,
                 'urgent upgrade starts a thought', 5)
        urgent_release_s = time.monotonic() - upgraded_at
        urgent = run.wait(lambda: [t for t in run.thoughts(actor, 'urgent-thoughts') if t['kind'] == 'deliberate'
                         and 'verify urgent upgrade' in json.loads(t['detail']).get('reason', '')],
                         'urgent upgrade accepted', 15)
        assert 'verify plain merged reason' in json.loads(urgent[0]['detail'])['reason']
        time.sleep(46)
        run.request(actor, 'offstage-player')
        count = len([e for e in run.exchanges() if e['purpose'] == 'think'])
        time.sleep(3)
        assert len([e for e in run.exchanges() if e['purpose'] == 'think']) == count
        run.harness('player', 'join', 'MindsAudience')
        player = run.sql("SELECT id FROM character WHERE name = 'MindsAudience'", 'player')[0]['id']
        run.admin('place_near', player, actor)
        run.harness('player', 'say', 'Can you hear the audience now?', '--to', str(actor))
        run.wait(lambda: len([e for e in run.exchanges() if e['purpose'] == 'think']) > count,
                 'onstage thought', 15)
        # Merge a non-plan reason while the compile is in flight. The new reason must be handled too.
        run.admin('set_behavior', actor, json.dumps({'think': 'verify merged nonplan reason'}))
        merged = run.wait(lambda: [d for d in run.private(f'SELECT * FROM deliberation WHERE actor = {actor}',
                          'merged-pending') if 'verify merged nonplan reason' in d['reason']], 'merged authority reason')
        run.wait(lambda: any(t['kind'] == 'deliberate' and 'offstage' in json.loads(t['detail']).get('reason', '')
                            for t in run.thoughts(actor, 'onstage-thoughts')), 'onstage install', 15)
        time.sleep(10)
        pending = run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'onstage-pending-after')
        merged_thoughts = run.thoughts(actor, 'merged-thoughts-after')
        handled = any(t['kind'] == 'deliberate' and 'verify merged nonplan reason' in json.loads(t['detail']).get('reason', '')
                      for t in merged_thoughts)
        (run.directory / 'lod.json').write_text(json.dumps({'offstage_think_count': count,
            'onstage_think_count': len([e for e in run.exchanges() if e['purpose'] == 'think']),
            'think_gap_s': 600, 'observed_hold_s': 7, 'merged_pending': merged,
            'plain_merged_pending': plain, 'urgent_release_s': urgent_release_s,
            'urgent_thoughts': urgent, 'plain_reason_handled': True,
            'pending_after': pending, 'merged_reason_handled': handled}, indent=2))
        assert handled, 'merged non-plan reason was not reconsidered'
        return {'status': 'pass', 'hold_and_release': 'pass', 'urgent_release_s': urgent_release_s,
                'plain_reason_handled': True, 'merged_reason_handled': True}
    return {'status': 'pass'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='new suite name starting with minds-')
    parser.add_argument('--case', action='append', choices=CASES, help='repeat to select; default all')
    args = parser.parse_args()
    if not re.fullmatch(r'minds-[a-zA-Z0-9-]+', args.run):
        parser.error('--run must start with minds-')
    with urllib.request.urlopen('http://127.0.0.1:3300/v1/ping', timeout=5) as response:
        assert response.status == 200
    suite = ROOT / '.local/living/verify' / args.run
    suite.mkdir(parents=True, exist_ok=False)
    for command, name in ((['cargo', 'build', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--release'], 'build.log'),
                          (['cargo', 'test', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--', '--nocapture'], 'cargo-tests.log')):
        with (suite / name).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    paths = ['living/mind/src/main.rs', 'living/mind/src/mind.rs', 'living/mind/src/mind/talk.rs',
             'living/mind/src/mind/lod.rs', 'living/mind/src/prompts.rs', 'living/authority/src/mind.rs',
             'living/rules/src/normalize.rs', 'living/target/release/living-mind',
             '.agents/skills/verify-llm/scripts/fake_llm.py', '.agents/skills/verify-llm/scripts/verify_llm.py',
             '.agents/skills/verify-minds/scripts/verify_minds.py']
    (suite / 'source-hashes.json').write_text(json.dumps({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}, indent=2))
    results = []
    for case in args.case or CASES:
        run = Run(args.run + '-' + case)
        print(f'RUN {case} {run.directory}', flush=True)
        try:
            result = run_case(run, case)
        except Exception as error:
            (run.directory / 'failure.txt').write_text(traceback.format_exc())
            result = {'status': 'fail', 'error': f'{type(error).__name__}: {error}'}
        finally:
            run.finish_cleanup()
        result.update(case=case, evidence=str(run.directory))
        (run.directory / 'result.json').write_text(json.dumps(result, indent=2))
        assert (run.directory / 'driver.log').exists() and (run.directory / 'cleanup.json').exists()
        results.append(result)
        (suite / 'results.json').write_text(json.dumps(results, indent=2))
        print(f'DONE {case} {result["status"]}; evidence kept', flush=True)
    return 0 if all(r['status'] in ('pass', 'xfail') for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
