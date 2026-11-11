#!/usr/bin/env python3
"""Self-test of living/tools/store.py (docs/STORE.md). Everything happens in a temporary
directory: planted secrets in every format the scrubber must catch, a fake play session with the
owner's typed lines, a fake trial batch packed, published to a local-directory backend, fetched
back and unpacked, the motion library round trip, a fake home for the manifest, and the
Hugging Face gate refusing while it is off. No network; huggingface_hub is never imported.

Usage: python3 living/tools/store_selftest.py [-v]
"""
import gzip
import io
import json
import os
import random
import string
import sys
import tarfile
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

# Planted values: fake, but in the real formats. The token-shaped ones are generated at run time
# so that no key-shaped literal sits in the source (secret scanners would flag it).
_rng = random.Random(20261111)


def _fake(alphabet, n):
    return "".join(_rng.choice(alphabet) for _ in range(n))


_ALNUM = string.ascii_letters + string.digits
_B64URL = _ALNUM + "-_"
MISTRAL = _fake(_ALNUM, 32)                       # 32 alphanumerics, Mistral-style
HF = "hf" + "_" + _fake(_ALNUM, 34)
GH = "gh" + "p_" + _fake(_ALNUM, 36)
GH_PAT = "github" + "_pat_" + _fake(_ALNUM + "_", 60)
JWT = ".".join(("ey" + "J" + _fake(_B64URL, 20), "ey" + "J" + _fake(_B64URL, 40), _fake(_B64URL, 43)))
ANTH = "sk" + "-ant-" + _fake(_B64URL, 40)
AWS = "AK" + "IA" + _fake(string.ascii_uppercase + string.digits, 16)
NEO_PW = "n30-hunter2-pass"
LIVING_TOK = "lt_plain_9f8e7d6c5b"
EMAIL = "owner.person@example.org"
NAME = "Ada Quillfeather"
LOGIN = "adaq"
HOST = "spark-9z9z"


def ident(**kw):
    base = dict(names=[NAME], emails=[EMAIL], logins=[LOGIN], hostnames=[HOST], secrets=[MISTRAL])
    base.update(kw)
    return store.Identity(**base)


def scrubber(decisions=None, **kw):
    cfg = {"never_touch": {"test": []}, "never_touch_names": [], "decisions": {}}
    return store.Scrubber(ident(), decisions=decisions, cfg=cfg, machine="test", **kw)


