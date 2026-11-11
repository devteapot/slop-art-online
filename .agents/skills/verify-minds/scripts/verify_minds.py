#!/usr/bin/env python3
"""Drive real internal minds against the shared local fake model server."""
import argparse
import hashlib
import importlib.util
import json
import math
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
CASES = ('roundtrip', 'acts', 'conversation', 'consolidation', 'prune', 'reject', 'only', 'reconnect', 'lod',
         'takeover', 'sight', 'resident', 'animals', 'night', 'jev', 'rethink', 'rethink-llm', 'dealings', 'parked',
         'death-names', 'speech')
OPAQUE = {4, 7}             # rock, wall (living_rules::map::Terrain); a drop (8) and a low thing (9) are see-through
UNWALKABLE = {2, 4, 7, 8, 9}  # water, rock, wall, drop, low


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


def terrain(run):
    """The map's tiles from `terrain_chunk` (public)."""
    world = run.sql('SELECT width, height FROM world', 'world-size')[0]
    w, h = world['width'], world['height']
    tiles = bytearray(w * h)
    for row in run.sql('SELECT * FROM terrain_chunk', 'terrain'):
        data = row['tiles']
        data = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
        cx, cy = row['id'] & 0xFFFF, row['id'] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < w and y < h:
                tiles[y * w + x] = t
    return w, h, tiles


def wall_spots(run):
    """Two walkable tiles at most 4 apart on one axis with only rock or wall between (within
    even night sight), and a third walkable tile 3 tiles from the first in the open."""
    w, h, tiles = terrain(run)
    at = lambda x, y: tiles[y * w + x] if 0 <= x < w and 0 <= y < h else 4
    walk = lambda x, y: at(x, y) not in UNWALKABLE
    for y in range(4, h - 4):
        for x in range(4, w - 4):
            if not walk(x, y):
                continue
            for dx, dy in [(1, 0), (0, 1)]:
                for gap in (1, 2, 3):
                    bx, by = x + (gap + 1) * dx, y + (gap + 1) * dy
                    if walk(bx, by) and all(at(x + i * dx, y + i * dy) in OPAQUE for i in range(1, gap + 1)):
                        # The open witness: 3 tiles the other way along the axis, nothing opaque between.
                        ox, oy = x - 3 * dx, y - 3 * dy
                        if all(walk(x - i * dx, y - i * dy) for i in range(1, 4)):
                            return {'eye': (x + .5, y + .5), 'hidden': (bx + .5, by + .5), 'open': (ox + .5, oy + .5)}
    raise RuntimeError('no wall geometry on this map')


def run_case(run, case):
    if case in ('animals', 'night', 'jev'):
        return {'animals': animals_case, 'night': night_case, 'jev': jev_case}[case](run)
    if case in ('rethink', 'rethink-llm'):
        return rethink_case(run, 'jev' if case == 'rethink' else 'llm')
    if case == 'takeover':
        return takeover_case(run)
    if case == 'dealings':
        return dealings_case(run)
    if case == 'sight':
        return sight_case(run)
    if case == 'death-names':
        return death_names_case(run)
    if case == 'resident':
        return resident_case(run)
    if case == 'parked':
        return parked_case(run)
    if case == 'speech':
        return speech_case(run)
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
        # A thing the scene lists by id is a target like a creature (feedback-1): a gather aimed
        # at a resource id in sight goes ahead instead of "no #N in sight".
        me = run.private(f'SELECT * FROM body WHERE id = {actor}', 'actor-body')[0]
        near = run.sql(f"SELECT * FROM resource_node WHERE x > {me['x'] - 6} AND x < {me['x'] + 6} AND y > {me['y'] - 6} AND y < {me['y'] + 6}", 'resources-near')
        rid = min(near, key=lambda n: (n['x'] - me['x']) ** 2 + (n['y'] - me['y']) ** 2)['id'] if near else None
        act_reply = basic_reply(acts=([{'do': 'gather', 'target': {'id': rid}}] if rid else []) + [
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
        # The body as felt, from the vitals the service subscribes to (owner path): in words, no numbers.
        sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
        felt = [m.split('How your body feels: ', 1)[1].split('\n', 1)[0] for e in sent for m in [json.dumps(e, ensure_ascii=False).replace('\\n', '\n')] if 'How your body feels: ' in m]
        assert felt and not any(ch.isdigit() for ch in felt[0]), felt[:2]
        # The world's rules are told from the laws' own descriptions (docs/WORLD_RULES.md, since
        # laws-2): the sections and the numbers the script's laws give, the same in every prompt.
        told = [json.dumps(e, ensure_ascii=False).replace('\\n', '\n') for e in sent]
        for part in ('SENSES: How far a creature sees and hears, in metres (one tile is one metre). By day one sees 11 m',
                     'MOVING: How creatures move', 'FOOD: berries 12, fish 16', 'SETTLEMENTS: walls block the way'):
            assert all(part in m for m in told), part
    elif case == 'acts':
        run.wait(lambda: any(i['item'] == 'stone' and i['qty'] == 1 for i in run.sql(
            f'SELECT * FROM inventory WHERE owner = {other}', 'receiver-inventory-after')), 'give effect')
        run.wait(lambda: any(o['from'] == actor and o['to'] == other and o['give_item'] == 'stone'
                            for o in run.sql('SELECT * FROM trade_offer', 'offers-after')), 'offer effect')
        run.wait(lambda: any('verify_absent_item' in e['text'] and 'could not act' in e['text']
                for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'act-experiences')),
                'act failure feedback')
        if rid:
            told = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'id-target-experiences')
                                     if 'decided: gather' in e['text'] or 'did not work out: gather' in e['text'] or f'#{rid}' in e['text']],
                              'outcome of the act at a resource id', 90)
            # A resolved target is labelled by its kind ("gather → boulder (+1 stone)").
            assert not any(f'no #{rid} in sight' in e['text'] for e in told), [e['text'] for e in told]
            assert any('You did what you had decided: gather' in e['text'] for e in told), [e['text'] for e in told]
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
            # The turn offers every act the rules mark for conversation: host among the examples
            # (prompts::TALK_SHOWN skips listing it), so a resident can take someone in while talking.
            talk_sent = next(e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'talk')
            talk_text = json.dumps(talk_sent, ensure_ascii=False).replace('\\"', '"')
            assert '"do": "host"' in talk_text, 'the talk turn does not offer host'
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


