#!/usr/bin/env python3
"""Drive real internal minds against the shared local fake model server."""
import argparse
import functools
import hashlib
import importlib.util
import inspect
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
# The cases, by name, in the order they are defined below: each registers itself with @case.
CASES = {}


def case(*names, **fixed):
    """Register the decorated function as the case(s) NAMES. It is called with the case's run and
    FIXED, and with case=NAME when it takes a `case` argument (one body serving several cases)."""
    def register(function):
        takes_name = 'case' in inspect.signature(function).parameters
        for name in names:
            assert name not in CASES, f'case {name} registered twice'
            CASES[name] = functools.partial(function, **fixed, **({'case': name} if takes_name else {}))
        return function
    return register


# How a player-framed system prompt opens (LIVING_FRAME=player; prompts.rs PLAYER_FRAME).
PLAYER_FRAME_HEAD = 'You are an AI playing the person described under # Who you are'
OPAQUE = {4, 7}             # rock, wall (living_rules::map::Terrain); a drop (8) and a low thing (9) are see-through
UNWALKABLE = {2, 4, 7, 8, 9}  # water, rock, wall, drop, low
DROP, LOW = 8, 9
# How a scene tells a mind of a drop and of a low thing (living_rules::map::Terrain::words and
# ::passage, written by the authority's perceive::scene_json under `terrain_near`).
TERRAIN_WORDS = {DROP: 'a drop to ground at another level (stairs, ramps and roads join the levels)',
                 LOW: 'something low or open in the way, such as a cart, a low wall or an open stall'}
SEE_PAST = 'you can see past it but not walk through it'


class Run(shared.Run):
    def __init__(self, name):
        # gate-*: the merge's scene gate (living/tools/scene_gate.py), databases verify-gate-*.
        super().__init__(name, prefix='gate' if name.startswith('gate-') else 'minds')

    def note(self, text):
        with (self.directory / 'actions.log').open('a') as log:
            log.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def request(self, actor, marker, seconds=65, attempts=3):
        """Make the authority ask `actor`'s mind to deliberate, for the reason 'I finished my plan.
        verify <marker>': install a test graph whose think node asks it, and wait for the ask.

        Relies only on what the rules promise. A think node asks once the deliberation clock
        (`deliberated_ms`) has settled 45 s (brain.rs), and `think_min_s` (20 s for people) is shorter
        than that. A mind's reply (`mind_install`) clears the request, replaces the graph and sets
        the clock in one transaction, and with a new plan it drops 'I finished my plan' reasons that
        arrived while it was thinking (reasons.rs PLAN_STATE). So, while the mind runs:
        - first wait until the actor has no request pending: a reply still in flight would replace
          the test graph and drop the test's reason (fix-request, 2026-11-12);
        - the ask counts when the marker is in the reason of a newer thought row: the mind may answer
          within a second, between two polls (the greet failure in minds-fixtake-full2);
        - or when it is in a pending row that no read lacks: the mind is not running, or the marker's
          line arrived when the row was made (`arrived` against `requested_ms`), or the row is one
          the mind held through the quiet wait. A line merged into a request the mind has already
          read does not count, since that reply drops it;
        - when the graph is replaced without the marker reaching a thought, install it again.
        Returns the pending rows carrying the marker, else the thought rows that record the answer."""
        line = 'verify ' + marker
        has = lambda text: re.search(re.escape(line) + r'(?![\w-])', text or '') is not None
        pending_q = f'SELECT * FROM deliberation WHERE actor = {actor}'
        running = lambda: self.mind is not None and self.mind.poll() is None

        def reason(t):
            try:
                return json.loads(t.get('detail') or '{}').get('reason', '')
            except (ValueError, AttributeError):
                return ''

        def answered(base):
            return [t for t in self.sql(f'SELECT * FROM thought WHERE actor = {actor} AND id > {base}',
                                        'answered-' + marker) if has(reason(t))]

        def made_by_ask(d):
            # The marker's line arrived when the request was made: no read of the row lacks it.
            lines, times = d['reason'].split('\n'), d.get('arrived', '').split()
            at = [i for i, l in enumerate(lines) if has(l)]
            return bool(at) and at[0] < len(times) and int(times[at[0]]) <= d['requested_ms']

        for attempt in range(1, attempts + 1):
            held = False
            if running():
                # A request still pending is a deliberation in flight, or one the mind holds (LoD,
                # the rethink gate). A held one may stay: after 40 s the test think merges into it.
                quiet = time.monotonic() + 40
                while self.private(pending_q, 'pending-before-' + marker):
                    if time.monotonic() > quiet:
                        held = True
                        self.note(f'request {line!r}: a request still pending after 40 s is held; the ask merges into it')
                        break
                    time.sleep(0.5)
            base = max((t['id'] for t in self.thoughts(actor, 'thoughts-before-' + marker)), default=0)
            self.admin('set_behavior', actor, json.dumps({'think': 'I finished my plan. ' + line}))
            deadline = time.monotonic() + seconds
            replaced = False
            while time.monotonic() < deadline:
                if self.mind and self.mind.poll() is not None:
                    raise RuntimeError(f'mind exited while waiting for authority deliberation {line!r}; see mind.log')
                rows = [d for d in self.private(pending_q, 'pending-' + marker) if has(d['reason'])]
                if rows and (held or not running() or made_by_ask(rows[0])):
                    return rows
                done = answered(base)
                if done:
                    self.note(f'request {line!r}: answered before a poll saw it pending (thought {done[0]["id"]})')
                    return done
                brain = self.private(f'SELECT * FROM brain WHERE id = {actor}', 'brain-' + marker)
                if not brain or brain[0]['source'] != 'test' or line not in brain[0]['graph']:
                    # The replacing reply wrote its thought in the same transaction: read once more.
                    done = answered(base)
                    if done:
                        self.note(f'request {line!r}: answered before a poll saw it pending (thought {done[0]["id"]})')
                        return done
                    self.note(f'request {line!r}: attempt {attempt}: the test graph was replaced '
                              f'(source {brain[0]["source"] if brain else None!r}, plan {brain[0]["plan"] if brain else None!r}) '
                              'without its ask; installing it again')
                    replaced = True
                    break
                time.sleep(0.25)
            if not replaced:
                break
        raise RuntimeError(f'timed out waiting for authority deliberation {line!r}'
                           + (f' after {attempts} installs' if replaced else f' ({seconds}s)'))

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


def across_spots(info, between):
    """Two walkable tiles 2 to 5 apart on one axis with only tiles of class `between` between them
    (within even night sight, 6 tiles)."""
    w, h, tiles = info
    at = lambda x, y: tiles[y * w + x] if 0 <= x < w and 0 <= y < h else 4
    walk = lambda x, y: at(x, y) not in UNWALKABLE
    for y in range(5, h - 5):
        for x in range(5, w - 5):
            if not walk(x, y):
                continue
            for dx, dy in [(1, 0), (0, 1)]:
                for gap in (1, 2, 3, 4):
                    bx, by = x + (gap + 1) * dx, y + (gap + 1) * dy
                    if walk(bx, by) and all(at(x + i * dx, y + i * dy) == between for i in range(1, gap + 1)):
                        return {'eye': (x + .5, y + .5), 'across': (bx + .5, by + .5), 'gap': gap}
    raise RuntimeError(f'no walkable ground on both sides of tiles of class {between}')


def scene_sent(sent):
    """The scene in a prompt the model was sent (one line of JSON under its heading)."""
    m = re.search(r'# (?:What you perceive right now|Around you now)\n(\{.*\})\n', sent)
    return json.loads(m.group(1)) if m else None


@case('drop')
def drop_case(run):
    """A mind is told of a drop and of a low thing in words that say what they are and that
    one sees past them but cannot walk through them (`terrain_near`), and sees the creature on
    the other side, on the island (terraced towns' drops, carts and other low things)."""
    target = (Path(os.environ['CARGO_TARGET_DIR']) if os.environ.get('CARGO_TARGET_DIR') else ROOT / '.local/living/target-resident-island')
    run.harness('launch', '--seed', 'island', '--target-dir', str(target))
    run.harness('doctor')
    world = run.sql('SELECT * FROM world', 'world')[0]
    people = [p['id'] for p in sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
              if p['ai'] and p['alive'] and p['stage'] == 2 and p['controller'] == world['admin']][:3]
    assert len(people) == 3, people
    eye, across, past_low = people
    info = terrain(run)
    spots = {'drop': across_spots(info, DROP), 'low': across_spots(info, LOW)}
    (run.directory / 'spots.json').write_text(json.dumps(spots, indent=2))
    for who in people:
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    models = model(run, script)
    run.start(models, [eye], seed='island')
    told = {}
    for n, (name, cls, other) in enumerate((('drop', DROP, across), ('low', LOW, past_low))):
        run.admin('place_at', eye, *spots[name]['eye'])
        run.admin('place_at', other, *spots[name]['across'])
        time.sleep(1.0)
        run.admin('set_behavior', eye, json.dumps({'think': 'I finished my plan. verify ' + name}))
        request = run.wait(lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl')
                                    if e['purpose'] in ('think', 'deliberate') and ('verify ' + name) in json.dumps(e['body'])],
                           f'the {name} scene sent to the model', 60)[0]
        sent = '\n'.join(str(m.get('content', '')) for m in request['body'].get('messages', []))
        (run.directory / f'sent-prompt-{name}.txt').write_text(sent)
        scene = scene_sent(sent)
        assert scene, f'no scene in the {name} prompt'
        (run.directory / f'scene-{name}.json').write_text(json.dumps(scene, indent=2))
        near = scene.get('terrain_near', {}).get(name)
        assert near and TERRAIN_WORDS[cls] in near and SEE_PAST in near, (name, scene.get('terrain_near'))
        ids = [c['id'] for c in scene.get('creatures', [])]
        assert other in ids, (f'the one across the {name} is seen', ids)
        told[name] = {'terrain_near': near, 'seen_across': other, 'gap_tiles': spots[name]['gap']}
        # Let the mind's answer install before the next scene.
        time.sleep(3.0)
    return {'status': 'pass', 'told': told}


@case('run')
def breath_case(run):
    """A mind can run (docs/STAMINA.md): its prompt documents `"run": true` on a goto and the
    graph's `stamina` condition, its scene carries its breath, and an act it decides with
    `"run": true` runs at the run's share of its walk (the `run_share` law) and drains breath on
    the vitals row the mind service reads."""
    people = prepare(run)
    actor = people[0]['id']
    me = run.private(f'SELECT * FROM body WHERE id = {actor}', 'actor-body')[0]
    there = [round(me['x'] + 30.0, 1), round(me['y'], 1)]
    # Its walk first: the same goto, walked, from a graph the admin sets.
    run.admin('set_behavior', actor, json.dumps({'seq': [{'do': {'skill': 'goto', 'target': {'at': there}}}, {'wait': 120}]}))
    walk = run.wait(lambda: next((b['speed'] for b in [run.private(f'SELECT * FROM body WHERE id = {actor}', 'walking-body')[0]] if b['vx'] or b['vy']), None), 'the walk', 10)
    run.admin('set_behavior', actor, json.dumps({'wait': 120}))
    run.admin('place_at', actor, me['x'], me['y'])
    time.sleep(3.0)
    script = {'replies': {'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(acts=[{'do': 'goto', 'target': {'at': there}, 'run': True}])}}
    models = model(run, script)
    run.request(actor, 'verify run')
    run.start(models, [actor])
    accepted(run, actor)
    ran = run.wait(lambda: next((b for b in [run.private(f'SELECT * FROM body WHERE id = {actor}', 'running-body')[0]] if b['speed'] > walk * 1.5), None), 'the act runs', 30)
    v = run.private(f'SELECT * FROM vitals WHERE id = {actor}', 'running-vitals')[0]
    src = run.sql("SELECT source FROM script WHERE name = 'skills'", 'script')[0]['source']
    share = float(re.search(r'\brun_share: ([0-9.]+)', src).group(1))
    assert abs(ran['speed'] / walk - share) < 0.02, (walk, ran['speed'], share)
    assert v['stamina_rate'] < 0 and v['stamina_from_ms'] == v['at_ms'], v
    sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    text = '\n'.join(str(m.get('content', '')) for e in sent for m in e['body'].get('messages', []))
    (run.directory / 'sent-prompt-run.txt').write_text(text)
    assert '"run": true' in text and '{"stamina": {"below": 30}}' in text, 'the run and the stamina condition are documented'
    scene = scene_sent(text)
    assert scene and 'stamina' in scene.get('you', {}), scene and scene.get('you')
    act = run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'experiences')
    return {'status': 'pass', 'walk': walk, 'run': ran['speed'], 'ratio': round(ran['speed'] / walk, 3),
            'vitals_while_running': {k: v[k] for k in ('stamina', 'stamina_rate', 'stamina_from_ms', 'at_ms')},
            'scene_stamina': scene['you']['stamina'], 'experiences': len(act)}


@case('intents')
def intents_case(run):
    """A mind's plan can say a movement intent (docs/COMBAT_MIND.md §3.3): its prompt's skill
    reference documents keep_distance, close_in, circle and back_off with their distances and the
    speeds and sight rule from the laws; a fake model's plan `keep_distance` (3–6 m) from someone
    in sight installs as written, its steering holds that band (`steer`: a band goal held to them
    by sight), and when they walk at the character it backs off."""
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    for who in (actor, other):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    # An open row of walkable tiles with nothing that blocks sight, 3 wide and 16 long.
    w, h, tiles = terrain(run)
    ok = lambda x, y: 0 <= x < w and 0 <= y < h and tiles[y * w + x] not in UNWALKABLE
    row = next((x, y) for y in range(8, h - 8, 3) for x in range(8, w - 24, 2) if all(ok(x + i, y + d) for i in range(16) for d in (-1, 0, 1)))
    run.admin('place_at', actor, row[0] + 10.5, row[1] + 0.5)
    run.admin('place_at', other, row[0] + 14.5, row[1] + 0.5)
    time.sleep(1.0)
    me = run.private(f'SELECT * FROM body WHERE id = {actor}', 'actor-body')[0]
    plan = 'verify minds keep distance'
    graph = {'do': 'keep_distance', 'target': {'id': other}, 'min': 3, 'max': 6, 'qty': 120}
    script = {'replies': {'think': {'thought': 'I keep my distance from them.', 'intend': ['keep_distance'], 'say': None},
                          'deliberate': basic_reply(graph, plan=plan)}}
    models = model(run, script)
    run.request(actor, 'verify intents')
    run.start(models, [actor])
    accepted(run, actor, plan)
    time.sleep(2.0)
    run.private(f'SELECT * FROM brain WHERE id = {actor}', 'brain-after')
    run.private(f'SELECT * FROM mind_state WHERE id = {actor}', 'mind-state-after')
    run.private(f'SELECT * FROM activity WHERE id = {actor}', 'activity-after')
    st = run.wait(lambda: next((r for r in run.private(f'SELECT * FROM steer WHERE id = {actor}', 'steer') if r['goal'] == 5), None), 'the band held by steering', 30)
    assert st['target'] == other and abs(st['keep'] - 3) < 1e-3 and abs(st['far'] - 6) < 1e-3 and st['flags'] & 128, st
    # The plan is the character's "current plan" routine, as the model wrote it (normalized).
    plan_row = next(r for r in run.private(f'SELECT * FROM routine WHERE actor = {actor}', 'routines') if r['name'] == 'current plan')
    g = plan_row['graph'].replace(' ', '')
    assert '"skill":"keep_distance"' in g and '"min":3' in g and '"max":6' in g and f'"id":{other}' in g, plan_row['graph'][:400]
    start = run.private(f'SELECT * FROM body WHERE id = {actor}', 'before-approach')[0]
    other_at = run.private(f'SELECT * FROM body WHERE id = {other}', 'other-before')[0]
    # They walk at it, past where it stands: it backs off.
    run.admin('set_behavior', other, json.dumps({'seq': [{'do': {'skill': 'goto', 'target': {'at': [row[0] + 1.5, row[1] + 0.5]}}}, {'wait': 120}]}))
    moved = run.wait(lambda: next((b for b in [run.private(f'SELECT * FROM body WHERE id = {actor}', 'backing')[0]] if math.dist((b['x'], b['y']), (start['x'], start['y'])) > 1.5 or b['vx'] or b['vy']), None), 'it backs off', 15)
    sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    text = '\n'.join(str(m.get('content', '')) for e in sent for m in e['body'].get('messages', []))
    (run.directory / 'sent-prompt-intents.txt').write_text(text)
    for line in ('- keep_distance(target, min, max, run, qty, apart)', '- close_in(target, distance, run, apart)', '- circle(target, radius, side, run, qty, apart)', '- back_off(target, distance, run)', '- follow(target, distance, run, qty)'):
        assert line in text, f'the reference documents {line}'
    assert 'm/s' in text and 'lost sight of them' in text, 'speeds and the sight rule from the laws'
    return {'status': 'pass', 'plan_routine': plan_row['graph'], 'steer': {k: st[k] for k in ('goal', 'target', 'keep', 'far', 'flags')},
            'backing': {k: moved[k] for k in ('x', 'y', 'vx', 'vy', 'speed')}, 'other_from': [other_at['x'], other_at['y']]}


# A line of `prompts::own_timings` ("- strike: winds up 350 ms …") or its heading.
OWN_TIMING = re.compile(r'- [a-z_]+: (winds up \d|a dash at once|raised at once|takes effect at once)|How long the fighting moves you know take')


def timings_told(run, actor, sent, fire_bolt):
    """A mind is told the timing of the fighting moves its character knows, in its own prompt,
    and never of one it does not know (LIVING_SKILL_TIMINGS; docs/COMBAT_MIND.md §3.7): bowshot
    needs no technique, fire bolt needs fire_bolt. The shared system prompt states no timings."""
    knows = {k['technique'] for k in run.private(f'SELECT * FROM know_how WHERE actor = {actor}', 'know-how')}
    assert ('fire_bolt' in knows) == fire_bolt, knows
    if os.environ.get('LIVING_SKILL_TIMINGS', '').strip().lower() in ('0', 'off', 'false'):
        # The switch off: no timing line anywhere in what was sent.
        assert sent and not any(OWN_TIMING.search(json.dumps(e['body'])) for e in sent), 'timings sent with LIVING_SKILL_TIMINGS off'
        return
    users = ['\n'.join(m.get('content', '') for m in e['body'].get('messages', []) if m.get('role') == 'user') for e in sent]
    assert users and all('- bowshot: winds up 300 ms' in u and '- strike: winds up 350 ms' in u for u in users), users[0][-3000:]
    assert all(('- firebolt: winds up 450 ms' in u) == fire_bolt for u in users), [u.count('firebolt') for u in users]
    # The shared system prompt carries no one's own timings. (The world rules' COMBAT law says
    # "A person's attack winds up for 0.65 s": the world's rules, from the cards' timing, not anyone's own line.)
    assert not any(OWN_TIMING.search(system_text(e['body'])) for e in sent), 'timings in the shared system prompt'


@case('roundtrip', 'acts', 'conversation', 'consolidation', 'prune', 'reject', 'only', 'reconnect', 'lod', 'timings')
def basic_case(run, case):
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'],
                                   'say': None}, 'deliberate': basic_reply()}}
    if case == 'roundtrip':
        script['replies']['think']['say'] = 'verify minds round trip speech'
    if case == 'timings':
        # The positive control for roundtrip's timing check: this mind knows fire_bolt.
        run.admin('grant_know_how', actor, 'fire_bolt')
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
        # The default frame (no LIVING_FRAME) is the character frame: no request is player-framed.
        assert not any(PLAYER_FRAME_HEAD in system_text(e['body']) for e in shared.rows(run.directory / 'fake-requests.jsonl'))
        # The body as felt, from the vitals the service subscribes to (owner path): in words, no numbers.
        sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
        felt = [m.split('How your body feels: ', 1)[1].split('\n', 1)[0] for e in sent for m in [json.dumps(e, ensure_ascii=False).replace('\\n', '\n')] if 'How your body feels: ' in m]
        assert felt and not any(ch.isdigit() for ch in felt[0]), felt[:2]
        # The words are the world's `status_of` law's (since rules-senses-outcomes): one word per
        # meter, the health and energy ones always there (the shipped law's `felt`).
        health = ('unhurt', 'a little hurt', 'hurt', 'badly wounded', 'barely alive')
        energy = ('well rested', 'rested', 'a little tired', 'tired', 'exhausted', 'utterly spent')
        parts = [p.strip() for p in felt[0].split(';')[0].split(',')]
        assert any(p in health for p in parts) and any(p in energy for p in parts), felt[:2]
        # The world's rules are told from the laws' own descriptions (docs/WORLD_RULES.md, since
        # laws-2): the sections and the numbers the script's laws give, the same in every prompt.
        told = [json.dumps(e, ensure_ascii=False).replace('\\n', '\n') for e in sent]
        for part in ('SENSES: How far a creature sees and hears, in metres (one tile is one metre). By day one sees 11 m',
                     'MOVING: How creatures move', 'FOOD: berries 12, fish 16', 'SETTLEMENTS: walls block the way',
                     # The attack's windup from the skill cards' timing (`{windup:attack}`), not a hand-written range.
                     "COMBAT: fights are fast. A person's attack winds up for 0.65 s before it lands"):
            assert all(part in m for m in told), part
        timings_told(run, actor, sent, fire_bolt=False)
    elif case == 'timings':
        sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
        timings_told(run, actor, sent, fire_bolt=True)
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


@case('takeover')
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
              # The first takeover's reply takes 8 s; the second takeover's takes 25 s, so it is
              # still in flight when the person returns, however slowly the driver polls.
              'rules': [{'purpose': 'deliberate', 'delay_s': 8, 'times': 1},
                        {'purpose': 'deliberate', 'delay_s': 25, 'times': -1}]}
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
    deliberations = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'deliberate']
    asked_before = len(deliberations())
    # Away again: the held graph is installed again, and the takeover asks for a fresh
    # deliberation (presence.rs take_over: request, then reinstall). That deliberation is the
    # reply in flight, refused on return. The case does not ask again itself: reinstalling the
    # minds' graph counts as having just thought, so the rules ask nothing more for 45 s (the
    # think node's settle) or `think_min_s`; a `set_behavior` think here only showed up when it
    # landed before the mind sent the takeover's prompt (fix-takeover).
    run.wait(lambda: [p for p in run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-taken-2') if p['ai']], 'second takeover', 50)
    again = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-taken-2')[0]
    assert again['source'] == 'mind' and again['plan'] == 'verify minds wait' and again['graph'] == installed, again
    in_flight = run.wait(lambda: deliberations()[asked_before:], 'the takeover deliberation in flight', 40)[0]
    assert 'A quiet moment to take stock' in json.dumps(in_flight), in_flight['body_excerpt']
    run.harness('player', 'move', '0', '1')
    assert time.time() * 1000 < in_flight['at_ms'] + 25_000, 'the person returned after the reply was due'
    run.wait(lambda: 'not your character' in run.log(), 'in-flight reply refused', 50)
    final = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-final')[0]
    assert final['source'] == 'human', final
    assert final['revision'] > again['revision'], (again, final)
    return {'status': 'pass', 'takeover_after_s': (taken['control_ms'] - pending['changed_ms']) / 1000,
            'held_graph': 'kept and reinstalled', 'in_flight': 'refused'}


@case('dealings')
def dealings_case(run):
    """A mind sees and acts on a record (docs/WORLD_RULES.md): another character demands a stone
    of it; the rules tell it and ask its mind; its deliberation shows the demand among its
    dealings (worded by the script's `record_text`), and the (fake) model's act pays it, which
    the rules count: the demand is met and the demander told. Its conversation turns list the
    acts the rules mark for talk (offer_terms, demand)."""
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    # Both are held still before the demander is placed beside the other (as `answers` does):
    # their own instinct graphs would otherwise walk them apart while the mind service starts
    # (the default world's first adult is a guard on its way to the north gate).
    run.admin('set_behavior', other, json.dumps({'wait': 120}))
    run.admin('set_behavior', actor, json.dumps({'wait': 120}))
    run.admin('place_near', other, actor)
    run.admin('grant_items', actor, 'stone', 2)
    pay = basic_reply(acts=[{'do': 'give', 'target': {'id': other}, 'item': 'stone', 'qty': 1}])
    script = {'replies': {'think': {'thought': 'I am asked for a stone.', 'intend': ['give them the stone'], 'say': None},
                          'deliberate': basic_reply()},
              'rules': [{'purpose': 'deliberate', 'contains': 'demanded 1 stone (\\"verify dealing\\") of you', 'reply': pay, 'times': -1}]}
    models = model(run, script)
    run.start(models, [actor])
    accepted_before = len(run.thoughts(actor))
    # The demander, held still beside it, acts as its mind would decide.
    run.admin('mind_act', other, [json.dumps({'do': 'demand', 'target': {'id': actor}, 'item': 'stone', 'qty': 1, 'text': 'verify dealing'})], 'verify-minds')
    try:
        demand = run.wait(lambda: [r for r in run.private('SELECT * FROM record', 'records-demand') if r['kind'] == 'demand'], 'demand record', 60)[0]
    finally:
        # What the demander was told of its act (an outcome or a refusal), kept either way.
        run.private(f'SELECT * FROM experience WHERE observer = {other}', 'demander-experiences')
    told = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'told') if e['kind'] == 'record' and 'demands 1 stone of you' in e['text']], 'told the demand', 30)
    # The rules' `ask` goes through the authority's thinking cadence (`think_min_s`): a mind that
    # thought moments ago is not asked again. Its next thought sees the demand among its dealings.
    asked = bool(run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'asked'))
    met_now = lambda label: [r for r in run.private('SELECT * FROM record', label) if r['id'] == demand['id'] and r['status'] == 'met']
    if not asked and not met_now('records-before-request'):
        # The rules' ask may already have been answered between the two reads (its deliberation
        # row is gone once the mind replies): ask again only if the demand is still open, and
        # take either the pending request or the demand met as the answer (recipes-1).
        run.admin('set_behavior', actor, json.dumps({'think': 'I finished my plan. verify dealing'}))
        run.wait(lambda: run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'pending-dealing') or met_now('records-while-asking'), 'authority deliberation or the demand met', 65)
    met = run.wait(lambda: [r for r in run.private('SELECT * FROM record', 'records-met') if r['id'] == demand['id'] and r['status'] == 'met'], 'demand met', 90)
    sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'deliberate']
    shown = [e for e in sent if "Your dealings and your people's standing" in json.dumps(e) and 'demanded 1 stone' in json.dumps(e)]
    assert shown, 'the deliberation showed the demand among its dealings'
    paid = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {other}', 'demander-told') if 'paid the 1 stone you demanded' in e['text']], 'demander told', 30)
    inv = {r['item']: r['qty'] for r in run.sql(f'SELECT * FROM inventory WHERE owner = {other}', 'demander-inventory')}
    assert inv.get('stone') == 1, inv
    return {'status': 'pass', 'told': told[0]['text'], 'record': met[0]['status'], 'demander_told': paid[0]['text'],
            'deliberations_with_dealings': len(shown), 'thoughts_before': accepted_before, 'asked_by_the_rules': asked}


