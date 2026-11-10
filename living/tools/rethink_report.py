#!/usr/bin/env python3
"""Reports for the rethink gate (docs/MIND_HARNESS.md, "Rethink gate").

  rethink_report.py replay DIR
      DIR holds replay-jev.jsonl and replay-llm.jsonl (`living-mind rethink-replay`), the blind
      judge's sample (judge-key.jsonl) and its labels (labels*.jsonl). Prints how many trigger
      points each arm holds and, on the judged sample (weighted back to the population by
      sampling cell), what the held deliberations were: wasted, marginal or useful, and how many
      would have hurt the character to skip. Also a threshold sweep for Jev's answers.

  rethink_report.py live TRIALS_DIR BATCH
      One row per trial instance and a mean/range per variant: deliberations, model tokens and
      cost per game hour, gate calls and verdicts, outcomes from the probes (survival, eating,
      learned, built, sleeping under a roof) and asking loops (three or more lines to the same
      person in ten minutes without an answer from them).
"""
import collections
import glob
import json
import os
import statistics
import sys

# $ per million tokens (docs/MODEL_COST.md): input, cached input, output.
PRICES = {
    'zai-glm-5-3-flash': (0.15, 0.03, 0.50),
    'deepseek-v4-1-flash-1017': (0.30, 0.007, 1.20),
}
GAME_HOUR_S = 30