def takeover_case(run):
    """A player's character passes to the minds when its person has been gone for the
    `takeover_s` law, is thought for like any AI character, and comes back to its person at
    once: the minds' plan stops, their graph is kept for the next takeover and not run, and a
    reply still in flight is refused."""
    prepare(run)
    world = run.sql('SELECT * FROM world', 'world')[0]
    run.harness('player', 'join', 'MindsAway')
    me = run.sql("SELECT id FROM character WHERE name = 'MindsAway'", 'player')[0]['id']
    script = {'replies': {'think': {'thought': 'Alone now, I wait.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply()},
              # Replies take 8 s, so one can still be in flight when the person returns.
              'rules': [{'purpose': 'deliberate', 'delay_s': 8, 'times': -1}]}
    models = model(run, script)
    run.start(models, [me])
    # The join was an HTTP call: its connection is closed, so a takeover is pending.
    pending = run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-joined')[0]
    assert not pending['present'] and not pending['ai'] and pending['takeover_ms'] < 2**63, pending
    taken = run.wait(lambda: [p for p in run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-taken') if p['ai']], 'takeover', 50)[0]
    char = run.sql(f'SELECT * FROM character WHERE id = {me}', 'character-taken')[0]
    assert char['ai'] and char['controller'] == world['admin'], char
    accepted(run, me)
    brain = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-taken')[0]
    assert brain['source'] == 'mind' and brain['plan'] == 'verify minds wait', brain
    installed = brain['graph']
    lived = run.private(f'SELECT * FROM experience WHERE observer = {me}', 'experiences-taken')
    # Back: the person's next call hands it back before it runs.
    run.harness('player', 'move', '1', '0')
    back = run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-back')[0]
    char = run.sql(f'SELECT * FROM character WHERE id = {me}', 'character-back')[0]
    brain = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-back')[0]
    assert not back['ai'] and not char['ai'] and char['controller'] != world['admin'], (back, char)
    assert brain['source'] == 'human', brain
    # The minds' graph (their desires top level; the plan's wait is the "current plan" routine).
    assert back['ai_graph'] == installed and back['ai_plan'] == 'verify minds wait', back
    assert not run.private(f'SELECT * FROM deliberation WHERE actor = {me}', 'pending-back')
    assert not run.private(f'SELECT * FROM act_queue WHERE actor = {me}', 'acts-back')
    kept = run.private(f'SELECT * FROM experience WHERE observer = {me}', 'experiences-back')
    assert {e['id'] for e in lived} <= {e['id'] for e in kept}, 'experiences lived under the minds must stay'
    # Away again: the held graph is installed again; then a reply in flight is refused on return.
    run.wait(lambda: [p for p in run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-taken-2') if p['ai']], 'second takeover', 50)
    again = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-taken-2')[0]
    assert again['source'] == 'mind' and again['plan'] == 'verify minds wait' and again['graph'] == installed, again
    run.admin('set_behavior', me, json.dumps({'think': 'I finished my plan. verify in flight'}))
    run.wait(lambda: any(e['purpose'] == 'deliberate' for e in shared.rows(run.directory / 'fake-requests.jsonl')
                         if 'in flight' in json.dumps(e)), 'deliberation in flight', 40)
    run.harness('player', 'move', '0', '1')
    run.wait(lambda: 'not your character' in run.log(), 'in-flight reply refused', 30)
    final = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-final')[0]
    assert final['source'] == 'human', final
    return {'status': 'pass', 'takeover_after_s': (taken['control_ms'] - pending['changed_ms']) / 1000,
            'held_graph': 'kept and reinstalled', 'in_flight': 'refused'}


def dealings_case(run):
    """A mind sees and acts on a record (docs/WORLD_RULES.md): another character demands a stone
    of it; the rules tell it and ask its mind; its deliberation shows the demand among its
    dealings (worded by the script's `record_text`), and the (fake) model's act pays it, which
    the rules count: the demand is met and the demander told. Its conversation turns list the
    acts the rules mark for talk (offer_terms, demand)."""
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    run.admin('place_near', other, actor)
    run.admin('grant_items', actor, 'stone', 2)
    pay = basic_reply(acts=[{'do': 'give', 'target': {'id': other}, 'item': 'stone', 'qty': 1}])
    script = {'replies': {'think': {'thought': 'I am asked for a stone.', 'intend': ['give them the stone'], 'say': None},
                          'deliberate': basic_reply()},
              'rules': [{'purpose': 'deliberate', 'contains': 'demanded 1 stone (\\"verify dealing\\") of you', 'reply': pay, 'times': -1}]}
    models = model(run, script)
    run.start(models, [actor])
    accepted_before = len(run.thoughts(actor))
    # The demander is held still (its own instinct graph could keep its body busy) and acts as its
    # mind would decide.
    run.admin('set_behavior', other, json.dumps({'wait': 120}))
    run.admin('mind_act', other, [json.dumps({'do': 'demand', 'target': {'id': actor}, 'item': 'stone', 'qty': 1, 'text': 'verify dealing'})], 'verify-minds')
    demand = run.wait(lambda: [r for r in run.private('SELECT * FROM record', 'records-demand') if r['kind'] == 'demand'], 'demand record', 60)[0]
    run.private(f'SELECT * FROM experience WHERE observer = {other}', 'demander-experiences')
    told = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'told') if e['kind'] == 'record' and 'demands 1 stone of you' in e['text']], 'told the demand', 30)
    # The rules' `ask` goes through the authority's thinking cadence (`think_min_s`): a mind that
    # thought moments ago is not asked again. Its next thought sees the demand among its dealings.
    asked = bool(run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'asked'))
    if not asked:
        run.request(actor, 'dealing')
    met = run.wait(lambda: [r for r in run.private('SELECT * FROM record', 'records-met') if r['id'] == demand['id'] and r['status'] == 'met'], 'demand met', 90)
    sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'deliberate']
    shown = [e for e in sent if "Your dealings and your people's standing" in json.dumps(e) and 'demanded 1 stone' in json.dumps(e)]
    assert shown, 'the deliberation showed the demand among its dealings'
    paid = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {other}', 'demander-told') if 'paid the 1 stone you demanded' in e['text']], 'demander told', 30)
    inv = {r['item']: r['qty'] for r in run.sql(f'SELECT * FROM inventory WHERE owner = {other}', 'demander-inventory')}
    assert inv.get('stone') == 1, inv
    return {'status': 'pass', 'told': told[0]['text'], 'record': met[0]['status'], 'demander_told': paid[0]['text'],
            'deliberations_with_dealings': len(shown), 'thoughts_before': accepted_before, 'asked_by_the_rules': asked}


def sight_case(run):
    """A mind's scene and what it witnesses follow the sight rule: a creature behind rock or a
    wall is not in the scene the model is sent, and its death is not witnessed; one in the open
    is, and its death is."""
    people = prepare(run)
    eye, other = [p['id'] for p in people]
    third = next(p['id'] for p in run.sql("SELECT * FROM character WHERE kind = 'person'", 'people-all')
                 if p['ai'] and p['alive'] and p['stage'] == 2 and p['id'] not in (eye, other))
    spots = wall_spots(run)
    (run.directory / 'sight.json').write_text(json.dumps(spots, indent=2))
    for who in (eye, other, third):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    run.admin('place_at', eye, *spots['eye'])
    run.admin('place_at', other, *spots['hidden'])
    run.admin('place_at', third, *spots['open'])
    time.sleep(1.0)
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    models = model(run, script)
    pending = run.request(eye, 'sight')
    run.start(models, [eye])
    request = run.wait(lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')], 'scene sent to the model', 40)[0]
    sent = '\n'.join(str(m.get('content', '')) for m in request['body'].get('messages', []))
    (run.directory / 'sent-prompt.txt').write_text(sent)
    mentions = lambda id: re.search(r'"id":\s*%d\b' % id, sent) is not None
    names = {p['id']: p['name'] for p in run.sql('SELECT id, name FROM character', 'names')}
    scene = json.loads(pending[0]['scene']) if pending else None
    ids = [c['id'] for c in scene['creatures']] if scene else None
    assert ids is None or (third in ids and other not in ids), ids
    assert mentions(third) and not mentions(other), 'the model must be sent the creature in the open and not the hidden one'
    # Deaths: behind the wall unseen, in the open witnessed.
    since = max([e['id'] for e in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'before-deaths')] + [0])
    run.admin('kill', other, 'verify hidden death')
    run.admin('kill', third, 'verify open death')
    time.sleep(1.0)
    after = [e for e in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'after-deaths') if e['id'] > since]
    deaths = [e for e in after if e['kind'] == 'death']
    assert any(e['subject'] == third for e in deaths) and not any(e['subject'] == other for e in deaths), deaths
    return {'status': 'pass', 'scene_ids': ids, 'witnessed': [e['text'] for e in deaths],
            'hidden': names.get(other), 'open': names.get(third)}


