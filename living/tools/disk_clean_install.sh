#!/bin/sh
# Install the automatic disk cleanup (living/tools/disk_clean.py; policy in docs/TOOLING.md).
# Copies the script to ~/.local/share/slop-tools/ (so removing a worktree never breaks it) and
# runs it every 30 minutes with --apply: a systemd user timer on Linux (with lingering on, it
# runs without a login), a launchd agent on macOS. Re-run after the script changes.
# The machine's protected paths are in ~/.config/slop-disk/protect.txt (one per line, # comments,
# ~ expanded); every run reads it, so an edit applies from the next run. The installer writes a
# commented template when there is none, checks the file and prints the protected paths; an
# invalid file stops the installation.
# Usage: living/tools/disk_clean_install.sh [--floor-gb 40] [--target-gb N] [--every-min 30] [--repo PATH] [--uninstall]
set -eu
FLOOR=40 TARGET="" EVERY=30 REPO="" UNINSTALL=""
while [ $# -gt 0 ]; do
  case $1 in
    --floor-gb) FLOOR=$2; shift 2 ;;
    --target-gb) TARGET=$2; shift 2 ;;
    --every-min) EVERY=$2; shift 2 ;;
    --repo) REPO=$2; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) sed -n '2,6p' "$0"; exit 2 ;;
  esac
done
HERE=$(cd "$(dirname "$0")" && pwd)
[ -n "$REPO" ] || REPO=$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")
[ -n "$TARGET" ] || TARGET=$((FLOOR + 30))
DEST="$HOME/.local/share/slop-tools"
PY=$(command -v python3)
ARGS="--apply --repo $REPO --floor-gb $FLOOR --target-gb $TARGET"
NAME=slop-disk-clean
PROTECT="$HOME/.config/slop-disk/protect.txt"

protect_check() {  # the script to be installed reads the file as the timer will
  if [ ! -e "$PROTECT" ]; then
    mkdir -p "$(dirname "$PROTECT")"
    cat > "$PROTECT" <<'TEMPLATE'
# Paths disk_clean.py must never touch on this machine, besides its built-in list
# (docs/TOOLING.md, "Disk"). One path per line; ~ is expanded; # starts a comment.
# A path protects everything under it, and any build folder that holds it.
# ~/dev/slop-trials
TEMPLATE
    echo "disk_clean_install: wrote a template $PROTECT (no paths in it yet)"
  fi
  "$PY" "$HERE/disk_clean.py" --repo "$REPO" --list-protected || {
    echo "disk_clean_install: fix $PROTECT first; the timer is not (re)installed" >&2; exit 1; }
}

case "$(uname -s)" in
  Linux)
    UNIT="$HOME/.config/systemd/user"
    if [ -n "$UNINSTALL" ]; then
      systemctl --user disable --now "$NAME.timer" 2>/dev/null || true
      rm -f "$UNIT/$NAME.service" "$UNIT/$NAME.timer"
      systemctl --user daemon-reload
      echo "disk_clean_install: removed $NAME.timer"; exit 0
    fi
    mkdir -p "$DEST" "$UNIT"
    protect_check
    install -m 0755 "$HERE/disk_clean.py" "$DEST/disk_clean.py"
    cat > "$UNIT/$NAME.service" <<EOF
[Unit]
Description=Remove idle Slop Art Online build folders (docs/TOOLING.md)

[Service]
Type=oneshot
Nice=10
IOSchedulingClass=idle
# the installing shell's PATH, so podman/docker are found for the container check
Environment="PATH=$PATH"
ExecStart=$PY $DEST/disk_clean.py $ARGS
# exit 3 means still under the floor after cleaning: reported, not a unit failure
SuccessExitStatus=3
EOF
    # A calendar schedule: OnUnitActiveSec counts from the service's last run, so a timer
    # restarted after that moment had passed showed "elapsed" with no next trigger and never
    # fired again (the Spark, 2026-11-12). Intervals that do not divide an hour keep the
    # monotonic form, with OnActiveSec so a restart always schedules a first run.
    if [ $((60 % EVERY)) -eq 0 ] 2>/dev/null && [ "$EVERY" -lt 60 ]; then
      TIMER_LINES="OnCalendar=*:0/$EVERY"
    else
      TIMER_LINES="OnActiveSec=1min
OnUnitActiveSec=${EVERY}min"
    fi
    cat > "$UNIT/$NAME.timer" <<EOF
[Unit]
Description=Run $NAME every $EVERY minutes

[Timer]
$TIMER_LINES
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$NAME.timer"
    # The timer must have a next trigger, or it will never run (see the schedule note above).
    NEXT_RT=$(systemctl --user show "$NAME.timer" -p NextElapseUSecRealtime --value 2>/dev/null || true)
    NEXT_MONO=$(systemctl --user show "$NAME.timer" -p NextElapseUSecMonotonic --value 2>/dev/null || true)
    case "$NEXT_RT" in ""|n/a|0|infinity) NEXT_RT="" ;; esac
    case "$NEXT_MONO" in ""|n/a|0|infinity) NEXT_MONO="" ;; esac
    if [ -z "$NEXT_RT$NEXT_MONO" ]; then
      echo "disk_clean_install: WARNING: $NAME.timer has no next trigger; check: systemctl --user list-timers $NAME.timer" >&2
    fi
    echo "disk_clean_install: $NAME.timer every $EVERY min: $PY $DEST/disk_clean.py $ARGS"
    if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != yes ]; then
      echo "disk_clean_install: lingering is off, so the timer runs only while you are logged in: loginctl enable-linger $(id -un)"
    fi
    echo "reports: ~/.local/state/slop-disk/reports/  journal: journalctl --user -u $NAME.service"
    ;;
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/dev.slop.disk-clean.plist"
    if [ -n "$UNINSTALL" ]; then
      launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
      rm -f "$PLIST"
      echo "disk_clean_install: removed $PLIST"; exit 0
    fi
    mkdir -p "$DEST" "$HOME/Library/LaunchAgents" "$HOME/.local/state/slop-disk"
    protect_check
    install -m 0755 "$HERE/disk_clean.py" "$DEST/disk_clean.py"
    ARGS_XML=""
    for a in $ARGS; do ARGS_XML="$ARGS_XML<string>$a</string>"; done
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.slop.disk-clean</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DEST/disk_clean.py</string>$ARGS_XML</array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH:/usr/local/bin:/opt/homebrew/bin</string></dict>
  <key>StartInterval</key><integer>$((EVERY * 60))</integer>
  <key>RunAtLoad</key><true/>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/.local/state/slop-disk/launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/.local/state/slop-disk/launchd.log</string>
</dict></plist>
EOF
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "disk_clean_install: launchd agent dev.slop.disk-clean every $EVERY min: $PY $DEST/disk_clean.py $ARGS"
    echo "macOS: give $PY Full Disk Access if the report shows folders it cannot read"
    ;;
  *) echo "disk_clean_install: unsupported system $(uname -s)" >&2; exit 1 ;;
esac
