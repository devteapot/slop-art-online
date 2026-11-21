#!/usr/bin/env bash
# gate_pause.sh -- CMD [ARGS...]: run a heavy command (a cargo build, Blender, a bundle) that
# gives the machine to a scene gate (docs/TOOLING.md, "Heavy work during a gate"). Install:
#   install -m 755 living/tools/gate_pause.sh ~/.local/share/slop-tools/build-bin/gate_pause.sh
#
# - At start: while a gate holds gate.lock exclusively, wait.
# - Running: the command runs in a process group of its own (setsid). Every SLOP_GATE_POLL_S
#   seconds (default 3) the lock is tested without blocking (`flock -n -s`, in a child process
#   that closes it at once). While a gate holds it, the group is stopped (SIGSTOP), and continued
#   (SIGCONT) when the gate releases it.
# - Cap: a hold longer than SLOP_GATE_PAUSE_CAP_S (default 5400 s, 90 min: longer than a full gate
#   with scenes and the render group) is taken for a leaked lock. The command is continued and not
#   paused again during that hold, and the hold is logged as such. The wait at start has the same cap.
# - The gate's own work is never paused: when this process or any of its ancestors has the lock
#   file open (a gate's shell, `flock -x gate.lock python3 scene_gate.py ...`, or a gate's Python
#   whose children do not inherit the descriptor), the caller holds the lock, and the command
#   runs without waiting or pausing. Checked at start and before every pause.
# - The lock is never open in this shell, and a descriptor on it that the caller passed down is
#   closed before the command starts.
# - Nested (a step run through gate_pause.sh that starts Blender through blender_gate.sh): the
#   inner call runs its command straight, in the outer group, and the outer call pauses it all. A
#   second setsid would put the inner command out of the outer pause's reach, and an inner call
#   stopped by the outer pause could not stop its own command. SLOP_GATE_PAUSE_OUTER names the
#   outer call while it lives.
# - SLOP_GATE_WAIT=0: no waiting, no pausing. Without /proc or flock(1) (macOS): no waiting.
# - INT, TERM and HUP go to the command's group (continued first, so a stopped group acts on
#   them). The exit code is the command's.
# Log: stderr and SLOP_GATE_LOG (default ~/.local/state/slop-build/gate-pause.log).
# For tests: SLOP_GATE_LOCK, SLOP_GATE_LOG, SLOP_GATE_POLL_S.
set -u
[ "${1:-}" = "--" ] && shift
if [ $# -eq 0 ]; then
  echo "usage: gate_pause.sh -- CMD [ARGS...]" >&2
  exit 2
fi
L=${SLOP_GATE_LOCK:-$HOME/.local/state/slop-build/gate.lock}
LOG=${SLOP_GATE_LOG:-$HOME/.local/state/slop-build/gate-pause.log}
POLL=${SLOP_GATE_POLL_S:-3}
CAP=${SLOP_GATE_PAUSE_CAP_S:-5400}
NAME=${SLOP_GATE_NAME:-$(basename "$1")}

say() {
  local m="gate-pause [$$] ($NAME): $*"
  echo "$m" >&2
  { mkdir -p "$(dirname "$LOG")" && echo "$(date -u +%FT%TZ) $m" >> "$LOG"; } 2>/dev/null || true
}

if [ -n "${SLOP_GATE_PAUSE_OUTER:-}" ] && kill -0 "$SLOP_GATE_PAUSE_OUTER" 2>/dev/null; then
  exec "$@"
fi
if [ "${SLOP_GATE_WAIT:-1}" = 0 ] || [ ! -d /proc/$$/fd ] || ! command -v flock >/dev/null 2>&1; then
  exec "$@"
fi

want=$(readlink -f "$L" 2>/dev/null || echo "$L")
# A descriptor on the lock passed down by the caller: close it, so the command never inherits it.
for fd in /proc/$$/fd/*; do
  n=${fd##*/}
  [ "$n" -gt 2 ] 2>/dev/null || continue
  if [ "$(readlink -f "$fd" 2>/dev/null)" = "$want" ]; then
    eval "exec $n>&-"
    passed=1
  fi
done

# Does an ancestor of this process (its caller, the caller's caller, ...) have the lock file open?
ancestor_holds() {
  local pid=$PPID ppid fd
  [ "${passed:-0}" = 1 ] && return 0
  while [ "${pid:-0}" -gt 1 ] 2>/dev/null; do
    for fd in /proc/$pid/fd/*; do
      [ "$(readlink -f "$fd" 2>/dev/null)" = "$want" ] && return 0
    done
    ppid=$(awk '/^PPid:/ {print $2}' /proc/$pid/status 2>/dev/null)
    [ -n "$ppid" ] || break
    pid=$ppid
  done
  return 1
}

# Held exclusively by someone (a gate): a shared lock cannot be taken. The test runs in a child
# process that opens, tries and closes the file; nothing stays open here.
held() { [ -e "$L" ] && ! flock -n -s "$L" true 2>/dev/null; }

if held; then
  if ancestor_holds; then
    say "the caller holds the gate lock (an ancestor has it open): running without waiting or pausing"
    exec "$@"
  fi
  say "a scene gate is running; waiting (at most ${CAP} s; SLOP_GATE_WAIT=0 skips)"
  if ! flock -w "$CAP" -s "$L" true 2>/dev/null; then
    say "WARNING: the gate lock has been held over ${CAP} s; starting anyway (a leaked lock? see docs/TOOLING.md)"
  fi
fi

# A command started with `&` in a script has INT and QUIT ignored, and a shell cannot undo that;
# `env --default-signal` gives the command the default actions back, so a forwarded INT ends it.
export SLOP_GATE_PAUSE_OUTER=$$
setsid env --default-signal=INT,QUIT "$@" &
pid=$!
paused=0; paused_at=0; capped=0; own=0

forward() {
  local sig=$1
  kill -CONT -- -"$pid" 2>/dev/null
  kill -"$sig" -- -"$pid" 2>/dev/null
}
trap 'forward INT' INT
trap 'forward TERM' TERM
trap 'forward HUP' HUP

while kill -0 "$pid" 2>/dev/null; do
  if held; then
    now=$(date +%s)
    if [ "$paused" = 0 ] && [ "$capped" = 0 ] && [ "$own" = 0 ]; then
      if ancestor_holds; then
        own=1
        say "the caller took the gate lock (an ancestor has it open): not pausing"
      elif kill -STOP -- -"$pid" 2>/dev/null; then
        paused=1; paused_at=$now; say "a scene gate took the lock: group $pid paused"
      fi
    elif [ "$paused" = 1 ] && [ $((now - paused_at)) -ge "$CAP" ]; then
      kill -CONT -- -"$pid" 2>/dev/null
      paused=0; capped=1
      say "WARNING: paused ${CAP} s and the lock is still held: group $pid continued, not paused again during this hold (a leaked lock? see docs/TOOLING.md)"
    fi
  else
    if [ "$paused" = 1 ]; then
      kill -CONT -- -"$pid" 2>/dev/null
      say "the gate let the lock go: group $pid continued after $(( $(date +%s) - paused_at )) s"
    fi
    paused=0; capped=0; own=0
  fi
  sleep "$POLL" &
  wait $! 2>/dev/null
done
wait "$pid"
exit $?
