#!/usr/bin/env python3
"""Report recorded population development, controller calls and support continuity.

This is an evidence report, not a society success score. Event ordering shows what
happened after a loss; it does not by itself prove why a character chose an action.
"""
import argparse
import collections
import contextlib
import hashlib
import io
import json
from pathlib import Path

from summarize_knowledge import summarize as summarize_knowledge


def reference(event):
    return dict(event=event['id'], actor=event.get('actor'), kind=event['kind'],
                time_ms=event['data'].get('time_ms'), parents=event.get('parents', []),
                data=event['data'])


def analyze(world, events, calls, participants):
    events = sorted(events, key=lambda event: event['id'])
    initial_ids = {player['id'] for player in world['initial']['players']}
    players = {player['id']: player for player in world['players']}
    births = [event for event in events if event['kind'] == 'actor_created']
    deaths = [event for event in events if event['kind'] == 'death']
    enrollment = {participant['actor']: participant for participant in participants}
    rows = []
    for birth in births:
        actor = birth['actor']
        player = players.get(actor, {})
        life = world.get('lifecycle', {}).get(str(actor), {})
        own = [event for event in events if event.get('actor') == actor]
        care = [event for event in events if event['kind'] == 'care_given' and event['data'].get('target') == actor]
        practice = [event for event in own if event['kind'] == 'practice_completed']
        independence = [event for event in own if event['kind'] == 'self_support_acquired']
        knowledge = [event for event in own if event['kind'] == 'perception' and event['data'].get('kind') == 'knowledge_report']
        independent_gathers = [event for event in own if event['kind'] == 'resource_change'
                               and event['data'].get('food_delta', 0) < 0
                               and event['data'].get('nature') != 'guided_practice'
                               and any(ready['id'] < event['id'] for ready in independence)]
        actor_calls = [call for call in calls if call['actor'] == actor]
        losses = []
        for death in deaths:
            if death['id'] <= birth['id']:
                continue
            prior_care = [event for event in care if event['actor'] == death['actor'] and event['id'] < death['id']]
            creator = death['actor'] in birth['data'].get('creators', [])
            if not prior_care and not creator:
                continue
            later_care = [event for event in care if event['id'] > death['id']]
            losses.append(dict(loss=reference(death), was_creator=creator,
                               care_before_loss=[reference(event) for event in prior_care],
                               care_after_loss=[reference(event) for event in later_care],
                               later_caregivers=sorted({event['actor'] for event in later_care}),
                               practice_after_loss=[reference(event) for event in practice if event['id'] > death['id']],
                               independence_after_loss=[reference(event) for event in independence if event['id'] > death['id']],
                               independent_gathers_after_loss=[reference(event) for event in independent_gathers if event['id'] > death['id']]))
        rows.append(dict(actor=actor, name=player.get('name', birth['data'].get('name')),
                         birth=reference(birth), final_health=player.get('health'), final_food=player.get('food'),
                         final_hunger=player.get('hunger'), final_energy=player.get('energy'),
                         final_lifecycle=life, enrollment=enrollment.get(actor),
                         care=[reference(event) for event in care], practice=[reference(event) for event in practice],
                         independence=[reference(event) for event in independence],
                         independent_gathers=[reference(event) for event in independent_gathers],
                         knowledge_acquisitions=[reference(event) for event in knowledge],
                         creator_or_caregiver_losses=losses,
                         model_attempts=len(actor_calls),
                         model_http_successes=sum(isinstance(call.get('status'), int) and 200 <= call['status'] < 300 for call in actor_calls),
                         model_completed_without_error=sum(call.get('phase') == 'completed' and not call.get('error') and not call.get('provider_error') for call in actor_calls),
                         accepted_command_receipts=sum(call.get('accepted_command_receipts', 0) for call in actor_calls),
                         rejected_command_receipts=sum(call.get('rejected_command_receipts', 0) for call in actor_calls),
                         model_reported_tokens=sum(call.get('total_tokens', 0) or 0 for call in actor_calls),
                         model_calls=actor_calls))
    rejections = [event for event in events if event['kind'] == 'participant_rejected']
    return dict(initial_population=len(initial_ids), created_population=len(births),
                final_population=len(players), living_population=sum(player['health'] > 0 for player in players.values()),
                methods=dict(collections.Counter(event['data'].get('method', 'unknown') for event in births)),
                newcomers=rows, deaths=[reference(event) for event in deaths],
                reproduction_agreements=[reference(event) for event in events if event['kind'] == 'reproduction_committed'],
                rejections=[reference(event) for event in rejections],
                disturbances=[reference(event) for event in events if event['kind'] == 'scenario_disturbance'],
                interpretation='Birth is not independence. Care and practice require their own authority events; model attempts require saved call journals. Later support is an observed sequence, not proof of intent or causal effect. Survival and self-support are measured only through the recorded endpoint.')


def summarize(out):
    out = Path(out).resolve()
    with contextlib.redirect_stdout(io.StringIO()):
        knowledge = summarize_knowledge(out)
    pilot = json.loads((out / 'pilot.json').read_text())
    run = out / pilot['run']
    source = run / ('final-snapshot.json' if (run / 'final-snapshot.json').exists() else 'snapshot.json')
    record = json.loads(source.read_text())
    society = json.loads((out / 'SOCIETY_RESULT.json').read_text())
    participants = json.loads((run / 'participants.json').read_text())
    result = analyze(record['world'], record['events'], society['calls'], participants)
    result.update(run=pilot['run'], phase=pilot['phase'], seconds=society['seconds'],
                  food_balance={key: society[key] for key in ('initial_food', 'produced', 'final_food', 'eaten', 'lifecycle_food_consumed', 'food_consumed_by_reason', 'conservation_violations')},
                  knowledge_copy_audit_violations=knowledge['copy_audit_violations'],
                  source=str(source.relative_to(out)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    (out / 'POPULATION_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('run', 'seconds', 'initial_population', 'created_population', 'living_population', 'methods', 'food_balance')}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    summarize(parser.parse_args().output)
