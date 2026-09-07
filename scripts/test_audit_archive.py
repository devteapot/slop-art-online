import json
import unittest
from owner_snapshot import parse_audit_page, export_audit_json

class AuditExportTests(unittest.TestCase):
    def test_exact_bytes_and_pages(self):
        bodies = [f'{{ "run":"r", "id":{i}, "n":1.00 }}' for i in range(1, 4100)]
        calls=[]
        def call(name, run, start, end, limit):
            calls.append((name, start, end, limit))
            return json.dumps([0, bodies[start-1:min(end-1,start-1+limit)]])
        self.assertEqual(export_audit_json(call,'r',4100),bodies)
        self.assertEqual(len(calls),2)
    def test_gaps_foreign_and_wrong_result_fail(self):
        for wire in ['[1,"run unavailable"]','[0,[]]', '[0,["{}"]]',
                     json.dumps([0,['{"run":"other","id":1}']]),
                     json.dumps([0,['{"run":"r","id":2}']]),
                     json.dumps([0,['{"run":"r","id":1,"id":1}']])]:
            with self.assertRaises(ValueError):parse_audit_page(wire,'r',1,2)
