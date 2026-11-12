# Game interface: validation records

Each validated run of `verify-ui` has its own file here, named `<YYYY-MM-DD>-<HHMM>-<branch-or-run>.md` (the date and time in UTC when the record is written). **The newest files are the last validated runs.**

- Write a new file for each run, and never edit an existing one. A rerun, a pass after merging main, or a correction gets a file of its own that names the record it follows.
- A record names the branch and commit, the server, the run names with their evidence under `.local/living/verify/`, what passed and failed (with the failures' text), and what was not covered.
- [history.md](history.md) is the single record kept until 2026-11-12, newest first. It is closed: do not add to it.

`python3 .agents/skills/verify/scripts/latest_validation.py` lists the newest records of every surface (`--surface ui`, `-n 5`); `--check` fails on a misnamed file or a `references/validation.md` brought back by a merge.