@case('answers')
def answers_case(run):
    """A mind answers by id (docs/WORLD_RULES.md, "Answering"): another character proposes terms
    to it and offers it a trade. Its deliberation shows the trade's id in "asked of you" and the
    proposal's record id among its dealings; the (fake) model's acts accept the trade by its id
    (though terms stand) and decline the terms by their record id. The goods move, the record is
    declined and the proposer is told."""
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    run.admin('set_behavior', other, json.dumps({'wait': 120}))
    run.admin('set_behavior', actor, json.dumps({'wait': 120}))
    run.admin('place_near', other, actor)
    run.admin('grant_items', actor, 'berries', 3)
    run.admin('grant_items', other, 'wood', 4)
    run.admin('mind_act', other, [json.dumps({'do': 'offer_terms', 'target': {'id': actor}, 'item': 'wood', 'qty': 2, 'want': 'berries', 'want_qty': 2})], 'verify-minds')
    rec = run.wait(lambda: [r for r in run.private('SELECT * FROM record', 'records-offered') if r['kind'] == 'agreement' and r['status'] == 'offered'], 'proposal', 60)[0]
    run.admin('mind_act', other, [json.dumps({'do': 'offer', 'target': {'id': actor}, 'item': 'wood', 'qty': 2, 'want': 'berries', 'want_qty': 1})], 'verify-minds')
    offer = run.wait(lambda: [o for o in run.private('SELECT * FROM trade_offer', 'trade-offer') if o['to'] == actor], 'trade offer', 60)[0]
    answer = basic_reply(acts=[{'do': 'accept', 'target': {'id': other}, 'offer': offer['id']},
                               {'do': 'decline', 'target': {'id': other}, 'record': rec['id']}])
    script = {'replies': {'think': {'thought': 'I am asked to trade.', 'intend': ['answer them'], 'say': None},
                          'deliberate': basic_reply()},
              'rules': [{'purpose': 'deliberate', 'contains': f"toward them, record {rec['id']})", 'reply': answer, 'times': 1}]}
    models = model(run, script)
    wood0 = {r['item']: r['qty'] for r in run.sql(f'SELECT * FROM inventory WHERE owner = {actor}', 'inventory-before')}.get('wood', 0)
    run.start(models, [actor])
    # As in `dealings` (recipes-1): the mind may answer before the first read, its deliberation
    # row gone once it replies. Ask again only while the terms are still open, and take either
    # the pending request or the terms declined as the answer (fix-takeover).
    declined_now = lambda label: [r for r in run.private('SELECT * FROM record', label) if r['id'] == rec['id'] and r['status'] == 'declined']
    if not run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'asked') and not declined_now('records-before-request'):
        run.admin('set_behavior', actor, json.dumps({'think': 'I finished my plan. verify answers'}))
        run.wait(lambda: run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'pending-answers') or declined_now('records-while-asking'), 'authority deliberation or the terms declined', 65)
    declined =run.wait(lambda: [r for r in run.private('SELECT * FROM record', 'records-declined') if r['id'] == rec['id'] and r['status'] == 'declined'], 'proposal declined', 120)
    inv = {r['item']: r['qty'] for r in run.sql(f'SELECT * FROM inventory WHERE owner = {actor}', 'inventory-after')}
    assert inv.get('wood', 0) == wood0 + 2, ('the named trade was taken', wood0, inv)
    assert not [o for o in run.private('SELECT * FROM trade_offer', 'trade-offer-after') if o['id'] == offer['id']], 'the accepted offer is gone'
    told = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {other}', 'proposer-told') if e['kind'] == 'record' and 'declined your terms' in e['text']], 'proposer told', 30)
    sent = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'deliberate']
    blob = [json.dumps(e) for e in sent]
    with_ids = [b for b in blob if f"record {rec['id']})" in b and re.search(r'\\"offer\\": ?%d\b' % offer['id'], b)]
    assert with_ids, 'the deliberation showed the offer id in asked-of-you and the record id in the dealings'
    outcomes = [e['text'] for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'actor-experiences') if e['kind'] == 'act']
    return {'status': 'pass', 'offer': offer['id'], 'record': rec['id'], 'record_status': declined[0]['status'],
            'proposer_told': told[0]['text'], 'outcomes': outcomes[-4:], 'deliberations_with_ids': len(with_ids)}


