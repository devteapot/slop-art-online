#!/bin/bash
# Self-test for living/tools/build-slot's pruning of dead and reused-pid records, in a scratch
# BUILD_SLOT_DIR (never the laptop's real .local/build-slots). Usage: bash living/tools/build_slot_selftest.sh
# Waiters: a dead pid, a dead pid in the old one-line format, a live pid whose recorded start time
# is not its own (a reused pid), a live pid in the old format, and a real build-slot waiting behind
# a real holder. Only the first three may be dropped. Slots: a dead holder, a reused-pid holder and
# an old-format live holder; only the first two are freed, and a job then runs in a freed slot.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BS="$HERE/build-slot"
T=$(mktemp -d "${TMPDIR:-/tmp}/build-slot-selftest.XXXXXX")
export BUILD_SLOT_DIR="$T/slots" BUILD_SLOT_MIN_FREE_GB=0 BUILD_SLOT_SCCACHE=0
FAIL=0; PIDS=()
ok() { echo "ok    $*"; }
bad() { echo "FAIL  $*"; FAIL=1; }
cleanup() { exec 2>/dev/null; for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done; touch "$T/release"; wait 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
dead_pid() { sleep 0 & local p=$!; wait "$p"; echo "$p"; }
live_pid() { sleep 300 & PIDS+=($!); }
until_file() { for _ in $(seq 1 100); do [ -e "$1" ] && return 0; sleep 0.1; done; return 1; }
BOGUS="Mon Jan 1 00:00:00 2001"

echo "== waiters (BUILD_SLOTS=1, scratch dir $BUILD_SLOT_DIR)"
export BUILD_SLOTS=1
# A real holder (holds slot-1 until $T/release exists) and a real waiter behind it.
"$BS" --label holder bash -c "while [ ! -e '$T/release' ]; do sleep 0.2; done" & HOLDER=$!; PIDS+=($HOLDER)
until_file "$BUILD_SLOT_DIR/slot-1/start" || bad "the holder never took slot-1"
"$BS" --label waiter true & WAITER=$!; PIDS+=($WAITER)
until_file "$BUILD_SLOT_DIR/waiting/$WAITER" || bad "the waiter never wrote its file"
sleep 0.3
grep -q '^start=.' "$BUILD_SLOT_DIR/waiting/$WAITER" && ok "a real waiter records its start time" \
  || bad "the waiter's file has no start time: $(cat "$BUILD_SLOT_DIR/waiting/$WAITER")"
[ -s "$BUILD_SLOT_DIR/slot-1/start" ] && ok "a real holder records its start time (slot-1/start)" \
  || bad "slot-1/start is empty"
D1=$(dead_pid); D2=$(dead_pid)
printf 'pid %s dead since 00:00:00: x\nstart=%s\n' "$D1" "$BOGUS" > "$BUILD_SLOT_DIR/waiting/$D1"
printf 'pid %s dead-old since 00:00:00: x\n' "$D2" > "$BUILD_SLOT_DIR/waiting/$D2"
live_pid; R=$!
printf 'pid %s reused since 00:00:00: x\nstart=%s\n' "$R" "$BOGUS" > "$BUILD_SLOT_DIR/waiting/$R"
live_pid; L=$!
printf 'pid %s live-old since 00:00:00: x\n' "$L" > "$BUILD_SLOT_DIR/waiting/$L"
echo "-- build-slot --status"
"$BS" --status | sed 's/^/   /'
for p in "$D1" "$D2" "$R"; do
  [ -e "$BUILD_SLOT_DIR/waiting/$p" ] && bad "waiter $p should be dropped" || ok "waiter $p dropped"
done
for p in "$WAITER" "$L"; do
  [ -e "$BUILD_SLOT_DIR/waiting/$p" ] && ok "waiter $p kept" || bad "waiter $p should be kept"
done
[ -d "$BUILD_SLOT_DIR/slot-1" ] && [ "$(cat "$BUILD_SLOT_DIR/slot-1/pid")" = "$HOLDER" ] \
  && ok "the live holder's slot-1 kept" || bad "the live holder's slot-1 was freed"
touch "$T/release"; wait "$HOLDER"; wait "$WAITER"; rc=$?
[ "$rc" = 0 ] && [ ! -e "$BUILD_SLOT_DIR/waiting/$WAITER" ] && ok "the waiter ran once the holder ended, and its file is gone" \
  || bad "the waiter exited $rc, file left: $(ls "$BUILD_SLOT_DIR/waiting")"
rm -f "$T/release"

echo "== slots (BUILD_SLOTS=3)"
export BUILD_SLOTS=3
mk_slot() { mkdir -p "$BUILD_SLOT_DIR/slot-$1"; echo "$2" > "$BUILD_SLOT_DIR/slot-$1/pid"; echo "$4" > "$BUILD_SLOT_DIR/slot-$1/label"
            echo 00:00:00 > "$BUILD_SLOT_DIR/slot-$1/since"; [ -n "$3" ] && echo "$3" > "$BUILD_SLOT_DIR/slot-$1/start"; return 0; }
mk_slot 1 "$(dead_pid)" "$BOGUS" dead
live_pid; mk_slot 2 "$!" "$BOGUS" reused
live_pid; L2=$!; mk_slot 3 "$L2" "" live-old
echo "-- build-slot --status"
"$BS" --status | sed 's/^/   /'
[ -d "$BUILD_SLOT_DIR/slot-1" ] && bad "slot-1 (dead holder) should be freed" || ok "slot-1 (dead holder) freed"
[ -d "$BUILD_SLOT_DIR/slot-2" ] && bad "slot-2 (reused pid) should be freed" || ok "slot-2 (reused pid) freed"
[ -d "$BUILD_SLOT_DIR/slot-3" ] && ok "slot-3 (old-format live holder) kept" || bad "slot-3 (old-format live holder) was freed"
# A reused-pid holder must also be freed by a job looking for a slot, not only by --status.
live_pid; mk_slot 1 "$!" "$BOGUS" reused; live_pid; mk_slot 2 "$!" "$BOGUS" reused
BUILD_SLOTS=2 "$BS" --label job echo ran >"$T/job.out" 2>&1 &
JOB=$!; PIDS+=($JOB)
for _ in $(seq 1 50); do kill -0 "$JOB" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$JOB" 2>/dev/null; then bad "a job did not take a reused-pid slot within 5 s"
else wait "$JOB"; grep -q ran "$T/job.out" && ok "a job reclaimed a reused-pid slot and ran" || bad "the job did not run: $(cat "$T/job.out")"; fi

echo; [ "$FAIL" = 0 ] && echo "build-slot selftest: PASS" || echo "build-slot selftest: FAIL"
exit "$FAIL"
