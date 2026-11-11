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
import re
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
        out, acc = self.run_text("see experience_ada.txt and ADA_NOTES")
        self.assertEqual(out, "see experience_player.txt and PLAYER_NOTES")
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
        for name, why in ((".env", "secret path"), ("neo4j.env", "secret path"), ("cli.toml", "secret path"),
                          ("id_ed25519", "secret path"), ("._summary.json", "macOS"), (".DS_Store", "macOS")):
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
            self.assertEqual(st["FEEDBACK.md"], "excluded")              # outside session/: held by rule
            self.assertEqual(st["ffprof/prefs.js"], "refused")
            self.assertEqual(st["ffprof/extensions.json"], "refused")
            self.assertEqual(st["shot.png"], "excluded")
            self.assertEqual(st["diagnosis/REPORT.md"], "excluded")
            self.assertEqual(st["session/journal/Linnet_Abbot.jsonl"], "held")
            # the redaction itself, on the report's text
            rep = s.scrub_text("First “hi there” at 07:59. Ada typed “wassup mate”.", store.Findings())
            self.assertNotIn("hi there", rep)
            self.assertNotIn("wassup", rep)
            self.assertTrue("[owner line]" in rep or "[line dropped" in rep)
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
            self.assertIn("Evening.", j)             # the talk entry stays, its prompt redacted
            self.assertTrue(any("think" in d["where"] for d in s2.dropped))   # its reply repeated the line
            self.assertNotIn("/home/adaq", j)
            self.assertNotIn("192.168.7.42", j)
            self.assertNotIn("Quillfeather", j)
            self.assertEqual(s2.scrub_text("diagnosis/journal_talk_wassup mate.txt", store.Findings()),
                             "diagnosis/journal_talk_[owner line].txt")
            self.assertEqual(s2.publish_path("diagnosis/journal_talk_wassup mate.txt"),
                             "diagnosis/journal_talk_owner-line.txt")
            self.assertEqual(s2.publish_path("diagnosis/journal_reply_hi_there.txt"),
                             "diagnosis/journal_reply_owner-line.txt")
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
            for secret in (MISTRAL, NEO_PW, "/home/adaq", "Quillfeather", "dummy-local-only", HOST, "/home/a…"):
                self.assertNotIn(secret.encode(), blob, secret)
            be = store.LocalBackend(os.path.join(t, "remote"))
            be.publish("runs", out, store.unit_path("batch", "l9", "test"), "batch l9")
            dest = os.path.join(t, "fetched")
            path = store.fetch_batch(be, "l9", dest, unpack=True)
            self.assertEqual(path, "batches/test/l9")
            be.publish("runs", out, store.unit_path("session", "pt9", "test"), "session pt9")
            self.assertEqual(store.fetch_batch(be, "pt9", os.path.join(t, "fs"), top="sessions"), "sessions/test/pt9")
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


