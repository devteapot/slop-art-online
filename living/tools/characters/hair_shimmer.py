#!/usr/bin/env python3
"""Shimmer of a hand-made hair's lock ink lines (docs/HANDMADE_HAIR.md, "Ink shimmer"): the v1.1
tool, now `ink_shimmer.py --slot hair` with the same arguments, region, numbers and output folder
(`.local/living/hair-shimmer/<stem>/<time>/`).

    python3 living/tools/characters/hair_shimmer.py view/<file>.glb [--out DIR] [--binary PATH]
                                                    [--plain-stills DIR] [--ink-stills DIR]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ink_shimmer import main  # noqa: E402

if __name__ == "__main__":
    main(["--slot", "hair", *sys.argv[1:]], tool="hair_shimmer")