def rows(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def cost(entry):
    if entry.get('cost_usd') is not None:
        return float(entry['cost_usd'])
    price = PRICES.get(entry.get('model'))
    if not price:
        return 0.0
    prompt = entry.get('prompt_tokens') or 0
    cached = entry.get('cached_tokens') or 0
    out = entry.get('completion_tokens') or 0
    return ((prompt - cached) * price[0] + cached * price[1] + out * price[2]) / 1e6


# ---- replay -----------------------------------------------------------------------------

def replay(d):
    arms = {arm: {(r['run'], r['idx']): r for r in rows(os.path.join(d, f'replay-{arm}.jsonl'))} for arm in ('jev', 'llm')}
    key = {k['item']: k for k in rows(os.path.join(d, 'judge-key.jsonl'))}
    labels = {}
    for path in sorted(glob.glob(os.path.join(d, 'labels*.jsonl'))):
        for r in rows(path):
            labels[r['item']] = r
    total = len(arms['jev'])
    gated = [k for k, r in arms['jev'].items() if r['verdict'] not in ('urgent', 'first')]
    print(f'{total} trigger points from {len({k[0] for k in arms["jev"]})} runs; {total - len(gated)} urgent or first (never judged); {len(gated)} judged')
    for arm, rs in arms.items():
        v = collections.Counter(rs[k]['verdict'] for k in gated)
        lat = sorted(rs[k]['judged']['latency_ms'] for k in gated if rs[k].get('judged'))
        tok = [rs[k]['judged']['tokens'] for k in gated if rs[k].get('judged')]
        usd = sum(rs[k]['judged']['cost_usd'] for k in gated if rs[k].get('judged'))
        print(f'  {arm}: hold {v["hold"]} ({v["hold"] / len(gated):.0%}), rethink {v["rethink"]}, fallback {v["fallback"]}; '
              f'latency p50 {lat[len(lat) // 2]} ms, p95 {lat[int(len(lat) * .95)]} ms; {statistics.mean(tok):.0f} tokens per question'
              + (f'; ${usd:.4f} in all' if usd else ''))
    # Sampling weights: population of each (jev, llm) verdict cell over its sampled count.
    cell_pop = collections.Counter((arms['jev'][k]['verdict'], arms['llm'][k]['verdict']) for k in gated)
    judged = [(key[i], labels[i]) for i in key if i in labels]
    cell_n = collections.Counter(tuple(k['cell']) for k, _ in judged)
    weight = lambda k: cell_pop[tuple(k['cell'])] / cell_n[tuple(k['cell'])]
    print(f'\nBlind judge: {len(judged)} of {len(key)} sampled points labelled; weighted to the {len(gated)} judged points.')
    pop = collections.Counter()
    for k, lab in judged:
        pop[lab['label']] += weight(k)
    n = sum(pop.values())
    print('  all judged triggers: ' + ', '.join(f'{l} {pop[l] / n:.0%}' for l in ('useful', 'marginal', 'wasted'))
          + f'; harm if skipped {sum(weight(k) for k, l in judged if l["harm_if_skipped"]) / n:.0%}')

    def table(name, verdict_of):
        held = [(k, l) for k, l in judged if verdict_of(k) == 'hold']
        went = [(k, l) for k, l in judged if verdict_of(k) != 'hold']
        w = lambda xs: sum(weight(k) for k, _ in xs)
        lab = lambda xs, f: w([(k, l) for k, l in xs if f(l)])
        wasted = lambda l: l['label'] == 'wasted'
        useful = lambda l: l['label'] == 'useful'
        harm = lambda l: l['harm_if_skipped']
        loop = lambda l: l.get('waste_kind') == 'asking_loop'
        all_w = lab(judged, wasted)
        print(f'  {name}: holds {w(held) / n:.0%} of judged triggers. Of the held: wasted {lab(held, wasted) / max(w(held), 1e-9):.0%}, '
              f'useful {lab(held, useful) / max(w(held), 1e-9):.0%}, harm if skipped {lab(held, harm) / max(w(held), 1e-9):.0%}. '
              f'Catches {lab(held, wasted) / max(all_w, 1e-9):.0%} of wasted deliberations, {lab(held, loop) / max(lab(judged, loop), 1e-9):.0%} of asking loops; '
              f'holds {lab(held, useful) / max(lab(judged, useful), 1e-9):.0%} of useful ones and {lab(held, harm) / max(lab(judged, harm), 1e-9):.0%} of the harmful-to-skip. '
              f'Of those let through: wasted {lab(went, wasted) / max(w(went), 1e-9):.0%}.')
        return held

    print()
    table('Jev', lambda k: arms['jev'][(k['run'], k['idx'])]['verdict'])
    table('GLM', lambda k: arms['llm'][(k['run'], k['idx'])]['verdict'])
    print('\nJev threshold sweep (p = max(plan_broken, unhandled) × (1 − would_repeat), and without the `unless`):')
    for unless in (True, False):
        for thr in (0.3, 0.4, 0.5, 0.6, 0.7):
            def v(k, thr=thr, unless=unless):
                a = arms['jev'][(k['run'], k['idx'])]['judged']['answers']
                p = max(a['plan_broken'], a['unhandled']) * ((1 - a['would_repeat']) if unless else 1)
                return 'hold' if p < thr else 'rethink'
            held = [(k, l) for k, l in judged if v(k) == 'hold']
            hw = sum(weight(k) for k, _ in held)
            ww = sum(weight(k) for k, l in held if l['label'] == 'wasted')
            hu = sum(weight(k) for k, l in held if l['harm_if_skipped'])
            tw = sum(weight(k) for k, l in judged if l['label'] == 'wasted')
            th = sum(weight(k) for k, l in judged if l['harm_if_skipped'])
            print(f'  {"with" if unless else "without"} unless, threshold {thr}: holds {hw / n:.0%}; wasted among held {ww / max(hw, 1e-9):.0%}; '
                  f'catches {ww / max(tw, 1e-9):.0%} of wasted; holds {hu / max(th, 1e-9):.0%} of harmful-to-skip')
    agree = sum(1 for k in gated if (arms['jev'][k]['verdict'] == 'hold') == (arms['llm'][k]['verdict'] == 'hold'))
    print(f'\nJev and GLM agree on {agree / len(gated):.0%} of judged triggers. Cells: {dict(cell_pop)}')


# ---- live -------------------------------------------------------------------------------

def asking_loops(exps, me):
    """Runs of three or more lines to one person within ten minutes with no answer from them."""
    said = [e for e in exps if e['kind'] == 'said' and e['subject'] == me and e['object']]
    answers = collections.defaultdict(list)
    for e in exps:
        if e['kind'] in ('speech', 'gesture', 'heard') and e['subject'] != me:
            answers[e['subject']].append(e['at_ms'])
    loops, unanswered = 0, 0
    by_to = collections.defaultdict(list)
    for e in said:
        by_to[e['object']].append(e['at_ms'])
    for to, times in by_to.items():
        run = []
        for t in sorted(times):
            if run and (t - run[0] > 600_000 or any(run[-1] < a <= t for a in answers[to])):
                if len(run) >= 3:
                    loops += 1
                    unanswered += len(run)
                run = []
            run.append(t)
        if len(run) >= 3:
            loops += 1
            unanswered += len(run)
    return loops, unanswered


def instance(path):
    s = json.load(open(os.path.join(path, 'summary.json')))
    hours = float(s.get('minutes_run') or 0) * 60 / GAME_HOUR_S
    journal = [e for p in glob.glob(os.path.join(path, 'journal', '*.jsonl')) for e in rows(p)]
    calls = [e for e in journal if e.get('purpose') not in ('rethink-gate',)]
    model = [e for e in calls if e.get('purpose') not in ('rethink',)]
    gate_calls = [e for e in calls if e.get('purpose') == 'rethink']
    gates = [e for e in journal if e.get('purpose') == 'rethink-gate']
    thoughts = rows(os.path.join(path, 'thoughts.jsonl'))
    me = int(str(s['subject']).split('#')[1])
    exps = [e for e in rows(os.path.join(path, 'experiences.jsonl')) if e.get('observer') == me]
    loops, unanswered = asking_loops(exps, me)
    samples = rows(os.path.join(path, 'samples.jsonl'))
    sleeps = [x for x in samples if (x.get('activity') or [None])[0] == 'sleep']
    food = s.get('food_gained') or {}
    built = s.get('built') or {}
    gate_tokens = sum(e.get('tokens') or 0 for e in gate_calls)
    return {
        'run': os.path.basename(path), 'variant': s['variant'], 'minutes': s.get('minutes_run'), 'game_hours': round(hours, 1),
        'survived': s.get('survived'), 'death': s.get('death'),
        'deliberations': sum(1 for t in thoughts if t['kind'] == 'deliberate'),
        'delib_per_game_h': round(sum(1 for t in thoughts if t['kind'] == 'deliberate') / max(hours, 1e-9), 2),
        'think_compile_tokens_per_game_h': round(sum(e.get('tokens') or 0 for e in model if e.get('purpose') in ('think', 'deliberate')) / max(hours, 1e-9)),
        'model_tokens_per_game_h': round(sum(e.get('tokens') or 0 for e in model) / max(hours, 1e-9)),
        'model_usd_per_game_h': round(sum(cost(e) for e in model) / max(hours, 1e-9), 4),
        'gate_calls': len(gate_calls), 'gate_tokens': gate_tokens, 'gate_usd': round(sum(cost(e) for e in gate_calls), 4),
        'verdicts': dict(collections.Counter(g['verdict'] for g in gates)),
        'first_eat_min': s.get('first_eat_min'), 'food_gained': sum(food.values()) if isinstance(food, dict) else food,
        'hunger_max': s.get('hunger_max'), 'hp_min': s.get('hp_min'),
        'learned': len(s.get('learned') or []), 'built': sum(built.values()) if isinstance(built, dict) else built,
        'built_kinds': built, 'sleep_samples': len(sleeps),
        'lines_said': s.get('lines_said'), 'asking_loops': loops, 'unanswered_lines': unanswered,
        'repeats': sum(1 for e in exps if e['kind'] == 'repeat'), 'refusals': s.get('refusals'),
    }


def live(trials, batch):
    out = []
    for path in sorted(glob.glob(os.path.join(trials, batch, '*-r*'))):
        if os.path.isdir(path) and os.path.exists(os.path.join(path, 'summary.json')):
            out.append(instance(path))
    keys = ['minutes', 'survived', 'deliberations', 'delib_per_game_h', 'think_compile_tokens_per_game_h', 'model_tokens_per_game_h',
            'model_usd_per_game_h', 'gate_calls', 'gate_usd', 'first_eat_min', 'food_gained', 'hunger_max', 'learned', 'built',
            'sleep_samples', 'lines_said', 'asking_loops', 'unanswered_lines', 'repeats', 'refusals']
    for r in out:
        print(json.dumps(r))
    print()
    by = collections.defaultdict(list)
    for r in out:
        by[r['variant']].append(r)
    for v, rs in sorted(by.items()):
        cells = []
        for k in keys:
            xs = [r[k] for r in rs if isinstance(r[k], (int, float)) and not isinstance(r[k], bool)]
            if k == 'survived':
                cells.append(f'survived {sum(1 for r in rs if r[k])}/{len(rs)}')
            elif xs:
                cells.append(f'{k} {statistics.mean(xs):.4g} [{min(xs):.4g}–{max(xs):.4g}]')
        print(f'{v} (n={len(rs)}): ' + '; '.join(cells))
    with open(os.path.join(trials, batch, 'rethink-report.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'replay':
        replay(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'live':
        live(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