def death_names_case(run):
    """A community member killed in view of a mind's character, who shares the community and
    feels something for them: the experience the authority gives that mind names the dead, and
    the next prompt the model is sent names them in what happened and in the relations, not as
    "a stranger" (`die` keeps the community's names as acquaintances, `perception::remember_member`;
    the mind's `known_as` reads them). The killer's experience reads "killed by you"; a bystander
    who knew neither reads strangers."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 4, True)
    made = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    assert len(made) == 4, made
    victim, member, killer, bystander = made
    names = {c['id']: c['name'] for c in run.sql('SELECT id, name FROM character', 'names')}
    vname = names[victim]
    for who in made:
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    act = lambda who, node: run.admin('mind_act', who, [json.dumps(node)], 'verify-minds')
    run.admin('place_near', member, victim)
    act(victim, {'do': 'found', 'text': f'Verify Hollow {victim}'})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {victim}', 'victim-membership'), 'community founded', 20)
    act(member, {'do': 'join', 'target': {'id': victim}})
    run.wait(lambda: run.sql(f'SELECT * FROM join_request WHERE asker = {member}', 'join-request'), 'join request', 20)
    act(victim, {'do': 'welcome', 'target': {'id': member}})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {member}', 'member-membership'), 'member welcomed', 20)
    assert not run.sql(f'SELECT * FROM membership WHERE member = {killer} OR member = {bystander}', 'outsiders-membership')
    # The member feels something for the victim (an authored relation), so the relations the
    # prompt lists include the victim, named as the member knows them (`known_as`).
    run.admin('set_background', member, json.dumps({'sheet': {'narrative': 'I keep the hollow with my neighbour.',
        'values': ['care'], 'goals': ['keep the hollow'], 'mood': 'settled',
        'relations': [{'id': victim, 'trust': 40, 'affinity': 50, 'label': 'neighbour'}]}}))
    for who in (killer, bystander):
        run.admin('place_near', who, victim)
    time.sleep(1.0)
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    models = model(run, script)
    run.start(models, [member])
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    sent_text = lambda e: '\n'.join(str(m.get('content', '')) for m in e['body'].get('messages', []))
    asked = lambda marker: [sent_text(e) for e in requests() if f'verify {marker}' in sent_text(e)]
    run.admin('set_behavior', member, json.dumps({'think': 'I finished my plan. verify alive'}))
    alive_prompt = run.wait(lambda: asked('alive'), 'prompt while the victim lives', 60)[0]
    (run.directory / 'prompt-alive.txt').write_text(alive_prompt)
    accepted(run, member)
    run.wait(lambda: run.sql(f'SELECT * FROM relation WHERE actor = {member} AND other = {victim}', 'relation-before'), 'authored relation', 20)
    deliberated = time.monotonic()
    # The victim gives in and the blows go on to death (as verify-core's death-names scene).
    run.admin('grant_items', killer, 'spear', 1)
    run.admin('set_behavior', victim, json.dumps({'seq': [{'do': 'yield', 'target': {'id': killer}}, {'wait': 120}]}))
    run.wait(lambda: run.sql(f"SELECT * FROM chronicle WHERE kind = 'yield' AND a = {victim}", 'yield'), 'victim yields', 30)
    run.admin('set_behavior', killer, json.dumps({'first': [{'do': {'skill': 'attack', 'target': {'id': victim}}}, {'wait': 1}]}))
    run.wait(lambda: not run.sql(f'SELECT alive FROM character WHERE id = {victim}', 'victim-alive')[0]['alive'], 'victim dead', 90)
    run.admin('set_behavior', killer, json.dumps({'wait': 120}))
    dead = run.sql(f'SELECT * FROM character WHERE id = {victim}', 'killed')[0]
    known = run.private(f'SELECT * FROM acquaintance WHERE known = {victim}', 'acquaintance-after')
    deaths = {w: run.wait(lambda w=w: [e['text'] for e in run.private(f'SELECT * FROM experience WHERE observer = {w}', f'experiences-{w}')
                                       if e['kind'] == 'death' and e['subject'] == victim], f'death witnessed by #{w}', 20)
              for w in (member, killer, bystander)}
    # A person's mind is asked again only after its think_min_s (20 s) unless urgent.
    time.sleep(max(0.0, 21 - (time.monotonic() - deliberated)))
    run.admin('set_behavior', member, json.dumps({'think': 'I finished my plan. verify after-death'}))
    after_prompt = run.wait(lambda: asked('after-death'), 'prompt after the death', 60)[0]
    (run.directory / 'prompt-after-death.txt').write_text(after_prompt)
    lines = lambda text, words: [l for l in text.split('\n') if words in l]
    texts = {'victim': vname, 'killer': names[killer], 'cause': dead['cause'],
             'acquaintance_observers': sorted(r['observer'] for r in known),
             'death': {'member': deaths[member], 'killer': deaths[killer], 'bystander': deaths[bystander]},
             'prompt_alive': {'relation': lines(alive_prompt, f'(#{victim})')},
             'prompt_after_death': {'relation': lines(after_prompt, f'(#{victim})'), 'death': lines(after_prompt, 'was killed by')}}
    (run.directory / 'death-names.json').write_text(json.dumps(texts, indent=2))
    checks = {
        'member_keeps_name': sorted(r['observer'] for r in known) == [member],
        'member_death_names_victim': any(t.startswith(f'{vname} was killed by') for t in deaths[member]),
        'killer_reads_you': any('was killed by you' in t for t in deaths[killer]) and not any(names[killer] in t for t in deaths[killer]),
        'bystander_reads_strangers': any(t.startswith('A stranger was killed by a stranger') for t in deaths[bystander]),
        'prompt_alive_names_relation': f'{vname} (#{victim})' in alive_prompt,
        'prompt_after_names_relation': f'{vname} (#{victim})' in after_prompt and f'a stranger (#{victim})' not in after_prompt,
        'prompt_after_names_death': any(f'{vname} was killed by' in l and f'{vname}=#{victim}' in l for l in lines(after_prompt, 'was killed by')),
    }
    texts['checks'] = checks
    (run.directory / 'death-names.json').write_text(json.dumps(texts, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **texts}


def animals_case(run):
    """Cheaper animal minds (LIVING_ANIMAL_MINDS=salient,choose,pack; mind/animal.rs): one deer
    picks one of a few options in one call and the graph built from it is installed; the deer it
    sees reuse that decision without a call (pack); asked again with nothing new, it lives by
    instinct without a call (salient)."""
    run.harness('launch')
    run.harness('doctor')
    person = next(p for p in sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id']) if p['alive'] and p['stage'] == 2)
    deer = [d['id'] for d in sorted(run.sql("SELECT * FROM character WHERE kind = 'deer'", 'deer'), key=lambda d: d['id']) if d['alive'] and d['stage'] == 2][:3]
    assert len(deer) == 3
    # The herd stays where the lead deer grazes (in the open); the person comes to them.
    at = run.sql(f"SELECT x, y FROM body WHERE id = {deer[0]}", 'lead-at')[0]
    run.admin('set_behavior', person['id'], json.dumps({'wait': 300}))
    run.admin('place_at', person['id'], at['x'] + 3, at['y'])
    for i, d in enumerate(deer):
        run.admin('set_behavior', d, json.dumps({'wait': 300}))
        run.admin('place_at', d, at['x'] + (i % 2), at['y'] + (i // 2))
    time.sleep(1.0)
    models = model(run, {})
    run.start(models, deer, extra_env={'LIVING_ANIMAL_MINDS': 'salient,choose,pack', 'LIVING_ANIMAL_PACK_S': '120'})
    detail = lambda t: json.loads(t['detail']) if t['detail'] else {}
    # A mind's install counts as having just thought: within its species' think_min_s (240 s)
    # the authority asks an animal only for urgent reasons, and every urgent reason is news to
    # its salience check. A fresh deer has not thought, so the first asks go through.
    ask = lambda d, marker: run.admin('set_behavior', d, json.dumps({'think': f'A quiet moment. verify {marker}'}))
    lead, *rest = deer
    ask(lead, 'animal-lead')
    first = run.wait(lambda: [t for t in run.thoughts(lead, 'lead-thoughts') if t['kind'] == 'deliberate' and detail(t).get('mode') == 'choose'], 'a chosen option', 60)[0]
    d0 = detail(first)
    assert d0['valid_pick'] and len(d0['options']) >= 3 and set(d0['pack']) >= set(rest), d0
    brain = run.sql(f'SELECT * FROM brain WHERE id = {lead}', 'lead-brain')[0]
    assert brain['source'] == 'mind' or d0['options'][d0['pick']].startswith('carry on'), brain
    for d in rest:
        ask(d, 'animal-member')
    shared_ = {d: run.wait(lambda d=d: [t for t in run.thoughts(d, f'member-{d}') if t['kind'] == 'deliberate' and detail(t).get('mode') == 'pack'], f'pack decision for {d}', 60)[0] for d in rest}
    assert all(detail(t)['by'] == lead for t in shared_.values())
    chosen = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'choose']
    compiled = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'deliberate']
    assert len(chosen) == 1 and not compiled, (len(chosen), len(compiled))
    # The lead asked again with nothing new, once its thinking throttle (240 s after its chosen
    # option) has passed (since 2026-11-11 no dawn broadcast skips it). Wolves that would come
    # into view meanwhile are news; the scene removes those that range near the herd.
    wolves = [w['id'] for w in run.sql("SELECT * FROM character WHERE kind = 'wolf'", 'wolves') if w['alive']]
    for w in wolves:
        b = run.sql(f'SELECT x, y FROM body WHERE id = {w}', f'wolf-{w}')
        if b and math.hypot(b[0]['x'] - at['x'], b[0]['y'] - at['y']) < 120:
            run.admin('kill', w, 'verify: kept away from the herd')
    time.sleep(max(0.0, (first['at_ms'] + 245_000) / 1000 - time.time()))
    ask(lead, 'animal-again')
    run.wait(lambda: any(t['kind'] == 'instinct' for t in run.thoughts(lead, 'lead-again')), 'a request answered by instinct', 60)
    assert len([e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'choose']) == 1, 'nothing new: no call'
    return {'status': 'pass', 'lead': lead, 'pick': d0['options'][d0['pick']], 'weight': d0.get('weight'), 'members': rest, 'model_calls_for_three_deer': 1}


def night_case(run):
    """Reorganization at night (mind/sleep.rs): with LIVING_NIGHT covering the whole day and no
    gap, a mind that integrated once goes to sleep in the night's batch round; under the timer
    no night round happens. Neo4j is off here, so nothing is sent (an empty mind needs no
    reorganization); verify-knowledge's sleep feature sends the batch."""
    people = prepare(run)
    actor = people[0]['id']
    script = {'replies': {'deliberate': basic_reply()}}
    models = model(run, script)
    run.request(actor, 'night')
    run.start(models, [actor], extra_env={'LIVING_REORGANIZE': 'night-batch', 'LIVING_NIGHT': '0-24', 'LIVING_REORGANIZE_GAP_S': '0', 'LIVING_REORGANIZE_MIN': '1'})
    run.wait(lambda: ' integrated ' in run.log(), 'one integration', 120)
    line = run.wait(lambda: re.search(r'night (\d+): 1 of 1 minds go to sleep \(1 in a batch, 0 direct; 1 due\)', run.log()), 'a night round', 30)
    run.wait(lambda: re.search(r'sleep: .+ slept \((batch|direct), night Some\(\d+\)', run.log()), 'the sleep ends', 30)
    assert 'reorganization: Config { mode: NightBatch' in run.log()
    return {'status': 'pass', 'night': int(line[1])}


