#!/usr/bin/env python3
"""blender_gate.sh on a fake Blender (docs/TOOLING.md, "Heavy work during a gate").

    python3 living/tools/blender_gate_selftest.py

blender_gate.sh is a thin caller of gate_pause.sh, so this runs gate_pause_selftest.py's cases
through it: `python3 living/tools/gate_pause_selftest.py --blender`. Exits as that does.
"""

import subprocess
import sys
from pathlib import Path

sys.exit(subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "gate_pause_selftest.py"), "--blender"]).returncode)
