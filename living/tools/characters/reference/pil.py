"""Pillow from the user's site packages: the scripts run with `python3 -I` (they read third-party
files), which leaves the user site off the path."""
import site
import sys

sys.path.append(site.getusersitepackages())