def jev_case(run):
    """A cached judgment drives a graph (mind/judge.rs; `judged` condition): a defender whose
    graph flees while `fight_risk` is above 0.6 is struck; the fake Jev answers 0.9; the mind
    caches it with mind_judged and the authority's tick takes the flee branch. The request
    carries only the defender's own state."""
    people = prepare(run)
    defender, attacker = people[0]['id'], people[1]['id']
    at = run.sql(f"SELECT x, y FROM body WHERE id = {defender}", 'defender-at')[0]
    graph = {'desires': [{'want': 'this fight', 'weight': {'base': 1.0}, 'do': {'first': [
        {'if': {'cond': {'judged': {'q': 'fight_risk', 'above': 0.6}}, 'then': {'do': {'skill': 'flee', 'target': 'attacker'}}}},
        {'if': {'cond': {'hurt_within': 10}}, 'then': {'do': {'skill': 'strike', 'target': 'attacker'}}}, {'wait': 1}]}}]}
    script = {'replies': {'deliberate': {'thought': 'I hold my ground.', 'graph': 'keep'}, 'think': {'thought': 'I hold my ground.', 'intend': [], 'say': None}},
              'rules': [{'purpose': 'judge', 'noul': 0.9, 'times': -1}]}
    models = model(run, script)
    port = models['profiles']['local']['base_url'].split(':')[2].split('/')[0]
    run.start(models, [defender], extra_env={'LIVING_JEV': '1', 'LIVING_JEV_URL': f'http://127.0.0.1:{port}/v1/systemone', 'TYPESAFE_API_KEY': 'fake-only'})
    run.admin('place_at', defender, at['x'], at['y'])
    run.admin('place_at', attacker, at['x'] - 1.2, at['y'])
    run.admin('set_behavior', defender, json.dumps(graph))
    run.admin('set_behavior', attacker, json.dumps({'seq': [{'do': {'skill': 'strike', 'target': {'id': defender}}}, {'wait': 2}]}))
    cached = run.wait(lambda: run.private(f'SELECT * FROM judged WHERE actor = {defender}', 'judged'), 'a cached judgment', 60)
    assert cached[0]['q'] == 'fight_risk' and abs(cached[0]['value'] - 0.9) < 1e-6 and cached[0]['expires_ms'] > cached[0]['updated_ms']
    run.wait(lambda: any('flee' in (a['label'] or '').lower() for a in run.private(f'SELECT * FROM activity WHERE id = {defender}', 'activity')), 'the flee branch', 30)
    asked = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'judge']
    state = asked[0]['body']['state']
    assert set(state) >= {'actor', 'body', 'recently_perceived'} and 'fight_risk' in asked[0]['body']['questions']
    judged = [e for e in run.exchanges() if e['purpose'] == 'judge']
    assert judged and judged[0]['judged'][0]['q'] == 'fight_risk'
    return {'status': 'pass', 'judgments': len(judged), 'value': cached[0]['value']}