class Text(unittest.TestCase):
    def run_text(self, text, decisions=None):
        acc = store.Findings()
        out = scrubber(decisions).scrub_text(text, acc)
        return out, acc

    def assertGone(self, secret, text, cat):
        out, acc = self.run_text(text)
        self.assertNotIn(secret, out, f"{cat} leaked: {out!r}")
        self.assertIn(cat, acc.counts, f"{cat} not counted: {acc.counts}")
        for c, exs in acc.examples.items():
            for e in exs:
                self.assertNotIn(secret, e, f"example for {c} shows the secret")
        return out

    def test_tokens(self):
        self.assertGone(MISTRAL, f"MISTRAL_API_KEY={MISTRAL}\n", "known-secret")
        self.assertGone(MISTRAL, f"the key was {MISTRAL} yesterday", "known-secret")
        self.assertGone(HF, f"token: {HF}", "hf-token")
        self.assertGone(GH, f"git push https://{GH}@github.com/x/y", "github-token")
        self.assertGone(GH_PAT, f"GH={GH_PAT}", "github-token")
        self.assertGone(JWT, f'{{"identity":"c200","token":"{JWT}"}}', "jwt")
        self.assertGone(ANTH, f"ANTHROPIC_API_KEY='{ANTH}'", "api-key")
        self.assertGone(AWS, f"aws {AWS} here", "aws-key")

    def test_context(self):
        other = _fake(_ALNUM, 32)
        self.assertGone(other, f"Authorization: Bearer {other}", "bearer")
        self.assertGone(other, f"OTHER_API_KEY={other}", "secret-assignment")
        self.assertGone(LIVING_TOK, f"export LIVING_TOKEN={LIVING_TOK}", "secret-assignment")
        self.assertGone(LIVING_TOK, f'"LIVING_TOKEN": "{LIVING_TOK}"', "secret-assignment")
        self.assertGone(NEO_PW, f"NEO4J_AUTH=neo4j/{NEO_PW}", "secret-assignment")
        self.assertGone("s3cr3tpw", "postgres://bob:s3cr3tpw@db:5432/x", "url-credentials")
        self.assertGone("abc123def456", "x-api-key: abc123def456", "secret-assignment")

    def test_json_fields(self):
        s = scrubber()
        acc = store.Findings()
        out = s.scrub_obj({"LIVING_VERIFY_FAKE_KEY": "dummy-local-only", "spacetimedb_token": "zzzzzzzzzz",
                           "prompt_cache_key": "sao:9:glm-flash:think", "max_tokens": 6000,
                           "cached_tokens": 12, "key": "inventory-slot-3"}, acc)
        self.assertEqual(out["LIVING_VERIFY_FAKE_KEY"], "[redacted:secret]")
        self.assertEqual(out["spacetimedb_token"], "[redacted:secret]")
        self.assertEqual(out["prompt_cache_key"], "sao:9:glm-flash:think")
        self.assertEqual(out["max_tokens"], 6000)
        self.assertEqual(out["key"], "inventory-slot-3")
        self.assertEqual(acc.counts.get("secret-field"), 2)

    def test_identity(self):
        out = self.assertGone(EMAIL, f"mail {EMAIL} now", "owner-email")
        self.assertIn("[owner-email]", out)
        self.assertGone("someone@else.com", "cc someone@else.com", "email")
        out = self.assertGone(NAME, f"Author: {NAME} <x>", "owner-name")
        self.assertGone("Quillfeather", "Quillfeather wrote", "owner-name")
        out, acc = self.run_text("Ada killed Cuth Marrow")
        self.assertEqual(out, "Player killed Cuth Marrow")
        out, acc = self.run_text("Ada killed Cuth Marrow", {"owner_first_name": "include"})
        self.assertEqual(out, "Ada killed Cuth Marrow")
        out = self.assertGone("/home/adaq", "cd /home/adaq/dev/slop && ls", "home-path")
        self.assertIn("~/dev/slop", out)
        out = self.assertGone("/Users/zed", "at /Users/zed/dev/x", "home-path")
        self.assertGone(LOGIN, f"ssh {LOGIN}@box", "login")

    def test_network(self):
        for ip in ("192.168.7.42", "10.0.0.5", "172.20.1.1", "100.100.1.2"):
            self.assertGone(ip, f"ssh host {ip}:22", "private-ip")
        for keep in ("172.32.0.1", "100.128.0.1", "127.0.0.1", "8.8.8.8", "version 10.5", "hp 100.0"):
            out, _ = self.run_text(f"at {keep} ok")
            self.assertIn(keep, out)
        self.assertGone(HOST, f"running on {HOST} now", "hostname")
        self.assertGone("box.tail1234.ts.net", "ssh box.tail1234.ts.net", "hostname")
        self.assertGone("Adas-MacBook-Pro", "on Adas-MacBook-Pro.local", "hostname")
        self.assertGone("Adas-MacBook-Air", "host Adas-MacBook-Air ready", "hostname")
        blob = "data:image/png;base64,3qx3Hjxcmy/UuYXJ1aq2cWviMacQ0hWvfQNtgaTL+" + "A" * 40
        out, _ = self.run_text(blob)
        self.assertEqual(out, blob)

    def test_no_false_positives(self):
        for keep in ("cd ~/dev/slop-trials-e6/.local/living/trials", "system/68ee91a7fbf3890de158dac02833a5c1.txt",
                     "the bearer of the letter came", "tokens: 2849", "max_tokens: 6000",
                     '"prompt_cache_key":"sao:9:glm-flash:consolidate"', "Brackenford's gate at 07:00",
                     "password protected door", "a secret: the well"):
            out, acc = self.run_text(keep)
            self.assertEqual(out, keep, f"changed: {keep!r} -> {out!r} ({acc.counts})")


