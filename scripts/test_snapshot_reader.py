import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_living_clearing import SnapshotReader


class SnapshotReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'snapshot.json'
        self.reader = SnapshotReader()

    def replace(self, value):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value))
        temporary.replace(self.path)

    def test_concurrent_unchanged_reads_decode_once(self):
        expected = {'world': {'players': [{'id': 1, 'health': 100}]}, 'events': []}
        self.replace(expected)
        with patch('run_living_clearing.json.load', wraps=json.load) as decode:
            with concurrent.futures.ThreadPoolExecutor(max_workers=18) as workers:
                values = list(workers.map(lambda _: self.reader.read(self.path), range(72)))
            self.assertTrue(all(value == expected for value in values))
            self.assertEqual(decode.call_count, 1)

    def test_equal_size_equal_mtime_replacement_updates_alive_state(self):
        self.replace({'health': 1})
        self.assertEqual(self.reader.read(self.path), {'health': 1})
        previous = self.path.stat()
        self.replace({'health': 0})
        os.utime(self.path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size, previous.st_size)
        self.assertEqual(self.reader.read(self.path), {'health': 0})

    def test_failed_current_export_does_not_return_cached_success(self):
        self.assertIsNone(self.reader.read(self.path))
        self.replace({'health': 1})
        self.assertEqual(self.reader.read(self.path), {'health': 1})
        self.path.write_text('{')
        self.assertIsNone(self.reader.read(self.path))
        self.replace({'health': 0})
        self.assertEqual(self.reader.read(self.path), {'health': 0})
        self.path.unlink()
        self.assertIsNone(self.reader.read(self.path))

    def test_run_path_change_cannot_reuse_another_world(self):
        self.replace({'run': 'first'})
        self.assertEqual(self.reader.read(self.path), {'run': 'first'})
        other = self.path.with_name('other.json')
        other.write_text(json.dumps({'run': 'second'}))
        self.assertEqual(self.reader.read(other), {'run': 'second'})
        self.assertEqual(self.reader.read(self.path), {'run': 'first'})


if __name__ == '__main__':
    unittest.main()