def rethink_case(run, arm):
    """The rethink gate (mind/rethink.rs; `LIVING_RETHINK=jev|llm`) in front of non-urgent
    deliberations. The fake judge holds by default and answers per marker in the request: a
    held request stays pending and gathers later reasons while the character still takes
    conversation turns; an urgent reason bypasses the judge and the deliberation sees all that
    gathered; a yes goes through; a failing or slow judge falls back to deliberating; a request
    held `max_hold_s` goes through. Every decision is journaled with purpose `rethink-gate`."""
    people = prepare(run)
    actor = people[0]['id']
    if arm == 'jev':
        yes = {'noul': {'plan_broken': 0.9, 'unhandled': 0.2, 'would_repeat': 0.1}}
        hold = {'noul': 0.1}
    else:
        yes = {'reply': {'rethink': True, 'p': 0.9}}
        hold = {'reply': {'rethink': False, 'p': 0.1}}
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'I answer.', 'say': 'verify rethink talk reply', 'end': True}},
              'rules': [{'purpose': 'rethink', 'contains': 'verify yes', 'times': -1, **yes},
                        {'purpose': 'rethink', 'contains': 'verify broken', 'status': 503, 'times': -1},
                        {'purpose': 'rethink', 'contains': 'verify slow', 'delay_s': 6, 'times': -1, **hold},
                        {'purpose': 'rethink', 'times': -1, **hold}]}
    models = model(run, script)
    port = models['profiles']['local']['base_url'].split(':')[2].split('/')[0]
    cfg = json.loads((ROOT / 'living/configs/rethink.json').read_text())
    cfg.update(max_hold_s=90)
    cfg['jev']['timeout_ms'] = 2000
    cfg['llm'].update(route='local', timeout_ms=4000)
    (run.directory / 'rethink.json').write_text(json.dumps(cfg, indent=2))
    run.start(models, [actor], extra_env={'LIVING_RETHINK': arm, 'LIVING_RETHINK_CONFIG': str(run.directory / 'rethink.json'),
              'LIVING_RETHINK_URL': f'http://127.0.0.1:{port}/v1/systemone', 'TYPESAFE_API_KEY': 'fake-only'})
    run.wait(lambda: 'rethink gate on:' in run.log(), 'the gate switched on', 30)
    gates = lambda: [e for e in run.exchanges() if e.get('purpose') == 'rethink-gate']
    thinks = lambda: len([e for e in run.exchanges() if e.get('purpose') == 'think'])
    asked = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e.get('purpose') == 'rethink']
    gate = lambda marker, verdict, s=40: run.wait(lambda: [g for g in gates() if marker in g['reason'] and g['verdict'] == verdict], f'gate {verdict} on {marker}', s)
    thought = lambda marker, s=40: run.wait(lambda: [t for t in run.thoughts(actor, 'thoughts-' + marker.replace(' ', '-'))
                                                    if t['kind'] == 'deliberate' and marker in json.loads(t['detail']).get('reason', '')], f'deliberation on {marker}', s)
    out = {}
    # A fake mind answers within a second, so the driver waits on the gate's journal, not on
    # the pending row.
    ask = lambda marker: run.admin('set_behavior', actor, json.dumps({'think': 'I finished my plan. verify ' + marker}))
    # 1. The first thought since the service started is never gated.
    ask('first')
    gate('verify first', 'first')
    thought('verify first')
    assert not asked(), 'the first thought asked the judge'
    # 2. A non-urgent trigger is held: it stays pending, no thought starts. (Re-raised triggers
    #    with nothing new are held without asking; that rule is the unit test
    #    `a_held_request_is_asked_again_only_when_something_changed`, since percepts arrive
    #    on the world's schedule.)
    time.sleep(46)
    before = thinks()
    run.admin('set_behavior', actor, json.dumps({'think': 'verify gated one'}))
    held = gate('verify gated one', 'hold')[0]
    assert held['p'] is not None and held['p'] < 0.5 and held['state']['why_it_is_asked_to_think']
    assert set(held['state']) >= {'current_plan', 'since_last_thought', 'spoke_to_without_answer', 'body', 'recent_thoughts'}
    # 3. While held, the character still takes a conversation turn.
    run.harness('player', 'join', 'RethinkListener')
    player = run.sql("SELECT id FROM character WHERE name = 'RethinkListener'", 'player')[0]['id']
    run.admin('place_near', player, actor)
    run.harness('player', 'say', 'Are you still there?', '--to', str(actor))
    run.wait(lambda: [e for e in run.exchanges() if e.get('purpose') == 'talk'], 'a talk turn while held', 30)
    time.sleep(5)
    assert thinks() == before, 'a held request was deliberated'
    assert run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'held-pending'), 'the held request is gone'
    out['asked_while_held'] = len(asked())
    # 4. A later reason merges into the held request and is judged again.
    run.admin('set_behavior', actor, json.dumps({'think': 'verify gated two'}))
    gate('verify gated two', 'hold')
    assert thinks() == before
    # 5. An urgent reason is never judged, and the deliberation sees everything that gathered.
    n = len(asked())
    run.admin('set_behavior', actor, json.dumps({'think': 'Wolf is attacking you! verify urgent'}))
    gate('verify urgent', 'urgent')
    urgent = json.loads(thought('verify urgent')[0]['detail'])['reason']
    assert 'verify gated one' in urgent and 'verify gated two' in urgent, urgent
    assert len(asked()) == n, 'an urgent trigger was judged'
    # 6. A yes goes through.
    time.sleep(46)
    ask('yes')
    out['yes_p'] = gate('verify yes', 'rethink')[0]['p']
    thought('verify yes')
    # 7. A failing judge falls back to deliberating, and so does a slow one.
    for marker in ('broken', 'slow'):
        time.sleep(46)
        ask(marker)
        out[marker] = gate('verify ' + marker, 'fallback')[0]['error']
        thought('verify ' + marker)
    # 8. A request held for max_hold_s goes through.
    time.sleep(46)
    ask('gated three')
    gate('verify gated three', 'hold')
    started = time.monotonic()
    gate('verify gated three', 'max_hold', 120)
    thought('verify gated three')
    out['max_hold_release_s'] = round(time.monotonic() - started, 1)
    verdicts = [g['verdict'] for g in gates()]
    stats = run.wait(lambda: re.findall(r'rethink gate \(\w+\): Stats \{([^}]*)\}', run.log()), 'a stats line', 70)
    (run.directory / 'rethink.json-result').write_text(json.dumps({'verdicts': verdicts, 'stats': stats[-1], **out}, indent=2))
    return {'status': 'pass', 'arm': arm, 'verdicts': verdicts, 'stats': stats[-1], **out}


