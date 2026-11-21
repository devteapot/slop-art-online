#!/usr/bin/env bash
# blender_gate.sh: the dev-box's `blender` on PATH (docs/TOOLING.md, "Blender during a gate").
# Blender pauses while a scene gate holds gate.lock exclusively, and goes on when the gate lets
# it go, including in the middle of a long file. Install:
#   install -m 755 living/tools/blender_gate.sh ~/.local/share/slop-tools/build-bin/blender
#
# - At start: while a gate holds the lock, wait (as before).
# - Running: Blender is started in a process group of its own (setsid). Every SLOP_GATE_POLL_S
#   seconds (default 3) the lock is tested without blocking (`flock -n -s`, in a child process
#   that closes it at once). While a gate holds it, the group is stopped (SIGSTOP), and continued
#   (SIGCONT) when the gate releases it.
# - Cap: a hold longer than SLOP_GATE_PAUSE_CAP_S (default 5400 s, 90 min: longer than a full gate
#   with scenes and the render group) is taken for a leaked lock. Blender is continued and not
#   paused again during that hold, and the hold is logged as such. The wait at start has the same cap.
# - The lock is never open in this shell, and a descriptor on it that the caller passed down is
#   closed before Blender starts. Such a caller holds the lock itself (a gate running Blender),
#   so then Blender is not paused.
# - SLOP_GATE_WAIT=0: no waiting, no pausing. INT and TERM to the wrapper go to Blender's group
#   (continued first, so a stopped Blender acts on them). The exit code is Blender's.
# Log: stderr and ~/.local/state/slop-build/blender-gate.log.
# For tests: SLOP_BLENDER_REAL (default /usr/bin/blender), SLOP_GATE_LOCK, SLOP_GATE_LOG.
set -u
REAL=${SLOP_BLENDER_REAL:-/usr/bin/blender}
L=${SLOP_GATE_LOCK:-$HOME/.local/state/slop-build/gate.lock}
LOG=${SLOP_GATE_LOG:-$HOME/.local/state/slop-build/blender-gate.log}
POLL=${SLOP_GATE_POLL_S:-3}
CAP=${SLOP_GATE_PAUSE_CAP_S:-5400}

say() {
  local m="blender-gate [$$]: $*"
  echo "$m" >&2
  { mkdir -p "$(dirname "$LOG")" && echo "$(date -u +%FT%TZ) $m" >> "$LOG"; } 2>/dev/null || true
}

# A descriptor on the lock passed down by the caller: close it, so Blender never inherits it.
caller_holds=0
want=$(readlink -f "$L" 2>/dev/null || echo "$L")
for fd in /proc/$$/fd/*; do
  n=${fd##*/}
  [ "$n" -gt 2 ] 2>/dev/null || continue
  if [ "$(readlink -f "$fd" 2>/dev/null)" = "$want" ]; then
    caller_holds=1
    eval "exec $n>&-"
  fi
done

if [ "${SLOP_GATE_WAIT:-1}" = 0 ]; then
  exec "$REAL" "$@"
fi
if [ "$caller_holds" = 1 ]; then
  say "the caller passed down the gate lock (it holds it): running without pausing"
  exec "$REAL" "$@"
fi

# Held exclusively by someone (a gate): a shared lock cannot be taken. The test runs in a child
# process that opens, tries and closes the file; nothing stays open here.
held() { ! flock -n -s "$L" true 2>/dev/null; }

if [ -e "$L" ] && held; then
  say "a scene gate is running; waiting (at most ${CAP} s; SLOP_GATE_WAIT=0 skips)"
  if ! flock -w "$CAP" -s "$L" true 2>/dev/null; then
    say "WARNING: the gate lock has been held over ${CAP} s; starting anyway (a leaked lock? see docs/TOOLING.md)"
  fi
fi

# A command started with `&` in a script has INT and QUIT ignored, and a shell cannot undo that;
# `env --default-signal` gives Blender the default actions back, so a forwarded INT ends it.
setsid env --default-signal=INT,QUIT "$REAL" "$@" &
pid=$!
paused=0; paused_at=0; capped=0

forward() {
  local sig=$1
  kill -CONT -- -"$pid" 2>/dev/null
  kill -"$sig" -- -"$pid" 2>/dev/null
}
trap 'forward INT' INT
trap 'forward TERM' TERM
trap 'forward HUP' HUP

while kill -0 "$pid" 2>/dev/null; do
  if [ -e "$L" ] && held; then
    now=$(date +%s)
    if [ "$paused" = 0 ] && [ "$capped" = 0 ]; then
      kill -STOP -- -"$pid" 2>/dev/null && { paused=1; paused_at=$now; say "a scene gate took the lock: Blender (group $pid) paused"; }
    elif [ "$paused" = 1 ] && [ $((now - paused_at)) -ge "$CAP" ]; then
      kill -CONT -- -"$pid" 2>/dev/null
      paused=0; capped=1
      say "WARNING: paused ${CAP} s and the lock is still held: Blender (group $pid) continued, not paused again during this hold (a leaked lock? see docs/TOOLING.md)"
    fi
  else
    if [ "$paused" = 1 ]; then
      kill -CONT -- -"$pid" 2>/dev/null
      say "the gate let the lock go: Blender (group $pid) continued after $(( $(date +%s) - paused_at )) s"
    fi
    paused=0; capped=0
  fi
  sleep "$POLL" &
  wait $! 2>/dev/null
done
wait "$pid"
exit $?
