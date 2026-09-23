#!/usr/bin/env python3
"""Compare paired recorded intentions, never infer that agreement means correctness."""
import argparse
import json
import math
import statistics
from pathlib import Path


def summarize(root):
    rows = []
    for folder in sorted(root.glob('actor-*')):
        if not folder.is_dir():
            continue
        trial_path = folder/'trial.json'
        trial = json.loads(trial_path.read_text()) if trial_path.exists() else {}
        calls = trial.get('calls', [])
        # Roles repeat in longer trials; match the primary journal's planned role and
        # file creation time, preserving the serial order of calls in this process.
        primary_paths = sorted(folder.glob('harness-*.json'), key=lambda p:p.stat().st_mtime_ns)
        for index, path in enumerate(primary_paths):
            primary = json.loads(path.read_text())
            shadow_path = folder/'shadow'/path.name
            shadow = json.loads(shadow_path.read_text()) if shadow_path.exists() else None
            row = {'actor':folder.name, 'primary_id':primary['id'], 'role':primary['responsibility'],
                   'primary_error':primary.get('error'), 'primary_phase':primary.get('phase'),
                   'capture':primary.get('shadow_capture'), 'primary_usage':primary.get('reply',{}).get('usage'),
                   'primary_served_model':primary.get('reply',{}).get('served_model'),
                   'primary_turn_ms':calls[index]['elapsed_ms'] if index<len(calls) else None,
                   'primary_journal':str(path.relative_to(root)),
                   'shadow_journal':str(shadow_path.relative_to(root)) if shadow else None}
            row['same_context'] = shadow is not None and primary['participant_context']==shadow['request']['state']['participant_context']
            if shadow:
                row.update(shadow_phase=shadow.get('phase'), shadow_error=shadow.get('error'),
                           shadow_http_status=shadow.get('http_status'),
                           shadow_http_ms=shadow.get('elapsed_ms'), shadow_applied=shadow.get('applied'),
                           shadow_decision_age_ms=shadow.get('completion_age_ms'),
                           shadow_usage=shadow.get('response',{}).get('usage'),
                           shadow_served_model=shadow.get('response',{}).get('model'))
            try:
                proposal = json.loads(primary['reply']['raw_output'])
            except (KeyError, TypeError, ValueError):
                proposal = None
            valid_primary = primary.get('phase')=='completed' and primary.get('error') is None and primary.get('result') is not None
            if valid_primary and isinstance(proposal,dict):
                row['primary_operations'] = [op['op'] for op in proposal['operations']]
                row['primary_proposed_operation'] = bool(proposal['operations'])
                row['primary_reported_reason'] = proposal.get('reason')
                row['receipts'] = primary['result'].get('receipts',[])
            valid_shadow = shadow and shadow.get('phase')=='completed' and shadow.get('error') is None and 'response' in shadow
            if valid_shadow:
                row['shadow_answers'] = shadow['response']['answers']
            row['comparable'] = bool(valid_primary and valid_shadow and row['same_context'])
            if row['comparable']:
                probability = shadow['response']['answers']['should_operate']['noul']
                row['shadow_operate_at_0_5'] = probability>=0.5
                row['coarse_agreement'] = row['primary_proposed_operation']==row['shadow_operate_at_0_5']
            rows.append(row)
    comparable = [r for r in rows if r['comparable']]
    shadow_ok = [r for r in rows if r.get('shadow_answers')]
    latencies = sorted(r['shadow_http_ms'] for r in shadow_ok)
    tokens = sum(r['shadow_usage']['input_tokens'] for r in shadow_ok)
    return {'schema':'sao-shadow-comparison-v1', 'pairs':len(rows), 'comparable':len(comparable),
            'same_context':sum(r['same_context'] for r in rows),
            'coarse_agreement':sum(r['coarse_agreement'] for r in comparable),
            'shadow_successes':len(shadow_ok),
            'shadow_errors':sum(bool(r.get('shadow_error')) for r in rows),
            'shadow_missing':sum(r['shadow_journal'] is None for r in rows),
            'primary_rejected_operations':sum(receipt.get('ok') is False for r in rows for receipt in r.get('receipts',[])),
            'shadow_http_ms_median':statistics.median(latencies) if latencies else None,
            'shadow_input_tokens':tokens, 'estimated_shadow_input_usd':tokens*0.042/1e6,
            'shadow_http_ms_nearest_rank':{str(p):latencies[max(0,math.ceil(len(latencies)*p/100)-1)] for p in (50,95,99)} if latencies else {},
            'comparison_limits':'Descriptive operate/no-operation comparison at reporting threshold 0.5, not correctness. Primary turn time includes observation, generation and submission; shadow HTTP time only includes its model request. No equivalent-task speedup claim. Receipts do not prove physical outcomes. Sample is not calibration or capacity evidence.',
            'rows':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('trial',type=Path)
    a=p.parse_args()
    result=summarize(a.trial)
    (a.trial/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
