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
CASES = ('roundtrip', 'acts', 'conversation', 'consolidation', 'prune', 'reject', 'only', 'reconnect', 'lod',
         'takeover', 'sight')
OPAQUE = {4, 7}             # rock, wall (living_rules::map::Terrain)
UNWALKABLE = {2, 4, 7}      # water, rock, wall


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
    if case == 'takeover':
        return takeover_case(run)
    if case == 'sight':
        return sight_case(run)
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
             'living/mind/src/mind/lod.rs', 'living/mind/src/prompts.rs', 'living/authority/src/mind.rs',
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
