#!/usr/bin/env python3
"""Row writes per table over a gate run's window, and the commitlog bytes they account for
(docs/GATE_216.md): `gate_tables.py <run dir> [window] [--top N]`.

The server counts the rows each table inserts and deletes (`spacetime_num_rows_inserted_total`,
`spacetime_num_rows_deleted_total`, by table). An update is a delete and an insert. Each row
written is estimated at the table's mean stored row size at the window's end
(`spacetime_data_size_bytes_used_by_rows` / `spacetime_num_table_rows`), which approximates its
encoded size in the commitlog. The sum is compared with the replica's measured `clog` growth over
the same samples, so the estimate shows how much of the log it explains. Per-sender view tables
(`seen_*`, `my_*`) are listed apart: their rows are re-materialized in the writing transaction.
"""
import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\} (\S+)$')
WANT = {'spacetime_num_rows_inserted_total', 'spacetime_num_rows_deleted_total',
        'spacetime_data_size_bytes_used_by_rows', 'spacetime_num_table_rows'}


def per_table(lines, db):
    out = defaultdict(lambda: defaultdict(float))
    for l in lines:
        m = LINE.match(l)
        if not m or m.group(1) not in WANT:
            continue
        lab = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
        if lab.get('db') != db or 'table_name' not in lab:
            continue
        try:
            out[lab['table_name']][m.group(1)] += float(m.group(3))
        except ValueError:
            pass
    return out


def clog_bytes(disk):
    """The largest replica's clog size (the run's database; others are idle)."""
    sizes = [int(l.split('\t')[0]) for l in (disk or '').splitlines() if l.endswith('/clog') and l.split('\t')[0].isdigit()]
    return sizes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run')
    ap.add_argument('window', nargs='?', default='battle')
    ap.add_argument('--top', type=int, default=20)
    a = ap.parse_args()
    d = Path(a.run)
    m = json.loads((d / 'marks.json').read_text())
    t0, t1 = {'window': (m['window_start'], m['window_end']), 'calm': (m['window_start'], m['battle_start']),
              'battle': (m['battle_start'], m['window_end'])}[a.window]
    samples = [json.loads(l) for l in gzip.open(d / 'samples.jsonl.gz', 'rt')]
    ms = [s for s in samples if s.get('metrics') and t0 <= s['t'] <= t1]
    db = None
    for l in ms[0]['metrics']:
        g = re.search(r'db="([0-9a-f]{64})"', l)
        if g and 'num_rows_inserted' in l:
            db = g.group(1)
            break
    first, last = ms[0], ms[-1]
    secs = last['t'] - first['t']
    p0, p1 = per_table(first['metrics'], db), per_table(last['metrics'], db)
    rows = []
    for t, v in p1.items():
        ins = (v['spacetime_num_rows_inserted_total'] - p0[t]['spacetime_num_rows_inserted_total']) / secs
        dele = (v['spacetime_num_rows_deleted_total'] - p0[t]['spacetime_num_rows_deleted_total']) / secs
        n = v['spacetime_num_table_rows']
        size = v['spacetime_data_size_bytes_used_by_rows'] / n if n else 0
        rows.append((t, ins, dele, size, (ins + dele) * size))
    view = lambda t: t.startswith(('seen_', 'my_'))
    tables = sorted((r for r in rows if not view(r[0])), key=lambda r: -r[4])
    views = sorted((r for r in rows if view(r[0])), key=lambda r: -r[4])
    # The clog growth between the disk samples nearest the metric samples.
    ds = [s for s in samples if s.get('disk') and t0 - 30 <= s['t'] <= t1 + 30]
    c0, c1 = clog_bytes(ds[0]['disk']), clog_bytes(ds[-1]['disk'])
    grew = max((b - a_) for a_, b in zip(c0, c1)) if c0 and len(c0) == len(c1) else None
    dsecs = ds[-1]['t'] - ds[0]['t']
    print(f'{d.name} {a.window}: {secs:.0f} s of metrics; clog grew {grew / dsecs / 1e3:.0f} KB/s over {dsecs:.0f} s' if grew is not None else f'{d.name}: no clog samples')
    est = sum(r[4] for r in tables)
    print(f'estimated from table writes: {est / 1e3:.0f} KB/s ({100 * est / (grew / dsecs):.0f}% of the clog growth)' if grew else '')
    print('\n| Table | Inserted/s | Deleted/s | Mean row (B) | Est. KB/s | Share of tables |')
    print('|---|---|---|---|---|---|')
    for t, i, de, s, b in tables[:a.top]:
        print(f'| {t} | {i:.0f} | {de:.0f} | {s:.0f} | {b / 1e3:.1f} | {100 * b / est:.0f}% |')
    print('\nView tables (re-materialized per sender):\n')
    print('| View | Inserted/s | Deleted/s | Mean row (B) | Est. KB/s |')
    print('|---|---|---|---|---|')
    for t, i, de, s, b in views[:a.top]:
        print(f'| {t} | {i:.0f} | {de:.0f} | {s:.0f} | {b / 1e3:.1f} |')


if __name__ == '__main__':
    main()
