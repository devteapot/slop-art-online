#!/usr/bin/env python3
"""Paid-wrapper fixture: inert child, no database or model calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

folder, scenario = Path(sys.argv[1]), sys.argv[2]
child = subprocess.Popen([sys.executable, '-c',
    'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'])
(folder / 'dry-child.json').write_text(json.dumps({'pid': child.pid, 'pgid': os.getpgrp()}))
time.sleep(0.2)
if scenario == 'exit':
    sys.exit(0)
if scenario == 'driver-killed':
    os.kill(os.getpid(), signal.SIGKILL)
time.sleep(120)
