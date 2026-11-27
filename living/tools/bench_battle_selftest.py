#!/usr/bin/env python3
"""Check battle benchmark arguments and sample boundaries without a server."""
import tempfile
import unittest
from pathlib import Path

from bench_battle import build_parser, summarize_sample


class BattleBenchTest(unittest.TestCase):
    def test_parse_documented_command(self):
        args = build_parser().parse_args([
            "--run", "ui-battle-bench-01", "--out", ".local/battle-bench/01",
            "--size", "1920x1080", "--look", "classic", "--scale", "100",
        ])
        self.assertEqual(args.run, "ui-battle-bench-01")
        self.assertEqual(args.out, Path(".local/battle-bench/01"))
        self.assertEqual((args.size, args.look, args.scale), ("1920x1080", "classic", "100"))
        self.assertIsNone(args.bin)

    def test_sample_excludes_warmup_and_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp) / "frames.csv"
            sample = Path(tmp) / "sample.csv"
            frames.write_text("999999,200000,200000\n" + "".join(
                f"{timestamp},10000,8000\n" for timestamp in range(1_000_000, 13_000_000, 10_000)
            ) + "13000000,300000,300000\n")
            stats = summarize_sample(
                frames, "1970-01-01T00:00:01Z INFO live script: wait:12 (me Some(65))\n", sample,
            )
            self.assertEqual(stats["frames"], 1200)
            self.assertEqual(stats["mean_ms"], 10.0)
            self.assertEqual(stats["frames_over_16_7ms"], 0)
            self.assertEqual(stats["sample_start_unix_us"], 1_000_000)
            self.assertEqual(stats["sample_end_unix_us"], 13_000_000)


if __name__ == "__main__":
    unittest.main()
