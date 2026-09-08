"""Validate paused owner SQL diagnostics against the canonical World export."""
import json
import hashlib
from collections import Counter


def verify_native_trace(tables, world, run, require_all=True):
    participants = tables['sim_native_participant']
    indexes = {row[2]: row for row in tables['sim_native_trace_index']}
    payloads = {(row[2], row[3]): row for row in tables['sim_native_experience']}
    if len(indexes) != len(tables['sim_native_trace_index']) or len(payloads) != len(tables['sim_native_experience']):
        raise ValueError('duplicate native trace identity')
    heads = {row[2]: row for row in tables.get('sim_native_trace_head', [])}
    pages = {row[0]: row for row in tables.get('sim_native_trace_page', [])}
    bodies = {row[0]: row for row in tables.get('sim_native_evidence_body', [])}
    retention = {row[0]: row for row in tables.get('sim_native_evidence_retention', [])}
    for name, values in [('sim_native_trace_head', heads), ('sim_native_trace_page', pages),
                         ('sim_native_evidence_body', bodies), ('sim_native_evidence_retention', retention)]:
        if len(values) != len(tables.get(name, [])):
            raise ValueError('duplicate paged trace storage identity')
    paged, used_pages, references = set(), set(), Counter()
    logical_bytes = 0
    migrated, retained, expected_payloads = set(), 0, set()
    for row in participants:
        key, scope, actor = row[:3]
        if scope != run or key != f'{run}:{actor}':
            raise ValueError('participant scope mismatch')
        experiences = world['participants'][str(actor)]['experiences']
        expected = [[e[k] for k in ('cursor', 'source', 'tick', 'location', 'kind', 'parents')] for e in experiences]
        if row[6] == 'sao-native-trace-pages-v4':
            paged.add(actor)
            head = heads.get(actor)
            if head is None or head[:3] != [key, scope, actor]:
                raise ValueError('paged trace head scope mismatch')
            entries = []
            for first in head[3]:
                page_key = f'{run}:{actor}:{first}'
                page = pages.get(page_key)
                if page_key in used_pages or page is None or page[:4] != [page_key, run, actor, first]:
                    raise ValueError('missing, repeated or foreign trace page')
                used_pages.add(page_key)
                if not page[4] or len(page[4]) > 32 or page[4][0][0][0] != first:
                    raise ValueError('invalid trace page shape')
                if any(entry[0][0] // 32 != first // 32 for entry in page[4]):
                    raise ValueError('invalid trace page cursor bucket')
                entries.extend(page[4])
            if [entry[0] for entry in entries] != expected or len({m[0] for m in expected}) != len(expected):
                raise ValueError('paged ordered metadata or cursor mismatch')
            for (_, body_id), e in zip(entries, experiences):
                body = bodies.get(body_id)
                if body is None or json.loads(body[3]) != e['data']:
                    raise ValueError('missing or mismatched paged evidence body')
                references[body_id] += 1
                logical_bytes += len(body[3].encode())
            retained += len(experiences)
            continue
        if row[6] == 'sao-native-trace-index-v3':
            migrated.add(actor)
            index = indexes.get(actor)
            if index is None or index[:3] != [key, scope, actor] or index[3] != expected:
                raise ValueError('typed trace scope or ordered metadata mismatch')
        elif require_all:
            raise ValueError('participant still uses legacy trace storage')
        cursors = set()
        for e, metadata in zip(experiences, expected):
            identity = (actor, e['cursor'])
            if e['cursor'] in cursors:
                raise ValueError('duplicate retained cursor')
            cursors.add(e['cursor'])
            expected_payloads.add(identity)
            payload = payloads.get(identity)
            if payload is None or payload[:3] != [f'{run}:{actor}:{e["cursor"]}', run, actor] or payload[3:9] != metadata or json.loads(payload[9]) != e['data']:
                raise ValueError('retained evidence metadata or payload mismatch')
            retained += 1
    if set(indexes) != migrated or set(payloads) != expected_payloads:
        raise ValueError('unreferenced or missing current evidence rows')
    if set(heads) != paged or set(pages) != used_pages or set(bodies) != set(references) or set(retention) != set(references):
        raise ValueError('missing or unreferenced paged trace storage')
    for body_id, (stored_id, identity, scope, data) in bodies.items():
        digest = hashlib.sha256()
        for value in (scope, 'personal-evidence-v4', data):
            value = value.encode()
            digest.update(len(value).to_bytes(8, 'little')); digest.update(value)
        digest.update(b'shared')
        if body_id == 0 or stored_id != body_id or scope != run or digest.hexdigest() != identity:
            raise ValueError('evidence body scope or content identity mismatch')
        if retention[body_id] != [body_id, run, references[body_id]]:
            raise ValueError('evidence reference balance mismatch')
    if len(participants) != len(world['participants']):
        raise ValueError('participant count differs from canonical export')
    return dict(passed=True, participants=len(participants), typed_indexes=len(indexes)+len(heads),
                legacy_indexes=len(indexes), paged_heads=len(heads), pages=len(pages), body_rows=len(bodies),
                body_references=sum(references.values()), logical_body_bytes=logical_bytes,
                stored_body_bytes=sum(len(r[3].encode()) for r in bodies.values()),
                retained_experiences=retained, payload_rows=len(payloads),
                note='Paused owner diagnostics: exact scope, ordered metadata, payloads and current-row retention.')