def _direction_word(a, b):
    """`living_rules::sight::direction_word`: which way `b` lies from `a` (+y is south)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return 'here'
    d = math.degrees(math.atan2(dy, dx))
    for lo, hi, w in ((-22.5, 22.5, 'east'), (22.5, 67.5, 'southeast'), (67.5, 112.5, 'south'), (112.5, 157.5, 'southwest'),
                      (-67.5, -22.5, 'northeast'), (-112.5, -67.5, 'north'), (-157.5, -112.5, 'northwest')):
        if lo <= d < hi:
            return w
    return 'west'


def _rough_dist(d):
    """`living_rules::sight::rough_dist`: whole metres up to 30, then to the nearest ten."""
    return float(round(d)) if d < 30 else float(round(d / 10.0) * 10)


@case('place-bearings')
def place_bearings_case(run):
    """Remembered places in a mind's scene carry a bearing (docs/MOVEMENT_MIND.md, step 3): each of
    the character's own places, out of sight too, is listed under `places` with the same `dir`
    and `dist` words as things in sight, from where it stands, nearest first; a place only
    another character knows is not listed. Checked in the scene the authority wrote and in the
    prompt the fake model is sent. The island, whose residents have places."""
    # The island: its residents have places of their own (homes, work, the square).
    target = (Path(os.environ['CARGO_TARGET_DIR']) if os.environ.get('CARGO_TARGET_DIR') else ROOT / '.local/living/target-resident-island')
    run.harness('launch', '--seed', 'island', '--target-dir', str(target))
    run.harness('doctor')
    # Two adult residents with places of their own.
    places = run.sql('SELECT * FROM place', 'places')
    owners = {p['actor'] for p in places}
    people = sorted((p for p in run.sql("SELECT * FROM character WHERE kind = 'person'", 'people') if p['id'] in owners and p['ai'] and p['alive'] and p['stage'] == 2), key=lambda p: p['id'])
    assert len(people) >= 2, ('two residents with places', len(people))
    eye, other = people[0]['id'], people[1]['id']
    run.admin('set_behavior', eye, json.dumps({'wait': 120}))
    mine = [p for p in places if p['actor'] == eye]
    theirs = [p for p in places if p['actor'] == other]
    names = {p['name'] for p in mine}
    foreign = [p['name'] for p in theirs if p['name'] not in names]
    assert mine, ('the character has places of its own', eye)
    time.sleep(0.5)
    script = {'replies': {'think': {'thought': 'I think of where things are.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    models = model(run, script)
    pending = run.request(eye, 'place bearings')
    run.start(models, [eye])
    request = run.wait(lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')], 'scene sent to the model', 40)[0]
    sent = '\n'.join(str(m.get('content', '')) for m in request['body'].get('messages', []))
    (run.directory / 'sent-prompt.txt').write_text(sent)
    scene = json.loads(pending[0]['scene'])
    listed = scene.get('places', [])
    assert listed, ('the scene lists its places', list(scene))
    # Where it stood (it waits, so its body is at rest): the scene's `you.at` is rounded.
    b = run.sql(f'SELECT x, y, vx, vy FROM body WHERE id = {eye}', 'eye-body')[0]
    assert b['vx'] == 0 and b['vy'] == 0, ('standing still', b)
    at = (b['x'], b['y'])
    expect = sorted(((math.dist(at, (p['x'], p['y'])), p) for p in mine), key=lambda t: t[0])[:12]
    rows = [{'name': p['name'], 'dir': _direction_word(at, (p['x'], p['y'])), 'dist': _rough_dist(d)} for d, p in expect]
    got = [{'name': p['name'], 'dir': p['dir'], 'dist': float(p['dist'])} for p in listed]
    assert got == rows, ('each own place with its bearing from here, nearest first', got, rows)
    far = [r for r in got if r['dist'] > 11]
    assert far, ('a place out of sight is listed too', got)
    assert not any(n in {p['name'] for p in listed} for n in foreign), ('a place only another knows is not listed', foreign)
    assert '"places"' in sent and all(f'"name":"{r["name"]}"' in sent.replace(' ', '') or r['name'] in sent for r in got), 'the prompt carries the places'
    return {'status': 'pass', 'at': at, 'places': got, 'not_listed': foreign[:3]}


@case('sight')
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


@case('fov')
def fov_case(run):
    """Sight that depends on facing (docs/PERCEPTION.md, "Heard, not seen"), on by the admin's
    `set_world_law fov_on`: a resident faces away from another standing 4.5 m behind it. The
    scene its mind is sent lists the other not among the creatures but under "you hear (out of
    sight)", in a person's words (what it sounds like, where from the way it faces and by the
    compass, how far) and with no id; its own facing is in `you`. Its body notices the sound
    ("You hear a person near, behind you, ..."). Given the shipped person instinct
    (`instincts.json`), whose "turn to a sound" branch the character owns, it turns to face the
    sound."""
    people = prepare(run)
    eye, other = [p['id'] for p in people]
    spots = wall_spots(run)
    e = spots['open']
    # The eye on open ground facing west, the other 4.5 m east of it (behind).
    # Both held still first (a resident's own graph would walk it to company meanwhile).
    run.admin('set_behavior', other, json.dumps({'wait': 300}))
    run.admin('set_behavior', eye, json.dumps({'wait': 300}))
    run.admin('place_at', eye, *e)
    run.admin('place_at', other, e[0] + 4.5, e[1])
    run.admin('set_behavior', eye, json.dumps({'seq': [{'do': {'skill': 'face', 'target': {'at': [e[0] - 4.0, e[1]]}}}, {'wait': 300}]}))
    run.wait(lambda: [u for u in run.private('SELECT * FROM skill_use', 'uses-face') if u['actor'] == eye and u['skill'] == 'face' and u['outcome']], 'the eye turned away', 20)
    time.sleep(1.0)
    # Then short waits, so its graph is evaluated (and what it notices taken in) every second;
    # a body in a long wait is looked at again only when the wait ends.
    run.admin('set_behavior', eye, json.dumps({'wait': 1}))
    run.admin('set_world_law', 'fov_on', 'true')
    try:
        # Its body notices the sound (read before the mind connects: the service prunes the
        # experiences it has taken in).
        told = run.wait(lambda: [x for x in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'experience-eye') if x['kind'] == 'signal' and x['text'].startswith('You hear a person near, behind you')], 'the sound noticed', 20)
        assert all(x['subject'] == 0 for x in told), told
        script = {'replies': {'think': {'thought': 'Something behind me.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
        models = model(run, script)
        pending = run.request(eye, 'fov')
        run.start(models, [eye])
        request = run.wait(lambda: [x for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] in ('think', 'deliberate')], 'scene sent to the model', 40)[0]
        sent = '\n'.join(str(m.get('content', '')) for m in request['body'].get('messages', []))
        (run.directory / 'sent-prompt.txt').write_text(sent)
        scene = json.loads(pending[0]['scene']) if pending else {}
        (run.directory / 'scene.json').write_text(json.dumps(scene, indent=2))
        heard = scene.get('you hear (out of sight)', [])
        ids = [c['id'] for c in scene.get('creatures', [])]
        assert other not in ids, ids
        assert any(h.get('what') == 'a person' and h.get('where', '').startswith('behind you') and h.get('how far') == 'near' for h in heard), heard
        assert all(set(h) == {'what', 'where', 'how far'} for h in heard), heard
        assert scene.get('you', {}).get('facing') == 'west', scene.get('you')
        assert 'you hear (out of sight)' in sent and 'behind you, to the east' in sent, 'the model is sent what is heard in words'
        assert re.search(r'"id":\s*%d\b' % other, sent) is None, 'the model is not sent the heard one\'s id'
        # The starting habit (`instincts.json`, a person's instinct graph, which the character
        # owns): standing with a sound within 5 m, it turns to face it. The eye is put back facing
        # away and given the shipped person instinct.
        instinct = json.loads((ROOT / 'living/seeds/instincts.json').read_text())['person']
        habit = 'turn to a sound' in json.dumps(instinct) and '"sound"' in json.dumps(instinct)
        assert habit, 'the person instinct carries the habit'
        run.admin('place_at', eye, *e)
        run.admin('place_at', other, e[0] + 4.5, e[1])
        run.admin('set_behavior', eye, json.dumps({'seq': [{'do': {'skill': 'face', 'target': {'at': [e[0] - 4.0, e[1]]}}}, {'wait': 2}]}))
        time.sleep(3.0)
        since = max([u['at_ms'] for u in run.private('SELECT * FROM skill_use', 'uses-before')] + [0])
        run.admin('set_behavior', eye, json.dumps(instinct))
        # The branch is a continuous guard: once the sound is in view it is no longer heard and the
        # turn may stop there ("broken off"), the other already seen.
        turned = run.wait(lambda: [u for u in run.private('SELECT * FROM skill_use', 'uses-after') if u['actor'] == eye and u['skill'] == 'face' and u['at_ms'] > since and u['outcome'] in ('done', 'broken off')], 'the habit turns the body to the sound', 30)
        # Toward the sound: the turn's aim is where the other stands (the eye may walk on after,
        # its instinct's next branch, so its heading later is not the test).
        aim = (turned[0]['aim_x'] - e[0], turned[0]['aim_y'] - e[1])
        facing = math.atan2(aim[1], aim[0])
        assert abs(facing) < 0.6 and math.hypot(*aim) > 3.0, f'the turn is toward the sound to the east: {aim}'
    finally:
        run.admin('set_world_law', 'fov_on', 'false')
    return {'status': 'pass', 'heard': heard, 'facing': scene.get('you', {}).get('facing'), 'noticed': [x['text'] for x in told], 'habit_turned': turned[:1], 'facing_after': round(facing, 2)}
@case('doing')
def doing_case(run):
    """What someone is visibly doing reaches a mind (docs/PERCEPTION.md, "What someone is visibly
    doing"): a resident faces another 3 m east of it who holds up a guard (`block`, held). The
    scene of its deliberation request lists the other with `visibly` {is: block, phase: holding}
    (`at` only as `you`, when the other's guard happens to face it), the prompt the fake model is sent carries it, and the
    graph grammar the mind is given documents the `doing` condition."""
    people = prepare(run)
    eye, other = [p['id'] for p in people]
    e = wall_spots(run)['open']
    run.admin('set_behavior', other, json.dumps({'wait': 300}))
    run.admin('set_behavior', eye, json.dumps({'wait': 300}))
    run.admin('place_at', eye, *e)
    run.admin('place_at', other, e[0] + 3.0, e[1])
    # Turned away first, then to the other: a graph's turn to where it already faces is refused
    # ("you already face it") and leaves no `skill_use` row, and the eye may face east already;
    # after the turn west, the turn east is a real one with its row (`body.heading` is the
    # segment's start, not the facing now).
    run.admin('set_behavior', eye, json.dumps({'seq': [{'first': [{'do': {'skill': 'face', 'target': {'at': [e[0] - 4.0, e[1]]}}}, {'wait': 0.1}]}, {'wait': 1.5},
                                                       {'first': [{'do': {'skill': 'face', 'target': {'at': [e[0] + 4.0, e[1]]}}}, {'wait': 0.1}]}, {'wait': 300}]}))
    run.wait(lambda: [u for u in run.private('SELECT * FROM skill_use', 'uses-face') if u['actor'] == eye and u['skill'] == 'face' and u['aim_x'] > e[0] and u['outcome']], 'the eye turned to the other', 20)
    run.admin('set_behavior', other, json.dumps({'first': [{'do': {'skill': 'block', 'qty': 5000}}]}))
    run.wait(lambda: [f for f in run.private(f'SELECT * FROM fighter WHERE id = {other}', 'fighter-other') if f['act'] != 0], 'the guard is up', 20)
    script = {'replies': {'think': {'thought': 'They hold up a guard.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    models = model(run, script)
    pending = run.request(eye, 'doing')
    scene = json.loads(pending[0]['scene']) if pending and 'scene' in pending[0] else {}
    (run.directory / 'scene.json').write_text(json.dumps(scene, indent=2))
    entry = next((c for c in scene.get('creatures', []) if c.get('id') == other), {})
    seen = entry.get('visibly') or {}
    # A guard is aimed at nobody: `at` is 'you' only when the other happens to face the eye.
    assert {k: v for k, v in seen.items() if k != 'at'} == {'is': 'block', 'phase': 'holding'} and seen.get('at', 'you') == 'you', entry
    run.start(models, [eye])
    reqs = run.wait(lambda: [x for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] in ('think', 'deliberate')] or None, 'prompts sent to the model', 60)
    run.wait(lambda: [x for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] == 'deliberate'] or None, 'the deliberate prompt', 60)
    reqs = [x for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] in ('think', 'deliberate')]
    text = {x['purpose']: '\n'.join(str(m.get('content', '')) for m in x['body'].get('messages', [])) for x in reqs}
    (run.directory / 'sent-prompts.txt').write_text('\n\n=====\n\n'.join(f'[{k}]\n{v}' for k, v in text.items()))
    sent = '\n'.join(text.values())
    assert re.search(r'"visibly":\s*\{[^}]*"phase":\s*"holding"', sent) and '"is":"block"' in sent.replace(' ', ''), 'the model is sent what the other visibly does'
    grammar = text.get('deliberate', '')
    assert '{"doing": {"who": "person", "is": "hostile", "phase": "winding up"' in grammar and 'about to release' in grammar, 'the grammar documents the doing condition'
    run.admin('set_behavior', other, json.dumps({'wait': 300}))
    return {'status': 'pass', 'visibly': entry.get('visibly'), 'entry': entry, 'purposes': sorted(text)}



def dodge_wall(run):
    """A walkable tile, the next one along an axis walkable and the one after it wall or rock, the
    tile beside the first (a quarter turn) walkable: the tile, the axis, the side."""
    w, h, tiles = terrain(run)
    at = lambda x, y: tiles[y * w + x] if 0 <= x < w and 0 <= y < h else 4
    walk = lambda x, y: at(x, y) not in UNWALKABLE
    bodies = [(b['x'], b['y']) for b in run.sql('SELECT x, y FROM body', 'bodies')]
    for y in range(6, h - 6):
        for x in range(6, w - 6):
            if not walk(x, y) or any(math.dist((x + .5, y + .5), q) < 8 for q in bodies):
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if walk(x + dx, y + dy) and at(x + 2 * dx, y + 2 * dy) in OPAQUE and walk(x - dy, y + dx) and walk(x - dy + dx, y + dx + dy):
                    return (x, y), (dx, dy), (-dy, dx)
    raise RuntimeError('no wall to dodge into on this map')


def fast_config(run, **fast):
    """A rethink config whose `fast` section routes to the fake (`local`)."""
    cfg = json.loads((ROOT / 'living/configs/rethink.json').read_text())
    cfg['fast'] = {'route': 'local', 'timeout_ms': 6000, 'experiences': 12, **fast}
    path = run.directory / 'rethink-fast.json'
    path.write_text(json.dumps(cfg, indent=2))
    return str(path)


FAST_PATCH = {'patch': {'label': 'combat', 'graph': {'first': [{'do': 'dodge'}, {'wait': 0.7}]}}, 'thought': 'verify fast: I will get out of its way.'}
COUNT_WORDS = re.compile(r'again|\btimes\b|\(×|\d+(st|nd|rd|th) time')


@case('fast-lane')
def fast_lane_case(run):
    """The fast lane (docs/FAST_LANE.md) with the fake model: the other strikes at the eye with a
    spear (heavy blow, over and over), the world's `fast_lane_on` law on.

    - (e) asleep: the eye sleeps; the other's one blow issues nothing (it wakes the eye, as before).
    - (a) a blow taken issues one fast request; its prompt holds why now (the eye's own line for
      the blow), what has just happened, the top level and the routines, and no count or "again";
      the reply's `combat` branch is installed through `mind_patch` (source `fast`, a `fast`
      thought), and the eye's next deliberation is not counted as thinking (`deliberated_ms`).
    - (g) the slow deliberation the same blow started (its compile held 5 s) installs after the
      patch and keeps the patched `combat` branch.
    - (b) blows inside `fast_lane_gap_s` (6 s) merge: one fast request in the first 5.5 s.
    - (c) the next request's reply is held 2.5 s; an install in between (admin `set_behavior`)
      changes the plan, and the reply is refused by the plan check ("refused: the plan changed
      since it was asked"), changing nothing.
    - (f) with `fast_lane_on` off, blows ask nothing."""
    people = prepare(run)
    eye, other = [p['id'] for p in people]
    e = wall_spots(run)['open']
    for who in (eye, other):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    run.admin('place_at', eye, *e)
    run.admin('place_at', other, e[0] + 1.2, e[1])
    run.admin('grant_items', other, 'spear', 1)
    run.admin('set_world_law', 'fast_lane_on', 'true')
    script = {'replies': {'think': {'thought': 'Someone is hitting me.', 'intend': ['stand my ground'], 'say': None}, 'deliberate': basic_reply()},
              'rules': [{'purpose': 'fast', 'reply': FAST_PATCH, 'times': 1},
                        {'purpose': 'fast', 'reply': FAST_PATCH, 'delay_s': 2.5, 'times': 1},
                        {'purpose': 'deliberate', 'delay_s': 5, 'times': -1}]}
    # A staged mix, as the shipped models are (compile by stage of attention): with no player in
    # sight the eye is off stage for model routing, which must not keep the fast lane off.
    models = model(run, script)
    models['mixes'] = {'staged': {'deliberate': {'on_stage': 'local', 'off_stage': 'local'}, '*': 'local'}}
    models['assign'] = {people[0]['name']: 'staged'}
    run.start(models, [eye], extra_env={'LIVING_RETHINK_CONFIG': fast_config(run)})
    requests = lambda: [x for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] == 'fast']
    body = lambda x: '\n'.join(str(m.get('content', '')) for m in x['body'].get('messages', []) if m.get('role') == 'user')
    clock = lambda: run.sql('SELECT last_ms FROM clock', 'clock')[0]['last_ms']
    fast_thoughts = lambda: [t for t in run.private(f'SELECT * FROM thought WHERE actor = {eye}', 'thoughts') if t['kind'] == 'fast']
    # (e) asleep: one blow on a sleeper issues nothing.
    run.admin('set_behavior', eye, json.dumps({'do': 'sleep'}))
    run.wait(lambda: [a for a in run.private(f'SELECT * FROM activity WHERE id = {eye}', 'eye-activity') if a['skill'] == 'sleep'] or None, 'the eye asleep', 20)
    run.admin('set_behavior', other, json.dumps({'seq': [{'do': {'skill': 'attack', 'target': {'id': eye}}}, {'wait': 120}]}))
    run.wait(lambda: [x for x in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'eye-told') if x['kind'] == 'attacked'] or None, 'the sleeper struck', 30)
    time.sleep(2.0)
    assert not requests() and not run.private(f'SELECT * FROM fast_ask WHERE actor = {eye}', 'fast-ask-asleep'), 'a sleeper was fast-laned'
    # (a) a blow taken, and (b) the gap.
    run.admin('set_behavior', other, json.dumps({'wait': 300}))
    run.admin('set_behavior', eye, json.dumps({'wait': 300}))
    time.sleep(8.0)
    t0 = clock()
    run.admin('set_behavior', other, json.dumps({'first': [{'do': {'skill': 'attack', 'target': {'id': eye}}}, {'wait': 0.3}]}))
    first = run.wait(lambda: requests() or None, 'a fast request after a blow', 30)[0]
    patched = run.wait(lambda: [b for b in run.sql(f'SELECT * FROM brain WHERE id = {eye}', 'brain-patched') if b['source'] == 'fast' and '"wait":0.7' in b['graph'].replace(' ', '')] or None, 'the fast patch installed', 20)[0]
    text = body(first)
    why = text.split('# Why now')[1].split('# What has just happened')[0]
    blows = [x['text'] for x in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'eye-blows') if x['kind'] == 'attacked' and x['at_ms'] >= t0]
    assert '# What has just happened' in text and '# Your top level' in text and '# Your routines' in text, text[:600]
    # Stable parts first (the providers' prefix caches): who, the top level, the routines, then why now.
    assert text.startswith('# Who you are') and text.index('# Your routines') < text.index('# Why now') < text.index('# What has just happened'), text[:600]
    assert blows and any(b in why for b in blows), {'why': why, 'blows': blows}
    assert not COUNT_WORDS.search(why) and not COUNT_WORDS.search(text.split('# What has just happened')[1]), 'a count or "again" in the fast prompt'
    assert any('combat branch rewritten' in t['summary'] for t in fast_thoughts()), fast_thoughts()
    time.sleep(5.5)
    in_gap = [x for x in requests() if x['at_ms'] < first['at_ms'] + 5500]
    assert len(in_gap) == 1, f'{len(in_gap)} fast requests inside the 6 s gap'
    # (g) the slow deliberation the blow started lands after the patch and keeps its branch.
    slow = run.wait(lambda: [b for b in run.sql(f'SELECT * FROM brain WHERE id = {eye}', 'brain-slow') if b['source'] == 'mind' and b['installed_ms'] > patched['installed_ms']] or None, 'the slow install after the patch', 30)[0]
    assert '"wait":0.7' in slow['graph'].replace(' ', ''), 'the slow install dropped the fast-patched combat branch'
    # (c) the plan check: the next reply is held; an install meanwhile changes the plan.
    second = run.wait(lambda: requests()[1:] or None, 'a second fast request', 30)[0]
    run.admin('set_behavior', eye, json.dumps({'wait': 30}))
    refused = run.wait(lambda: [t for t in fast_thoughts() if t['summary'].startswith('refused: the plan changed')] or None, 'the stale reply refused', 20)
    brain = run.sql(f'SELECT * FROM brain WHERE id = {eye}', 'brain-after-refusal')[0]
    assert brain['source'] != 'fast' or brain['installed_ms'] < second['at_ms'], brain
    # (f) the switch off.
    run.admin('set_world_law', 'fast_lane_on', 'false')
    time.sleep(3.0)
    n = len(requests())
    time.sleep(10.0)
    assert len(requests()) == n, 'fast requests with the fast lane off'
    run.admin('set_behavior', other, json.dumps({'wait': 300}))
    (run.directory / 'fast-prompt.txt').write_text(text)
    return {'status': 'pass', 'fast_requests': len(requests()), 'refused': [t['summary'] for t in refused][:2], 'why': why.strip()[:200]}


@case('fast-takeover')
def fast_takeover_case(run):
    """(d) The controller rule (docs/FAST_LANE.md): a player's character, taken over by the minds,
    is struck and its fast request's reply held 12 s; its person comes back meanwhile (handback):
    the request is dropped (`fast_ask` gone) and the late reply changes nothing. Away again, the
    minds take it over again; the reply prepared before is refused (no open request), and the
    played body got no fast patch."""
    people = prepare(run)
    other = people[0]['id']
    # Taken over 5 s after its person is gone (the `takeover_s` law), so the second takeover
    # comes before the held reply.
    run.admin('set_world_law', 'takeover_s', '5')
    run.harness('player', 'join', 'FastAway')
    me = run.sql("SELECT id FROM character WHERE name = 'FastAway'", 'player')[0]['id']
    run.admin('set_world_law', 'fast_lane_on', 'true')
    script = {'replies': {'think': {'thought': 'Alone now, I wait.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()},
              'rules': [{'purpose': 'fast', 'reply': FAST_PATCH, 'delay_s': 12, 'times': -1}]}
    run.start(model(run, script), [me], extra_env={'LIVING_RETHINK_CONFIG': fast_config(run, timeout_ms=30000)})
    run.wait(lambda: [p for p in run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-taken') if p['ai']] or None, 'takeover', 60)
    at = run.sql(f'SELECT x, y FROM body WHERE id = {me}', 'me-at')[0]
    run.admin('place_at', other, at['x'] + 1.2, at['y'])
    run.admin('grant_items', other, 'spear', 1)
    run.admin('set_behavior', other, json.dumps({'seq': [{'do': {'skill': 'attack', 'target': {'id': me}}}, {'wait': 120}]}))
    requests = lambda: [x for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] == 'fast']
    run.wait(lambda: requests() or None, 'a fast request for the taken-over character', 30)
    run.harness('player', 'move', '1', '0')
    back = run.sql(f'SELECT * FROM character WHERE id = {me}', 'character-back')[0]
    assert not back['ai'], back
    assert not run.private(f'SELECT * FROM fast_ask WHERE actor = {me}', 'fast-ask-back'), 'the request outlived the handback'
    # Away again (its connection closed): the minds take over again before the reply comes.
    run.wait(lambda: [p for p in run.private(f'SELECT * FROM presence WHERE id = {me}', 'presence-again') if p['ai']] or None, 'takeover again', 60)
    time.sleep(14.0)
    brains = run.sql(f'SELECT * FROM brain WHERE id = {me}', 'brain-end')
    fast = [t for t in run.private(f'SELECT * FROM thought WHERE actor = {me}', 'thoughts') if t['kind'] == 'fast']
    assert brains and brains[0]['source'] != 'fast' and '"wait":0.7' not in brains[0]['graph'].replace(' ', ''), brains
    assert not [t for t in fast if 'rewritten' in t['summary']], fast
    return {'status': 'pass', 'fast_requests': len(requests()), 'fast_thoughts': [t['summary'] for t in fast]}


@case('dodge-told')
def dodge_told_case(run):
    """A dodge's outcome reaches the mind truthfully, and a cooldown's refusals once (fix-dodge-told;
    docs/COMBAT.md "A dodge over before the blow came"). The eye dodges, toward the other, as
    soon as the other's heavy blow (`attack`, a spear) winds up at it: the dash is over before the
    blow releases, the blow lands, and the eye is told "You failed to dodge: it was over before the
    blow came" (and its `skill_use` says so). Then it retries a dodge every tick for 4 s: "dodge is
    not ready yet" is told at most once per cooldown (not once a tick). The prompt the fake model
    is sent carries the first line, and no more "not ready yet" lines than cooldowns."""
    people = prepare(run)
    eye, other = [p['id'] for p in people]
    # The eye two tiles short of a wall, the other beside it: the eye's dodge, aimed at the wall,
    # has room for half its 2.6 m and ends within the blow's reach (1.4 m and the 0.6 m lunge).
    (x, y), (dx, dy), (sx, sy) = dodge_wall(run)
    e = (x + 0.5, y + 0.5)
    for who in (eye, other):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    run.admin('place_at', eye, *e)
    run.admin('place_at', other, e[0] + sx, e[1] + sy)
    run.admin('grant_items', other, 'spear', 1)
    # The mind runs throughout: a prompt lists what it was told while connected.
    script = {'replies': {'think': {'thought': 'My dodge was too soon.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    run.start(model(run, script), [eye])
    time.sleep(3.0)
    run.admin('set_behavior', eye, json.dumps({'first': [
        {'if': {'cond': {'doing': {'is': 'attack', 'phase': 'winding up', 'at_me': True}}, 'then': {'do': {'skill': 'dodge', 'target': {'at': [e[0] + 3 * dx, e[1] + 3 * dy]}}}}},
        {'wait': 0.2}]}))
    t0 = run.sql('SELECT last_ms FROM clock', 'clock')[0]['last_ms']
    run.admin('set_behavior', other, json.dumps({'seq': [{'do': {'skill': 'attack', 'target': {'id': eye}}}, {'wait': 300}]}))
    early = run.wait(lambda: [x for x in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'eye-told') if x['at_ms'] >= t0 and 'it was over before the blow came' in x['text']] or None, 'the eye told its dodge was over before the blow came', 20)
    uses = [u for u in run.private('SELECT * FROM skill_use', 'uses-early') if u['at_ms'] >= t0 and u['actor'] in (eye, other)]
    blow = [u for u in uses if u['actor'] == other and u['skill'] == 'attack']
    dodge = [u for u in uses if u['actor'] == eye and u['skill'] == 'dodge' and u['outcome'].startswith('made way: it was over before')]
    assert early[0]['text'] == 'You failed to dodge: it was over before the blow came', early
    assert blow and blow[-1]['outcome'].startswith('hit for') and dodge and dodge[-1]['accepted_ms'] >= blow[-1]['accepted_ms'], (blow, dodge)
    # A dodge whose condition holds and nothing else: started again on the next tick after each
    # one, so refused until it is ready (r2c's plans), for 4 s; once the mind has answered the
    # attack (its reply installs a plan of its own).
    run.admin('set_behavior', other, json.dumps({'wait': 300}))
    run.wait(lambda: not run.private(f'SELECT * FROM deliberation WHERE actor = {eye}', 'pending-after-attack') or None, 'the mind answered the attack', 60)
    time.sleep(2.0)
    t1 = run.sql('SELECT last_ms FROM clock', 'clock')[0]['last_ms']
    run.admin('set_behavior', eye, json.dumps({'if': {'cond': {'chance': 1.0}}, 'then': {'do': 'dodge'}}))
    time.sleep(4.0)
    run.admin('set_behavior', eye, json.dumps({'wait': 300}))
    told = [x for x in run.private(f'SELECT * FROM experience WHERE observer = {eye}', 'eye-told-streak') if x['at_ms'] >= t1 and 'is not ready yet' in x['text']]
    made = [u for u in run.private('SELECT * FROM skill_use', 'uses-streak') if u['actor'] == eye and u['skill'] == 'dodge' and u['at_ms'] >= t1 and u['accepted_ms']]
    assert made and len(told) <= len(made) + 1, {'told': [x['text'] for x in told], 'dodges': len(made)}
    run.request(eye, 'dodge-told')
    body = lambda x: '\n'.join(str(m.get('content', '')) for m in x['body'].get('messages', []))
    asked = run.wait(lambda: [body(x) for x in shared.rows(run.directory / 'fake-requests.jsonl') if x['purpose'] in ('think', 'deliberate') and 'verify dodge-told' in body(x)] or None, 'the prompt of the asked thought', 90)
    (run.directory / 'sent-prompts.txt').write_text('\n\n=====\n\n'.join(body(x) for x in shared.rows(run.directory / 'fake-requests.jsonl')))
    text = asked[0]
    assert 'You failed to dodge: it was over before the blow came' in text, 'the model is told the dodge was over before the blow came'
    waiting = len(re.findall(r'dodge is not ready yet', text))
    assert waiting <= len(made) + 1, {'not_ready_lines_in_prompt': waiting, 'dodges': len(made)}
    return {'status': 'pass', 'early': early[0]['text'], 'not_ready_told': len(told), 'dodges_in_streak': len(made), 'not_ready_in_prompt': waiting}

@case('death-names')
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


@case('watch-fight')
def watch_fight_case(run):
    """A mind watching others fight can still tell who is winning and who fell, from folded lines
    (docs/BATTLE_SCALE.md, fix 4; `witness_fold_ms`). W, the only mind, stands between two fights
    it is not party to: A, with a spear, strikes V until V falls; C strikes D, who blocks. The
    think prompt W's model is sent then carries W's folded lines: each fight's blows counted with
    their outcomes (A's landed on V, D blocked C), V's fall, and each stranger anchored by the id
    W's scene knows them by. The blows its lines count are the blows W could see (`fight_seen`
    rows naming W, read while the fights go on), no more than the strikes the rules resolved."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 5, True)
    made = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    assert len(made) == 5, made
    w, a, v, c, d = made
    for who in made:
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    for who in (a, v, c, d):
        run.admin('place_near', who, w)
    time.sleep(1.0)
    script = {'replies': {'think': {'thought': 'I watch the fighting.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    run.start(model(run, script), [w])
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    sent_text = lambda e: '\n'.join(str(m.get('content', '')) for m in e['body'].get('messages', []))
    asked = lambda marker: [sent_text(e) for e in requests() if f'verify {marker}' in sent_text(e)]
    run.admin('set_behavior', w, json.dumps({'think': 'I finished my plan. verify before'}))
    run.wait(lambda: asked('before'), 'first prompt', 60)
    accepted(run, w)
    deliberated = time.monotonic()
    t0 = run.sql('SELECT last_ms FROM clock', 'clock-0')[0]['last_ms']
    run.admin('grant_items', a, 'spear', 1)
    run.admin('set_behavior', d, json.dumps({'first': [{'if': {'cond': {'threatened': True}, 'then': {'do': {'skill': 'block'}}}}, {'wait': 60}]}))
    run.admin('set_behavior', c, json.dumps({'first': [{'do': {'skill': 'attack', 'target': {'id': d}}}, {'wait': 60}]}))
    run.admin('set_behavior', a, json.dumps({'first': [{'do': {'skill': 'attack', 'target': {'id': v}}}, {'wait': 60}]}))
    # The blows W could see (`fight_seen` rows naming W), read while the fights go on: a row goes
    # once every onlooker has been told it.
    # W's lines too: its mind consolidates as the fight goes on, and consolidation takes the
    # integrated rows out of the inbox (`mind_consolidated`).
    rows, w_lines, start = {}, {}, time.monotonic()

    def gather():
        for r in run.private('SELECT * FROM fight_seen', 'fight-seen'):
            rows[r['id']] = r
        for e in run.private(f'SELECT * FROM experience WHERE observer = {w}', f'experiences-{w}'):
            if e['kind'] == 'fight' and e['at_ms'] >= t0:
                w_lines[e['id']] = e
    while time.monotonic() - start < 90:
        gather()
        if not run.sql(f'SELECT alive FROM character WHERE id = {v}', 'v-alive')[0]['alive']:
            break
        time.sleep(0.3)
    for who in (a, c):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    # The law in force: the world's own value, else the installed script's.
    own = [r['value'] for r in run.private('SELECT * FROM world_law', 'laws') if r['name'] == 'witness_fold_ms']
    src = run.private("SELECT source FROM script WHERE name = 'skills'", 'script')[0]['source']
    fold = float(own[0]) if own else float(re.search(r'\bwitness_fold_ms: ([0-9.]+)', src).group(1))
    # Blows still in flight land first, then every onlooker's window holding them ends.
    end = time.monotonic() + 3 + fold / 1000 + 1.5
    while time.monotonic() < end:
        gather()
        time.sleep(0.3)
    seen_by_w = [r for r in rows.values() if (r['attacker'], r['victim']) in ((a, v), (c, d)) and w in [x & 0x7FFFFFFF for x in r['onlookers']]]
    exp = lambda who: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {who}', f'experiences-{who}') if e['at_ms'] >= t0]
    lines = [e['text'] for e in sorted(w_lines.values(), key=lambda e: e['id'])]
    # The strikes as the rules resolved them (`skill_use` outcomes); V's own lines go with V's death.
    struck = [u for u in run.sql('SELECT * FROM skill_use', 'skill-uses') if (u['actor'], u['target']) in ((a, v), (c, d)) and u['outcome_ms'] >= t0
              and re.match(r'(hit for|blocked|killed|dodged|missed)', u['outcome'] or '')]
    counted = sum(int(n) for n in re.findall(r'(\d+) (?:blow|shot)s? \(', ' '.join(lines)))
    time.sleep(max(0.0, 21 - (time.monotonic() - deliberated)))
    run.admin('set_behavior', w, json.dumps({'think': 'I finished my plan. verify watched'}))
    prompt = run.wait(lambda: asked('watched'), 'prompt after the fights', 60)[0]
    (run.directory / 'prompt-watched.txt').write_text(prompt)
    in_prompt = [l for l in prompt.split('\n') if re.search(r'\d+ blows? \(', l)]
    a_on_v = re.compile(rf'#{a}\) (?:attacked|kept on at) [^:]*#{v}\): \d+ blows? \([^)]*landed')
    texts = {'fold_ms': fold, 'w_fight_lines': lines[:8], 'w_line_count': len(lines), 'blows_counted': counted, 'struck': len(struck), 'seen_by_w': len(seen_by_w),
             'prompt_lines': in_prompt[:8]}
    checks = {
        # Rows are read by polling (a lower bound); W among every row read saw the fights whole.
        'folded_lines_count_every_blow_w_saw': 0 < len(seen_by_w) <= counted <= len(struck) and counted > len(lines) > 0
                                                 and (counted == len(struck) if len(seen_by_w) == len([r for r in rows.values() if (r['attacker'], r['victim']) in ((a, v), (c, d))]) else True),
        'who_is_winning_a_landed_on_v': any(a_on_v.search(l) for l in lines),
        'd_blocked_c': any(re.search(rf'#{c}\) (?:attacked|kept on at) [^:]*#{d}\): \d+ blows? \([^)]*blocked', l) for l in lines),
        'who_fell_v': sum(l.count(f'#{v}) fell.') for l in lines) == 1,
        'prompt_carries_the_folded_lines': in_prompt and any(a_on_v.search(l) for l in in_prompt) and any(f'#{v}) fell.' in l for l in in_prompt),
    }
    texts['checks'] = checks
    (run.directory / 'watch-fight.json').write_text(json.dumps(texts, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **texts}


FAR = 'someone too far away to make out'
FAR_HANDLE_BASE = 1_000_000_000


@case('far-figure')
def far_figure_case(run):
    """A mind cannot name someone it cannot make out (far-handle, docs/STRANGERS.md §1). The mind's
    character M and its neighbour F share a community, and F is in M's relations (the prompt lists
    "F (#id)"). An overlay of `perceived_of` makes everyone past 4 m `far` (as Cullet's law past
    24 m). F stands 5 m from M and says a line. M's prompt shows a figure too far away to make out
    under a handle of its own (not F's id), F's line tagged with that handle, and nowhere ties the
    figure to F's name or id. M acts on the handle (a wave reaches F). F comes within 2 m: M is
    told whom the figure was (the handle joined to F's id), and the scene names F."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 2, True)
    m, f = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    names = {c['id']: c['name'] for c in run.sql('SELECT id, name FROM character', 'names')}
    fname = names[f]
    for who in (m, f):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    act = lambda who, node: run.admin('mind_act', who, [json.dumps(node)], 'verify-minds')
    run.admin('place_near', f, m)
    act(m, {'do': 'found', 'text': f'Verify Strand {m}'})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {m}', 'm-membership'), 'community founded', 20)
    act(f, {'do': 'join', 'target': {'id': m}})
    run.wait(lambda: run.sql(f'SELECT * FROM join_request WHERE asker = {f}', 'join-request'), 'join request', 20)
    act(m, {'do': 'welcome', 'target': {'id': f}})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {f}', 'f-membership'), 'neighbour welcomed', 20)
    run.admin('set_background', m, json.dumps({'sheet': {'narrative': 'I keep the strand with my neighbour.', 'values': ['care'], 'goals': ['keep the strand'],
        'mood': 'settled', 'relations': [{'id': f, 'trust': 50, 'affinity': 50, 'label': 'neighbour', 'note': 'lives two doors down'}]}}))
    # Everyone past 4 m is too far away to make out.
    shipped = (ROOT / 'living/scripts/skills.rhai').read_text()
    overlay = shipped.replace('fn perceived_of(p)', 'fn base_perceived_of(p)', 1) + \
        '\nfn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }\n'
    (run.directory / 'far-overlay.rhai').write_text(overlay)
    subprocess.run([sys.executable, str(ROOT / 'living/tools/install_script.py'), run.db, str(run.directory / 'far-overlay.rhai')], check=True, cwd=ROOT, capture_output=True, timeout=120)
    try:
        body = run.sql(f'SELECT * FROM body WHERE id = {m}', 'm-body')[0]
        run.admin('place_at', f, body['x'] + 5.0, body['y'])
        time.sleep(2.0)
        script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
        run.start(model(run, script), [m])
        # F says a line to the room, as the world's minds say one (`mind_say`, admin).
        run.admin('mind_say', f, 'Fine weather on the strand today.', 0, 'say', 0, {'kind': 'talk', 'summary': 'verify far-figure line', 'detail': '', 'latency_ms': 0, 'tokens': 0, 'model': '', 'reference': ''})
        time.sleep(2.0)
        requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
        sent_text = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
        asked = lambda marker: [sent_text(e) for e in requests() if f'verify {marker}' in sent_text(e)]
        run.admin('set_behavior', m, json.dumps({'think': 'I finished my plan. verify far'}))
        prompt = run.wait(lambda: asked('far'), 'prompt with the far figure', 60)[0]
        (run.directory / 'prompt-far.txt').write_text(prompt)
        handles = sorted({int(h) for h in re.findall(r'"id": ?(\d{10,})', prompt) if int(h) >= FAR_HANDLE_BASE})
        figure = [l for l in prompt.split('\n') if FAR in l]
        tied = [l for l in prompt.split('\n') if any(str(h) in l for h in handles) and (fname in l or f'#{f})' in l or f'=#{f}' in l or f'"id": {f}' in l or f'"id":{f}' in l)]
        checks = {
            'scene_has_a_far_figure_by_handle': bool(handles) and any(FAR in l for l in figure),
            'scene_has_no_entry_with_f_id': not re.search(r'"id": ?%d\b' % f, prompt),
            'relations_list_names_f': f'{fname} (#{f})' in prompt,
            'f_line_tagged_by_handle': any('Fine weather' in l and any(f'=#{h}' in l for h in handles) and f'#{f}' not in l and fname not in l for l in prompt.split('\n')),
            'nothing_ties_the_figure_to_f': not tied,
        }
        # The mind acts on the handle: a wave reaches F.
        if handles:
            t0 = run.sql('SELECT last_ms FROM clock', 'clock')[0]['last_ms']
            act(m, {'do': 'wave', 'target': {'id': handles[0]}})
            waves = run.wait(lambda: [u for u in run.private(f'SELECT * FROM skill_use WHERE actor = {m}', 'waves') if u['skill'] == 'wave' and u['at_ms'] >= t0], 'the wave at the handle', 20)
            checks['an_act_on_the_handle_reaches_f'] = waves[0]['target'] == f
        # Brought within 2 m: M is told whom the figure was; the scene names F.
        run.admin('place_at', f, body['x'] + 2.0, body['y'])
        time.sleep(21.0)
        run.admin('set_behavior', m, json.dumps({'think': 'I finished my plan. verify near'}))
        near = run.wait(lambda: asked('near'), 'prompt with F made out', 60)[0]
        (run.directory / 'prompt-near.txt').write_text(near)
        made = [e for e in run.private(f'SELECT * FROM experience WHERE observer = {m}', 'experiences-m') if e['kind'] == 'made_out']
        checks['made_out_joins_handle_to_f'] = any(e['subject'] == f and e['object'] in handles for e in made)
        checks['near_scene_names_f'] = bool(re.search(r'"id": ?%d\b' % f, near)) and f'"{fname}"' in near
    finally:
        subprocess.run([sys.executable, str(ROOT / 'living/tools/install_script.py'), run.db], cwd=ROOT, capture_output=True, timeout=120)
    result = {'f': f, 'name': fname, 'handles': handles, 'figure_lines': figure[:4], 'tied': tied, 'made_out': [e['text'] for e in made], 'checks': checks}
    (run.directory / 'far-figure.json').write_text(json.dumps(result, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('house-owner')
def house_owner_case(run):
    """Whose a house is reaches a mind's prompt whatever its owner is doing (house-owner-label,
    docs/PERCEPTION.md "Whose a thing is"). M and its neighbour F share a community; X is a
    stranger to M. F has a house, X a house and a storage. An overlay makes anyone past 4 m too far
    away to make out (as Cullet's `perceived_of` past 24 m) and lets a storage show its owner
    (`shows_owner`). With F and X 30 m off, M's think prompt shows F's house with F's name
    (`home_of`, `by`), X's house with no owner, X's storage with X's name (it shows its owner), and
    no structure labelled by a far figure. What M notices of F's house and X's storage names them
    and is tagged with their ids (`{F=#id}`), never a far figure's handle; X's house is noticed
    with no tag (an owner the line does not name is not tied to it)."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 3, True)
    m, f, x = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    names = {c['id']: c['name'] for c in run.sql('SELECT id, name FROM character', 'names')}
    for who in (m, f, x):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    act = lambda who, node: run.admin('mind_act', who, [json.dumps(node)], 'verify-minds')
    run.admin('place_near', f, m)
    act(m, {'do': 'found', 'text': f'Verify Row {m}'})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {m}', 'm-membership'), 'community founded', 20)
    act(f, {'do': 'join', 'target': {'id': m}})
    run.wait(lambda: run.sql(f'SELECT * FROM join_request WHERE asker = {f}', 'join-request'), 'join request', 20)
    act(m, {'do': 'welcome', 'target': {'id': f}})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {f}', 'f-membership'), 'neighbour welcomed', 20)
    shipped = (ROOT / 'living/scripts/skills.rhai').read_text()
    overlay = shipped.replace('fn perceived_of(p)', 'fn base_perceived_of(p)', 1).replace('fn structures()', 'fn base_structures()', 1) + \
        '\nfn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }\n' + \
        'fn structures() { let l = base_structures(); for i in 0..l.len() { if l[i].name == "storage" { l[i].shows_owner = true; } } l }\n'
    (run.directory / 'house-overlay.rhai').write_text(overlay)
    subprocess.run([sys.executable, str(ROOT / 'living/tools/install_script.py'), run.db, str(run.directory / 'house-overlay.rhai')], check=True, cwd=ROOT, capture_output=True, timeout=120)
    try:
        body = run.sql(f'SELECT * FROM body WHERE id = {m}', 'm-body')[0]
        bx, by = body['x'], body['y']
        # Offsets toward the middle of the map (a body near an edge has no room the other way).
        dy = 40.0 if by < 200 else -40.0
        dx = 30.0 if bx < 200 else -30.0
        # M away while the houses go up, so it first sees them with their owners gone.
        run.admin('place_at', m, bx, by + dy)
        run.admin('place_at', f, bx - 3.0, by)
        run.admin('place_structure', f, 'house')
        run.admin('place_at', x, bx + 3.0, by)
        run.admin('place_structure', x, 'house')
        run.admin('place_at', x, bx + 3.0, by + 2.0)
        run.admin('place_structure', x, 'storage')
        st = {(s['owner'], s['kind']): s['id'] for s in run.sql('SELECT * FROM structure', 'structures') if s['owner'] in (f, x)}
        run.admin('place_at', f, bx + dx, by - 3.0)
        run.admin('place_at', x, bx + dx, by + 3.0)
        t0 = run.sql('SELECT last_ms FROM clock', 'clock')[0]['last_ms']
        run.admin('place_at', m, bx, by + 1.0)
        time.sleep(2.0)
        script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
        run.start(model(run, script), [m])
        requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
        sent_text = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
        run.request(m, 'house')
        prompt = run.wait(lambda: [sent_text(e) for e in requests() if 'verify house' in sent_text(e)], 'prompt with the houses', 60)[0]
        (run.directory / 'prompt-house.txt').write_text(prompt)
        entries, dec = {}, json.JSONDecoder()
        for at in [mm.start() for mm in re.finditer(r'\{"at":', prompt)]:
            try:
                o, _ = dec.raw_decode(prompt, at)
            except ValueError:
                continue
            if o.get('kind') in ('house', 'storage'):
                entries[o.get('id')] = o
        fh, xh, xs = entries.get(st.get((f, 'house'))), entries.get(st.get((x, 'house'))), entries.get(st.get((x, 'storage')))
        # The mind integrates its experience rows; what it noticed is read from what it was sent.
        everything = '\n'.join(sent_text(e) for e in shared.rows(run.directory / 'fake-requests.jsonl'))
        noticed = sorted(set(re.findall(r'You notice a (?:house|storage)[^"\\\n]*', everything)))
        checks = {
            'neighbour_away_house_named': bool(fh) and fh.get('home_of') == names[f] and fh.get('by') == names[f],
            'stranger_house_unnamed': bool(xh) and 'home_of' not in xh and 'by' not in xh,
            'shows_owner_storage_named': bool(xs) and xs.get('by') == names[x],
            'no_structure_by_a_far_figure': not [o for o in entries.values() if FAR in json.dumps(o)],
            'noticed_house_built_by_neighbour_tagged_by_id': any(f'house built by {names[f]}' in t and f'{{{names[f]}=#{f}}}' in t for t in noticed),
            'noticed_storage_built_by_x_tagged_by_id': any(f'storage built by {names[x]}' in t and f'{{{names[x]}=#{x}}}' in t for t in noticed),
            'stranger_house_noticed_untagged': any(t.startswith('You notice a house,') and '=#' not in t for t in noticed),
            'no_notice_line_tagged_by_a_far_handle': not [t for t in noticed if FAR in t],
        }
    finally:
        subprocess.run([sys.executable, str(ROOT / 'living/tools/install_script.py'), run.db], cwd=ROOT, capture_output=True, timeout=120)
    result = {'m': m, 'f': names[f], 'x': names[x], 'entries': list(entries.values()), 'noticed': noticed, 'checks': checks}
    (run.directory / 'house-owner.json').write_text(json.dumps(result, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('first-sight')
def first_sight_case(run):
    """A first sight of someone one cannot place asks for one thought (docs/FIRST_SIGHT.md, the
    `first_sight_thinks` law), and the think request the model is sent carries the first-sight
    line word for word under "# Why you are thinking now". M's mind runs on the fake model; once
    its first thought has settled (past `think_min_s`), U, a stranger to M, is placed 2 m away.
    The laws are set with `set_world_law` (the gap at 0: M's opening thought may itself be a first
    sight of someone else in view) and restored."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 2, True)
    m, u = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    for who in (m, u):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    body = run.sql(f'SELECT * FROM body WHERE id = {m}', 'm-body')[0]

    def place_off(who, offsets):
        # The first offset with a free walkable tile (water, rock or a crowd may fill one).
        for dx, dy in offsets:
            try:
                run.admin('place_at', who, body['x'] + dx, body['y'] + dy)
                return (dx, dy)
            except RuntimeError:
                continue
        raise RuntimeError(f'no free tile for {who} at any of {offsets}')
    place_off(u, [(60.0, 60.0), (-60.0, 60.0), (60.0, -60.0), (-60.0, -60.0), (70.0, 0.0), (-70.0, 0.0), (0.0, 70.0), (0.0, -70.0)])
    run.admin('set_world_law', 'first_sight_thinks', 'true')
    # (no gap: M's opening thought may itself be a first sight of someone else in view)
    run.admin('set_world_law', 'first_sight_gap_s', '0')
    try:
        laws = {w['name']: w['value'] for w in run.sql('SELECT * FROM world_law', 'world-law')}
        assert laws.get('first_sight_thinks') == 'true', laws
        script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
        run.start(model(run, script), [m])
        requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'think']
        sent_text = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
        # Past think_min_s (20 s) of any opening thought (a first sight of someone else in view).
        time.sleep(30.0)
        seen_before = len(requests())
        t0 = run.sql('SELECT last_ms FROM clock', 'clock')[0]['last_ms']
        place_off(u, [(2.0, 0.0), (-2.0, 0.0), (0.0, 2.0), (0.0, -2.0), (1.5, 1.5), (-1.5, -1.5)])
        line = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {m}', 'experiences-m')
                                 if e['at_ms'] >= t0 and e['text'].startswith('For the first time you see') and u in (e['subject'], e['object'])], 'the first-sight line', 20)[0]['text']
        asked = run.wait(lambda: [sent_text(e) for e in requests()[seen_before:] if line in sent_text(e)], 'a think request carrying the line', 60)[0]
        (run.directory / 'prompt-first-sight.txt').write_text(asked)
        why = asked.split('# Why you are thinking now\n', 1)[1].split('\n\n', 1)[0] if '# Why you are thinking now\n' in asked else ''
        checks = {
            'line_names_a_stranger': 'a stranger' in line,
            'reason_section_holds_the_line_word_for_word': any(l.strip() == line or l.strip().endswith(line) for l in why.split('\n')),
            'no_words_added_to_the_line': not any(w in why.lower() for w in ('newcomer', 'visitor', 'new to you', 'near your home', 'worth')),
        }
    finally:
        run.admin('set_world_law', 'first_sight_thinks', 'false')
        run.admin('set_world_law', 'first_sight_gap_s', '300')
    result = {'m': m, 'u': u, 'line': line, 'why': why, 'checks': checks}
    (run.directory / 'first-sight.json').write_text(json.dumps(result, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}



TALK_THOUGHT = {'kind': 'talk', 'summary': 'verify room-address line', 'detail': '', 'latency_ms': 0, 'tokens': 0, 'model': '', 'reference': ''}


@case('room-address')
def room_address_case(run):
    """How a line to the room was said reaches a mind in its own labels (speech-address,
    `speech::room_address`). H (thought for) founds a community and welcomes K; S and U are
    strangers to H. All four stand within a few metres. S says to the room a line naming K and U:
    H's experience reads "A stranger said to the room, naming <K> and a stranger: …"
    (K known, U not; no name H does not know). Then S says a line to K, and a line to the room:
    H's experience reads "… said to the room while talking with <K>: …". H's next prompt carries
    both lines as they were heard."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 4, True)
    h, k, u, sp = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    names = {c['id']: c['name'] for c in run.sql('SELECT id, name FROM character', 'names')}
    for who in (h, k, u, sp):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    act = lambda who, node: run.admin('mind_act', who, [json.dumps(node)], 'verify-minds')
    run.admin('place_near', k, h)
    act(h, {'do': 'found', 'text': f'Verify Row {h}'})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {h}', 'h-membership'), 'community founded', 20)
    act(k, {'do': 'join', 'target': {'id': h}})
    run.wait(lambda: run.sql(f'SELECT * FROM join_request WHERE asker = {k}', 'join-request'), 'join request', 20)
    act(h, {'do': 'welcome', 'target': {'id': k}})
    run.wait(lambda: run.sql(f'SELECT * FROM membership WHERE member = {k}', 'k-membership'), 'K welcomed', 20)
    body = run.sql(f'SELECT * FROM body WHERE id = {h}', 'h-body')[0]
    for who, dx in ((k, 1.5), (u, -1.5), (sp, 2.5)):
        run.admin('place_at', who, body['x'] + dx, body['y'] + 1.0)
    time.sleep(1.5)
    script = {'replies': {'think': {'thought': 'I listen.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply(),
                          'talk': {'thought': 'I listen.', 'say': '', 'to': 0, 'acts': [], 'end': True, 'settled': None}}}
    run.start(model(run, script), [h])
    kn, un = names[k], names[u]
    say = lambda who, text, to: run.admin('mind_say', who, text, to, 'say', 0, TALK_THOUGHT)
    say(sp, f'{kn.split()[0]}! {un.split()[0]}! Come and look at this.', 0)
    time.sleep(2.6)
    say(sp, f'Good morning to you, {kn.split()[0]}.', k)
    time.sleep(2.6)
    say(sp, 'Has anyone seen the cart?', 0)
    time.sleep(1.5)
    heard = [e['text'] for e in run.private(f'SELECT * FROM experience WHERE observer = {h}', 'experiences-h') if e['kind'] == 'speech' and e['subject'] == sp]
    naming = next((t for t in heard if 'Come and look' in t), '')
    talking = next((t for t in heard if 'seen the cart' in t), '')
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    sent_text = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
    run.admin('set_behavior', h, json.dumps({'think': 'I finished my plan. verify address'}))
    prompt = run.wait(lambda: [sent_text(e) for e in requests() if 'verify address' in sent_text(e)], 'prompt after the lines', 60)[0]
    (run.directory / 'prompt-address.txt').write_text(prompt)
    checks = {
        'naming_reads_known_then_stranger': naming.startswith(f'A stranger said to the room, naming {kn} and a stranger:'),
        'no_unknown_name_in_the_detail': un not in naming.split('“')[0],
        'talking_with_reads_the_partner': talking.startswith(f'A stranger said to the room while talking with {kn}:'),
        'prompt_carries_both': f'naming {kn} and a stranger' in prompt and f'while talking with {kn}' in prompt,
        'addressed_line_has_no_room_detail': not any('to the room' in t for t in heard if 'Good morning' in t),
    }
    result = {'h': h, 'k': kn, 'u': un, 'heard': heard, 'checks': checks}
    (run.directory / 'room-address.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}

def open_line(run, length, clear=30.0):
    """A row of `length` open tiles (west to east), five tiles wide, that nothing blocks the sight
    along, with no body within `clear` m of it (verify-core's `quiet_line`)."""
    w = run.sql('SELECT width, height FROM world', 'world-size')[0]
    W, H = w['width'], w['height']
    tiles = bytearray(W * H)
    for row in run.sql('SELECT * FROM terrain_chunk', 'terrain'):
        data = row['tiles']
        data = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
        cx, cy = row['id'] & 0xFFFF, row['id'] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    bodies = [(b['x'], b['y']) for b in run.private('SELECT x, y FROM body', 'bodies')]
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    for y in range(8, H - 8, 3):
        for x in range(8, W - length - 8, 2):
            if not all(walk(x + i, y + d) for i in range(length) for d in (-2, -1, 0, 1, 2)):
                continue
            mid = (x + length / 2, y + .5)
            if all(math.dist(mid, b) > clear + length / 2 for b in bodies):
                return [(x + i + .5, y + .5) for i in range(length)]
    raise RuntimeError('no quiet open line on this map')


@case('earshot')
def earshot_case(run):
    """Who would hear you now, as a perception fact (earshot, `earshot::reach`,
    docs/COMMUNICATION.md §17). On a quiet open line by day (sight 11 m, a said line carries 9 m,
    a call 22.5 m): H (thought for) stands with A 3 m east (seen, within a said line), B 10 m east
    (seen, beyond a said line, within a call) and C 15 m west (beyond sight, within a call). A and
    C first tell H their names from beside H. H's think prompt then carries "who would hear you
    now" with the `earshot` law on (as shipped since earshot-on; turned off first, its prompt has no such key): A by name at
    say, B as a stranger added by a call, C nowhere (not perceived, so never named). H then says a line to the room and calls one: the people who receive each, among the
    ones H sees, are exactly the scene's list at that way, and C, unseen, receives the call."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 4, True)
    h, a, b, c = sorted(x['id'] for x in run.sql('SELECT id FROM character', 'ids-after') if x['id'] not in before)
    names = {x['id']: x['name'] for x in run.sql('SELECT id, name FROM character', 'names')}
    for who in (h, a, b, c):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    line = open_line(run, 28)
    at = lambda i: line[i]
    run.admin('place_at', h, *at(15))
    for who, i in ((a, 16), (c, 14), (b, 17)):
        run.admin('place_at', who, *at(i))
    time.sleep(1.5)
    say = lambda who, text, to, way='say': run.admin('mind_say', who, text, to, way, 0, TALK_THOUGHT)
    say(a, f"I'm {names[a]}.", 0)
    say(c, f"I'm {names[c]}.", 0)
    time.sleep(1.0)
    known = {x['known'] for x in run.private(f'SELECT * FROM acquaintance WHERE observer = {h}', 'h-knows')}
    for who, i in ((a, 18), (b, 25), (c, 0)):
        run.admin('place_at', who, *at(i))
    time.sleep(1.5)
    bodies = {x['id']: (x['x'], x['y']) for x in run.private('SELECT id, x, y FROM body', 'bodies-placed') if x['id'] in (h, a, b, c)}
    dist = {who: round(math.dist(bodies[h], bodies[who]), 1) for who in (a, b, c)}
    script = {'replies': {'think': {'thought': 'I listen.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply(),
                          'talk': {'thought': 'I listen.', 'say': '', 'to': 0, 'acts': [], 'end': True, 'settled': None}}}
    run.start(model(run, script), [h])
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    sent_text = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
    # The `earshot` law turned off (on as shipped): the scene does not say it.
    run.admin('set_world_law', 'earshot', 'false')
    run.admin('set_behavior', h, json.dumps({'think': 'I finished my plan. verify earshot-off'}))
    off = run.wait(lambda: [sent_text(e) for e in requests() if 'verify earshot-off' in sent_text(e)], 'prompt with the law off', 60)[0]
    (run.directory / 'prompt-earshot-off.txt').write_text(off)
    run.admin('set_world_law', 'earshot', 'true')
    run.admin('set_behavior', h, json.dumps({'think': 'I finished my plan. verify earshot-on'}))
    prompt = run.wait(lambda: [sent_text(e) for e in requests() if 'verify earshot-on' in sent_text(e)], 'prompt with the earshot', 60)[0]
    (run.directory / 'prompt-earshot.txt').write_text(prompt)
    m = re.search(r'"who would hear you now":"((?:[^"\\]|\\.)*)"', prompt)
    earshot = json.loads(f'"{m.group(1)}"') if m else ''
    parts = {p.strip().split(' would')[0].split(' if')[0]: p for p in earshot.rstrip('.').split(';')}
    ids_in = lambda part: {int(x) for x in re.findall(r'#(\d+)', part)}
    said_part = next((p for p in parts.values() if p.startswith('Within earshot if you say it')), '')
    call_part = next((p for p in parts.values() if 'a call would' in p), '')
    ours = {a, b, c}
    # The lines: a said one, then a call (the call's own 6 s gap does not apply to a first call).
    say(h, 'Is anyone near enough to hear me?', 0)
    time.sleep(2.6)
    say(h, 'Hello out there!', 0, 'call')
    time.sleep(1.5)
    rows = run.private(f'SELECT * FROM experience WHERE subject = {h}', 'heard-h')
    got = lambda words: {r['observer'] for r in rows if r['kind'] == 'speech' and words in r['text']} & ours
    heard_say, heard_call = got('near enough to hear me'), got('Hello out there')
    seen_ids = ids_in(said_part) | ids_in(call_part)
    # By night (sight 6 m) B at 10 m is out of sight too: a call then adds no one H sees.
    night = '"night":true' in prompt
    unseen = {c} | ({b} if night else set())
    checks = {
        'placed_as_planned': dist[a] <= 6.0 and 9.0 < dist[b] <= 11.0 and 11.0 < dist[c] <= 22.5,
        'a_and_c_are_known_by_name': {a, c} <= known,
        'law_off_the_scene_does_not_say_it': 'who would hear you now' not in off,
        'scene_carries_earshot': bool(earshot),
        'said_lists_a_by_name': ids_in(said_part) & ours == {a} and names[a] in said_part,
        'call_adds_b_as_a_stranger_by_day': ('a call would reach no one more' in call_part) if night else ('also reach' in call_part and ids_in(call_part) & ours == {b} and 'a stranger' in call_part),
        'unseen_are_never_named': not (unseen & seen_ids) and names[c] not in earshot,
        'said_line_reaches_exactly_the_said_list': heard_say == ids_in(said_part) & ours,
        'call_reaches_the_listed_and_the_unseen': heard_call - unseen == seen_ids & ours and unseen <= heard_call,
    }
    result = {'h': h, 'a': a, 'b': b, 'c': c, 'night': night, 'dist': dist, 'earshot': earshot, 'heard_say': sorted(heard_say), 'heard_call': sorted(heard_call), 'checks': checks}
    (run.directory / 'earshot.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('say-way')
def say_way_case(run):
    """A decision's line names its way of speaking (mind-say-way, `mind_install_way`,
    docs/COMMUNICATION.md §18). On a quiet open line, H (thought for) stands with A 15 m east
    (beyond a said line, within a call) and B 1 m west. H's think prompt names the optional
    `"way"` of its `say`. Four think requests, each answered by the fake model with a line:
    a call to A (A hears it from about 15 m; the chronicle keeps "<H> (call) to <A>"), a whisper to
    no one (refused in the rules' words, told to H as `unsaid`, and the decision stands), a
    whisper to B (B gets the words as a whisper), and a line in "shout", a way the world lacks
    (said aloud: B hears "said to you")."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 3, True)
    h, a, b = sorted(x['id'] for x in run.sql('SELECT id FROM character', 'ids-after') if x['id'] not in before)
    for who in (h, a, b):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    line = open_line(run, 28)
    run.admin('place_at', h, *line[10])
    run.admin('place_at', a, *line[25])
    run.admin('place_at', b, *line[9])
    time.sleep(1.5)
    think = lambda marker, say: {'purpose': 'think', 'contains': f'verify {marker}', 'times': 1,
                                 'reply': {'thought': f'verify {marker}', 'intend': ['wait'], 'say': say}}
    script = {'replies': {'think': {'thought': 'I listen.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply(),
                          'talk': {'thought': 'I listen.', 'say': '', 'to': 0, 'acts': [], 'end': True, 'settled': None}},
              'rules': [think('way-call', {'text': 'Verify call: can you hear me down there?', 'to': a, 'way': 'call'}),
                        think('way-whisper-none', {'text': 'Verify whisper to no one.', 'to': None, 'way': 'whisper'}),
                        think('way-whisper-b', {'text': 'Verify whisper: keep this between us.', 'to': b, 'way': 'whisper'}),
                        think('way-shout', {'text': 'Verify shout: said aloud instead.', 'to': b, 'way': 'shout'})]}
    run.start(model(run, script), [h])
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'think']
    sent_text = lambda e: '\n'.join(str(m.get('content', '')) for m in e['body'].get('messages', []))
    rows = lambda who: run.private(f'SELECT * FROM experience WHERE observer = {who}', f'experiences-{who}')
    def decide(marker, words):
        run.admin('set_behavior', h, json.dumps({'think': f'I finished my plan. verify {marker}'}))
        run.wait(lambda: any(words in r['text'] for who in (h, a, b) for r in rows(who) if r['kind'] in ('speech', 'whisper', 'said', 'unsaid')), f'the {marker} line', 60)
        time.sleep(2.6)
    decide('way-call', 'can you hear me down there')
    decide('way-whisper-none', 'whisper to no one')
    decide('way-whisper-b', 'keep this between us')
    decide('way-shout', 'said aloud instead')
    prompt = next((sent_text(e) for e in requests() if 'verify way-call' in sent_text(e)), '')
    (run.directory / 'prompt-say-way.txt').write_text(prompt)
    rh, ra, rb = rows(h), rows(a), rows(b)
    find = lambda rs, words, kind=None: [r for r in rs if words in r['text'] and (kind is None or r['kind'] == kind)]
    dist = round(math.dist(line[10], line[25]), 1)
    thoughts = [t['summary'] for t in run.thoughts(h) if t['kind'] == 'deliberate']
    checks = {
        'think_format_names_the_way': '"way": "say" or "whisper" or "call" (optional; default "say")' in prompt,
        'a_is_beyond_a_said_line_within_a_call': 9.0 < dist <= 22.5,
        'call_reaches_a': bool(find(ra, 'can you hear me down there', 'speech')) and 'calls out to you' in (find(ra, 'can you hear me down there') or [{'text': ''}])[0]['text'],
        # H's own row may be integrated (and deleted) by its mind already: the chronicle keeps the way.
        'h_called_out': any(' (call) to ' in r['text'] and 'can you hear me down there' in r['text'] for r in run.private(f"SELECT * FROM chronicle WHERE kind = 'speech'", 'chronicle-speech') if r['a'] == h),
        'whisper_to_no_one_is_refused_and_told': any(r['text'] == 'You did not say “Verify whisper to no one.”: a whisper needs someone to whisper to.' for r in find(rh, 'whisper to no one', 'unsaid')),
        'refused_whisper_said_to_no_one': not any(find(rs, 'whisper to no one', k) for rs in (ra, rb) for k in ('speech', 'whisper')),
        'decisions_stand': sum(1 for t in thoughts if 'verify way-' in t) >= 4,
        'whisper_reaches_b_only': bool(find(rb, 'keep this between us', 'whisper')) and not find(ra, 'keep this between us'),
        'a_way_the_world_lacks_is_said_aloud': bool(find(rb, 'said aloud instead', 'speech')) and any(r['text'].startswith('You said to') for r in find(rh, 'said aloud instead', 'said')),
    }
    result = {'h': h, 'a': a, 'b': b, 'dist_a': dist, 'h_rows': [r['text'] for r in rh if 'Verify' in r['text']],
              'a_rows': [r['text'] for r in ra if 'Verify' in r['text']], 'b_rows': [r['text'] for r in rb if 'Verify' in r['text']], 'checks': checks}
    (run.directory / 'say-way.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('think-framing')
def think_framing_case(run):
    """The think prompt's framing is the world's `think_framing` law (docs/FRAMING.md). With the
    law off, the think request the model is sent carries today's framing sentence and the section
    "# Why you are thinking now". With it on (`set_world_law`), the system prompt is the same text
    with that sentence replaced by the neutral one, word for word as replayed (N2), and the user
    prompt has the same sections in the same order, the reason's renamed "# What just happened".
    The law is restored at the end."""
    today = ("Start from why you are thinking now: that is what this moment of thought is about. "
             "Think about it as that person: what you make of it, and what you mean to do.")
    neutral = ("What just happened is shown beside what you perceive. Think as that person about whatever "
               "matters to you now, which may or may not be what just happened, and decide what you mean to do.")
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 1, True)
    m = next(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    run.admin('set_behavior', m, json.dumps({'wait': 300}))
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply()}}
    run.start(model(run, script), [m])
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'think']
    msgs = lambda e: {x.get('role'): str(x.get('content', '')) for x in e['body'].get('messages', [])}
    heads = lambda u: [l for l in u.split('\n') if l.startswith('# ')]
    asked = lambda marker: [msgs(e) for e in requests() if f'verify {marker}' in msgs(e).get('user', '')]
    try:
        run.admin('set_world_law', 'think_framing', 'false')
        run.request(m, 'framing off')
        off = run.wait(lambda: asked('framing off'), 'the think request with the law off', 90)[0]
        run.admin('set_world_law', 'think_framing', 'true')
        laws = {w['name']: w['value'] for w in run.sql('SELECT * FROM world_law', 'world-law')}
        assert laws.get('think_framing') == 'true', laws
        time.sleep(3.0)
        run.request(m, 'framing on')
        on = run.wait(lambda: asked('framing on'), 'the think request with the law on', 90)[0]
    finally:
        run.admin('set_world_law', 'think_framing', 'false')
    (run.directory / 'prompt-off.json').write_text(json.dumps(off, indent=1))
    (run.directory / 'prompt-on.json').write_text(json.dumps(on, indent=1))
    renamed = [h.replace('# Why you are thinking now', '# What just happened') for h in heads(off['user'])]
    checks = {
        'off_system_has_today_once': off['system'].count(today) == 1 and neutral not in off['system'],
        'off_user_has_why_section': '\n# Why you are thinking now\n' in off['user'] and '# What just happened' not in off['user'],
        'on_system_is_off_with_the_sentence_replaced': on['system'] == off['system'].replace(today, neutral, 1),
        'on_user_has_just_happened_not_why': '\n# What just happened\n' in on['user'] and '# Why you are thinking now' not in on['user'],
        'on_user_sections_same_order_renamed': heads(on['user']) == renamed,
    }
    result = {'m': m, 'off_heads': heads(off['user']), 'on_heads': heads(on['user']), 'checks': checks}
    (run.directory / 'think-framing.json').write_text(json.dumps(result, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('sissly-scene')
def sissly_scene_case(run):
    """Play-test 6's scene, replayed on the island seed with the fake model (talk-turns,
    docs/COMMUNICATION.md §19). The lines are paraphrased markers, not the play-test's words.
    Sissly Fenner (a child) and her mother Agnes Fenner are thought for; S, a spawned stranger,
    stands in for the owner, 3 m from Sissly; Agnes stands 5 m from her.

    1. S says two lines to Sissly; she answers each (talk turns 1 and 2).
    2. Sissly's deliberation is asked for; its think says nothing, and its deliberate step (held
       7 s by the fake model) installs a plan whose first node says "Verify stale …" to S.
       Meanwhile S asks "verify crust …?" and Sissly answers in a turn alongside, settling that
       she will bring S to the inn. That turn is her third with S.
    3. Sissly says to S "Verify: … ask Mother first. Can they have the crust, Mother?".

    Checks: the plan's line is not said (the conversation moved on since the decision perceived
    its scene, `line_overtaken`); turn 3's prompt does not tell her to make it her last word (a
    question is open) and holds the answered line once; Agnes's row of line 3 reads "…, naming
    you" (a kin word: Agnes is Sissly's parent) and Agnes takes a turn on it."""
    target = (Path(os.environ['CARGO_TARGET_DIR']) if os.environ.get('CARGO_TARGET_DIR') else ROOT / '.local/living/target-resident-island')
    run.harness('launch', '--seed', 'island', '--target-dir', str(target))
    run.harness('doctor')
    people = run.sql("SELECT * FROM character WHERE kind = 'person'", 'people')
    byname = {p['name']: p['id'] for p in people}
    sissly, agnes = byname['Sissly Fenner'], byname['Agnes Fenner']
    before = {p['id'] for p in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 1, True)
    s = next(x['id'] for x in run.sql('SELECT id FROM character', 'ids-after') if x['id'] not in before)
    for who in (sissly, agnes, s):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    line = open_line(run, 20)
    run.admin('place_at', sissly, *line[10])
    run.admin('place_at', s, *line[13])
    run.admin('place_at', agnes, *line[5])
    time.sleep(1.5)
    talk = lambda marker, reply: {'purpose': 'talk', 'contains': marker, 'times': 1, 'reply': {'thought': 'verify talk', 'acts': [], **reply}}
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply(),
                          'talk': {'thought': 'I listen.', 'say': '', 'to': 0, 'acts': [], 'end': True, 'settled': None}},
              'rules': [talk('naming you', {'say': 'Verify Agnes: yes, ask me for it.', 'to': s, 'end': True, 'settled': None}),
                        talk('verify crust', {'say': 'Verify: I like crust too, come on.', 'to': s, 'end': True, 'settled': 'verify bringing them to the inn'}),
                        talk('verify yes', {'say': 'Verify: then come to the inn. Crust or filling?', 'to': s, 'end': False, 'settled': None}),
                        talk('verify hi', {'say': 'Verify hullo: are you here for pie?', 'to': s, 'end': False, 'settled': None}),
                        {'purpose': 'think', 'contains': 'verify stale', 'times': 1,
                         'reply': {'thought': 'verify stale: I will ask again and go to the inn', 'intend': ['ask again', 'go to the inn'], 'say': None}},
                        {'purpose': 'deliberate', 'contains': 'verify stale', 'times': 1, 'delay_s': 7,
                         'reply': {'plan': 'verify stale plan', 'intent': {'weight': 0.7, 'graph': {'first': [{'say': 'Verify stale: crust or filling?', 'to': {'id': s}}, {'wait': 30}]}}}}]}
    run.start(model(run, script), [sissly, agnes], seed='island')
    say = lambda who, text, to: run.admin('mind_say', who, text, to, 'say', 0, TALK_THOUGHT)
    chron = lambda: run.private("SELECT * FROM chronicle WHERE kind = 'speech'", 'chronicle-speech')
    said_by = lambda who, words: any(c['a'] == who and words in c['text'] for c in chron())
    say(s, 'verify hi', sissly)
    run.wait(lambda: said_by(sissly, 'Verify hullo'), 'turn 1', 40)
    time.sleep(2.6)
    say(s, 'verify yes', sissly)
    run.wait(lambda: said_by(sissly, 'Verify: then come'), 'turn 2', 40)
    time.sleep(2.6)
    run.admin('set_behavior', sissly, json.dumps({'think': 'I finished my plan. verify stale'}))
    requests = lambda: shared.rows(run.directory / 'fake-requests.jsonl')
    sent_text = lambda e: '\n'.join(str(m.get('content', '')) for m in e['body'].get('messages', []))
    run.wait(lambda: any(e['purpose'] == 'deliberate' and 'verify stale' in sent_text(e) for e in requests()), 'the deliberate step', 40)
    time.sleep(1.0)
    say(s, 'verify crust, can you bring me there?', sissly)
    run.wait(lambda: said_by(sissly, 'I like crust too'), 'turn 3', 40)
    # The plan installs when the held deliberate step returns (7 s); its first node comes due.
    run.wait(lambda: any(t['kind'] == 'deliberate' and 'verify stale plan' in t['summary'] for t in run.thoughts(sissly)), 'the plan installed', 40)
    time.sleep(4.0)
    stale_said = said_by(sissly, 'Verify stale')
    turn3 = next((sent_text(e) for e in requests() if e['purpose'] == 'talk' and 'verify crust' in sent_text(e)), '')
    (run.directory / 'prompt-turn3.txt').write_text(turn3)
    user3 = next((str(m.get('content', '')) for e in requests() if e['purpose'] == 'talk' and 'verify crust' in sent_text(e) for m in e['body'].get('messages', []) if m.get('role') == 'user'), '')
    time.sleep(2.6)
    # A remark that asks nothing is answered by temperament (`answers_remarks`), for a named
    # hearer as for an addressed one; the line also asks, so the turn does not hang on a draw.
    say(sissly, 'Verify Agnes line: you have to ask Mother first. Can they have the crust, Mother?', s)
    try:
        run.wait(lambda: any(e['purpose'] == 'talk' and 'naming you' in sent_text(e) for e in requests()), 'a turn for Agnes', 20)
    except Exception:
        pass  # checked below (before talk-turns there is none)
    rows_a = [r['text'] for r in run.private(f'SELECT * FROM experience WHERE observer = {agnes}', 'experiences-agnes') if 'Verify Agnes line' in r['text']]
    agnes_turn = next((sent_text(e) for e in requests() if e['purpose'] == 'talk' and 'naming you' in sent_text(e)), '')
    (run.directory / 'prompt-agnes.txt').write_text(agnes_turn)
    # A reply waits until the line it answers has had time to be said (`saying_ms`).
    if agnes_turn:
        try:
            run.wait(lambda: said_by(agnes, 'Verify Agnes: yes'), "Agnes's line", 20)
        except Exception:
            pass  # checked below
    checks = {
        'stale_plan_line_not_said': not stale_said,
        'turn3_not_forced_last_word': bool(user3) and 'make this your last word' not in user3,
        'turn3_says_the_plain_fact': 'You have said about as much as you usually do' in user3,
        'answered_line_once': user3.count('verify crust, can you bring me there?') == 1,
        'agnes_row_names_her': any(', naming you: ' in t for t in rows_a),
        'agnes_takes_a_turn': bool(agnes_turn) and said_by(agnes, 'Verify Agnes: yes'),
    }
    result = {'sissly': sissly, 'agnes': agnes, 's': s, 'stale_said': stale_said, 'agnes_rows': rows_a, 'checks': checks}
    (run.directory / 'sissly-scene.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('named-turn')
def named_turn_case(run):
    """A hearer named in a line said to someone else takes one turn (talk-turns): a player says
    to A a line naming B and C, both thought for; B stands nearer the player than C. B's and C's
    rows read "…, naming you"; only B, the nearest named hearer, takes a turn, and the turn's
    prompt says how it was said ("A stranger said to a stranger, naming you and a stranger."). B has just settled a conversation
    with A, which does not count as being busy."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 3, True)
    a, b, c = sorted(x['id'] for x in run.sql('SELECT id FROM character', 'ids-after') if x['id'] not in before)
    names = {x['id']: x['name'] for x in run.sql('SELECT id, name FROM character', 'names')}
    run.harness('player', 'join', 'MindsNamer')
    me = next(x['id'] for x in run.sql('SELECT * FROM character', 'chars') if x['name'] == 'MindsNamer')
    for who in (a, b, c):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    line = open_line(run, 20)
    run.admin('place_at', me, *line[10])
    run.admin('place_at', a, *line[12])
    run.admin('place_at', b, *line[8])
    run.admin('place_at', c, *line[5])
    time.sleep(1.5)
    talk = lambda marker, reply, times=1: {'purpose': 'talk', 'contains': marker, 'times': times, 'reply': {'thought': 'verify talk', 'acts': [], **reply}}
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply(),
                          'talk': {'thought': 'I listen.', 'say': '', 'to': 0, 'acts': [], 'end': True, 'settled': None}},
              'rules': [talk('naming you', {'say': 'Verify named: I heard my name.', 'to': me, 'end': True, 'settled': None}, -1),
                        talk('verify settle', {'say': 'Verify: agreed, see you later.', 'to': a, 'end': True, 'settled': 'verify meet later'})]}
    run.start(model(run, script), [a, b, c])
    say = lambda who, text, to: run.admin('mind_say', who, text, to, 'say', 0, TALK_THOUGHT)
    chron = lambda: run.private("SELECT * FROM chronicle WHERE kind = 'speech'", 'chronicle-speech')
    said_by = lambda who, words: any(x['a'] == who and words in x['text'] for x in chron())
    # B settles an exchange with A first.
    say(a, 'verify settle: shall we meet later?', b)
    run.wait(lambda: said_by(b, 'agreed, see you later'), 'B settles with A', 40)
    time.sleep(2.6)
    first_b, first_c = names[b].split()[0], names[c].split()[0]
    run.harness('player', 'say', f'Is {first_b} about, and {first_c}?', '--to', str(a))
    run.wait(lambda: said_by(b, 'Verify named') or said_by(c, 'Verify named'), 'a named turn', 30)
    time.sleep(4.0)
    rows = {who: [r['text'] for r in run.private(f'SELECT * FROM experience WHERE observer = {who}', f'experiences-{who}') if f'{first_b} about' in r['text']] for who in (b, c)}
    requests = shared.rows(run.directory / 'fake-requests.jsonl')
    sent_text = lambda e: '\n'.join(str(m.get('content', '')) for m in e['body'].get('messages', []))
    named_prompts = [sent_text(e) for e in requests if e['purpose'] == 'talk' and 'naming you' in sent_text(e)]
    (run.directory / 'prompt-named.txt').write_text(named_prompts[0] if named_prompts else '')
    checks = {
        'b_and_c_rows_name_them': all(any(', naming you' in t or 'and you:' in t for t in rows[w]) for w in (b, c)),
        'nearest_named_b_takes_the_turn': said_by(b, 'Verify named'),
        'only_one_turn': not said_by(c, 'Verify named') and len(named_prompts) == 1,
        # Under the answered line: "A stranger said to a stranger, naming you and a stranger."
        'turn_says_how_it_was_said': bool(named_prompts) and bool(re.search(r'said to [^\n]*, naming [^\n]*\byou\b[^\n]*\.\n?', named_prompts[0].split('# What you are answering')[-1])),
    }
    result = {'a': a, 'b': b, 'c': c, 'player': me, 'rows': rows, 'checks': checks}
    (run.directory / 'named-turn.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('spoken-ids')
def spoken_ids_case(run):
    """Ids are not words (fix-spoken-ids): every speaking mind's system prompt (think, deliberate)
    carries the one sentence that the `#<id>` handles are for acts and memory and never spoken
    (prompts.rs `IDS_NOT_SPOKEN`). A deliberation whose line names someone by `#id` anyway is
    spoken without it (the speech primitive); the speaker gets a `spoken_as` experience with what
    it wrote beside what was said; the mind journals it in `outcomes/spoken_as.jsonl`, which
    trials.py counts per batch."""
    people = prepare(run)
    actor, other = people[0]['id'], people[1]['id']
    run.admin('set_behavior', actor, json.dumps({'wait': 300}))
    run.admin('place_near', other, actor)
    written = f'Watch out, #{other} is here.'
    sentence = ('Refer to people by the ids you see in your acts and your memory; the ids are handles, never words: '
                'when you speak, name people by their name or as you would describe them.')
    # The decision speaks (think's `say`); the compile carries it out and never adds speech.
    script = {'replies': {'think': {'thought': 'I warn the room.', 'intend': ['warn everyone'], 'say': {'text': written, 'to': None}},
                          'deliberate': basic_reply()}}
    run.request(actor, 'spoken ids')
    run.start(model(run, script), [actor])
    accepted(run, actor)
    lines = lambda: [c for c in run.sql(f'SELECT * FROM chronicle WHERE a = {actor}', 'spoken-ids-chronicle') if c['kind'] == 'speech' and 'Watch out,' in c['text']]
    said = run.wait(lines, 'the deliberation\'s line is spoken', 60)[0]['text']
    rows = lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'spoken-ids-experience') if e['kind'] == 'spoken_as']
    spoken_as = run.wait(rows, 'a spoken_as experience', 30)[0]
    outcome = run.journal / 'outcomes' / 'spoken_as.jsonl'
    journaled = run.wait(lambda: [r for r in shared.rows(outcome) if r.get('actor') == actor] if outcome.exists() else [], 'the mind journals the line', 30)
    requests = list(shared.rows(run.directory / 'fake-requests.jsonl'))
    system = lambda purpose: [str(m.get('content', '')) for e in requests if e['purpose'] == purpose for m in e['body'].get('messages', []) if m.get('role') == 'system']
    checks = {
        'think_prompt_has_the_sentence_once': bool(system('think')) and all(s.count(sentence) == 1 for s in system('think')),
        'deliberate_prompt_has_the_sentence_once': bool(system('deliberate')) and all(s.count(sentence) == 1 for s in system('deliberate')),
        'spoken_without_the_id': f'#{other}' not in said and 'is here.' in said,
        'spoken_as_keeps_both': written in spoken_as['text'] and f'#{other}' in spoken_as['text'] and said.split('“')[-1].rstrip('”') in spoken_as['text'],
        'journaled_with_both': written in journaled[0].get('line', '') and journaled[0].get('name'),
    }
    result = {'actor': actor, 'other': other, 'said': said, 'spoken_as': spoken_as['text'], 'journaled': journaled[0], 'checks': checks}
    (run.directory / 'spoken-ids.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('say-once')
def say_once_case(run):
    """A plan's say node does not say again a line its speaker said to the same person in the
    last 45 s (say-once; ew2's Mirren Quill double). Replayed with the reducer calls a
    deliberation makes, in the order the mind service makes them (`apply_routines`, then
    `mind_install_way`), as the admin, so the order of events is fixed:

    1. M's top level weighs "the plan" (`current plan` routine: wait).
    2. The routine edit: `current plan` becomes "say a line to A, then wait". The body runs it and
       speaks the line.
    3. Within 2 s, the install: the same plan, with the decision's own line to A. It is refused
       ("speaking too fast", told as `unsaid`), and the install clears the say node's mark.

    Before say-once, the node then said its line again 2–3 s later (`repeat`). Now it is said
    once: one chronicle line, no "(×2)", 7 s later.

    Then what the rule leaves alone (scope decided 2026-11-13): the same steps with a line to
    the room (`current plan` says it to no one; a second install clears the mark) say it again,
    and a scene's graph (`set_behavior`, installed twice) says its line to A again."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 2, True)
    m, a = sorted(x['id'] for x in run.sql('SELECT id FROM character', 'ids-after') if x['id'] not in before)
    line = open_line(run, 20)
    run.admin('place_at', m, *line[8])
    run.admin('place_at', a, *line[10])
    time.sleep(1.0)
    thought = lambda marker: {'kind': 'deliberate', 'summary': f'verify {marker}', 'detail': '', 'latency_ms': 0, 'tokens': 0, 'model': '', 'reference': ''}
    top = json.dumps({'desires': [{'want': 'the plan', 'weight': {'base': 3.5}, 'do': {'routine': 'current plan'}}]})
    routine = lambda graph: run.admin('mind_routines', m, [{'name': 'current plan', 'graph': json.dumps(graph)}])
    # A short wait: a routine edit does not wake the body, which takes the new routine when its
    # running leaf ends (a 30 s wait here let the line come after the 15 s window).
    routine({'wait': 2})
    run.admin('mind_install_way', m, top, 'verify first plan', '', 0, '', 0, thought('first'))
    time.sleep(3.0)
    words = 'Verify once: stay a moment, close, where I can see your face.'
    routine({'seq': [{'say': words, 'to': {'id': a}}, {'wait': 30}]})
    chron = lambda: [c for c in run.private("SELECT * FROM chronicle WHERE kind = 'speech'", 'chronicle-speech') if c['a'] == m and 'Verify once' in c['text']]
    run.wait(lambda: chron(), 'the routine speaks its first line', 20)
    run.admin('mind_install_way', m, top, 'verify second plan', 'Verify decision line: hear me.', a, 'say', 0, thought('second'))
    time.sleep(7.0)
    rows = chron()
    told = [r['text'] for r in run.private(f'SELECT * FROM experience WHERE observer = {m}', 'experiences-m') if r['kind'] in ('unsaid', 'repeat')]

    def said(marker, label):
        """How many times M's lines holding `marker` were said (chronicle rows, "(×n)" counted)."""
        n = 0
        for c in run.private("SELECT * FROM chronicle WHERE kind = 'speech'", label):
            if c['a'] == m and marker in c['text']:
                times = re.search(r'\(×(\d+)\)\s*$', c['text'])
                n += int(times.group(1)) if times else 1
        return n

    # A line to the room, through the same plan steps: not held back.
    room = 'Verify crier: fresh bread at the oven, warm loaves.'
    routine({'seq': [{'say': room}, {'wait': 30}]})
    run.wait(lambda: said('Verify crier', 'chronicle-room'), 'the plan says its room line', 40)
    run.admin('mind_install_way', m, top, 'verify third plan', '', 0, '', 0, thought('third'))
    time.sleep(7.0)
    room_said = said('Verify crier', 'chronicle-room-after')
    # A scene's graph (the admin's), to A, installed twice: not held back.
    scene = json.dumps({'seq': [{'say': 'Verify scene: hold still there, by the post.', 'to': {'id': a}}, {'wait': 30}]})
    run.admin('set_behavior', m, scene)
    run.wait(lambda: said('Verify scene', 'chronicle-scene'), 'the scene graph says its line', 20)
    time.sleep(3.0)
    run.admin('set_behavior', m, scene)
    time.sleep(6.0)
    scene_said = said('Verify scene', 'chronicle-scene-after')
    checks = {
        'line_said_once': len(rows) == 1 and '(×' not in rows[0]['text'],
        'no_repeat_row': not any(t.startswith('You said almost the same thing') for t in told),
        'decision_line_refused_and_told': any('Verify decision line' in t and 'speaking too fast' in t for t in told),
        'a_room_line_is_said_again': room_said >= 2,
        'a_scene_line_is_said_again': scene_said >= 2,
    }
    result = {'m': m, 'a': a, 'rows': [r['text'] for r in rows], 'told': told, 'room_said': room_said, 'scene_said': scene_said, 'checks': checks}
    (run.directory / 'say-once.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('named-room-call')
def named_room_call_case(run):
    """A room line or call naming exactly one hearer is theirs to answer (talk-named-room, after
    ew2's Petra case). P (not thought for) calls to the room; N (thought for) stands 5 m away and
    D (thought for) 19 m away, within a call's carry and beyond a said line's. D is in a
    conversation with P (P's line to D, D's reply), so a room line would give D a turn.

    1. Control: P calls to the room naming no one; D, talking with P, takes a turn.
    2. P calls to the room naming N by given name ("Verify call: <N>! Come to the smokehouse.").
       N's row reads "…, naming you, from about 5 m"; D's names N. N takes the turn; D, though
       still talking with P, takes none."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 3, True)
    p, n, d = sorted(x['id'] for x in run.sql('SELECT id FROM character', 'ids-after') if x['id'] not in before)
    names = {x['id']: x['name'] for x in run.sql('SELECT id, name FROM character', 'names')}
    for who in (p, n, d):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    line = open_line(run, 28)
    run.admin('place_at', p, *line[2])
    run.admin('place_at', n, *line[7])
    run.admin('place_at', d, *line[21])
    time.sleep(1.5)
    talk = lambda marker, reply: {'purpose': 'talk', 'contains': marker, 'times': 1, 'reply': {'thought': 'verify talk', 'acts': [], **reply}}
    script = {'replies': {'think': {'thought': 'I look around.', 'intend': ['wait'], 'say': None}, 'deliberate': basic_reply(),
                          'talk': {'thought': 'I listen.', 'say': '', 'to': 0, 'acts': [], 'end': True, 'settled': None}},
              # The first matching rule wins: any turn on the named call answers it; D's own turns
              # (its name is in its prompt only: the three do not know each other) answer the chat,
              # then the unnamed call; N's turn on the unnamed call (the only one within 6 m) is silent.
              'rules': [talk('smokehouse', {'say': 'Verify answer to the named call.', 'to': p, 'end': False, 'settled': None}),
                        talk(names[d], {'say': 'Verify D: yes, what is it?', 'to': p, 'end': False, 'settled': None}),
                        talk(names[d], {'say': 'Verify D: I am here.', 'to': p, 'end': False, 'settled': None})]}
    run.start(model(run, script), [n, d])
    say = lambda text, to, way='say': run.admin('mind_say', p, text, to, way, 0, TALK_THOUGHT)
    chron = lambda: run.private("SELECT * FROM chronicle WHERE kind = 'speech'", 'chronicle-speech')
    said_by = lambda who, words: any(x['a'] == who and words in x['text'] for x in chron())
    dist = round(math.dist(line[2], line[21]), 1)
    # D and P talk (P walks to D to say it, then back: a said line carries 9 m).
    run.admin('place_at', p, *line[19])
    time.sleep(1.0)
    say('verify chat: a word, D?', d)
    run.wait(lambda: said_by(d, 'Verify D: yes'), 'D answers P', 40)
    run.admin('place_at', p, *line[2])
    time.sleep(2.6)
    say('Verify call: anyone about?', 0, 'call')
    control = bool(run.wait(lambda: said_by(d, 'Verify D: I am here'), 'D answers the unnamed call', 30))
    time.sleep(7.0)
    first = names[n].split()[0]
    say(f'Verify call: {first}! Come to the smokehouse.', 0, 'call')
    n_turn = bool(run.wait(lambda: said_by(n, 'Verify answer to the named call'), 'N answers the named call', 30))
    time.sleep(6.0)
    d_turn = said_by(d, 'Verify answer to the named call')
    rows = {who: [r['text'] for r in run.private(f'SELECT * FROM experience WHERE observer = {who}', f'experiences-{who}') if 'smokehouse' in r['text']] for who in (n, d)}
    checks = {
        'd_is_within_a_call_beyond_a_said_line': 9.0 < dist <= 22.5,
        'control_d_answers_an_unnamed_room_call': control,
        'n_row_names_n': any(', naming you' in t for t in rows[n]),
        'd_row_names_one_other': any('to the room, naming ' in t and ', naming you' not in t for t in rows[d]),
        'n_takes_the_turn': n_turn,
        'd_takes_none': not d_turn,
    }
    result = {'p': p, 'n': n, 'd': d, 'dist_d': dist, 'rows': rows, 'checks': checks}
    (run.directory / 'named-room-call.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(checks.values()), checks
    return {'status': 'pass', **result}


@case('health-seen')
def health_seen_case(run):
    """A mind in a fight is told its opponent's health as the band everyone sees, never as a
    number, except while its own appraisal of them holds (`act::fight_report`,
    `perception::health_seen`, docs/PERCEPTION.md). Two strangers fight: A is thought for by
    the real mind service (the fake model's plans keep A attacking), B by a guarding graph. The fight
    reports reach A's prompts; after A appraises B, a report inside the 20 s reveal gives B's
    exact health. B only holds its guard toward A (blocked blows count toward a report and B
    takes a quarter of each), so A is never hurt into yielding, which would break the
    appraisal off. Before 2026-11-11 the report read "theirs looks about 70%"."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    run.admin('spawn_crowd', 2, True)
    a, b = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    for who in (a, b):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    run.admin('place_near', b, a)
    attack = lambda target: {'first': [{'do': {'skill': 'attack', 'target': {'id': target}}}, {'wait': 1}]}
    script = {'replies': {'think': {'thought': 'I fight on.', 'intend': ['attack'], 'say': None},
                          'deliberate': {'graph': attack(b), 'weight': 1.5, 'plan': 'verify minds fight'}}}
    models = model(run, script)
    run.start(models, [a])
    requests = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] in ('think', 'deliberate')]
    sent_text = lambda e: '\n'.join(str(m.get('content', '')) for m in e['body'].get('messages', []))
    reports = lambda: [l for e in requests() for l in sent_text(e).split('\n') if 'The fight with' in l]
    guard = {'first': [{'do': {'skill': 'block', 'target': {'id': a}, 'qty': 8000}}, {'wait': 0.2}]}
    run.admin('set_behavior', a, json.dumps(attack(b)))
    run.admin('set_behavior', b, json.dumps(guard))
    banded = run.wait(lambda: reports(), 'a fight report in a prompt', 90)
    words = ('unhurt', 'scratched', 'hurt', 'badly hurt', 'barely standing')
    exact = re.compile(r'they have \d+ of \d+ health\.')
    band_only = lambda l: any(f'they look {w}.' in l for w in words) and not exact.search(l) and 'theirs looks about' not in l and '%' not in l
    n_before = len(banded)
    # A pause, and A looks B over (a deliberate act, as a mind or a player would; a reflex
    # under attack would break it off). Then the fight goes on.
    for who in (a, b):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    time.sleep(2.0)
    run.admin('mind_act', a, [json.dumps({'do': 'appraise', 'target': {'id': b}})], 'verify-minds')
    try:
        reveal = run.wait(lambda: run.private(f'SELECT * FROM reveal WHERE observer = {a} AND target = {b}', 'reveal'), 'the appraisal reveals', 20)[0]
    finally:
        run.private(f'SELECT * FROM experience WHERE observer = {a}', 'experiences-a')
        run.private(f'SELECT * FROM activity WHERE id = {a}', 'activity-a')
        run.private(f'SELECT * FROM act_queue WHERE actor = {a}', 'act-queue-a')
        run.private(f'SELECT * FROM brain WHERE id = {a}', 'brain-a')
    run.admin('set_behavior', a, json.dumps(attack(b)))
    run.admin('set_behavior', b, json.dumps(guard))
    max_b = round(run.private(f'SELECT * FROM vitals WHERE id = {b}', 'vitals-b')[0]['max_hp'])
    appraised = run.wait(lambda: [l for l in reports()[n_before:] if exact.search(l)], 'a report with exact health inside the reveal', 25)
    for who in (a, b):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    out = {'band_reports': banded, 'appraised_reports': appraised, 'all_reports': reports(), 'reveal_until_ms': reveal['until_ms'], 'max_hp_b': max_b}
    (run.directory / 'health-seen.json').write_text(json.dumps(out, indent=2))
    checks = {'band_reports_have_band_words': all(band_only(l) for l in banded),
              'appraised_report_has_exact_health': any(f'of {max_b} health.' in l for l in appraised),
              'no_percentage_anywhere': not any('theirs looks about' in l for l in reports())}
    out['checks'] = checks
    (run.directory / 'health-seen.json').write_text(json.dumps(out, indent=2))
    assert all(checks.values()), checks
    return {'status': 'pass', **out}


@case('animals')
def animals_case(run):
    """Cheaper animal minds (LIVING_ANIMAL_MINDS=salient,choose; mind/animal.rs): each deer of a
    herd decides on its own, in its own `choose` call, and the graph built from its own pick is
    installed; `pack` in the switch list (retired 2026-11-12, docs/PACK_MIND.md: one animal's
    decision copied to the others it saw was shared hidden state) changes nothing; asked again
    with nothing new, the lead lives by instinct without a call (salient).

    Staging (fix-animals-race, 2026-11-12): the case's three deer are chosen among adults with no
    request to think pending, every other deer is held still and moved off the herd's ground, the
    three graze twice before the mind starts, and a call counts as a deer's only when its prompt's
    scene is that deer's own (`you.id`). Races made it flaky on main: a deer outside the three
    courted one of them ("asked to start a family"); the three already had requests pending from
    their own instincts ("My actions keep failing (a child is already on the way)"); a deer's own
    later re-think (its one-step flight over, "Nothing in my current plan works") landed as the
    lead was asked again and was counted as the lead's; the lead's flight ended at the edge of its
    sight of the person, so at 240 s the person was gone from its scene, which is news; and a lead
    that started near hunger 30 crossed 50 in the four minutes, news too. Before the lead's
    throttle ends the three stand still and the person stands 4 m from the lead again."""
    run.harness('launch')
    run.harness('doctor')
    person = next(p for p in sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id']) if p['alive'] and p['stage'] == 2)
    every = [d for d in sorted(run.sql("SELECT * FROM character WHERE kind = 'deer'", 'deer'), key=lambda d: d['id']) if d['alive']]
    # Every deer stands still first, so none courts another or wanders in while the scene is set.
    for d in every:
        run.admin('set_behavior', d['id'], json.dumps({'wait': 300}))
    time.sleep(2.0)
    pending = {r['actor'] for r in run.sql('SELECT actor FROM deliberation', 'pending-before')}
    deer = [d['id'] for d in every if d['stage'] == 2 and d['id'] not in pending][:3]
    assert len(deer) == 3, ('three adult deer with nothing pending', [d['id'] for d in every], sorted(pending))
    # The herd stays where the lead deer grazes (in the open); the person comes to them.
    at = run.sql(f"SELECT x, y FROM body WHERE id = {deer[0]}", 'lead-at')[0]
    run.admin('set_behavior', person['id'], json.dumps({'wait': 300}))
    run.admin('place_at', person['id'], at['x'] + 3, at['y'])
    for i, d in enumerate(deer):
        run.admin('place_at', d, at['x'] + (i % 2), at['y'] + (i // 2))
    # The other deer off the herd's ground (out of its sight), as the wolves are kept away below.
    for d in every:
        if d['id'] in deer:
            continue
        b = run.sql(f"SELECT x, y FROM body WHERE id = {d['id']}", f"deer-{d['id']}")
        if not b or math.hypot(b[0]['x'] - at['x'], b[0]['y'] - at['y']) >= 40:
            continue
        for k in range(8):
            v = k * math.pi / 4
            run.admin('place_at', d['id'], at['x'] + 60 * math.cos(v), at['y'] + 60 * math.sin(v))
            b = run.sql(f"SELECT x, y FROM body WHERE id = {d['id']}", f"deer-{d['id']}")
            if b and math.hypot(b[0]['x'] - at['x'], b[0]['y'] - at['y']) >= 40:
                break
        else:
            run.admin('kill', d['id'], 'verify: kept off the herd')
    # Fed first: hunger rises about 22 over the case's four minutes, and a lead that starts near
    # 30 crosses 50 meanwhile, which is news to the salience check. Two grazings take off 28.
    for d in deer:
        run.admin('set_behavior', d, json.dumps({'seq': [{'do': {'skill': 'graze'}}, {'do': {'skill': 'graze'}}, {'wait': 300}]}))
    time.sleep(10.0)
    for d in deer:
        run.admin('set_behavior', d, json.dumps({'wait': 300}))
    fed = {v['id']: round(v['hunger'], 1) for v in run.sql('SELECT id, hunger FROM vitals', 'fed') if v['id'] in deer}
    assert fed.get(deer[0], 99) < 25, ('the lead fed below hunger 25 before the mind starts', fed)
    time.sleep(1.0)
    still = sorted(r['actor'] for r in run.sql('SELECT actor FROM deliberation', 'pending-at-start') if r['actor'] in deer)
    assert not still, ('nothing pending for the three when the mind starts', still)
    models = model(run, {})
    # `pack` is passed on purpose: it is retired and must not make one deer decide for another.
    run.start(models, deer, extra_env={'LIVING_ANIMAL_MINDS': 'salient,choose,pack', 'LIVING_ANIMAL_PACK_S': '120'})
    detail = lambda t: json.loads(t['detail']) if t['detail'] else {}

    def caller(e):
        """Whose call this is: the `you` of the scene in its prompt (`# Around you now`)."""
        text = '\n'.join(str(m.get('content', '')) for m in (e.get('body') or {}).get('messages', []))
        i = text.find('# Around you now\n')
        try:
            return json.loads(text[i:].split('\n')[1])['you']['id'] if i >= 0 else None
        except (ValueError, KeyError, IndexError):
            return None

    calls = lambda purpose, who: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == purpose and caller(e) == who]
    # A mind's install counts as having just thought: within its species' think_min_s (240 s)
    # the authority asks an animal only for urgent reasons, and every urgent reason is news to
    # its salience check. A fresh deer has not thought, so the first asks go through.
    ask = lambda d, marker: run.admin('set_behavior', d, json.dumps({'think': f'A quiet moment. verify {marker}'}))
    lead, *rest = deer
    ask(lead, 'animal-lead')
    first = run.wait(lambda: [t for t in run.thoughts(lead, 'lead-thoughts') if t['kind'] == 'deliberate' and detail(t).get('mode') == 'choose'], 'a chosen option', 60)[0]
    d0 = detail(first)
    assert d0['valid_pick'] and len(d0['options']) >= 3 and 'pack' not in d0, d0
    brain = run.sql(f'SELECT * FROM brain WHERE id = {lead}', 'lead-brain')[0]
    assert brain['source'] == 'mind' or d0['options'][d0['pick']].startswith('carry on'), brain
    for d in rest:
        ask(d, 'animal-member')
    # Each of the others decides on its own: its own `choose` thought, never one made by the lead.
    own = {d: run.wait(lambda d=d: [t for t in run.thoughts(d, f'member-{d}') if t['kind'] == 'deliberate' and detail(t).get('mode') == 'choose'], f'own decision for {d}', 90)[0] for d in rest}
    for d in deer:
        copied = [t for t in run.thoughts(d, f'copied-{d}') if detail(t).get('mode') == 'pack' or detail(t).get('by') not in (None, d)]
        assert not copied, (d, copied)
    chosen = [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'choose']
    counts = {d: (len(calls('choose', d)), len(calls('deliberate', d))) for d in deer}
    assert all(counts[d] == (1, 0) for d in deer), ('one call each, its own', counts)
    # No prompt tells an animal that others will do what it picks.
    assert not any('Your pack' in json.dumps(e) for e in chosen), 'a choose prompt still speaks for a pack'
    # The lead asked again with nothing new, once its thinking throttle (240 s after its chosen
    # option) has passed (since 2026-11-11 no dawn broadcast skips it). Wolves that would come
    # into view meanwhile are news; the scene removes those that range near the herd.
    wolves = [w['id'] for w in run.sql("SELECT * FROM character WHERE kind = 'wolf'", 'wolves') if w['alive']]
    for w in wolves:
        b = run.sql(f'SELECT x, y FROM body WHERE id = {w}', f'wolf-{w}')
        if b and math.hypot(b[0]['x'] - at['x'], b[0]['y'] - at['y']) < 120:
            run.admin('kill', w, 'verify: kept away from the herd')
    # Nothing new for the lead when its throttle ends: what it saw when it chose (the person 3 m
    # off). Its picked plan, a flight, is over by now and has stopped working ("Nothing in my
    # current plan works"), and the flight left it at the edge of its sight of the person (11 m,
    # 12 kept), in or out by inches: a person out of sight is news to the salience check. So
    # the three stand still and the person stands 4 m from the lead again, before the lead's own
    # held request comes due at 240 s.
    time.sleep(max(0.0, (first['at_ms'] + 228_000) / 1000 - time.time()))
    for d in deer:
        run.admin('set_behavior', d, json.dumps({'wait': 300}))
    here = run.sql(f"SELECT x, y FROM body WHERE id = {lead}", 'lead-again-at')[0]
    run.admin('place_at', person['id'], here['x'] + 4, here['y'])
    time.sleep(max(0.0, (first['at_ms'] + 245_000) / 1000 - time.time()))
    ask(lead, 'animal-again')
    run.wait(lambda: any(t['kind'] == 'instinct' for t in run.thoughts(lead, 'lead-again')), 'a request answered by instinct', 60)
    # The lead's own calls only: another deer may think again on its own by now (its plan over).
    assert len(calls('choose', lead)) == 1, ('nothing new: no call by the lead', {d: len(calls('choose', d)) for d in deer})
    return {'status': 'pass', 'lead': lead, 'pick': d0['options'][d0['pick']], 'weight': d0.get('weight'), 'members': rest,
            'own_decisions': {d: detail(t).get('pick') for d, t in own.items()}, 'model_calls_for_three_deer': 3,
            'later_calls': {d: len(calls('choose', d)) - 1 for d in deer}}


@case('night')
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


@case('jev')
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
    # Jev's price is never committed (living/mind/src/prices.rs): a scratch prices file with a
    # made-up price, so the journal's cost is checked against tokens × price
    price = 2.5
    (run.directory / 'prices.json').write_text(json.dumps({'models': {'jev-1.14.0': {'input_usd_per_m': price}}}))
    run.start(models, [defender], extra_env={'LIVING_JEV': '1', 'LIVING_JEV_URL': f'http://127.0.0.1:{port}/v1/systemone', 'TYPESAFE_API_KEY': 'fake-only',
                                             'LIVING_PRICES': str(run.directory / 'prices.json')})
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
    for e in judged:
        assert e['prompt_tokens'] and abs(e['cost_usd'] - e['prompt_tokens'] * price / 1e6) < 1e-12, (e['prompt_tokens'], e['cost_usd'])
    assert 'jev-1.14.0 priced from' in run.log()
    return {'status': 'pass', 'judgments': len(judged), 'value': cached[0]['value'], 'cost_usd_checked': len(judged)}
# Stacked decorators register bottom first: rethink, then rethink-llm.
@case('rethink-llm', arm='llm')
@case('rethink', arm='jev')
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
    assert 'usd' not in json.dumps(cfg), 'the committed rethink.json carries a price'
    # No prices file (LIVING_PRICES names one that does not exist): Jev's cost is unknown, never 0
    run.start(models, [actor], extra_env={'LIVING_RETHINK': arm, 'LIVING_RETHINK_CONFIG': str(run.directory / 'rethink.json'),
              'LIVING_RETHINK_URL': f'http://127.0.0.1:{port}/v1/systemone', 'TYPESAFE_API_KEY': 'fake-only',
              'LIVING_PRICES': str(run.directory / 'no-prices.json')})
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
    # Cost: unknown without a price, never 0. The Jev arm journals its own exchange (purpose
    # rethink, cost_usd null); the chat arm's call is journaled by llm.rs, and the gate's own
    # Judged carries no cost for it either.
    assert re.search(r'cost_usd: None', stats[-1]), stats[-1]
    if arm == 'jev':
        jev = [e for e in run.exchanges() if e.get('purpose') == 'rethink' and e.get('profile') == 'jev']
        assert jev and all(e['cost_usd'] is None for e in jev), [e.get('cost_usd') for e in jev]
        assert "jev-1.14.0's cost is unknown" in run.log()
        unknown = int(re.search(r'cost_unknown: (\d+)', stats[-1])[1])
        assert unknown > 0, stats[-1]
        out['jev_cost_unknown'] = len(jev)
    (run.directory / 'rethink.json-result').write_text(json.dumps({'verdicts': verdicts, 'stats': stats[-1], **out}, indent=2))
    return {'status': 'pass', 'arm': arm, 'verdicts': verdicts, 'stats': stats[-1], **out}


@case('resident')
def resident_case(run):
    """On the island every resident has a mind from the start (an AI character the world
    admin controls): this service thinks for it, it answers a player through `mind_say`,
    trades and teaches through its own acts, and a replacing projection keeps its given places
    (work, inn, square, evening: world facts its starting ways walk to)."""
    target = (Path(os.environ['CARGO_TARGET_DIR']) if os.environ.get('CARGO_TARGET_DIR') else ROOT / '.local/living/target-resident-island')
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
                                   'places': [{'name': 'verify after', 'x': 41.0, 'y': 61.0}], 'thought': {'none': []}, 'replace': True, 'cues': {'none': []}})
    places = {p['name'] for p in run.sql(f'SELECT * FROM place WHERE actor = {rid}', 'places-after')}
    assert 'verify after' in places and places_before <= places, (places_before, places)
    final = run.sql(f'SELECT * FROM character WHERE id = {rid}', 'resident-final')[0]
    assert final['ai'] and final['controller'] == world['admin']
    talks = [e for e in run.exchanges() if e['purpose'] == 'talk']
    return {'status': 'pass', 'resident': rid, 'lesson': lesson, 'talk_turns': len(talks),
            'places_kept': sorted(places_before), 'places_after': sorted(places)}


@case('parked')
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
    # The old rule, selected explicitly (`concurrent` is the default since 2026-11-11; `alongside` covers it).
    run.start(models, [actor], extra_env={'LIVING_PARK': 'wait'})
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


@case('alongside')
def alongside_case(run):
    """LIVING_PARK=concurrent (talk.rs `turn_alongside`, `deliberation_decided`, `unanswered_say`):
    (1) a line heard just after a deliberation's prompt was built gets its turn while the think
    step is still running; (2) a line heard later waits for the think step, and gets its turn as
    soon as the decision says nothing to the speaker, while the compile step still runs; (3) when
    the decision would speak to the speaker that a turn alongside already answered, the
    deliberation's words are not said."""
    people = prepare(run)
    actor = people[0]['id']
    run.harness('player', 'join', 'MindsAlongside')
    player = run.sql("SELECT id FROM character WHERE name = 'MindsAlongside'", 'player')[0]['id']

    def say_now(text):
        # Straight over HTTP with the player's token (from the run's state.json): a line that must
        # land within 2 s of a deliberation's prompt cannot wait for a harness subprocess under load.
        token = json.loads((run.directory / 'state.json').read_text())['token']
        req = urllib.request.Request(f"{shared.STDB_URL}/v1/database/{run.db}/call/human_say", data=json.dumps([text, actor]).encode(),
                                     headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 200
        with (run.directory / 'actions.log').open('a') as log:
            log.write(f"{time.strftime('%H:%M:%S')} player human_say{json.dumps([text, actor])} -> 200 (HTTP, fast)\n")
    run.admin('place_near', player, actor)
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'Answering alongside my thinking.', 'say': 'verify minds alongside answer', 'end': True}},
              # Think requests carry the graph's 'verify' words: the warm-up's and the next two take
              # 8 s, the third case's 6 s and speaks to the player.
              'rules': [{'purpose': 'think', 'contains': 'verify', 'delay_s': 8, 'times': 3},
                        {'purpose': 'think', 'contains': 'verify', 'delay_s': 6, 'times': 1,
                         'reply': {'thought': 'I tell them while I think.', 'intend': ['wait'],
                                   'say': {'text': 'verify minds deliberation words', 'to': player}}},
                        {'purpose': 'deliberate', 'contains': 'verify', 'delay_s': 8, 'times': -1}]}
    models = model(run, script)
    requests = lambda: list(shared.rows(run.directory / 'fake-requests.jsonl'))
    talks = lambda: [e for e in requests() if e['purpose'] == 'talk']
    thinks = lambda: [e for e in requests() if e['purpose'] == 'think' and 'verify' in json.dumps(e['body'])]
    run.start(models, [actor], extra_env={'LIVING_PARK': 'concurrent'})
    run.wait(lambda: 'conversation switches' in run.log(), 'switches logged')
    # A first plan, so that each case below starts from an accepted one.
    run.request(actor, 'warmup')
    accepted(run, actor)
    time.sleep(3)
    spoken = lambda text: [c for c in run.sql(f'SELECT * FROM chronicle WHERE a = {actor}', 'alongside-speech') if text in c['text']]
    # 1. Fresh: the line comes within 2 s of the prompt; the think step has 8 s to go.
    compiles = lambda: [e for e in requests() if e['purpose'] == 'deliberate' and 'verify' in json.dumps(e['body'])]
    c0, t0 = len(compiles()), len(thinks())
    run.request(actor, 'first')
    run.wait(lambda: len(thinks()) >= t0 + 1, 'first think running', 60)
    say_now('Hello, do you have a moment?')
    run.wait(lambda: talks(), 'a turn alongside the running think step', 5)
    assert len(compiles()) == c0, 'the turn waited for the think step'
    run.wait(lambda: spoken('verify minds alongside answer'), 'alongside answer spoken', 10)
    assert 'gets its turn alongside' in run.log()
    deliberated = lambda n: len([t for t in run.thoughts(actor, 'thoughts') if t['kind'] == 'deliberate']) >= n
    base = len([t for t in run.thoughts(actor, 'thoughts-before') if t['kind'] == 'deliberate'])
    run.wait(lambda: deliberated(base + 1), 'first deliberation done', 40)
    time.sleep(3)
    first = len(talks())
    # 2. Late: the line comes 4 s into the think step; it waits for the decision, which says
    # nothing to the player, and gets its turn before the compile step ends.
    run.request(actor, 'second')
    run.wait(lambda: len(thinks()) >= t0 + 2, 'second think running', 60)
    time.sleep(4)
    run.harness('player', 'say', 'Another matter entirely: where does the river bend north?', '--to', str(actor))
    time.sleep(2)
    assert len(talks()) == first, 'a late line got its turn before the decision'
    run.wait(lambda: len(talks()) > first, 'the turn after the decision', 15)
    assert len(compiles()) == c0 + 2 and not deliberated(base + 2), 'the deliberation ended first'
    assert 'has decided, and not to speak to' in run.log()
    run.wait(lambda: deliberated(base + 2), 'second deliberation done', 40)
    time.sleep(3)
    # 3. The decision would speak to the player, whom a turn alongside already answered.
    run.request(actor, 'third')
    run.wait(lambda: len(thinks()) >= t0 + 3, 'third think running', 60)
    say_now('Something new: are the fish running today?')
    run.wait(lambda: 'already answered' in run.log(), "the deliberation's words withheld", 40)
    time.sleep(10)
    assert not spoken('verify minds deliberation words'), 'the deliberation spoke to someone already answered'
    return {'status': 'pass', 'talk_turns': len(talks())}


@case('greet')
def greet_case(run):
    """LIVING_GREET (talk.rs `Facts::drawn`, `faced`): with the world keeping who heard each line
    (`speech_audience`), a stranger's line to no one, said with two residents within 6 m, draws
    no turn under `off`, one turn from the nearest under `nearest`, and under `facing` a turn
    from the resident the speaker faces (here the farther one) and none from the nearer."""
    people = prepare(run)
    a, b = [p['id'] for p in people]
    run.harness('player', 'join', 'MindsStranger')
    player = run.sql("SELECT id FROM character WHERE name = 'MindsStranger'", 'player')[0]['id']
    # a, the player 1 m east of a, b 3 m east of the player (both within the 6 m address distance).
    body = run.sql(f'SELECT * FROM body WHERE id = {a}', 'body-a')[0]

    def placed():
        # `place_at` takes the nearest free tile: a body standing on a target moves one elsewhere
        # (minds-fixreq-g02: a 3 m and b 2 m from the player). Check what the scene became:
        # a nearer than b, b within the 6 m address distance, and a outside a 0.6 rad cone toward b.
        pos = {r['id']: (r['x'], r['y']) for i in (a, player, b) for r in run.sql(f'SELECT * FROM body WHERE id = {i}', 'body-placed')}
        if len(pos) < 3:
            return False
        (px, py), (ax, ay), (bx, by) = pos[player], pos[a], pos[b]
        da, db = math.hypot(ax - px, ay - py), math.hypot(bx - px, by - py)
        off = abs(math.atan2(ay - py, ax - px) - math.atan2(by - py, bx - px)) % (2 * math.pi)
        return da + 1 <= db <= 5 and min(off, 2 * math.pi - off) > 1.0

    def place():
        anchors = [(body['x'], body['y'])]
        for x, y in anchors + [(r['x'], r['y']) for r in run.sql(f'SELECT * FROM body WHERE id = {a}', 'body-a-now')]:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                try:
                    run.admin('place_at', a, x, y)
                    run.admin('place_at', player, x + dx, y + dy)
                    run.admin('place_at', b, x + 4 * dx, y + 4 * dy)
                except Exception:
                    continue
                if placed():
                    return
                run.note(f'greet: the scene at ({x:.1f}, {y:.1f}) toward ({dx}, {dy}) did not come out as placed; trying another')
        raise RuntimeError('greet: no placement put a nearer than b within 5 m of the player (body-placed.json)')
    place()
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'A stranger speaks.', 'say': 'verify minds greet answer', 'end': True}}}
    models = model(run, script)
    talks = lambda: [e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'talk']
    # Answers by their talk-turn thought rows (the chronicle merges a line repeated word for word
    # into its earlier row, so a second identical fake answer adds no row there).
    answers = lambda: sorted((t for t in run.sql(f'SELECT * FROM thought WHERE kind = \'talk\'', 'greet-answers')
                              if json.loads(t.get('detail') or '{}').get('with') == player and 'verify minds greet answer' in t['summary']), key=lambda t: t['id'])
    results = {}
    for arm, text in (('off', 'Hello there!'), ('nearest', 'Good day to you all.'), ('facing', 'Fine weather today.')):
        if run.mind:
            shared.stop(run.mind)
            time.sleep(2)
        subscribed = run.log().count('world subscribed:')
        if run.mind is None:
            run.start(models, [a, b], extra_env={'LIVING_GREET': arm})
            # The shipped rules keep who heard each line (`speech_audience`, on by default).
            assert (ROOT / 'living/scripts/skills.rhai').read_text().count('speech_audience: true,') == 1
        else:
            run.env['LIVING_GREET'] = arm
            run.launch_mind()
        run.wait(lambda: run.log().count('world subscribed:') > subscribed, f'{arm}: subscribed')
        for who in (a, b):
            run.request(who, f'{arm}-{who}')
        run.wait(lambda: not run.private(f'SELECT * FROM deliberation WHERE actor = {a} OR actor = {b}', f'pending-{arm}'), f'{arm}: deliberations done', 60)
        time.sleep(3)
        # Residents wander on their own ways between arms: everyone back in place for each line.
        place()
        time.sleep(1)
        if arm == 'facing':
            run.harness('player', 'act', json.dumps({'do': 'face', 'target': {'id': b}}))
            time.sleep(2)
        before, heard = len(answers()), len(talks())
        run.harness('player', 'say', text)
        time.sleep(8)
        new = answers()[before:]
        aud = [r for r in run.sql(f'SELECT * FROM audience WHERE speaker = {player}', f'audience-{arm}')]
        assert aud, f'{arm}: no audience row for the line'
        row = max(aud, key=lambda r: r['at_ms'])
        hs = [h if isinstance(h, list) else [h['id'], h['d'], h['off']] for h in row['hearers']]
        # The rule's own reading of the row: the nearest, and the one within 6 m and 0.6 rad of the facing.
        # The nearest of the hearers this service thinks for (other residents may stand nearer).
        nearest = min((h for h in hs if h[0] in (a, b)), key=lambda h: h[1])[0]
        cone = [h for h in hs if h[1] <= 6.0 and h[2] <= 0.6]
        faced = min(cone, key=lambda h: (h[2], h[1]))[0] if cone else None
        results[arm] = {'answers_by': [t['actor'] for t in new], 'talk_requests': len(talks()) - heard, 'hearers': hs, 'nearest': nearest, 'faced': faced}
        # A restarted service replays speech under 30 s old (talk.rs STALE_MS): let this line age out.
        time.sleep(25)
    (run.directory / 'greet.json').write_text(json.dumps(results, indent=2))
    assert results['off']['answers_by'] == [] and results['off']['talk_requests'] == 0, results
    assert results['nearest']['answers_by'] == [a] and results['nearest']['nearest'] == a, results
    assert results['facing']['faced'] == b and results['facing']['nearest'] != b and results['facing']['answers_by'] == [b], results
    log = run.log()
    assert 'is drawn in by' in log and 'is faced by' in log
    return {'status': 'pass', **results}


@case('reasons')
def reasons_case(run):
    """A deliberation consumes the reasons its prompt contained (living_rules::reasons,
    `clear_deliberation`). The mind's plan finishes every few seconds and each model call takes
    longer than that, so "I finished my plan." arrives during calls (a person asks again at most
    every 20 s without a pending request, `think_min_s`). The old code then kept the feeling,
    and the next plan's own "I finished" merged into that surviving request (bypassing
    `think_min_s`), so thoughts ran back to back. Before 2026-11-11
    that churn kept a one-off feeling pending and the reason of every later thought. A reason
    arriving during a call (a player's offer) still waits for the next deliberation, and only
    that one. Each deliberate thought records its reasons with `carried_before`."""
    people = prepare(run)
    actor = people[0]['id']
    marker = 'verify one-off feeling'
    churn = {'seq': [{'wait': 1}, {'wait': 1}]}
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': {'graph': churn, 'weight': 1.5, 'plan': 'verify minds churn'}},
              'rules': [{'purpose': 'think', 'delay_s': 9, 'times': -1}]}
    models = model(run, script)
    # Before the mind starts: a one-off feeling, then the plan finishing (a sequence's root
    # ends every 8 s at most, brain.rs ROOT_MARK).
    run.admin('set_behavior', actor, json.dumps({'seq': [{'think': marker}, {'wait': 1}]}))
    run.wait(lambda: any(marker in d['reason'] for d in run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', 'pending-feeling')),
             'the feeling is pending', 30)
    run.harness('player', 'join', 'ReasonsTrader')
    player = run.sql("SELECT id FROM character WHERE name = 'ReasonsTrader'", 'trader')[0]['id']
    run.admin('place_near', player, actor)
    run.admin('grant_items', player, 'stone', 2)
    run.start(models, [actor])
    requests = lambda: shared.rows(run.directory / 'fake-requests.jsonl')
    in_call = lambda: (lambda r: len([e for e in r if e.get('purpose') == 'think']) > len([e for e in r if e.get('purpose') == 'deliberate']))(requests())
    installed = {'revision': None}

    def deliberations(save='thoughts'):
        # The mind's plan finishes once (a desire); the churn is a sequence root, reinstalled
        # over each plan the mind installs, which reports "I finished my plan." every 8 s.
        brain = run.private(f'SELECT * FROM brain WHERE id = {actor}', 'brain')
        if brain and brain[0]['source'] == 'mind' and brain[0]['revision'] != installed['revision']:
            run.admin('set_behavior', actor, json.dumps(churn))
            installed['revision'] = brain[0]['revision']
        return [json.loads(t['detail']) for t in run.thoughts(actor, save) if t['kind'] == 'deliberate']
    run.wait(lambda: len(deliberations()) >= 2, 'two deliberations', 120)
    # A reason that arrives during a call: the player's offer.
    run.wait(lambda: deliberations() is not None and in_call(), 'a model call in flight', 60)
    offer_at = int(time.time() * 1000)
    run.harness('player', 'act', json.dumps({'do': 'offer', 'target': {'id': actor}, 'item': 'stone', 'qty': 1, 'want': 'wood', 'want_qty': 1}))
    run.wait(lambda: len(deliberations()) >= 5, 'five deliberations', 300)
    ds = deliberations('thoughts-final')
    carrying = [i for i, d in enumerate(ds) if marker in d['reason']]
    offers = [i for i, d in enumerate(ds) if 'offers you' in d['reason']]
    reasons = [r for d in ds for r in d.get('reasons', [])]
    plan_finished_during_calls = len([d for d in ds[1:] if 'I finished my plan' in d['reason']])
    out = {'deliberations': len(ds), 'carrying_feeling': len(carrying), 'carrying_offer': len(offers),
           'offer_sent_ms': offer_at, 'max_carried_before': max((r['carried_before'] for r in reasons), default=None),
           'plan_finished_reasons': plan_finished_during_calls}
    (run.directory / 'reasons.json').write_text(json.dumps({**out, 'reasons': [d.get('reasons') for d in ds]}, indent=2))
    assert all('reasons' in d for d in ds), 'a deliberate thought without its reasons record'
    assert carrying == [0], f'the one-off feeling was carried by deliberations {carrying} of {len(ds)}'
    assert len(offers) == 1 and offers[0] > 0, f'the offer that arrived during a call: deliberations {offers}'
    assert out['max_carried_before'] == 0, f'a reason was carried twice: {out}'
    # Later thoughts were asked for by the plan finishing (the old code dropped those lines
    # on install and kept the feeling instead, so this count is 0 there).
    assert plan_finished_during_calls >= 2, f'no plan churn to test against: {out}'
    return {'status': 'pass', **out}


@case('scene-since')
def scene_since_case(run):
    """A prompt's scene and its experiences describe one moment (docs/PERCEPTION.md, "One moment
    per prompt"). What a deliberation leaves pending is handed on with a scene taken then
    (`clear_deliberation`): before 2026-11-12 it kept the scene of when the request was last
    merged into, and the mind (which lists experiences up to when it builds the prompt) told Gwil
    in fs1n "right now" that a stranger stood 1.2 m away, beside his own later hail of that
    stranger 28 m off. As in his case, the gap is the compile step: a think reply's routine rework
    merges into the request (refreshing its scene), and the decision is installed a compile later.
    Here M's first deliberation has its think held 9 s and its compile 8 s. A player 2 m away
    offers a trade during the think; during the compile, once the request has its last merge (it
    still places the player near), the player is moved some 30 m off. The request handed on at
    the install, and the next prompt, which carries the offer, must not place the player near.
    A merge between the move and the install would refresh the scene on its own: the case then
    stops as inconclusive rather than pass."""
    people = prepare(run)
    actor = people[0]['id']
    run.harness('player', 'join', 'SceneSinceTrader')
    player = run.sql("SELECT id FROM character WHERE name = 'SceneSinceTrader'", 'trader')[0]['id']
    run.admin('place_near', player, actor)
    run.admin('grant_items', player, 'stone', 2)
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply()},
              'rules': [{'purpose': 'think', 'contains': 'verify scene first', 'delay_s': 9, 'times': 1},
                        {'purpose': 'deliberate', 'contains': 'verify scene first', 'delay_s': 8, 'times': 1},
                        {'purpose': 'think', 'contains': 'offers you', 'delay_s': 6, 'times': 1}]}
    models = model(run, script)
    run.request(actor, 'scene first')
    run.start(models, [actor])
    requests = lambda: list(shared.rows(run.directory / 'fake-requests.jsonl'))
    sent_text = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
    pending = lambda save='pending': run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', save)

    def scene_of(text):
        head = '# What you perceive right now\n'
        return json.loads(text.split(head, 1)[1].split('\n', 1)[0]) if head in text else {}

    def entry(scene, who):
        return next((c for c in scene.get('creatures', []) if c.get('id') == who), None)
    run.wait(lambda: any(e['purpose'] == 'think' and 'verify scene first' in sent_text(e) for e in requests()), 'the first think call in flight', 90)
    run.harness('player', 'act', json.dumps({'do': 'offer', 'target': {'id': actor}, 'item': 'stone', 'qty': 1, 'want': 'wood', 'want_qty': 1}))
    run.wait(lambda: [d for d in pending('pending-offer') if 'offers you' in d['reason']], 'the offer merged into the request in flight', 20)
    run.wait(lambda: any(e['purpose'] == 'deliberate' and 'verify scene first' in sent_text(e) for e in requests()), 'the compile call in flight', 40)
    time.sleep(1.5)  # the think reply's own merges (routine rework, plan state) land first
    before = pending('pending-before-move')
    assert before and 'offers you' in before[0]['reason'], f'the offer is not pending before the move: {before}'
    near = entry(json.loads(before[0]['scene'] or '{}'), player)
    assert near and near['dist'] <= 4.0, f'the request does not place the player near before the move: {near}'
    body = run.sql(f'SELECT * FROM body WHERE id = {actor}', 'm-body')[0]
    moved = None
    for dx, dy in [(30.0, 0.0), (-30.0, 0.0), (0.0, 30.0), (0.0, -30.0), (22.0, 22.0), (-22.0, -22.0), (22.0, -22.0), (-22.0, 22.0)]:
        try:
            run.admin('place_at', player, body['x'] + dx, body['y'] + dy)
            moved = (dx, dy)
            break
        except RuntimeError:
            continue
    assert moved, 'no free tile 30 m from M'
    moved_ms = run.sql('SELECT last_ms FROM clock', 'clock-moved')[0]['last_ms']
    first = run.wait(lambda: [t for t in run.thoughts(actor, 'thoughts-first') if t['kind'] == 'deliberate' and 'verify scene first' in (json.loads(t['detail'] or '{}').get('reason') or '')], 'the first deliberation installed', 60)[0]
    installed_ms = first['at_ms']
    # The rest of the request, as handed on (its next call is held 6 s).
    rest = run.wait(lambda: [d for d in pending('pending-rest') if 'offers you' in d['reason'] and 'verify scene first' not in d['reason']], 'the offer handed on', 20)[0]
    if moved_ms < rest['updated_ms'] < installed_ms:
        raise RuntimeError(f"inconclusive: the request was merged into after the move ({rest['updated_ms']}, moved {moved_ms}, installed {installed_ms}), which refreshes its scene on its own")
    asked = run.wait(lambda: [sent_text(e) for e in requests() if e['purpose'] == 'think' and 'offers you' in sent_text(e) and 'verify scene first' not in sent_text(e)], 'the next prompt, carrying the offer', 40)[0]
    (run.directory / 'prompt-after.txt').write_text(asked)
    there = entry(scene_of(asked), player)
    checks = {
        'rest_scene_taken_when_handed_on': rest['updated_ms'] >= installed_ms,
        'rest_row_scene_not_near': (entry(json.loads(rest['scene'] or '{}'), player) or {}).get('dist', 99.0) > 10.0,
        'next_prompt_scene_not_near': (there or {}).get('dist', 99.0) > 10.0,
    }
    result = {'actor': actor, 'player': player, 'moved': moved, 'before_move_ms': before[0]['updated_ms'], 'moved_ms': moved_ms,
              'installed_ms': installed_ms, 'rest_updated_ms': rest['updated_ms'], 'near_before_move': near,
              'in_rest_row': entry(json.loads(rest['scene'] or '{}'), player), 'in_next_prompt': there, 'checks': checks}
    (run.directory / 'scene-since.json').write_text(json.dumps(result, indent=2))
    assert all(checks.values()), result
    return {'status': 'pass', **result}


@case('sleeper')
def sleeper_case(run):
    """A sleeping body's mind thinks only on what wakes it (perceive.rs `Wake`, the `slumber`
    table): an offer made to a sleeper starts no deliberation while it sleeps and waits in its
    `slumber` row; a quiet line to it takes no talk turn and waits in `heard_asleep`; an attack
    wakes it, and its mind deliberates on why it woke ("You woke up: … is attacking you!") with
    the offer and the line that waited, and is told the line as heard while asleep."""
    people = prepare(run)
    actor, other = [p['id'] for p in people]
    run.admin('set_behavior', other, json.dumps({'wait': 120}))
    run.admin('grant_items', other, 'stone', 2)
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply()}}
    models = model(run, script)
    run.request(actor, 'first')
    run.start(models, [actor])
    # (the reply's plan holds it still)
    accepted(run, actor)
    run.admin('place_near', other, actor)
    pending = lambda label: run.private(f'SELECT * FROM deliberation WHERE actor = {actor}', label)
    run.wait(lambda: not pending('pending-before-sleep'), 'no request pending', 60)
    # Asleep (short sleeps one after another; the plan ending between them waits too).
    run.admin('set_behavior', actor, json.dumps({'seq': [{'do': 'sleep'}]}))
    slumber = lambda label: run.private(f'SELECT * FROM slumber WHERE actor = {actor}', label)
    run.wait(lambda: slumber('slumber-start'), 'asleep', 30)
    base = max((t['id'] for t in run.thoughts(actor, 'thoughts-asleep')), default=0)
    sent_before = len([e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e.get('purpose') == 'deliberate'])
    talks_before = len([e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e.get('purpose') == 'talk'])
    run.admin('mind_act', other, [json.dumps({'do': 'offer', 'target': {'id': actor}, 'item': 'stone', 'qty': 1, 'want': 'wood', 'want_qty': 1})], 'verify-minds')
    run.wait(lambda: any('offers you' in r['reason'] for r in slumber('slumber-offer')), 'the offer waits in slumber', 30)
    # A quiet line to the sleeper (another's `say`): no talk turn while it sleeps; kept for its waking.
    thought = {'kind': 'deliberate', 'summary': 'verify minds sleeper', 'detail': '', 'latency_ms': 0, 'tokens': 0, 'model': 'fake', 'reference': ''}
    run.admin('mind_say', other, 'verify quiet line to a sleeper', actor, '', 0, thought)
    run.wait(lambda: run.private(f'SELECT * FROM heard_asleep WHERE actor = {actor}', 'heard-asleep'), 'the line waits for its waking', 15)
    time.sleep(15)
    talks_asleep = len([e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e.get('purpose') == 'talk']) - talks_before
    assert talks_asleep == 0, f'a sleeper took {talks_asleep} talk turns'
    assert not [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'told-asleep') if 'verify quiet line' in e['text']], 'the line was told while asleep'
    later = [t for t in run.thoughts(actor, 'thoughts-after-offer') if t['id'] > base and t['kind'] == 'deliberate']
    asked = [d for d in pending('pending-after-offer') if 'offers you' in d['reason']]
    sent_asleep = len([e for e in shared.rows(run.directory / 'fake-requests.jsonl') if e.get('purpose') == 'deliberate']) - sent_before
    assert not later and not asked and sent_asleep == 0, f'a sleeper deliberated: thoughts {later}, pending {asked}, model calls {sent_asleep}'
    # Attacked: it wakes and thinks at once, on why it woke and the offer that waited.
    run.admin('set_behavior', other, json.dumps({'do': 'attack', 'target': {'nearest': 'person'}}))
    woke = run.wait(lambda: [t for t in run.thoughts(actor, 'thoughts-woken') if t['id'] > base and t['kind'] == 'deliberate'], 'a deliberation after the attack', 90)
    reason = json.loads(woke[0]['detail']).get('reason', '')
    run.admin('set_behavior', other, json.dumps({'wait': 120}))
    assert reason.startswith('You woke up: ') and 'attacking you' in reason.split('\n')[0], reason
    assert 'offers you' in reason, f'the offer that waited was not asked with the waking: {reason!r}'
    assert 'While you slept, you heard: ' in reason and 'verify quiet line to a sleeper' in reason, f'the line heard asleep was not asked with the waking: {reason!r}'
    # (the test graph may put it to sleep again until the mind's reply replaces it)
    run.wait(lambda: not slumber('slumber-after'), 'awake under the mind\'s plan', 30)
    told = [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'told') if e['kind'] == 'body' and e['text'].startswith('You woke up: ')]
    assert told, 'the sleeper was not told it woke'
    heard = [e for e in run.private(f'SELECT * FROM experience WHERE observer = {actor}', 'heard-on-waking') if e['kind'] == 'heard_asleep' and 'verify quiet line' in e['text']]
    assert len(heard) == 1, f'the line heard asleep was not told once on waking: {heard}'
    return {'status': 'pass', 'model_calls_asleep': sent_asleep, 'talk_turns_asleep': talks_asleep, 'woken_reason': reason, 'told': told[0]['text'], 'heard_asleep': heard[0]['text']}


