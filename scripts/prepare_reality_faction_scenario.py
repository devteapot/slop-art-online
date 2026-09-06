#!/usr/bin/env python3
"""Prepare the existing faction seed for operative scoped laws; never launch it."""
import argparse
import copy
import json
from pathlib import Path

from prepare_infrastructure_scenarios import build_faction

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = 'output/society-lab/implementations/reality-m7-1'


def build():
    previous, _ = build_faction()
    original = previous['scenarios/faction-world.json']
    scenario = copy.deepcopy(original)
    scenario['name'] = 'First faction world: operative territorial laws'
    old = 'The initial designation of a territorial editor is not an operative editing ability.'
    new = ('I have an initial local law-editing grant within this homeland. Its actual scope '
           'and current requirements are available through my ordinary tools. My title '
           'does not grant universal editing or command other people.')
    editors = {actor for region in scenario['society']['regions']
               for actor in region['territorial_editors']}
    assert editors == {2, 6, 10, 14}
    for person in scenario['players']:
        if person['id'] in editors:
            assert old in person['motive']
            person['motive'] = person['motive'].replace(old, new)
    restored = copy.deepcopy(scenario)
    restored['name'] = original['name']
    for person in restored['players']:
        person['motive'] = person['motive'].replace(new, old)
    assert restored == original, 'Only the display name and four obsolete grant descriptions change'
    path = 'scenarios/faction-world-reality.json'
    manifest = dict(
        hypothesis='The existing 36-person faction seed may remain operational when its four '
            'initial territorial grants become usable under scoped law mechanics. Local gods '
            'may edit, investigate, share or decline; civic office gives no editing entitlement.',
        evaluation='A fresh twelve-minute integration sample on reality-m7-1, with the same '
            '36 Luna-medium controllers, uncapped calls and fifteen seconds after each serial '
            'responsibility. Preserve the earlier faction-world seed and its actual Stage 5 '
            'outcome. This variant changes only its display name and four now-obsolete motive '
            'sentences that described territorial grants as inoperative. All physical stocks, '
            'geography, initial knowledge, survival habits, offices, organizations and controller '
            'settings match the prior seed. No law source, experimental cases, successful proof '
            'or required action is seeded. The four existing homeland grants are operative under '
            'the new rules; SF, the independent city and wild regions have no initial local '
            'editor. Shared mechanisms apply to every identity. Audit resource, knowledge, '
            'numeric and law records, exact source/binding hashes, update rates, model access, '
            'deaths and chosen actions. Report absence of edits as a result. This short integration '
            'sample does not establish stable provisioning, universal ascension or long-term '
            'societal continuity. Lifecycle creation and detailed fictional dependency physiology '
            'remain at the earlier seed settings; the four smaller law worlds provide the '
            'separate editing/research/disturbance evidence.',
        minutes=12, calls_per_actor=0, serial_ms=15000, concurrency=1,
        variants=[dict(id='faction-world-reality', port=19029,
            implementation=IMPLEMENTATION, scenario=f'{IMPLEMENTATION}/{path}',
            controllers=f'{IMPLEMENTATION}/configs/experiments/faction-36-medium.json',
            recovery=True)])
    return {path: scenario, 'configs/experiments/campaign/025-faction-reality.json': manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, value in build().items():
        path = ROOT / name
        text = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
        if args.check:
            if not path.is_file() or path.read_text() != text:
                raise SystemExit(f'Prepared input differs: {path}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    print('Faction reality inputs verified' if args.check else 'Faction reality inputs prepared')


if __name__ == '__main__':
    main()
