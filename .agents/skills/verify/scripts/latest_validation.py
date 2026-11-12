#!/usr/bin/env python3
"""The newest validation records of each verification surface.

Each surface skill keeps one file per validated run in references/validation/, named
<YYYY-MM-DD>-<HHMM>-<branch-or-run>.md (UTC), written new and never edited; history.md is the
closed record from before 2026-11-12. Run from anywhere in the repository:

  latest_validation.py                     the newest record of every surface
  latest_validation.py --surface minds -n 5
  latest_validation.py --check             exit 1 on a misnamed record, an edited history.md or a
                                           references/validation.md brought back by a merge
  latest_validation.py --split [--base origin/main]
      for a branch that edited the old references/validation.md: after merging main, git has
      carried those edits into history.md (or left validation.md behind). Every section the base
      lacks moves into a new <stamp>-<branch>.md, and history.md is restored to the base's.
"""
import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / '.agents/skills'
NAME = re.compile(r'^\d{4}-\d{2}-\d{2}-\d{4}-[A-Za-z0-9._-]+\.md$')
FIXED = {'README.md', 'history.md'}
# A record's sections: `## ` headings, or verify-ui's bold dated paragraphs.
SECTION = re.compile(r'^(## |\*\*\d{4}-\d{2}-\d{2})')


def surfaces():
    return sorted(p.parent.parent for p in SKILLS.glob('verify*/references/validation'))


def records(skill):
    folder = skill / 'references/validation'
    return sorted(p for p in folder.glob('*.md') if p.name not in FIXED)


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=check).stdout


def title(path):
    for line in path.read_text().splitlines():
        if line.startswith('#'):
            return line.lstrip('#').strip()
    return ''


def short(skill):
    return skill.name.removeprefix('verify-') if skill.name != 'verify' else 'verify'


def listing(args):
    chosen = [s for s in surfaces() if not args.surface or short(s) == args.surface or s.name == args.surface]
    if not chosen:
        sys.exit(f'no surface {args.surface}; known: {", ".join(short(s) for s in surfaces())}')
    for skill in chosen:
        found = records(skill)[-args.n:]
        print(f'{skill.name}:')
        if not found:
            print(f'  (no per-run record yet; see {(skill / "references/validation/history.md").relative_to(ROOT)})')
        for path in reversed(found):
            print(f'  {path.relative_to(ROOT)}  {title(path)}')


def added_at(path):
    """The commit that added history.md (the layout change), or None before it is committed."""
    out = git('log', '--no-renames', '--diff-filter=A', '--format=%H', '--', str(path.relative_to(ROOT)), check=False).split()
    return out[-1] if out else None


def check(_args):
    bad = []
    for skill in surfaces():
        old = skill / 'references/validation.md'
        if old.exists():
            bad.append(f'{old.relative_to(ROOT)} exists: run --split after merging main')
        for path in records(skill):
            if not NAME.match(path.name):
                bad.append(f'{path.relative_to(ROOT)}: not <YYYY-MM-DD>-<HHMM>-<branch-or-run>.md')
        history = skill / 'references/validation/history.md'
        first = added_at(history)
        if first and history.exists():
            then = git('show', f'{first}:{history.relative_to(ROOT)}', check=False)
            if then and then != history.read_text():
                bad.append(f'{history.relative_to(ROOT)} differs from its state at {first[:10]}: '
                           'history.md is closed; run --split')
    for line in bad:
        print('FAIL', line)
    print(f'{len(bad)} problem(s) in {len(surfaces())} surfaces' if bad else f'ok: {len(surfaces())} surfaces')
    return 1 if bad else 0


def sections(text):
    out, block = [], []
    for line in text.split('\n'):
        if SECTION.match(line) and block:
            out.append('\n'.join(block).strip('\n'))
            block = []
        block.append(line)
    if block:
        out.append('\n'.join(block).strip('\n'))
    return out


def split(args):
    branch = args.name or git('rev-parse', '--abbrev-ref', 'HEAD').strip()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d-%H%M')
    moved = 0
    for skill in surfaces():
        rel = (skill / 'references/validation/history.md').relative_to(ROOT)
        base = git('show', f'{args.base}:{rel}', check=False)
        if not base:
            sys.exit(f'{args.base} has no {rel}: merge main first')
        old = skill / 'references/validation.md'
        source = old if old.exists() else ROOT / rel
        mine = source.read_text()
        if mine == base:
            continue
        have = set(sections(base))
        new = [s for s in sections(mine)[1:] if s not in have]   # [0] is the title line
        if not new:
            print(f'{skill.name}: {source.relative_to(ROOT)} differs from {args.base} but adds no section; restored')
        else:
            target = skill / f'references/validation/{stamp}-{branch}.md'
            if target.exists():
                sys.exit(f'{target.relative_to(ROOT)} exists already')
            head = f'# {skill.name}: {branch}\n\nMoved from `references/validation.md` by `latest_validation.py --split`.\n\n'
            target.write_text(head + '\n\n'.join(new) + '\n')
            moved += len(new)
            print(f'{skill.name}: {len(new)} section(s) -> {target.relative_to(ROOT)}')
        (ROOT / rel).write_text(base)
        if old.exists():
            git('rm', '-q', '--cached', '--ignore-unmatch', str(old.relative_to(ROOT)), check=False)
            old.unlink()
    print(f'{moved} section(s) moved; review with git status and git diff, then commit')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--surface', help='core, minds, ui, ... (default: all)')
    ap.add_argument('-n', type=int, default=1, help='records per surface (default 1)')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--split', action='store_true')
    ap.add_argument('--base', default='origin/main', help='for --split: the main the branch merged')
    ap.add_argument('--name', help='for --split: the record name (default: the current branch)')
    args = ap.parse_args()
    if args.check:
        return check(args)
    if args.split:
        return split(args)
    listing(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