class Files(unittest.TestCase):
    def test_refusals(self):
        s = scrubber()
        for name, why in ((".env", "secrets"), ("neo4j.env", "secrets"), ("cli.toml", "secrets"),
                          ("id_ed25519", "secrets"), ("._summary.json", "macOS"), (".DS_Store", "macOS")):
            st, reason = s.classify(f"a/{name}")
            self.assertEqual(st, "refused", name)
            self.assertIn(why, reason)
        st, _ = s.classify("verify/build-knowledge/x.rlib")
        self.assertEqual(st, "skipped")
        st, why, out, _ = s.scrub_bytes("notes.txt", b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")
        self.assertEqual(st, "refused")
        self.assertIsNone(out)
        st, why, out, _ = s.scrub_bytes("blob.xyz", b"\x00\x01\x02binary")
        self.assertEqual(st, "refused")
        st, why, out, _ = s.scrub_bytes("take.npz", b"\x00PK numeric" + HOST.encode())
        self.assertEqual(st, "refused")
        st, why, out, _ = s.scrub_bytes("take.npz", b"\x00PK only numbers 0123")
        self.assertEqual(st, "ok")

    def test_never_touch(self):
        with tempfile.TemporaryDirectory() as t:
            nt = os.path.join(t, "slop-lab")
            os.makedirs(nt)
            cfg = {"never_touch": {"test": [nt]}, "never_touch_names": ["sao-living"], "decisions": {}}
            s = store.Scrubber(ident(), cfg=cfg, machine="test")
            self.assertEqual(s.classify("x.json", os.path.join(nt, "x.json"))[0], "refused")
            self.assertEqual(s.classify("x.json", os.path.join(t, "sao-living_data", "x.json"))[0], "refused")
            self.assertEqual(s.classify("x.json", os.path.join(t, "ok", "x.json"))[0], "ok")

    def test_jsonl_and_gz(self):
        s = scrubber()
        line = json.dumps({"reply": f"key {MISTRAL}", "n": 1}) + "\n"
        st, _, out, acc = s.scrub_bytes("x.jsonl", line.encode())
        self.assertNotIn(MISTRAL, out.decode())
        self.assertEqual(json.loads(out)["n"], 1)
        st, _, out, acc = s.scrub_bytes("x.jsonl.gz", gzip.compress(line.encode()))
        self.assertNotIn(MISTRAL, gzip.decompress(out).decode())


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def journal_entry(actor, purpose, user, reply):
    return json.dumps({"actor": actor, "at_ms": 1, "purpose": purpose, "model": "zai-glm-5-3-flash",
                       "tokens": 10, "latency_ms": 5, "error": None, "reply": reply,
                       "request": {"messages": [{"role": "system", "content_ref": "system/abc.txt"},
                                                {"role": "user", "content": user}]}}, ensure_ascii=False)


def fake_session(root):
    write(root, "session/run/client.log", "\x1b[32m INFO\x1b[0m living_game::net: playing character #26\n")
    talk = ("# You and a stranger (#26)\nenemy\n\n# The conversation so far\na stranger: “wassup mate”\n"
            "you: “evening”\n\n# What you are answering\na stranger: “wassup mate”")
    think = ("- [1063] day 1 07:59 A stranger said: “hi there” {someone=#26}\n"
             "- [1064] day 1 08:00 Mercy Abbot said: “welcome” {Mercy Abbot=#5}\n"
             "- [1065] day 1 08:01 Ada Quillfeather was here, at /home/adaq/x on 192.168.7.42")
    write(root, "session/journal/Linnet_Abbot.jsonl",
          journal_entry("Linnet Abbot", "talk", talk, '{"say": "Evening."}') + "\n" +
          journal_entry("Linnet Abbot", "think", think, '{"thought": "a stranger said hi there"}') + "\n")
    write(root, "session/journal/system/abc.txt", "You are a person in a world.")
    write(root, "session/journal/Ada.jsonl", journal_entry("Ada", "remember", "You said “hi there”.", "{}") + "\n")
    write(root, "FEEDBACK.md", "I liked it. — the owner\n")
    # a resident's own line to the player: the tags start with the addressee
    write(root, "session/journal/Mercy_Abbot.jsonl",
          journal_entry("Mercy Abbot", "think", "- [1751] day 1 19:00 You said to a stranger: “Do not greet me so.” "
                        "{someone=#26}", "{}") + "\n")
    write(root, "ffprof/prefs.js", 'user_pref("x", "addon@mozilla.org");\n')
    write(root, "ffprof/extensions.json", '{"id": "addon@mozilla.org"}')
    write(root, "diagnosis/REPORT.md", "First “hi there” at 07:59, `to = 0`. Ada typed “wassup mate”.\n")
    with open(os.path.join(root, "shot.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00pixels")


class OwnerLines(unittest.TestCase):
    def test_session(self):
        with tempfile.TemporaryDirectory() as t:
            fake_session(t)
            s = scrubber(kind="play-session")
            rows, totals, data = store.scrub_source(t, s, keep_data=True)
            self.assertEqual(s.player_ids, {26})
            self.assertEqual(s.owner_lines, {"wassup mate", "hi there"})
            self.assertIn("a stranger", s.player_labels)
            st = {r["path"]: r["status"] for r in rows}
            self.assertEqual(st["FEEDBACK.md"], "held")
            self.assertEqual(st["ffprof/prefs.js"], "refused")
            self.assertEqual(st["ffprof/extensions.json"], "refused")
            self.assertEqual(st["shot.png"], "held")
            self.assertEqual(st["session/journal/Linnet_Abbot.jsonl"], "held")
            rep = data["diagnosis/REPORT.md"].decode()
            self.assertNotIn("hi there", rep)
            self.assertNotIn("wassup", rep)
            self.assertIn("[owner line]", rep)
            self.assertGreaterEqual(totals.counts["owner-line"], 2)
            dec = store.decision_report(t, s, rows, totals)
            self.assertEqual(dec["owner_lines"]["distinct_lines"], 2)
            self.assertEqual(dec["model_exchanges"]["calls"], 4)
            for e in dec["owner_lines"]["examples"]:
                self.assertNotIn("wassup mate", e)
            # once model exchanges are included, the journals pass with the lines redacted
            s2 = scrubber({"model_exchanges": "include"}, kind="play-session")
            rows, totals, data = store.scrub_source(t, s2, keep_data=True)
            j = data["session/journal/Linnet_Abbot.jsonl"].decode()
            self.assertNotIn("wassup mate", j)
            self.assertNotIn("hi there", j)
            self.assertIn("welcome", j)              # a resident's line stays
            self.assertNotIn("/home/adaq", j)
            self.assertNotIn("192.168.7.42", j)
            self.assertNotIn("Quillfeather", j)
            names = {r.get("published_as") for r in rows}
            self.assertIn("session/journal/Player.jsonl", names)
            # and the owner may choose to keep their lines
            s3 = scrubber({"model_exchanges": "include", "owner_lines": "include"}, kind="play-session")
            _, _, data = store.scrub_source(t, s3, keep_data=True)
            self.assertIn("wassup mate", data["session/journal/Linnet_Abbot.jsonl"].decode())

    def test_dry_run_cli(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "playtest-9")
            fake_session(src)
            rep = os.path.join(t, "report")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = store.main(["scrub", "--dry-run", src, "--report", rep])
            self.assertEqual(rc, 0)
            with open(os.path.join(rep, "report.md")) as f:
                md = f.read()
            self.assertIn("owner_lines", md)
            self.assertIn("held", md)
            for secret in ("wassup mate", "192.168.7.42", "/home/adaq"):
                self.assertNotIn(secret, md)
                self.assertNotIn(secret, buf.getvalue())


def fake_batch(root):
    write(root, "batch.json", json.dumps({"trials": ["living/trials/life.json"], "fake": False}))
    write(root, "report.md", "# Batch\nran on spark-9z9z by Ada Quillfeather\n")
    for r in (1, 2):
        inst = f"life-iter11-r{r}"
        write(root, f"{inst}/summary.json", json.dumps({"db": f"verify-trial-x-{inst}", "survived": True}))
        write(root, f"{inst}/cast.json", json.dumps({"subject": 311}))
        write(root, f"{inst}/state.json", json.dumps({"status": "done"}))
        write(root, f"{inst}/mind-env.json", json.dumps({"LIVING_ROOT": "/home/adaq/dev/x",
                                                          "LIVING_VERIFY_FAKE_KEY": "dummy-local-only"}))
        write(root, f"{inst}/samples.jsonl", "".join(json.dumps({"at_ms": i, "hp": 10}) + "\n" for i in range(3)))
        write(root, f"{inst}/thoughts.jsonl", json.dumps({"at_ms": 5, "text": f"key {MISTRAL}"}) + "\n")
        write(root, f"{inst}/mind.log", f"INFO started with MISTRAL_API_KEY={MISTRAL}\n")
        write(root, f"{inst}/journal/Arlen.jsonl", journal_entry("Arlen", "think", "hello", "{}") + "\n")
        write(root, f"{inst}/journal/system/abc.txt", "system prompt")
        write(root, f"{inst}/snapshots/h00.json", json.dumps({"hour": 0}))
    write(root, "neo4j.env", f"NEO4J_AUTH=neo4j/{NEO_PW}\n")


class Batches(unittest.TestCase):
    def test_pack_publish_fetch_unpack(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "l9")
            fake_batch(src)
            s = scrubber()
            man = store.pack_batch(src, os.path.join(t, "packed"), s, machine="test")
            self.assertEqual(man["counts"]["instances"], 2)
            self.assertEqual(man["counts"]["calls"], 0)            # journals held: undecided
            with self.assertRaises(store.Refused):
                store.check_publishable(man, s)
            s = scrubber({"model_exchanges": "include"})
            out = os.path.join(t, "packed2")
            man = store.pack_batch(src, out, s, machine="test")
            store.check_publishable(man, s)
            self.assertEqual(man["counts"]["calls"], 2)
            self.assertEqual(man["counts"]["prompts"], 2)
            blob = b""
            for n in os.listdir(out):
                with open(os.path.join(out, n), "rb") as f:
                    b = f.read()
                blob += gzip.decompress(b) if n.endswith(".gz") else b
            for secret in (MISTRAL, NEO_PW, "/home/adaq", "Quillfeather", "dummy-local-only", HOST):
                self.assertNotIn(secret.encode(), blob, secret)
            be = store.LocalBackend(os.path.join(t, "remote"))
            be.publish("runs", out, store.unit_path("batch", "l9", "test"), "batch l9")
            dest = os.path.join(t, "fetched")
            path = store.fetch_batch(be, "l9", dest, unpack=True)
            self.assertEqual(path, "batches/test/l9")
            back = os.path.join(dest, "l9")
            self.assertTrue(os.path.exists(os.path.join(back, "life-iter11-r1", "journal", "Arlen.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(back, "life-iter11-r2", "samples.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(back, "life-iter11-r1", "snapshots", "h00.json")))
            self.assertTrue(os.path.exists(os.path.join(back, "life-iter11-r1", "journal", "system", "abc.txt")))
            self.assertFalse(os.path.exists(os.path.join(back, "neo4j.env")))
            # the unpacked tree equals the scrubbed source, file by file
            _, _, data = store.scrub_source(src, scrubber({"model_exchanges": "include"}), keep_data=True)
            for rel, body in data.items():
                p = os.path.join(back, rel)
                self.assertTrue(os.path.exists(p), rel)
                with open(p, "rb") as f:
                    got = f.read()
                if rel.endswith(".jsonl"):
                    self.assertEqual([json.loads(x) for x in got.splitlines()],
                                     [json.loads(x) for x in body.splitlines()], rel)
                else:
                    self.assertEqual(got, body, rel)

    def test_consolidation_accounting_is_published(self):
        """trials.py's per-character consolidation table and provider outages (summary.json
        `consolidations`, `outages`, `call_failures`; report.md's tables) are published with the
        batch while the journals, the mind's outcome lines among them, are held."""
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "ar2")
            fake_batch(src)
            table = {"total": {"attempted": 3, "primary": 1, "fallback": 1, "retried": 1, "lost": 0, "trimmed": 0, "capacity_429": 1},
                     "by_character": {"Mara Vane": {"attempted": 3, "primary": 1, "fallback": 1, "retried": 1, "lost": 0, "trimmed": 0, "capacity_429": 1}}}
            summary = {"db": "verify-trial-x-life-iter11-r1", "consolidations": table, "call_failures": {"capacity_429": 2},
                       "outages": [{"since_t": 10.0, "until_t": 50.0, "seconds": 40.0, "failed": 9, "kinds": {"capacity_429": 9}}]}
            write(src, "life-iter11-r1/summary.json", json.dumps(summary))
            write(src, "life-iter11-r1/journal/outcomes/consolidations.jsonl",
                  json.dumps({"actor": "Mara Vane", "outcome": "integrated", "route": "fallback", "model_call": True}) + "\n")
            row = "| life/iter11/r1 | Mara Vane | 3 | 1 | 1 | 1 | 0 | 0 | 1 |"
            write(src, "report.md", "# Batch\n\n## Consolidations\n\n" + row + "\n")
            out = os.path.join(t, "packed")
            s = scrubber()
            man = store.pack_batch(src, out, s, machine="test")
            with gzip.open(os.path.join(out, "instances.jsonl.gz"), "rt") as f:
                inst = {r["instance"]: r for r in map(json.loads, f)}
            got = json.loads(inst["life-iter11-r1"]["summary"])
            self.assertEqual((got["consolidations"], got["outages"], got["call_failures"]), (table, summary["outages"], summary["call_failures"]))
            with tarfile.open(os.path.join(out, "files.tar.gz")) as tf:
                names = tf.getnames()
                report = tf.extractfile("report.md").read().decode()
            self.assertIn(row, report)
            self.assertFalse(any("outcomes" in n for n in names), "the journal's outcome lines are held with it")
            held = [f for f in man["files"] if "outcomes" in f["path"]]
            self.assertEqual([f["status"] for f in held], ["held"])

    def test_fetch_missing(self):
        with tempfile.TemporaryDirectory() as t:
            be = store.LocalBackend(os.path.join(t, "remote"))
            os.makedirs(os.path.join(t, "remote", "runs"))
            with self.assertRaises(store.Refused):
                store.fetch_batch(be, "nope", os.path.join(t, "d"))


class Motion(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            lib = os.path.join(t, "library")
            os.makedirs(lib)
            for i in range(3):
                with open(os.path.join(lib, f"walk_s{i}.npz"), "wb") as f:
                    f.write(b"PK\x03\x04\x00" + bytes([i]) * 64)
            out = os.path.join(t, "stage")
            man = store.pack_motion(lib, out, scrubber(), machine="test")
            self.assertEqual(len(man["files"]), 3)
            be = store.LocalBackend(os.path.join(t, "remote"))
            be.publish("assets", os.path.join(out, "motion"), "motion", "motion")
            dest = os.path.join(t, "outputs", "library")
            self.assertEqual(store.fetch_motion(be, dest), (3, 0))
            self.assertEqual(store.fetch_motion(be, dest), (0, 3))
            with open(os.path.join(dest, "walk_s1.npz"), "wb") as f:
                f.write(b"different")
            with self.assertRaises(store.Refused):
                store.fetch_motion(be, dest)
            self.assertEqual(store.fetch_motion(be, dest, force=True), (1, 2))


class Gate(unittest.TestCase):
    """Publishing to Hugging Face refuses unless both the flag and the local switch are on."""

    class FakeApi:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def f(*a, **k):
                self.calls.append(name)
            return f

    def cfg(self, enabled):
        return {"publish_enabled": enabled, "backends": {"hf": {"namespace": "someone"}},
                "repos": {"runs": "r"}, "_local_config": "/nonexistent"}

    def test_refuses_while_off(self):
        with tempfile.TemporaryDirectory() as t:
            for enabled, flag in ((False, False), (False, True), (True, False)):
                api = self.FakeApi()
                be = store.HFBackend(self.cfg(enabled), yes_publish=flag, api=api)
                with self.assertRaises(store.Refused):
                    be.publish("runs", t, "batches/x/y", "m")
                self.assertEqual(api.calls, [], (enabled, flag))
            api = self.FakeApi()
            be = store.HFBackend(self.cfg(True), yes_publish=True, api=api)
            be.publish("runs", t, "batches/x/y", "m")
            self.assertEqual(api.calls, ["create_repo", "upload_folder"])
            for i in range(250):
                write(t, f"many/f{i:03}.npz", "x")
            api = self.FakeApi()
            be = store.HFBackend(self.cfg(True), yes_publish=True, api=api, op=lambda **k: k)
            be.publish("assets", os.path.join(t, "many"), "motion/raw", "m")
            self.assertEqual(api.calls, ["create_repo", "create_commit", "create_commit", "create_commit"])

    def test_cli_refuses_without_importing(self):
        poison = types.ModuleType("huggingface_hub")

        def boom(name):
            raise AssertionError("huggingface_hub touched while publishing is off")
        poison.__getattr__ = boom
        saved = sys.modules.get("huggingface_hub")
        sys.modules["huggingface_hub"] = poison
        old = os.environ.get("STORE_CONFIG")
        try:
            with tempfile.TemporaryDirectory() as t:
                os.environ["STORE_CONFIG"] = os.path.join(t, "absent.json")   # no local switch
                src = os.path.join(t, "l9")
                fake_batch(src)
                err = io.StringIO()
                with redirect_stderr(err), redirect_stdout(io.StringIO()):
                    rc = store.main(["publish", "batch", src, "--backend", "hf", "--yes-publish"])
                self.assertEqual(rc, 2)
                self.assertIn("switched off", err.getvalue())
                with open(os.path.join(t, "on.json"), "w") as f:
                    json.dump({"publish_enabled": True}, f)
                os.environ["STORE_CONFIG"] = os.path.join(t, "on.json")
                err = io.StringIO()
                with redirect_stderr(err), redirect_stdout(io.StringIO()):
                    rc = store.main(["publish", "batch", src, "--backend", "hf"])
                self.assertEqual(rc, 2)
                self.assertIn("--yes-publish", err.getvalue())
        finally:
            if old is None:
                os.environ.pop("STORE_CONFIG", None)
            else:
                os.environ["STORE_CONFIG"] = old
            if saved is None:
                sys.modules.pop("huggingface_hub", None)
            else:
                sys.modules["huggingface_hub"] = saved

    def test_repo_config_cannot_switch_on(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "repo.json")
            with open(p, "w") as f:
                json.dump({"publish_enabled": True}, f)
            with self.assertRaises(store.Refused):
                store.load_config(repo_config=p, local_config=os.path.join(t, "none.json"))

    def test_shipped_config_is_off(self):
        cfg = store.load_config(local_config="/nonexistent/config.json")
        self.assertFalse(cfg["publish_enabled"])


class Manifest(unittest.TestCase):
    def test_scan_fake_home(self):
        with tempfile.TemporaryDirectory() as home:
            co = os.path.join(home, "dev", "slop-trials")
            fake_batch(os.path.join(co, ".local", "living", "trials", "b1"))
            write(co, ".local/living/trials/b1.log", "log")
            write(co, ".local/living/trials/neo4j.env", "NEO4J_AUTH=x/y")
            write(co, ".local/living/trials/wasm/m.wasm", "x")
            write(co, ".local/living/journal/verify-trial-b1-x-r1/A.jsonl", "{}")
            write(co, ".local/living/journal/minds-1/A.jsonl", "{}")
            write(co, ".local/living/verify/minds-1/log.txt", "ok")
            write(co, ".local/living/verify/build-knowledge/x", "x")
            write(co, ".local/living/target-resident-island/x", "x")
            write(home, "playtest-4/FEEDBACK.md", "x")
            write(home, "kimodo-test/library/walk_s0.npz", "x")
            write(home, "clip-handoff/town.tar.gz", "x")
            nt = os.path.join(home, "dev", "slop-art-online")
            write(nt, ".local/living/trials/b9/batch.json", "{}")
            cfg = {"never_touch": {"spark": [nt]}, "never_touch_names": []}
            items = store.scan(home=home, cfg=cfg, machine="spark")
            kinds = {}
            for it in items:
                kinds.setdefault(it["kind"], []).append(it)
            self.assertEqual([i["unit"] for i in kinds["trial-batch"] if i["note"] != "runner log"], ["b1"])
            for k in ("secret", "trial-build", "journal-copy", "mind-journal", "verify-evidence", "build-output",
                      "play-session", "motion-raw", "clip-handoff", "never-touch"):
                self.assertIn(k, kinds, k)
            self.assertIsNone(kinds["never-touch"][0]["bytes"])
            self.assertFalse(any("b9" == i["unit"] for i in items))
            md = store.manifest_markdown(items, "spark", "now")
            self.assertIn("| `trial-batch` |", md)
            est = store.layout(items)
            self.assertEqual(est["runs"]["batches"]["units"], 1)


if __name__ == "__main__":
    unittest.main()
