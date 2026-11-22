#!/usr/bin/env python3
"""A process that wakes every 200 µs and does nothing else (as the relay's polling loop does when idle):
does another core's wake-up pattern change the database thread's cost? Runs until killed."""
import time
while True:
    time.sleep(0.0002)
