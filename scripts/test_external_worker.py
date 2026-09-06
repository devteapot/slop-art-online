"""Subprocess protocol checks; these fixtures contact no authority or provider."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from external_worker import ExternalWorker, PROTOCOL


FIXTURE = r'''
import json,os,pathlib,sys,time
root=pathlib.Path(sys.argv[1]);mode=sys.argv[2]
with (root/'starts').open('a') as out:out.write(str(os.getpid())+'\n')
for line in sys.stdin:
    job=json.loads(line)
    with (root/'messages').open('a') as out:out.write(json.dumps(job)+'\n')
    if job['op']=='shutdown':break
    if job['op']=='cancel':break
    if mode=='eof':break
    if mode=='wait':continue
    failed=mode=='first-error' and job['id']==1
    ack=dict(protocol='sao-external-worker-v1',id=job['id'],phase='failed' if failed else 'completed',
             exit_code=1 if failed else 0,error='fixture application rejection' if failed else None,worker_reusable=True)
    if mode=='wrong-id':ack['id']+=1
    body=json.dumps(ack)+'\n'
    if mode=='split':
        sys.stdout.write(body[:20]);sys.stdout.flush();time.sleep(.03);sys.stdout.write(body[20:]);sys.stdout.flush()
    else:print(body,end='',flush=True)
'''


class WorkerProtocolChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.script = self.root / "fixture.py"
        self.script.write_text(FIXTURE)
        self.workers = []

    def tearDown(self):
        for worker in self.workers:
            worker.stop(grace=.1)
        self.tmp.cleanup()

    def worker(self, mode="normal"):
        worker = ExternalWorker([sys.executable, "-u", str(self.script), str(self.root), mode],
                                cwd=self.root, env=os.environ.copy(), log_path=self.root / "worker.log")
        self.workers.append(worker)
        return worker

    def job(self, worker, job_id=1, *, stop=None, deadline=None):
        return worker.run(job_id, "behavior", self.root / "config.json", f"{job_id:02}-behavior",
                          deadline=deadline or time.monotonic() + 5,
                          cancelled=(stop.is_set if stop else lambda: False), alive=lambda: True)

    def test_two_jobs_keep_one_process_and_do_not_share_acknowledgements(self):
        worker = self.worker()
        first = self.job(worker)
        second = self.job(worker, 2)
        self.assertEqual([first["phase"], second["phase"]], ["completed", "completed"])
        self.assertEqual(first["worker_pid"], second["worker_pid"])
        worker.stop(grace=.2)
        self.assertEqual(len((self.root / "starts").read_text().splitlines()), 1)
        messages = [json.loads(line) for line in (self.root / "messages").read_text().splitlines()]
        self.assertEqual([message["id"] for message in messages if message["op"] == "job"], [1, 2])
        self.assertIsNone(worker.cleanup_error)

    def test_application_failure_keeps_transport_for_next_scheduled_job(self):
        worker = self.worker("first-error")
        first = self.job(worker)
        second = self.job(worker, 2)
        self.assertEqual(first["phase"], "failed")
        self.assertTrue(first["worker_reusable"])
        self.assertEqual(second["phase"], "completed")
        self.assertEqual(first["worker_pid"], second["worker_pid"])

    def test_partial_ack_line_is_buffered_until_complete(self):
        self.assertEqual(self.job(self.worker("split"))["phase"], "completed")

    def test_wrong_job_id_poisoning_does_not_spawn_replacement(self):
        worker = self.worker("wrong-id")
        first = self.job(worker)
        second = self.job(worker, 2)
        self.assertEqual(first["phase"], "failed")
        self.assertFalse(first["worker_reusable"])
        self.assertFalse(second["worker_reusable"])
        self.assertEqual(len((self.root / "starts").read_text().splitlines()), 1)

    def test_eof_becomes_structured_unavailable_result(self):
        worker = self.worker("eof")
        result = self.job(worker)
        self.assertEqual(result["phase"], "failed")
        self.assertIn("stdout closed", result["error"])
        self.assertFalse(result["worker_reusable"])

    def test_expired_first_job_never_spawns(self):
        worker = self.worker()
        self.assertEqual(self.job(worker, deadline=time.monotonic() - 1)["phase"], "interrupted")
        self.assertIsNone(worker.process)
        self.assertFalse((self.root / "starts").exists())

    def test_cancellation_stops_worker_without_replacement(self):
        worker = self.worker("wait")
        stop = threading.Event()
        timer = threading.Timer(.1, stop.set)
        timer.start()
        try:
            result = self.job(worker, stop=stop)
        finally:
            timer.join()
        self.assertEqual(result["phase"], "interrupted")
        self.assertFalse(result["worker_reusable"])
        self.assertIsNotNone(worker.process.returncode)

    def test_boolean_or_repeated_ids_are_rejected(self):
        worker = self.worker()
        with self.assertRaises(ValueError):
            self.job(worker, True)
        self.job(worker)
        with self.assertRaises(ValueError):
            self.job(worker)


if __name__ == "__main__":
    unittest.main()