def system_text(body):
    return '\n'.join(m.get('content', '') for m in body.get('messages', []) if m.get('role') == 'system')


@case('frame')
def frame_case(run):
    """LIVING_FRAME=player: a person's think, compile, talk and consolidation requests open with
    the player frame, as sent (fake log) and as journaled; a starting identity is not framed; a
    value that is neither frame stops the service before it connects."""
    bad = subprocess.run([str(shared.MIND_BIN)], cwd=ROOT, capture_output=True, text=True, timeout=30,
                         env=dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_FRAME='npc', LIVING_NEO4J='off',
                                  LIVING_SERVER='http://127.0.0.1:9', LIVING_TOKEN='unused'))
    (run.directory / 'bad-frame.log').write_text(bad.stdout + bad.stderr)
    assert bad.returncode != 0 and 'expected character or player' in bad.stdout + bad.stderr, bad.returncode
    people = prepare(run)
    actor = people[0]['id']
    script = {'replies': {'think': {'thought': 'I choose to wait for this check.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'A question.', 'say': 'verify frame answer', 'end': False},
                          'consolidate': {'summary': 'verify frame integrated speech', 'identity': None}}}
    models = model(run, script)
    run.request(actor, 'first')
    run.start(models, [actor], extra_env={'LIVING_FRAME': 'player'})
    assert 'prompt frame: player (LIVING_FRAME)' in run.log()
    accepted(run, actor)
    run.harness('player', 'join', 'FrameSpeaker')
    player = run.sql("SELECT id FROM character WHERE name = 'FrameSpeaker'", 'player')[0]['id']
    run.admin('place_near', player, actor)
    for line in ('Will you listen to this important verification question?',
                 'Can you remember the river and the missing berry basket?',
                 'Did you notice the stone tower and the winter campfire?',
                 'Will you recall our conversation when morning comes?'):
        run.harness('player', 'say', line, '--to', str(actor))
        time.sleep(2.2)
    sent = lambda: shared.rows(run.directory / 'fake-requests.jsonl')
    consolidation = lambda e: e['purpose'] == 'consolidate' and 'self-understanding' in system_text(e['body'])
    run.wait(lambda: {'think', 'deliberate', 'talk'} <= {e['purpose'] for e in sent()} and any(consolidation(e) for e in sent()),
             'think, compile, talk and consolidation requests', 110)
    framed = {}
    for e in sent():
        system = system_text(e['body'])
        kind = 'identity' if 'starting identity' in system else ('consolidation' if consolidation(e) else e['purpose'])
        framed.setdefault(kind, []).append(system.startswith(PLAYER_FRAME_HEAD))
    (run.directory / 'frame.json').write_text(json.dumps({k: f'{sum(v)}/{len(v)}' for k, v in framed.items()}, indent=2))
    for kind in ('think', 'deliberate', 'talk', 'consolidation'):
        assert framed.get(kind) and all(framed[kind]), (kind, framed.get(kind))
    assert not any(framed.get('identity', [])), framed.get('identity')
    # As journaled: system prompts are stored once beside the journal (content_ref).
    journaled = []
    for e in run.exchanges():
        for m in e.get('request', {}).get('messages', []):
            if m.get('role') == 'system':
                text = m.get('content') or (run.journal / m['content_ref']).read_text()
                journaled.append((e['purpose'], text.startswith(PLAYER_FRAME_HEAD)))
    assert any(f for p, f in journaled if p == 'talk') and any(f for p, f in journaled if p == 'think'), journaled[:6]
    return {'status': 'pass', 'framed': {k: f'{sum(v)}/{len(v)}' for k, v in framed.items()},
            'journaled_framed': sum(f for _, f in journaled), 'journaled': len(journaled), 'bad_value_exit': bad.returncode}


@case('speech')
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
    heard = run.private(f'SELECT * FROM line_heard WHERE speaker = {actor}', 'mind-heard')
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


@case('queued')
def queued_case(run):
    """A plan's queued line overtaken by a reply (`speech_truth`, brain.rs `line_overtaken`;
    docs/COMMUNICATION.md §15). The plan holds a line for the newcomer until the newcomer stands
    within 2 m (`near`); the newcomer waits 4 m off. It asks the resident a question 1 s after the
    install; as soon as the resident's talk turn has answered, the newcomer is moved beside it,
    which releases the queued line. The authority's speaking limit (2 s between two lines of one
    speaker, `SPEAK_GAP_MS`) holds it until 2 s after the reply, so two answers are never under
    2 s apart in this engine (the 1.5 s in ar2's inspector is not the authority's line times);
    here they come 2.3–2.4 s apart (minds-struth5/6-queued). Waking the graph with a second
    resident's line drew a reply of its own that reset the limit (minds-struth8-queued, 4.4 s). With the law off, the reply and the queued line both reach the
    newcomer about a second apart: two answers to one line, as Sefa's 1.5 s apart in ar2's
    `arrive-answer` `all` r3. With it on (the default), only the reply: the queued line is
    dropped, and nothing is said in its place. Times are the speaker's own `said` rows (the
    chronicle merges a line repeated word for word). A fixed wait could not do this: the talk
    turn took 5.7 s in minds-struth-queued and 2.9 s in minds-struth2-queued. (A nod as the
    release, minds-struth4-queued, never set the resident's `hailed_ms`; not pursued here.)"""
    people = prepare(run)
    actor = people[0]['id']
    run.harness('player', 'join', 'MindsNewcomer')
    player = run.sql("SELECT id FROM character WHERE name = 'MindsNewcomer'", 'player')[0]['id']
    run.admin('place_near', player, actor)
    plan = {'first': [{'if': {'near': {'target': {'id': player}, 'within': 2}}, 'then': {'say': {'text': 'verify minds queued line', 'to': {'id': player}}}}, {'wait': 120}]}
    script = {'replies': {'think': {'thought': 'I will greet the newcomer when they come up to me.', 'intend': ['ask who they are when they come close'], 'say': None},
                          'deliberate': basic_reply(graph=plan, plan='verify minds queued'),
                          # Not `end`: a settled pair takes no turn on a line like the last (minds-struth9-queued).
                          'talk': {'thought': 'I answer them.', 'say': 'verify minds talk reply', 'settled': None, 'end': False}}}
    models = model(run, script)
    token = json.loads((run.directory / 'state.json').read_text())['token']

    def as_player(reducer, args):
        # Over HTTP with the player's token: a harness subprocess takes seconds under load.
        req = urllib.request.Request(f"{shared.STDB_URL}/v1/database/{run.db}/call/{reducer}", data=json.dumps(args).encode(),
                                     headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 200
        with (run.directory / 'actions.log').open('a') as log:
            log.write(f"{time.strftime('%H:%M:%S')} player {reducer}{json.dumps(args)} -> 200 (HTTP, fast)\n")

    def http(path, body, tok, raw=False):
        req = urllib.request.Request(f"{shared.STDB_URL}{path}", data=(body if raw else json.dumps(body)).encode(),
                                     headers={'Content-Type': 'text/plain' if raw else 'application/json', 'Authorization': f'Bearer {tok}'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()

    def reply_seen(installed):
        # Straight SQL with the admin token (the harness's subprocess takes a second or more under load).
        _, body = http(f'/v1/database/{run.db}/sql', f'SELECT * FROM experience WHERE observer = {actor}', run.token, raw=True)
        res = json.loads(body)[-1]
        names = [e['name'].get('some', '?') for e in res['schema']['elements']]
        rows = [dict(zip(names, r)) for r in res['rows']]
        return any(r['kind'] == 'said' and r['object'] == player and r['at_ms'] > installed and 'verify minds talk reply' in r['text'] for r in rows)

    def said(installed, label):
        exps = run.private(f'SELECT * FROM experience WHERE observer = {actor}', f'exp-{label}')
        return exps, sorted((e for e in exps if e['kind'] == 'said' and e['object'] == player and e['at_ms'] > installed), key=lambda e: e['at_ms'])

    def arm(label, law):
        run.admin('set_world_law', 'speech_truth', law)
        # The newcomer waits 4 m off: within earshot, not within the plan's 2 m.
        run.admin('place_at', player, home[0] + 4.0, home[1])
        before = {b['installed_ms'] for b in run.private(f'SELECT * FROM brain WHERE id = {actor}', f'brain-before-{label}')}
        run.request(actor, 'queued ' + label)
        brain = run.wait(lambda: [b for b in run.private(f'SELECT * FROM brain WHERE id = {actor}', f'brain-{label}')
                                  if b['source'] == 'mind' and b['installed_ms'] not in before], f'{label}: the plan installed', 90)[0]
        installed = brain['installed_ms']
        while time.time() * 1000 < installed + 1000:
            time.sleep(0.05)
        # Each arm asks something new: words mostly like the exchange's earlier ones draw no turn.
        as_player('human_say', [{'off': 'Hello. I am new here. Who are you?', 'on': 'Another matter entirely: where does the river bend north?'}[label], actor])
        deadline = time.monotonic() + 40
        while not reply_seen(installed):
            assert time.monotonic() < deadline, f'{label}: no talk reply'
            time.sleep(0.05)
        status, _ = http(f'/v1/database/{run.db}/call/place_at', [player, home[0] + 1.0, home[1]], run.token)
        with (run.directory / 'actions.log').open('a') as log:
            log.write(f"{time.strftime('%H:%M:%S')} admin place_at{json.dumps([player, home[0] + 1.0, home[1]])} -> {status} (HTTP, fast)\n")
        time.sleep(8)
        exps, lines = said(installed, label)
        reply = [e for e in lines if 'verify minds talk reply' in e['text']]
        queued = [e for e in lines if 'verify minds queued line' in e['text']]
        gap = (queued[0]['at_ms'] - reply[0]['at_ms']) / 1000 if reply and queued else None
        silences = [e['text'] for e in exps if e['kind'] == 'silence' and e['at_ms'] > installed]
        run.sql(f'SELECT * FROM chronicle WHERE a = {actor}', f'chronicle-{label}')
        return {'installed_ms': installed, 'said': [((e['at_ms'] - installed) / 1000, e['text']) for e in lines], 'reply': len(reply), 'queued': len(queued),
                'gap_s': gap, 'silences': silences}

    run.request(actor, 'queued warmup')
    run.start(models, [actor])
    accepted(run, actor, 'verify minds queued')
    body = run.private(f'SELECT * FROM body WHERE id = {actor}', 'actor-body')[0]
    home = (body['x'], body['y'])
    time.sleep(3)
    off = arm('off', 'false')
    assert off['reply'] == 1 and off['queued'] == 1, f'law off: the double answer is not reproduced: {off}'
    assert off['gap_s'] is not None and 0 < off['gap_s'] <= 3.0, f'law off: the two answers are not within 3 s: {off}'
    time.sleep(3)
    on = arm('on', 'true')
    assert on['reply'] == 1 and on['queued'] == 0, f'law on: the queued line was said on top of the reply: {on}'
    assert not on['silences'], f'law on: an overtaken line is dropped, not told as unheard: {on}'
    return {'status': 'pass', 'off': off, 'on': on}


# A year of age every 20 real seconds on Cullet's day (48 minutes) and laws (90-year lives,
# adult from 15, old from 59.5): year = year_days 4 x pace x 48 min.
BODY_PACE = 20 / (4 * 48 * 60)


def body_seed(run):
    """The hamlet (12 people, two settlements, Cullet's day and laws) on a fast life pace, with
    a child who comes of age and an adult who grows old a couple of minutes in, written under
    this run's directory and named relative to living/seeds (as trials name derived seeds)."""
    seed = json.loads((ROOT / 'living/seeds/hamlet.json').read_text())
    seed['run'] = 'verify-body'
    seed['life_pace'] = BODY_PACE
    for t in seed['towns'] + seed['villages']:
        for r in t['residents']:
            if r['name'] == 'Lio Reed':
                r['age'] = 7.0       # adult (15) about 160 s after world creation
            if r['name'] == 'Cal Reed':
                r['age'] = 51.0      # old (59.5) about 170 s after
    path = run.directory / 'body-seed.json'
    path.write_text(json.dumps(seed, indent=1))
    return os.path.relpath(path.with_suffix(''), ROOT / 'living/seeds')


def prompts_of(run, name):
    """Every request the fake model got for `name`, oldest first: (purpose, prompt text). Think,
    deliberate and consolidate prompts head `# Who you are (Name)`; talk and reorganize prompts
    `# Who you are\nName`."""
    out = []
    path = run.directory / 'fake-requests.jsonl'
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        text = '\n'.join(m.get('content', '') for m in (e.get('body') or {}).get('messages', []) if isinstance(m.get('content'), str))
        if f'# Who you are ({name})' in text or f'# Who you are\n{name}\n' in text:
            out.append((e.get('purpose'), text))
    return out


def body_lines(text):
    return re.findall(r'^Your body: [^\n]*$', text, re.M)


@case('body')
def body_case(run):
    """The body's age and stage in every prompt's "# Who you are" (prompts::body_line), and a
    first identity from facts for a mind that starts once its character is grown (Origin::Grown).

    1. Coming of age: Lio Reed is a child when his mind starts; after his character row turns
       adult, his next talk prompt and his next consolidation prompt say "an adult for".
    2. Growing old: Cal Reed's prompts say "an adult" before and "old for" after.
    3. A late-starting run-born mind: Brisk and Edda Marrow (graph-only) start a family; the
       child is born and grows up with no mind; the mind is then restarted with it. Its first
       identity is written from facts with no model call (no identity request for it), names its
       parents, and has no values, goals, pastimes or mood; its first prompt carries it and the
       adult body line. With LIVING_PRIVACY_NEO4J set (privacy.py's scratch Neo4j), its mind
       also holds CHILD_OF edges to both parents and the `parent` relation rows are projected."""
    rel = body_seed(run)
    target = Path(os.environ['CARGO_TARGET_DIR']) / 'verify-body' if os.environ.get('CARGO_TARGET_DIR') else ROOT / '.local/living/target-body'
    run.harness('launch', '--seed', str((ROOT / 'living/seeds' / rel).resolve()) , '--target-dir', str(target))
    run.harness('doctor')
    people = {p['name']: p for p in run.sql("SELECT * FROM character WHERE kind = 'person'", 'people')}
    lio, cal, brisk, edda = (people[n]['id'] for n in ('Lio Reed', 'Cal Reed', 'Brisk Marrow', 'Edda Marrow'))
    assert people['Lio Reed']['stage'] == 1 and people['Cal Reed']['stage'] == 2, people
    # The couple lives on graphs (no mind) and starts a family.
    run.admin('place_near', edda, brisk)
    for a, b in ((brisk, edda), (edda, brisk)):
        run.admin('grant_items', a, 'berries', 6)
        run.admin('set_behavior', a, json.dumps({'seq': [{'do': 'conceive', 'target': {'id': b}}, {'wait': 600}]}))
    run.harness('player', 'join', 'BodyListener')
    me = run.sql("SELECT id FROM character WHERE name = 'BodyListener'", 'player')[0]['id']
    run.admin('place_near', me, lio)
    script = {'replies': {'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None},
                          'deliberate': basic_reply(),
                          'talk': {'thought': 'Someone speaks to me.', 'say': 'verify body: I hear you.', 'end': True},
                          'consolidate': {'summary': 'verify body summary', 'identity': None, 'nodes': [], 'edges': []}},
              'rules': [{'purpose': 'consolidate', 'delay_s': 1, 'times': -1}]}
    models = model(run, script)
    neo = os.environ.get('LIVING_PRIVACY_NEO4J') and os.environ.get('LIVING_PRIVACY_NEO4J_ENV')
    extra = {}
    if neo:
        container, uri = os.environ['LIVING_PRIVACY_NEO4J'].split(':', 1)
        pw = next(l.split('=', 1)[1].strip() for l in Path(os.environ['LIVING_PRIVACY_NEO4J_ENV']).read_text().splitlines() if l.startswith('LIVING_NEO4J_PASSWORD='))
        extra = {'LIVING_NEO4J': 'on', 'LIVING_NEO4J_URI': uri, 'LIVING_NEO4J_PASSWORD': pw}
    run.start(models, [lio, cal], seed=rel, extra_env=extra)
    stage = lambda who, save: run.sql(f'SELECT * FROM character WHERE id = {who}', save)[0]['stage']

    said = [0]

    def talked(words, skip, seconds=150):
        """Lines to Lio, standing beside him, until a talk prompt after the first `skip` carries
        `words` in its body line (the first line of an exchange may be answered by a thought)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            run.admin('place_near', me, lio)
            run.harness('player', 'say', f'verify body: line {said[0]}, can you hear me?', '--to', str(lio))
            said[0] += 1
            end = time.monotonic() + 8
            while time.monotonic() < end:
                hits = [b for p, t in prompts_of(run, 'Lio Reed')[skip:] if p == 'talk' for b in body_lines(t) if words in b]
                if hits:
                    return hits
                time.sleep(0.5)
        raise RuntimeError(f'no talk prompt with {words!r} in {seconds}s')

    # Before: a child's body line.
    talked('a child for', 0)
    n_before = len(prompts_of(run, 'Lio Reed'))
    run.wait(lambda: stage(lio, 'lio-stage') == 2, 'Lio comes of age', 240)
    seen_at = len(prompts_of(run, 'Lio Reed'))
    def after(purpose, who='Lio Reed', words='an adult for', skip=seen_at):
        return [b for p, t in prompts_of(run, who)[skip:] if p == purpose for b in body_lines(t) if words in b]
    # The first talk and the first consolidation prompts after he came of age: none says a child.
    talk_after = talked('an adult for', seen_at)
    first_talk = next(b for p, t in prompts_of(run, 'Lio Reed')[seen_at:] if p == 'talk' for b in body_lines(t))
    cons_after = run.wait(lambda: after('consolidate'), 'the next consolidation prompt carries the adult body line', 240)
    first_cons = next(b for p, t in prompts_of(run, 'Lio Reed')[seen_at:] if p == 'consolidate' for b in body_lines(t))
    # Growing old.
    cal_before = [b for p, t in prompts_of(run, 'Cal Reed') for b in body_lines(t)]
    run.wait(lambda: stage(cal, 'cal-stage') == 3, 'Cal grows old', 240)
    cal_seen = len(prompts_of(run, 'Cal Reed'))
    run.admin('set_behavior', cal, json.dumps({'think': 'I finished my plan. verify body old'}))
    cal_after = run.wait(lambda: after('deliberate', 'Cal Reed', 'old for', cal_seen) or after('think', 'Cal Reed', 'old for', cal_seen), 'Cal\'s next prompt says old', 120)
    # The couple's child, born and grown with no mind.
    child = run.wait(lambda: next((c for c in run.sql("SELECT * FROM character WHERE kind = 'person'", 'children')
                                   if c['parent_a'] in (brisk, edda) and c['parent_b'] in (brisk, edda)), None), 'a child born to Brisk and Edda', 240)
    cid, cname = child['id'], child['name']
    run.wait(lambda: stage(cid, 'child-stage') == 2, f'{cname} grows up with no mind', 420)
    run.note(f'{cname} (#{cid}) is grown; restarting the mind with it')
    shared.stop(run.mind)
    subscriptions = run.log().count('world subscribed:')
    run.env['LIVING_ONLY'] = ','.join(map(str, [lio, cal, cid]))
    run.launch_mind()
    run.wait(lambda: run.log().count('world subscribed:') > subscriptions, 'the restarted mind subscribed')
    persona = run.wait(lambda: run.private(f'SELECT * FROM persona WHERE id = {cid}', 'grown-persona'), f'{cname}\'s first identity', 60)[0]
    thoughts = run.thoughts(cid, 'grown-thoughts')
    first = [t for t in thoughts if 'grown before my mind began' in t['summary']]
    parents = sorted(people[n]['name'] for n in ('Brisk Marrow', 'Edda Marrow'))
    narrative = persona['narrative']
    run.admin('set_behavior', cid, json.dumps({'think': 'I finished my plan. verify body grown'}))
    grown_prompt = run.wait(lambda: [t for p, t in prompts_of(run, cname) if p in ('think', 'deliberate')], f'{cname}\'s first prompt', 90)[0]
    identity_calls = [p for p, t in prompts_of(run, cname) if p == 'consolidate' and ('Newborn:' in t or 'world holds about' in t)]
    checks = {
        'lio_child_line_before': n_before > 0,
        'lio_talk_after': talk_after[0], 'lio_consolidate_after': cons_after[0],
        'lio_next_talk_is_adult': 'an adult for' in first_talk, 'lio_next_consolidation_is_adult': 'an adult for' in first_cons,
        'cal_first_adult': next((b for b in cal_before if 'an adult for' in b), None), 'cal_after': cal_after[0],
        'grown_first_identity_thought': bool(first) and first[0]['model'] == 'facts',
        'grown_names_parents': all(n in narrative for n in parents),
        'grown_no_invented_wants': not persona['values'] and not persona['goals'] and not persona['pastimes'] and not persona['mood'] and not persona['calling'],
        'grown_no_identity_call': not identity_calls,
        'grown_prompt_has_identity': narrative in grown_prompt,
        'grown_prompt_body_line': next((b for b in body_lines(grown_prompt) if 'an adult for' in b), None),
    }
    if neo:
        q = (f"MATCH (s:Concept {{run: '{run.db}', actor: {cid}, key: 'self'}})-[r:CHILD_OF]->(p) RETURN p.key AS k, r.lived_under AS by;")
        out = subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c', 'NEO4J_PASSWORD="${NEO4J_AUTH#*/}" cypher-shell -a bolt://localhost:7687 -u neo4j --format plain'],
                             input=q, capture_output=True, text=True, timeout=60)
        (run.directory / 'grown-child-of.txt').write_text(out.stdout + out.stderr)
        checks['grown_child_of'] = all(f'person:{p}' in out.stdout for p in (brisk, edda))
        rels = run.wait(lambda: [r for r in run.private(f'SELECT * FROM relation WHERE actor = {cid}', 'grown-relations') if r['label'] == 'parent'], 'parent relations projected', 60)
        checks['grown_parent_relations'] = sorted(r['other'] for r in rels) == sorted((brisk, edda))
        clean = subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c', 'NEO4J_PASSWORD="${NEO4J_AUTH#*/}" cypher-shell -a bolt://localhost:7687 -u neo4j --format plain'],
                               input=f"MATCH (n) WHERE n.run = '{run.db}' DETACH DELETE n;", capture_output=True, text=True, timeout=60)
        checks['neo4j_cleaned'] = clean.returncode == 0
    else:
        checks['neo4j'] = 'skipped: set LIVING_PRIVACY_NEO4J and LIVING_PRIVACY_NEO4J_ENV to check CHILD_OF and parent relations'
    (run.directory / 'body.json').write_text(json.dumps({'checks': checks, 'grown': {'id': cid, 'name': cname, 'narrative': narrative,
        'persona': persona}, 'lio': talk_after + cons_after, 'cal': cal_after}, indent=2))
    ok = all(v for k, v in checks.items() if k != 'neo4j')
    return {'status': 'pass' if ok else 'fail', 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', help='new suite name starting with minds- (gate- for the merge scene gate)')
    parser.add_argument('--case', action='append', choices=list(CASES), help='repeat to select; default all')
    parser.add_argument('--list', action='store_true', help='print the registered cases, one per line, and exit')
    parser.add_argument('--no-unit-tests', action='store_true',
                        help="skip living-mind's cargo tests (the merge's scene gate runs them as its own case, mind-unit)")
    args = parser.parse_args()
    if args.list:
        print('\n'.join(CASES))
        return 0
    if not args.run:
        parser.error('--run is required')
    if not re.fullmatch(r'(minds|gate)-[a-zA-Z0-9-]+', args.run):
        parser.error('--run must start with minds- (or gate- for the merge scene gate)')
    with urllib.request.urlopen(os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/') + '/v1/ping', timeout=5) as response:
        assert response.status == 200
    suite = ROOT / '.local/living/verify' / args.run
    suite.mkdir(parents=True, exist_ok=False)
    for command, name in ((['cargo', 'build', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--release'], 'build.log'),
                          (['cargo', 'test', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--', '--nocapture'], 'cargo-tests.log')):
        if args.no_unit_tests and name == 'cargo-tests.log':
            (suite / name).write_text('skipped (--no-unit-tests)\n')
            continue
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
            result = CASES[case](run)
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