def resident_case(run):
    """On the island every resident has a mind from the start (an AI character the world
    admin controls): this service thinks for it, it answers a player through `mind_say`,
    trades and teaches through its own acts, and a replacing projection keeps its given places
    (work, inn, square, evening: world facts its starting ways walk to)."""
    target = ROOT / '.local/living/target-resident-island'
    run.harness('launch', '--seed', 'island', '--target-dir', str(target))
    run.harness('doctor')
    world = run.sql('SELECT * FROM world', 'world')[0]
    run.harness('player', 'join', 'MindsNewcomer')
    me = run.sql("SELECT id FROM character WHERE name = 'MindsNewcomer'", 'player')[0]['id']
    # A resident keeping its post (its starting ways), with a technique the newcomer lacks.
    mine = {k['technique'] for k in run.sql(f'SELECT technique FROM know_how WHERE actor = {me}', 'newcomer-know-how')}
    def pick():
        keeping = {a['id'] for a in run.sql("SELECT id, skill FROM activity", 'activities') if a['skill'] == 'keep'}
        for c in run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'):
            if c['id'] in keeping and c['alive'] and c['stage'] == 2 and c['ai'] and c['controller'] == world['admin']:
                knows = {k['technique'] for k in run.sql(f"SELECT technique FROM know_how WHERE actor = {c['id']}", 'resident-know-how')}
                lesson = sorted(knows - mine)
                if lesson:
                    return c, lesson[0]
        return None
    resident, lesson = run.wait(pick, 'a resident at its post who knows something the newcomer does not', 60)
    rid = resident['id']
    given = run.sql(f'SELECT * FROM place WHERE actor = {rid}', 'places-before')
    places_before = {p['name'] for p in given if p['given']}
    assert places_before, ('a seeded resident has given places', given)
    run.admin('place_near', me, rid)
    run.admin('grant_items', rid, 'wood', 2)
    acts = [{'do': 'accept', 'target': {'id': me}},
            {'do': 'teach', 'target': {'id': me}, 'item': lesson}]
    # A line that arrives while the resident's deliberation runs waits for it (talk.rs): its
    # think step's `say` answers the only person waiting, so that line gets no extra turn.
    script = {'replies': {'think': {'thought': 'A newcomer.', 'intend': ['wait'], 'say': 'verify minds welcome, newcomer'},
                          'deliberate': basic_reply(acts=acts),
                          'talk': {'thought': 'A newcomer asks where I work.', 'say': 'verify minds talk answer', 'end': False},
                          'consolidate': {'summary': 'verify minds met a newcomer',
                                          'places': [{'name': 'verify after', 'x': 41, 'y': 61}],
                                          'nodes': [], 'edges': []}},
              'rules': [{'purpose': 'consolidate', 'delay_s': 1, 'times': -1}]}
    models = model(run, script)
    run.start(models, [rid], seed='island')
    # The newcomer offers a trade, then speaks to the resident.
    run.harness('player', 'act', json.dumps({'do': 'offer', 'target': {'id': rid}, 'item': 'berries', 'qty': 1, 'want': 'wood', 'want_qty': 1}))
    run.wait(lambda: any('offers you' in d['reason'] for d in run.private(f'SELECT * FROM deliberation WHERE actor = {rid}', 'offer-asks-its-mind')) or
             any(t['kind'] == 'deliberate' for t in run.thoughts(rid, 'thoughts-offer')), 'the offer asks the resident\'s mind', 20)
    run.harness('player', 'say', 'verify minds: is there food and a bed here?', '--to', str(rid))
    heard = lambda text, save: any(text in e['text'] and e['subject'] == rid for e in run.private(f'SELECT * FROM experience WHERE observer = {me}', save))
    run.wait(lambda: heard('verify minds welcome', 'newcomer-heard'), 'the resident answers the newcomer (its deliberation says it)', 60)
    # Its deliberation decides acts: it accepts the trade and teaches the lesson.
    accepted(run, rid)
    run.wait(lambda: any(c['kind'] == 'trade' and c['b'] == rid for c in run.sql(f'SELECT * FROM chronicle WHERE b = {rid}', 'trade')),
             'trade accepted through mind_act', 60)
    run.wait(lambda: any(k['technique'] == lesson for k in run.sql(f'SELECT * FROM know_how WHERE actor = {me}', 'newcomer-learned')),
             'lesson taught through mind_act', 60)
    # More lines force a consolidation; its projection keeps the places it knew before.
    for line in ('verify minds: where do you work?', 'verify minds: who keeps the inn?', 'verify minds: thank you for the lesson.'):
        time.sleep(2.2)
        run.harness('player', 'say', line, '--to', str(rid))
    run.wait(lambda: heard('verify minds talk answer', 'newcomer-heard-talk'), 'a later line gets a talk turn answered through mind_say', 60)
    run.wait(lambda: any(t['kind'] == 'consolidate' for t in run.thoughts(rid, 'thoughts-consolidated')), 'consolidation', 90)
    # Without Neo4j the service projects without `replace`; with a store it sends the mind's
    # complete set (`replace: true`). Send that update as the service would: the places the
    # resident was given at world creation must survive a set that does not name them.
    run.admin('mind_update', rid, {'persona': {'none': []}, 'relations': [], 'beliefs': {'none': []}, 'judgments': [],
                                   'places': [{'name': 'verify after', 'x': 41.0, 'y': 61.0}], 'thought': {'none': []}, 'replace': True})
    places = {p['name'] for p in run.sql(f'SELECT * FROM place WHERE actor = {rid}', 'places-after')}
    assert 'verify after' in places and places_before <= places, (places_before, places)
    final = run.sql(f'SELECT * FROM character WHERE id = {rid}', 'resident-final')[0]
    assert final['ai'] and final['controller'] == world['admin']
    talks = [e for e in run.exchanges() if e['purpose'] == 'talk']
    return {'status': 'pass', 'resident': rid, 'lesson': lesson, 'talk_turns': len(talks),
            'places_kept': sorted(places_before), 'places_after': sorted(places)}


