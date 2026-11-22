#!/usr/bin/env python3
"""Every 2 s, one line: unix time, the host's busy CPU (jiffies, /proc/stat), the summed CPU (jiffies)
of the live processes under ~/.local/share/github-actions (other projects' self-hosted runners and
their jobs: not ours to stop), and how many there are. BATTLE_CONTRACT_CASES marks runs they disturb."""
import os
import sys
import time

ROOT = os.path.expanduser("~/.local/share/github-actions")
out = open(sys.argv[1], "a", buffering=1)
while True:
    cpu = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    busy = sum(cpu) - cpu[3] - cpu[4]
    tot = n = 0
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            if ROOT not in open(f"/proc/{p}/cmdline", "rb").read().decode(errors="ignore") and ROOT not in os.readlink(f"/proc/{p}/exe"):
                continue
            f = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
            tot += int(f[11]) + int(f[12])
            n += 1
        except OSError:
            continue
    out.write(f"{time.time():.2f} {busy} {tot} {n}\n")
    time.sleep(2)
