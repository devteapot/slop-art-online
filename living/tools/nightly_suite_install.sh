#!/bin/sh
# Install the nightly full suite (living/tools/nightly_suite.py; docs/TOOLING.md, "The nightly
# suite") as a systemd user timer on the Spark. Copies the script to ~/.local/share/slop-tools/
# (removing a worktree never breaks it) and runs it once a night with --repo REPO: it takes
# battle.lock first, waits for an idle merge queue and a load under --max-load before each entry,
# and starts no entry after --until. The default start, 04:40, follows the trial reclaim's 04:00
# window, which needs battle.lock free. Re-run after the script changes.
# Usage: living/tools/nightly_suite_install.sh [--at HH:MM] [--until HH:MM] [--lanes N] [--repo PATH]
#          [--print] [--uninstall]
#   --print shows the units it would write and changes nothing.
set -eu
AT=04:40 UNTIL=10:00 LANES=3 REPO="" PRINT="" UNINSTALL=""
while [ $# -gt 0 ]; do
  case $1 in
    --at) AT=$2; shift 2 ;;
    --until) UNTIL=$2; shift 2 ;;
    --lanes) LANES=$2; shift 2 ;;
    --repo) REPO=$2; shift 2 ;;
    --print) PRINT=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) sed -n '2,11p' "$0"; exit 2 ;;
  esac
done
HERE=$(cd "$(dirname "$0")" && pwd)
[ -n "$REPO" ] || REPO=$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")
DEST="$HOME/.local/share/slop-tools"
UNIT="$HOME/.config/systemd/user"
NAME=slop-nightly
PY=$(command -v python3)

SERVICE="[Unit]
Description=Slop nightly full suite (verify-core scenes no gate case reaches)

[Service]
Type=oneshot
Environment=PATH=$HOME/.cargo/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/bin/sh -c '. $HOME/slop-sysroot/env.sh 2>/dev/null; exec $PY $DEST/nightly_suite.py run --repo $REPO --until $UNTIL --lanes $LANES'
TimeoutStartSec=12h
KillSignal=SIGINT
"
TIMER="[Unit]
Description=Slop nightly full suite at $AT

[Timer]
OnCalendar=*-*-* $AT:00
Persistent=false

[Install]
WantedBy=timers.target
"

if [ -n "$PRINT" ]; then
  printf '# %s/%s.service\n%s\n# %s/%s.timer\n%s' "$UNIT" "$NAME" "$SERVICE" "$UNIT" "$NAME" "$TIMER"
  exit 0
fi
if [ -n "$UNINSTALL" ]; then
  systemctl --user disable --now "$NAME.timer" 2>/dev/null || true
  rm -f "$UNIT/$NAME.service" "$UNIT/$NAME.timer"
  systemctl --user daemon-reload
  echo "nightly_suite_install: removed $NAME.timer"; exit 0
fi
"$PY" "$HERE/nightly_suite.py" selftest --repo "$REPO" >/dev/null || {
  echo "nightly_suite_install: the selftest failed; nothing installed" >&2; exit 1; }
mkdir -p "$DEST" "$UNIT"
install -m 0755 "$HERE/nightly_suite.py" "$DEST/nightly_suite.py"
printf '%s' "$SERVICE" > "$UNIT/$NAME.service"
printf '%s' "$TIMER" > "$UNIT/$NAME.timer"
systemctl --user daemon-reload
systemctl --user enable --now "$NAME.timer"
systemctl --user list-timers --no-pager "$NAME.timer"
echo "nightly_suite_install: $NAME.timer at $AT (until $UNTIL, $LANES lanes, repo $REPO)"