def parked_case(run):
    """A line heard while the listener's deliberation runs waits for it to end and then gets its
    reply turn (talk.rs `deliberation_ended`), unless that deliberation spoke to the speaker."""
    people = prepare(run)
    actor = people[0]['id']
    run.harness('player', 'join', 'MindsParker')
    player = run.sql("SELECT id FROM character WHERE name = 'MindsParker'", 'player')[0]['id']
    run.admin('place_near', player, actor)
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'Answering after my thinking.', 'say': 'verify minds parked answer', 'end': True}},
              'rules': [{'purpose': 'think', 'contains': 'verify second', 'times': -1,
                         'reply': {'thought': 'I answer while I think.', 'intend': ['wait'],
                                   'say': {'text': 'verify minds answered while thinking', 'to': player}}},
                        {'purpose': 'deliberate', 'contains': 'verify second', 'delay_s': 8, 'times': 1},
                        {'purpose': 'deliberate', 'delay_s': 8, 'times': 1}]}
    models = model(run, script)
    requests = lambda: list(shared.rows(run.directory / 'fake-requests.jsonl'))
    talks = lambda: [e for e in requests() if e['purpose'] == 'talk']
    # 1. The deliberation says nothing to the player: the line gets its turn when it ends.
    run.request(actor, 'first')
    run.start(models, [actor])
    run.wait(lambda: any(e['purpose'] == 'deliberate' for e in requests()), 'first deliberation running', 60)
    run.harness('player', 'say', 'Will you answer me once you have thought it over?', '--to', str(actor))
    time.sleep(3)
    assert not talks(), 'a talk turn ran while the deliberation was running'
    run.wait(lambda: talks(), 'the parked line gets its talk turn after the deliberation', 40)
    run.wait(lambda: any('verify minds parked answer' in c['text'] and c['b'] == player for c in run.sql(
        f'SELECT * FROM chronicle WHERE a = {actor}', 'parked-speech')), 'parked answer spoken')
    log = run.log()
    assert 'waits for it to end' in log and 'gets its turn' in log
    after_first = len(talks())
    # 2. The deliberation speaks to the player after hearing them: no extra turn.
    time.sleep(2.2)
    run.request(actor, 'second')
    run.wait(lambda: any(e['purpose'] == 'deliberate' and 'verify second' in json.dumps(e['body']) for e in requests()),
             'second deliberation running', 60)
    run.harness('player', 'say', 'Another matter entirely: where does the river bend north?', '--to', str(actor))
    run.wait(lambda: any('verify minds answered while thinking' in c['text'] and c['b'] == player for c in run.sql(
        f'SELECT * FROM chronicle WHERE a = {actor}', 'deliberation-speech')), 'the deliberation answers', 40)
    time.sleep(6)
    assert len(talks()) == after_first, 'a talk turn repeated what the deliberation answered'
    assert 'in its deliberation' in run.log()
    return {'status': 'pass', 'talk_turns': len(talks())}