class Token(unittest.TestCase):
    """The store token comes from ~/.config/slop-store/hf_token only, and never reaches output."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.saved = {k: os.environ.get(k) for k in ("HOME", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "STORE_CONFIG",
                                                     "HF_HUB_DISABLE_IMPLICIT_TOKEN", "HF_TOKEN_PATH")}
        os.environ["HOME"] = self.home
        self.file_tok = "hf" + "_" + _fake(_ALNUM, 34)
        self.env_tok = "hf" + "_" + _fake(_ALNUM, 34)
        os.environ["HF_TOKEN"] = self.env_tok
        write(self.home, ".cache/huggingface/token", "hf" + "_" + _fake(_ALNUM, 34))
        self.tp = write(self.home, ".config/slop-store/hf_token", self.file_tok + "\n")
        os.chmod(self.tp, 0o600)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sys.modules.pop("huggingface_hub", None)
        self.tmp.cleanup()

    def test_only_source(self):
        self.assertEqual(store.read_token(), self.file_tok)
        os.chmod(self.tp, 0o644)
        with self.assertRaises(store.Refused):
            store.read_token()
        os.remove(self.tp)
        with self.assertRaises(store.Refused):     # HF_TOKEN and the hf cache are not used
            store.read_token()

    def test_never_in_output(self):
        seen = {}
        tok = self.file_tok

        class FakeHfApi:
            def __init__(self, token=None):
                seen["token"] = token

            def create_repo(self, *a, **k):
                raise RuntimeError(f"401 for token {tok} at /api/repos/create")

        fake = types.ModuleType("huggingface_hub")
        fake.HfApi = FakeHfApi
        sys.modules["huggingface_hub"] = fake
        conf = write(self.home, ".config/slop-store/config.json",
                     json.dumps({"publish_enabled": True, "backends": {"hf": {"namespace": "someone"}}}))
        os.environ["STORE_CONFIG"] = conf
        src = os.path.join(self.home, "l9")
        fake_batch(src)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = store.main(["publish", "batch", src, "--backend", "hf", "--yes-publish"])
        self.assertEqual(rc, 2)
        self.assertEqual(seen["token"], tok)                 # the file's token, passed explicitly
        self.assertNotIn("HF_TOKEN", os.environ)              # no other token left for the library
        self.assertEqual(os.environ.get("HF_HUB_DISABLE_IMPLICIT_TOKEN"), "1")
        for text in (out.getvalue(), err.getvalue()):
            self.assertNotIn(tok, text)
            self.assertNotIn(self.env_tok, text)
        self.assertIn("[redacted:token]", err.getvalue())
        # and the scrubber treats it as a known secret
        idn = store.Identity.from_runtime({"never_touch": {}, "never_touch_names": []}, "test")
        self.assertIn(tok, idn.secrets)


class Echoes(unittest.TestCase):
    LINES = {"ssssssssshi", "wassup", "hi", "I come from the northern hills"}

    def find(self, text):
        return store.EchoMatcher(self.LINES).find(text)

    def test_found(self):
        for text in ("demeanour: babbles nonsense ('sssshi', 'wassup'), does not flee",
                     "The stranger who said 'hi' to the crowd killed Cuth",
                     "Said hi, then set on my mother before the whole crowd.",
                     "He only babbled wassup and would not leave",
                     "he said he comes from the northern hills, far off"):
            self.assertTrue(self.find(text), text)

    def test_not_found(self):
        for text in ('{"say": "Hi! Are you new here? I\'m Bram Fenner"}', "Hi there, friend, welcome",
                     "the hill path north", "shining high above", "I greet her and sound her out"):
            self.assertFalse(self.find(text), text)


class SessionDrop(unittest.TestCase):
    def test_drop_and_learn(self):
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "playing character #26\n")
            talk = "# You and a stranger (#26)\n\n# What you are answering\na stranger: “wassup”"
            write(t, "session/journal/Mercy.jsonl",
                  journal_entry("Mercy", "talk", talk, '{"say": "Don\'t \'wassup\' me."}') + "\n" +
                  journal_entry("Mercy", "think", "the square at noon", '{"thought": "a quiet day"}') + "\n" +
                  journal_entry("Mercy", "consolidate", "notes", '{"demeanour": "babbles (\'wasssup\')"}') + "\n")
            mem = ("# Who you are (Ada)\n(played by a person: who they are shows only in what they do)\n"
                   "- [1188] day 1 09:15 You said to a child: “a line nobody heard” {someone=#11}")
            write(t, "session/journal/Ada.jsonl",
                  journal_entry("Ada", "internalize", mem, '{"edges": [{"props": {"what": "a line nobody heard"}}]}') + "\n")
            write(t, "session/run/authority.jsonl", json.dumps({"subject": 9, "text": "A stranger said: “wassup” {someone=#26}"}) + "\n" +
                  json.dumps({"subject": 9, "text": "Bram waved"}) + "\n")
            write(t, "session/run/notes.txt", "first line\nhe kept saying wassup\nlast line\n")
            write(t, "session/run/index.html", "<p>&ldquo;wassup&rdquo;</p>")
            write(t, "FEEDBACK.md", "mine")
            s = scrubber({"model_exchanges": "include", "owner_notes": "hold"}, kind="play-session")
            rows, totals, data = store.scrub_source(t, s, keep_data=True)
            self.assertIn("a line nobody heard", s.owner_lines)
            st = {r["path"]: r["status"] for r in rows}
            self.assertEqual(st["FEEDBACK.md"], "excluded")
            self.assertEqual(st["session/run/index.html"], "excluded")
            m = data["session/journal/Mercy.jsonl"].decode().splitlines()
            self.assertEqual(len(m), 1)                       # the talk and the consolidation dropped
            self.assertIn("a quiet day", m[0])
            self.assertNotIn("nobody heard", "".join(v.decode() for v in data.values()))
            r = data["session/run/authority.jsonl"].decode().splitlines()
            self.assertEqual(len(r), 1)
            self.assertIn("Bram waved", r[0])
            self.assertNotIn("wassup", data["session/run/notes.txt"].decode())
            self.assertIn("first line", data["session/run/notes.txt"].decode())
            self.assertGreaterEqual(len(s.dropped), 4)
            for d in s.dropped:
                self.assertNotIn("wassup", d["why"])
                self.assertNotIn("nobody heard", d["why"])
            man = {"files": [{"path": p, "status": v} for p, v in st.items()]}
            store.check_publishable(man, s)                   # held-by-owner files do not block


class Gates(unittest.TestCase):
    def test_models(self):
        cfg = store.load_config(local_config="/nonexistent/config.json")
        store.check_models({"models": {"zai-glm-5-3-flash": 3, "deepseek-v4-1-flash-1017": 1, "fake-trials": 2}}, cfg)
        for bad in ("mistral-small-latest", "gpt-6-luna", "ministral-8b-latest", "something-new"):
            with self.assertRaises(store.Refused):
                store.check_models({"models": {"zai-glm-5-3-flash": 3, bad: 1}}, cfg)

    def test_complete(self):
        with tempfile.TemporaryDirectory() as t:
            fake_batch(t)
            store.check_batch_complete(t)
            os.remove(os.path.join(t, "life-iter11-r2", "summary.json"))
            with self.assertRaises(store.Refused):
                store.check_batch_complete(t)

    def test_sessions_held(self):
        old = os.environ.get("STORE_CONFIG")
        with tempfile.TemporaryDirectory() as t:
            conf = write(t, "c.json", json.dumps({"publish_enabled": True}))
            os.environ["STORE_CONFIG"] = conf
            try:
                err = io.StringIO()
                with redirect_stderr(err), redirect_stdout(io.StringIO()):
                    rc = store.main(["publish", "session", t, "--backend", "local", "--root", t])
                self.assertEqual(rc, 2)
                self.assertIn("publish_sessions", err.getvalue())
            finally:
                if old is None:
                    os.environ.pop("STORE_CONFIG", None)
                else:
                    os.environ["STORE_CONFIG"] = old


class ManyBatches(unittest.TestCase):
    def test_deterministic_pack(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "l9")
            fake_batch(src)
            dec = {"model_exchanges": "include"}
            store.pack_batch(src, os.path.join(t, "a"), scrubber(dec), machine="test")
            store.pack_batch(src, os.path.join(t, "b"), scrubber(dec), machine="test")
            for n in store.PACK_FILES:
                if n == "MANIFEST.json":
                    continue
                with open(os.path.join(t, "a", n), "rb") as f1, open(os.path.join(t, "b", n), "rb") as f2:
                    self.assertEqual(f1.read(), f2.read(), n)

    def test_publish_batches_in_few_commits(self):
        with tempfile.TemporaryDirectory() as t:
            srcs = []
            for name in ("ba", "bb", "bc", "bd"):
                src = os.path.join(t, "src", name)
                fake_batch(src)
                srcs.append(src)
            # bd called an unverified model: held
            write(srcs[3], "life-iter11-r1/journal/Arlen.jsonl",
                  json.dumps({"actor": "Arlen", "purpose": "think", "model": "mistral-small-latest",
                              "request": {"messages": []}, "reply": "{}"}) + "\n")
            lst = write(t, "list.txt", "\n".join(srcs) + "\n")
            calls = []

            class Api:
                def create_repo(self, *a, **k):
                    calls.append("create_repo")

                def create_commit(self, **k):
                    calls.append(("commit", sorted({o["path_in_repo"].split("/")[2] for o in k["operations"]})))
                    return "url"
            cfg = store.load_config(local_config="/nonexistent/config.json")
            cfg.update({"publish_enabled": True})
            cfg["backends"] = {"hf": {"namespace": "someone"}}
            cfg["decisions"] = dict(cfg["decisions"], model_exchanges="include")
            be = store.HFBackend(cfg, yes_publish=True, api=Api(), op=lambda **k: k)
            old = store.make_backend
            store.make_backend = lambda *a, **k: be
            idn_old = store.Identity.from_runtime
            store.Identity.from_runtime = classmethod(lambda cls, *a, **k: ident())
            try:
                args = types.SimpleNamespace(list=lst, stage=os.path.join(t, "stage"), per_commit=2,
                                             backend="hf", yes_publish=True, root=None)
                with redirect_stdout(io.StringIO()) as out:
                    store.cmd_publish_batches(args, cfg, "test")
            finally:
                store.make_backend = old
                store.Identity.from_runtime = idn_old
            commits = [c for c in calls if c != "create_repo"]
            self.assertEqual(commits, [("commit", ["ba", "bb"]), ("commit", ["bc"])])
            self.assertIn("held bd", out.getvalue())
            self.assertIn("mistral-small-latest", out.getvalue())

    def test_packed_must_match(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "l9")
            fake_batch(src)
            cfg = store.load_config(local_config="/nonexistent/config.json")
            out = os.path.join(t, "p")
            store.pack_batch(src, out, scrubber({"model_exchanges": "include"}), machine="test")
            store.verify_pack(out, src, cfg, "test")
            other = os.path.join(t, "l10")
            fake_batch(other)
            with self.assertRaises(store.Refused):
                store.verify_pack(out, other, cfg, "test")
            with self.assertRaises(store.Refused):
                store.verify_pack(out, src, cfg, "laptop")


class SessionAllowList(unittest.TestCase):
    """A play session publishes session/journal, session/run, the scene's skills.rhai and a README
    that describes the scene; everything else is held and listed with its reason."""

    def test_allow_list(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "playtest-9")
            write(src, "session/run/client.log", "playing character #26\n")
            write(src, "session/run/mind.log", "INFO started\n")
            write(src, "session/run/created_utc", "2026-11-11T12:00:00Z\n")
            write(src, "session/run/installed_script.txt", "script\n")
            write(src, "session/journal/Bram.jsonl", journal_entry("Bram", "think", "the square", '{"thought": "quiet"}') + "\n")
            write(src, "session/journal/system/abc.txt", "You are a person.")
            write(src, "session/skills.rhai", "// sight 48 m\n")
            write(src, "session/README.md", "# A small town\n\n17 residents of Brackenford, all minds, on the island seed.\n")
            write(src, "session/CHECKLIST.md", "- [ ] owner arrives\n")
            write(src, "session/notes.md", "scene notes\n")
            write(src, "session/run/screen.mp4", "\x00\x00video")
            write(src, "session/run/blob.bin2", "\x00\x01")
            write(src, "session/journal/extra/thing.jsonl", "{}\n")
            write(src, "diagnosis/REPORT.md", "what the owner meant\n")
            write(src, "review/check.py", "print(1)\n")
            write(src, "FEEDBACK.md", "mine\n")
            write(src, "report/index.html", "<p>page</p>")
            cfg = store.load_config(local_config="/nonexistent/config.json")
            s = store.Scrubber(ident(), cfg=cfg, machine="test", kind="play-session")
            rows, totals, data = store.scrub_source(src, s, keep_data=True)
            st = {r["path"]: (r["status"], r["reason"]) for r in rows}
            published = {"session/run/client.log", "session/run/mind.log", "session/run/created_utc",
                         "session/run/installed_script.txt", "session/journal/Bram.jsonl",
                         "session/journal/system/abc.txt", "session/skills.rhai", "session/README.md"}
            self.assertEqual(set(data), published)
            for path in ("session/CHECKLIST.md", "session/notes.md", "session/run/screen.mp4", "session/run/blob.bin2",
                         "session/journal/extra/thing.jsonl", "diagnosis/REPORT.md", "review/check.py",
                         "FEEDBACK.md", "report/index.html"):
                self.assertEqual(st[path][0], "excluded", path)
                self.assertTrue(st[path][1].startswith("held"), (path, st[path][1]))
            # a README about the owner is held
            for text in ("You arrive on the square.\n", "The owner wants to test greetings.\n",
                         "Ada plays a newcomer.\n", "Run play.sh as adaq\n"):
                write(src, "session/README.md", text)
                s = store.Scrubber(ident(), cfg=cfg, machine="test", kind="play-session")
                rows, _, data = store.scrub_source(src, s, keep_data=True)
                self.assertNotIn("session/README.md", data, text)
                r = [x for x in rows if x["path"] == "session/README.md"][0]
                self.assertTrue(r["reason"].startswith("held: the README"), r["reason"])
            # the unit still publishes, and its manifest lists what was held, with reasons
            out = os.path.join(t, "packed")
            man = store.pack_session(src, out, store.Scrubber(ident(), cfg=cfg, machine="test", kind="play-session"),
                                     machine="test")
            store.check_publishable(man, s)
            self.assertEqual(man["unit"], "session")
            held = {h["path"]: h["reason"] for h in man["held"]}
            for path in ("diagnosis/REPORT.md", "FEEDBACK.md", "session/CHECKLIST.md", "session/README.md"):
                self.assertIn(path, held)


class Cards(unittest.TestCase):
    """The runs card declares every column the packer writes, with a type (the Hub's viewer
    otherwise types a column that is null throughout the first file as null)."""

    def test_runs_card_features(self):
        card = os.path.join(os.path.dirname(os.path.abspath(store.__file__)), "store_cards", "runs.md")
        with open(card, encoding="utf-8") as f:
            head = f.read().split("---")[1]
        declared, conf = {}, None
        configs = re.findall(r"- config_name: (\w+)\n  data_files", head)
        for line in head.splitlines():
            m = re.match(r"- config_name: (\w+)", line)
            if m:
                conf = m.group(1)
            m = re.match(r"\s+- name: (\w+)", line)
            if m and conf:
                declared.setdefault(conf, []).append(m.group(1))
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "l9")
            fake_batch(src)
            out = os.path.join(t, "p")
            store.pack_batch(src, out, scrubber({"model_exchanges": "include"}), machine="test")
            for conf in ("instances", "calls", "rows", "prompts"):
                with gzip.open(os.path.join(out, f"{conf}.jsonl.gz"), "rt") as f:
                    cols = set(json.loads(f.readline()))
                self.assertEqual(set(declared.get(conf, [])), cols, conf)
                if "session_" + conf in configs:
                    self.assertEqual(set(declared.get("session_" + conf, [])), cols, "session_" + conf)
        # every table the card configures has declared types
        self.assertEqual(set(configs), set(declared))
        self.assertNotIn("DRAFT", head)


class ReviewOutputs(unittest.TestCase):
    """Everything the scrubber writes, review files and stdout included, passes the same redaction
    as published content: no planted owner name, login or line anywhere, in contents or names."""

    PLANTED = (r"(?i)\bada\b", r"(?i)quillfeather", r"(?i)adaq", r"(?i)wassup mate", r"(?i)hi there",
               r"(?i)a line nobody heard", re.escape(EMAIL))

    def test_all_outputs_clean(self):
        with tempfile.TemporaryDirectory() as t:
            # a source outside home whose path holds the login
            src = os.path.join(t, "adaq-sessions", "playtest-9")
            fake_session(src)
            write(src, "diagnosis/experience_ada.txt", "Ada's rows\n")
            write(src, "diagnosis/journal_linnet_talk_wassup mate.txt", "excerpt\n")
            write(src, "report/report.json", json.dumps({"lines": [{"text": "wassup mate", "at_ms": 7}],
                                                         "player": "Ada"}))
            write(src, "commands.jsonl", json.dumps({"at_ms": 123, "cmd": "say", "text": "wassup mate"}) + "\n" +
                  json.dumps({"at_ms": 124, "cmd": "move", "to": [1, 2]}) + "\n")
            mem = ("# Who you are (Ada)\n(played by a person: who they are shows only in what they do)\n"
                   "- [1188] day 1 09:15 You said to a child: “a line nobody heard” {someone=#11}")
            write(src, "session/journal/Ada.jsonl", journal_entry("Ada", "internalize", mem, "{}") + "\n")
            old = store.Identity.from_runtime
            store.Identity.from_runtime = classmethod(lambda cls, *a, **k: ident())
            outs = []
            try:
                for args in (["scrub", "--dry-run", src, "--kind", "play-session", "--report", os.path.join(t, "r1")],
                             ["scrub", "--write", os.path.join(t, "w1"), src, "--kind", "play-session"]):
                    buf = io.StringIO()
                    with redirect_stdout(buf), redirect_stderr(buf):
                        self.assertEqual(store.main(args), 0)
                    outs.append(("stdout " + args[1], buf.getvalue()))
            finally:
                store.Identity.from_runtime = old
            for d in ("r1", "w1"):
                for root, _, names in os.walk(os.path.join(t, d)):
                    for n in names:
                        p = os.path.join(root, n)
                        rel = os.path.relpath(p, t)
                        outs.append(("name " + rel, rel))
                        with open(p, encoding="utf-8", errors="replace") as f:
                            outs.append((rel, f.read()))
            for where, text in outs:
                for pat in self.PLANTED:
                    self.assertIsNone(re.search(pat, text), f"{pat} in {where}")
            # the header names the source by a label, the login redacted
            with open(os.path.join(t, "r1", "report.md")) as f:
                head = f.readline()
            self.assertIn("[user]-sessions/playtest-9", head)
            # review files were scrubbed in the same pass and are not in the published tree
            rv = os.path.join(t, "w1", "review")
            self.assertTrue(os.path.exists(os.path.join(rv, "report", "report.json")))
            self.assertTrue(os.path.exists(os.path.join(rv, "commands.jsonl")))
            self.assertFalse(os.path.exists(os.path.join(t, "w1", "tree", "commands.jsonl")))
            with open(os.path.join(rv, "commands.jsonl")) as f:
                rows = [json.loads(l) for l in f]
            self.assertEqual(rows[0], {"at_ms": 123, "cmd": "say", "text": "[owner line]"})   # (d) kept
            self.assertEqual(rows[1]["to"], [1, 2])

    def test_review_files_held_from_packs(self):
        with tempfile.TemporaryDirectory() as t:
            fake_session(t)
            write(t, "report/report.json", "{}")
            write(t, "commands.jsonl", "{}\n")
            cfg = store.load_config(local_config="/nonexistent/config.json")
            s = store.Scrubber(ident(), cfg=cfg, machine="test", kind="play-session")
            man = store.pack_session(t, os.path.join(t, "_p"), s, machine="test")
            held = {h["path"]: h["reason"] for h in man["held"]}
            self.assertIn("report/report.json", held)
            self.assertIn("commands.jsonl", held)
            self.assertIn("review only", held["commands.jsonl"])
            with tarfile.open(os.path.join(t, "_p", "files.tar.gz")) as tf:
                self.assertFalse([m for m in tf.getnames() if m.endswith(("report.json", "commands.jsonl"))])


class ShortLinesAndTemplates(unittest.TestCase):
    """A four-word owner line made of common words does not echo into "can see it"; system prompt
    templates and installed scripts are touched only by an exact quoted substitution."""

    def test_common_words_and_templates(self):
        self.assertFalse(store.EchoMatcher({"I can see it"}).find("Yes, you can see it from the wall."))
        self.assertTrue(store.EchoMatcher({"the brass lantern flickers"}).find("a brass lantern flickering low"))
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "playing character #26\n")
            talk = "# You and a stranger (#26)\n\n# What you are answering\na stranger: “I can see it”"
            sysline = "When you can see it, act on what is in front of you."
            write(t, "session/journal/Bram.jsonl",
                  json.dumps({"actor": "Bram", "purpose": "talk", "model": "m", "reply": '{"say": "Yes, you can see it from the wall."}',
                              "request": {"messages": [{"role": "system", "content": sysline},
                                                       {"role": "user", "content": talk}]}}, ensure_ascii=False) + "\n")
            write(t, "session/journal/system/abc.txt", sysline + "\n")
            write(t, "session/journal/system/sub.txt", "Earlier someone said “I can see it”.\n")
            write(t, "session/run/installed_source.rhai", "// if you can see it, strike\nlet x = 1;\n")
            write(t, "session/skills.rhai", "// you can see it at 48 m\n")
            write(t, "session/run/mind.log", "INFO Bram: they can see it now\n")
            s = scrubber({"model_exchanges": "include"}, kind="play-session")
            rows, totals, data = store.scrub_source(t, s, keep_data=True)
            self.assertEqual(s.owner_lines, {"I can see it"})
            self.assertEqual(data["session/journal/system/abc.txt"].decode(), sysline + "\n")
            self.assertEqual(data["session/run/installed_source.rhai"].decode(), "// if you can see it, strike\nlet x = 1;\n")
            self.assertEqual(data["session/skills.rhai"].decode(), "// you can see it at 48 m\n")
            self.assertEqual(data["session/run/mind.log"].decode(), "INFO Bram: they can see it now\n")
            # an exact quoted substitution into a template is still caught
            self.assertEqual(data["session/journal/system/sub.txt"].decode(), "Earlier someone said “[owner line]”.\n")
            j = json.loads(data["session/journal/Bram.jsonl"].decode())
            self.assertEqual(j["request"]["messages"][0]["content"], sysline)      # inline system prompt untouched
            self.assertIn("you can see it from the wall", j["reply"])               # the reply is kept
            self.assertNotIn("“I can see it”", j["request"]["messages"][1]["content"])
            self.assertEqual(s.dropped, [])


class CommandRows(unittest.TestCase):
    def test_say_rows_kept_with_time(self):
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "playing character #26\n")
            write(t, "session/run/events.jsonl",
                  json.dumps({"at_ms": 5, "kind": "say", "text": "hi there"}) + "\n" +
                  json.dumps({"at_ms": 6, "kind": "press", "key": "F"}) + "\n" +
                  json.dumps({"at_ms": 7, "kind": "reply", "reducer": "human_say", "args": {"text": "hi there"}}) + "\n")
            s = scrubber(kind="play-session")
            rows, totals, data = store.scrub_source(t, s, keep_data=True)
            self.assertIn("hi there", s.owner_lines)          # learned from the client's own events
            out = [json.loads(l) for l in data["session/run/events.jsonl"].decode().splitlines()]
            self.assertEqual([r["at_ms"] for r in out], [5, 6, 7])
            self.assertEqual(out[0]["text"], "[owner line]")
            self.assertEqual(out[2]["args"]["text"], "[owner line]")
            self.assertEqual(out[1]["key"], "F")
            self.assertTrue(all(d.get("action", "").startswith("kept") for d in s.dropped))
            man = store.pack_session(t, os.path.join(t, "_p"), scrubber(kind="play-session"), machine="test")
            self.assertTrue(man["dropped"] and all(d["action"].startswith("kept") for d in man["dropped"]))


class SelfGivenNames(unittest.TestCase):
    """A name the player gives themself once is the player's name: replaced by "Player" wherever
    residents repeat it, in text, memory graphs and file names, with no flag."""

    def session(self, t, intro):
        write(t, "session/run/client.log", "2026-11-11T15:15:35.0Z INFO playing character #26\n"
                                           "2026-11-11T15:19:20.0Z INFO quit\n")
        talk = f"# You and a stranger (#26)\n\n# What you are answering\na stranger: “{intro}”"
        write(t, "session/journal/Bram.jsonl", "\n".join([
            journal_entry("Bram", "talk", talk, '{"say": "Well met."}'),
            journal_entry("Bram", "think", "- [1201] day 1 09:20 The stranger called «Zorbin» waved {Zorbin=#26}\n"
                                           "- Zorbin (#26) [Person]", '{"thought": "Zorbin seems kind"}'),
            journal_entry("Bram", "consolidate", "notes",
                          json.dumps({"nodes": [{"key": "person:26", "labels": ["Person"], "name": None,
                                                 "props": {"known_name": "Zorbin"}}],
                                      "relations": [{"id": 26, "trust": 5, "note": "goes by ZORBIN"}]})),
        ]) + "\n")
        write(t, "session/journal/Mercy.jsonl",
              journal_entry("Mercy", "think", "I heard of zorbin from Bram.", '{"thought": "the zorbin fellow"}') + "\n")
        write(t, "session/journal/Zorbin.jsonl", journal_entry("Zorbin", "internalize", "x", "{}") + "\n")
        write(t, "session/run/notes_about_zorbin.log", "Zorbin arrived\n")

    def check(self, t, s):
        rows, totals, data = store.scrub_source(t, s, keep_data=True)
        self.assertIn("Zorbin", s.self_names)
        blob = "".join(v.decode() for v in data.values())
        names = " ".join(s.publish_path(r) for r in data)
        self.assertIsNone(re.search(r"(?i)zorbin", blob), blob[:400])
        self.assertIsNone(re.search(r"(?i)zorbin", names), names)
        self.assertIn("Player", blob)
        self.assertIn("session/journal/Player.jsonl", names)
        self.assertIn("notes_about_player.log", names)
        return blob

    def test_intro_forms(self):
        for intro in ("I'm Zorbin", "hi, call me Zorbin!", "my name is zorbin", "Name's Zorbin.", "Hello, I am Zorbin"):
            with tempfile.TemporaryDirectory() as t:
                self.session(t, intro)
                self.check(t, scrubber({"model_exchanges": "include"}, kind="play-session"))

    def test_from_graph_only(self):
        """Named only in a memory graph (known_name about person:26), never in a typed line."""
        with tempfile.TemporaryDirectory() as t:
            self.session(t, "hello there friend")
            s = scrubber({"model_exchanges": "include"}, kind="play-session")
            self.check(t, s)

    def test_known_name_alone(self):
        """The only evidence is a memory graph node about person:26 with known_name, inside a
        model reply (JSON text); the name is then replaced in other journals and file names."""
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "playing character #26\n")
            write(t, "session/journal/Bram.jsonl", journal_entry("Bram", "consolidate", "notes", json.dumps(
                {"nodes": [{"key": "person:26", "labels": ["Person"], "props": {"known_name": "Velkas"}}]})) + "\n")
            write(t, "session/journal/Mercy.jsonl", journal_entry("Mercy", "think", "Velkas is near.", "{}") + "\n")
            write(t, "session/run/velkas-notes.log", "VELKAS left\n")
            s = scrubber({"model_exchanges": "include"}, kind="play-session")
            rows, _, data = store.scrub_source(t, s, keep_data=True)
            self.assertEqual(s.self_names, {"Velkas"})
            blob = "".join(v.decode() for v in data.values())
            self.assertNotIn("elkas", blob.lower())
            self.assertIn("PLAYER left", blob)
            self.assertIn("session/run/player-notes.log", [s.publish_path(r) for r in data])

    def test_states_are_not_names(self):
        s = scrubber(kind="play-session")
        for line in ("I'm fine", "I'm lost", "I am new here", "call me later", "it's cold"):
            s.self_names.clear()
            s.owner_lines = {line}
            s.finish_learning()
            self.assertEqual(s.self_names, set(), line)

    def test_player_name_option(self):
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "playing character #26\n")
            write(t, "session/run/mind.log", "Quix and Brummel walked by\n")
            s = scrubber(kind="play-session", player_names=["Quix", "Brummel"])
            _, _, data = store.scrub_source(t, s, keep_data=True)
            self.assertEqual(data["session/run/mind.log"].decode(), "Player and Player walked by\n")
            old = store.Identity.from_runtime
            store.Identity.from_runtime = classmethod(lambda cls, *a, **k: ident())
            try:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(store.main(["scrub", "--write", os.path.join(t, "w"), t, "--kind", "play-session",
                                                 "--player-name", "Quix", "--player-name", "Brummel"]), 0)
            finally:
                store.Identity.from_runtime = old
            with open(os.path.join(t, "w", "tree", "session", "run", "mind.log")) as f:
                self.assertEqual(f.read(), "Player and Player walked by\n")

    def test_said_rows_limited_to_the_played_span(self):
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "2026-11-11T15:15:35.0Z INFO playing character #26\n"
                                               "2026-11-11T15:19:20.0Z INFO quit\n")
            inside = store._iso_ms("2026-11-11T15:16:05Z")
            after = store._iso_ms("2026-11-11T15:20:15Z")
            write(t, "session/run/authority.jsonl",
                  json.dumps({"subject": 26, "at_ms": inside, "text": "You said to a child: “typed by the owner”"}) + "\n" +
                  json.dumps({"subject": 26, "at_ms": after, "text": "You said to a stranger: “said by the AI mind”"}) + "\n")
            s = scrubber(kind="play-session")
            store.scrub_source(t, s)
            self.assertIn("typed by the owner", s.owner_lines)
            self.assertNotIn("said by the AI mind", s.owner_lines)


class TrailingPunctuation(unittest.TestCase):
    def test_short_line_without_its_punctuation(self):
        with tempfile.TemporaryDirectory() as t:
            write(t, "session/run/client.log", "playing character #26\n")
            talk = "# You and a stranger (#26)\n\n# What you are answering\na stranger: “where am i ?”"
            write(t, "session/journal/Bram.jsonl", "\n".join([
                journal_entry("Bram", "talk", talk, '{"say": "Brackenford."}'),
                journal_entry("Bram", "think", "He asked “where am I?” and then “Where  am i”.", '{"thought": "lost"}'),
            ]) + "\n")
            write(t, "session/run/mind.log", "INFO Bram: the stranger wonders where am I\n")
            s = scrubber({"model_exchanges": "include"}, kind="play-session")
            _, _, data = store.scrub_source(t, s, keep_data=True)
            self.assertEqual(s.owner_lines, {"where am i ?"})
            blob = "".join(v.decode() for v in data.values())
            self.assertIsNone(re.search(r"(?i)where\s+am\s+i", blob), blob)


class CredentialFiles(unittest.TestCase):
    """Credential files are refused by name, never opened (an open() spy proves it), and listed
    as held with the reason."""

    def test_never_opened(self):
        import builtins
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "playtest-9")
            write(src, "session/run/client.log", "playing character #26\n")
            planted = [write(src, rel, "hf" + "_" + _fake(_ALNUM, 34) + "\n") for rel in
                       ("play3-state/tokens/player.token", "play3-state/tokens/README.txt", "session/run/a.key",
                        ".env", "session/.env.local", "secrets/x.json", "session/run/id_ed25519",
                        "session/run/admin.token", "creds.pem")]
            # a tarball holding a token: the member must not be extracted
            with tarfile.open(os.path.join(src, "state.tgz"), "w:gz") as tf:
                tf.add(planted[0], arcname="tokens/player.token")
                tf.add(os.path.join(src, "session/run/client.log"), arcname="session/run/client.log")
            opened, extracted = [], []
            real_open, real_extract = builtins.open, tarfile.TarFile.extractfile

            def spy_open(f, *a, **k):
                opened.append(os.path.abspath(str(f)) if not isinstance(f, int) else f)
                return real_open(f, *a, **k)

            def spy_extract(self, member):
                extracted.append(getattr(member, "name", member))
                return real_extract(self, member)
            builtins.open, tarfile.TarFile.extractfile = spy_open, spy_extract
            try:
                s = scrubber(kind="play-session")
                rows, totals, data = store.scrub_source(src, s, keep_data=True)
                man = store.pack_session(src, os.path.join(t, "packed"), scrubber(kind="play-session"), machine="test")
            finally:
                builtins.open, tarfile.TarFile.extractfile = real_open, real_extract
            for p in planted:
                self.assertNotIn(os.path.abspath(p), opened, p)
            self.assertNotIn("tokens/player.token", extracted)
            st = {r["path"]: (r["status"], r["reason"]) for r in rows}
            for rel in ("play3-state/tokens/player.token", "play3-state/tokens/README.txt", ".env",
                        "session/run/admin.token", "state.tgz!tokens/player.token"):
                self.assertEqual(st[rel], ("refused", "secret path, not read"), rel)
            held = {h["path"]: h["reason"] for h in man["held"]}
            self.assertEqual(held.get("play3-state/tokens/player.token"), "secret path, not read")
            self.assertEqual(totals.counts.get("hf-token"), None)     # nothing was read to redact


if __name__ == "__main__":
    unittest.main()