def speech_case(run):
    """Speech through a mind (docs/COMMUNICATION.md): a talk reply's `way` reaches `mind_say`
    (a way the world does not have is said aloud), a name that is news reaches the mind as an
    `introduced` row its consolidation sees tagged with the person (`{Name=#id}`, the anchor
    `person:<id>`), and the mind's own line reads as heard by those it saw (`heard`)."""
    people = prepare(run)
    actor = people[0]['id']
    run.harness('player', 'join', 'MindsTeller')
    player = run.sql("SELECT id FROM character WHERE name = 'MindsTeller'", 'player')[0]['id']
    run.admin('set_behavior', actor, json.dumps({'wait': 120}))
    run.admin('place_near', player, actor)
    gist = '$EXPTEXT:told you their name'
    script = {'replies': {'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'I answer, aloud.', 'say': 'verify minds spoken in a way', 'way': 'say', 'end': False},
                          'consolidate': {'summary': 'verify minds names', 'remember': [{'exp': '$EXP:told you their name', 'gist': gist, 'salience': 0.6, 'involves': ['$PERSON']}],
                                          'nodes': [], 'edges': [], 'retract': [], 'merge': [], 'identity': None, 'relations': [], 'judgments': [], 'places': []}},
              # A turn's prompt holds the conversation so far: the latest line's rule comes first.
              'rules': [{'purpose': 'talk', 'contains': 'over here', 'times': -1,
                         'reply': {'thought': 'I call back.', 'say': 'verify minds called back', 'way': 'call', 'end': True}},
                        # A whisper is answered in kind when the reply names no way.
                        {'purpose': 'talk', 'contains': 'a secret', 'times': -1,
                         'reply': {'thought': 'I answer quietly.', 'say': 'verify minds whispered back', 'end': False}},
                        {'purpose': 'talk', 'contains': 'shout it', 'times': -1,
                         'reply': {'thought': 'I shout back.', 'say': 'verify minds shouted back', 'way': 'shout', 'end': False}},
                        {'purpose': 'consolidate', 'cite': True, 'times': -1}]}
    models = model(run, script)
    # As in `conversation`: the mind's first deliberation is in before anyone speaks to it.
    run.request(actor, 'speech')
    run.start(models, [actor])
    accepted(run, actor)
    # The deliberation installs the fake's plan, which runs the resident's own routine: hold it
    # where it is, and bring the player beside it again.
    run.admin('set_behavior', actor, json.dumps({'wait': 120}))
    run.admin('place_near', player, actor)
    time.sleep(2)
    requests = lambda: list(shared.rows(run.directory / 'fake-requests.jsonl'))
    text_of = lambda e: json.dumps(e, ensure_ascii=False).replace('\\"', '"')
    spoken = lambda words: any(words in c['text'] and c['b'] == player for c in run.sql(f'SELECT * FROM chronicle WHERE a = {actor}', 'mind-speech'))
    # A question: a remark that asks nothing is answered only by chance (talk.rs, 0.3 + 0.65 x
    # sociability), which is what left minds-speech3, -4b and -6 without a turn.
    run.harness('player', 'say', 'I am MindsTeller. How are you today?', '--to', str(actor))
    run.wait(lambda: spoken('verify minds spoken in a way'), 'a talk reply with "way": "say" is spoken through mind_say', 60)
    intro = [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'introduced') if e['kind'] == 'introduced']
    assert len(intro) == 1 and intro[0]['subject'] == player and intro[0]['text'] == 'MindsTeller told you their name.', intro
    heard = run.private(f'SELECT * FROM heard WHERE speaker = {actor}', 'mind-heard')
    assert heard and all(player in h['hearers'] and h['way'] == 'say' for h in heard), heard
    time.sleep(2.2)
    run.harness('player', 'say', 'Can you shout it so the square hears?', '--to', str(actor))
    run.wait(lambda: spoken('verify minds shouted back'), 'a reply in a way the world lacks is said aloud', 60)
    talks = [e for e in requests() if e['purpose'] == 'talk']
    assert any(re.search(r'verify minds spoken in a way” \(heard by [^)]*MindsTeller', text_of(e)) for e in talks[1:]), 'the second talk turn does not read the mind\'s own line as heard'
    run.wait(lambda: any(e['purpose'] == 'consolidate' and 'MindsTeller told you their name.' in text_of(e) for e in requests()),
             'consolidation sees the introduction', 150)
    consolidation = next(e for e in requests() if e['purpose'] == 'consolidate' and 'MindsTeller told you their name.' in text_of(e))
    tagged = f'MindsTeller told you their name. {{MindsTeller=#{player}}}' in text_of(consolidation)
    assert tagged, 'the introduction is not tagged with the person (its anchor)'
    run.wait(lambda: any(t['kind'] == 'consolidate' for t in run.thoughts(actor, 'thoughts-consolidated')), 'consolidation applied', 60)
    ways = {c['name'] for c in run.sql('SELECT * FROM speech_card', 'speech-card')}
    whispered = called = None
    chronicle = lambda: run.sql(f'SELECT * FROM chronicle WHERE a = {actor}', 'mind-speech-ways')
    if 'whisper' in ways:
        # Beside the mind, the player whispers: the turn is told it was whispered, and the reply
        # (naming no way) is whispered back.
        body = run.private(f'SELECT * FROM body WHERE id = {actor}', 'actor-body')[0]
        run.admin('place_at', player, body['x'] + 1.0, body['y'])
        time.sleep(2.2)
        run.harness('call', 'human_speak', json.dumps(['verify minds: may I tell you a secret?', actor, 'whisper']), '--as-player')
        run.wait(lambda: any('verify minds whispered back' in c['text'] for c in chronicle()), 'a whisper answered', 60)
        whispered = next(c['text'] for c in chronicle() if 'verify minds whispered back' in c['text'])
        assert '(whisper)' in whispered, whispered
        talk = next(e for e in requests() if e['purpose'] == 'talk' and 'a secret' in text_of(e))
        assert 'They whispered this to you' in text_of(talk), 'the turn is not told the line was whispered'
    if 'call' in ways:
        # From 15 m the player calls: the turn is told the distance, and the reply calls back.
        body = run.private(f'SELECT * FROM body WHERE id = {actor}', 'actor-body')[0]
        run.admin('place_at', player, body['x'] + 15.0, body['y'])
        # A listener takes at most its stamina's turns in one exchange (talk.rs), and an
        # exchange starts afresh after 90 s of quiet: this one has had three turns already.
        time.sleep(92)
        run.harness('call', 'human_speak', json.dumps(['verify minds: can you hear me over here?', actor, 'call']), '--as-player')
        run.wait(lambda: any('verify minds called back' in c['text'] for c in chronicle()), 'a call answered', 60)
        called = next(c['text'] for c in chronicle() if 'verify minds called back' in c['text'])
        talk = next(e for e in requests() if e['purpose'] == 'talk' and 'over here' in text_of(e))
        assert '(call)' in called and re.search(r'calls out to you from about 1[3-7] m', text_of(talk)) and 'An ordinary voice carries 9 m' in text_of(talk), (called, 'distance and voice in the prompt')
        assert '\\"way\\": how you say it' in json.dumps(talk) or '"way": how you say it' in text_of(talk), 'the talk turn does not list the ways'
    replies = [json.loads(t['detail']).get('reply', {}) for t in run.thoughts(actor, 'thoughts-talk') if t['kind'] == 'talk']
    return {'status': 'pass', 'talk_turns': len(talks), 'reply_ways': [r.get('way') for r in replies], 'introduced': intro[0]['text'],
            'heard_rows': len(heard), 'consolidation_tagged': tagged, 'whispered_back': whispered, 'called_back': called}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='new suite name starting with minds-')
    parser.add_argument('--case', action='append', choices=CASES, help='repeat to select; default all')
    args = parser.parse_args()
    if not re.fullmatch(r'minds-[a-zA-Z0-9-]+', args.run):
        parser.error('--run must start with minds-')
    with urllib.request.urlopen(os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/') + '/v1/ping', timeout=5) as response:
        assert response.status == 200
    suite = ROOT / '.local/living/verify' / args.run
    suite.mkdir(parents=True, exist_ok=False)
    for command, name in ((['cargo', 'build', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--release'], 'build.log'),
                          (['cargo', 'test', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--', '--nocapture'], 'cargo-tests.log')):
        with (suite / name).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    paths = ['living/mind/src/main.rs', 'living/mind/src/mind.rs', 'living/mind/src/mind/talk.rs',
             'living/mind/src/mind/lod.rs', 'living/mind/src/mind/rethink.rs', 'living/configs/rethink.json', 'living/mind/src/prompts.rs', 'living/authority/src/mind.rs',
             'living/rules/src/normalize.rs', str(shared.MIND_BIN),
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
