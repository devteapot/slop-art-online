"""Run with python3 -B; requires no server or credentials."""
import importlib.util
import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scenes


class SceneCredentialsTest(unittest.TestCase):
    def test_command_redacts_credentials_before_writing(self):
        cli_token = "synthetic-cli-credential"
        bearer = "synthetic-bearer-credential"
        identity_token = "synthetic-identity-credential"
        jwt = "eyJfake.payload.signature"
        run = "core-redaction"
        with tempfile.TemporaryDirectory() as directory, patch.object(scenes, "BASE", Path(directory)):
            output = Path(directory) / run
            output.mkdir()
            (output / "state.json").write_text(json.dumps({"db": "verify-" + run, "published": True}))
            scene = scenes.Scene(run, "fake")
            reply = subprocess.CompletedProcess(
                [], 0, f"Your auth token is {cli_token}\nrows intact\n",
                f"Authorization: Bearer {bearer}\nCLI diagnostic {jwt}",
            )
            with patch.object(scenes.subprocess, "run", return_value=reply) as command:
                scene.command("call", json.dumps({"token": identity_token}))
            self.assertIn(identity_token, command.call_args.args[0][-1])
            action = json.loads(scene.log.read_text())
            self.assertIn("rows intact", action["stdout"])
            self.assertEqual(json.loads(action["args"][1])["token"], "<redacted>")
            self.assertIn("<redacted>", action["stderr"])
            for path in output.iterdir():
                for secret in (cli_token, bearer, identity_token, jwt):
                    self.assertNotIn(secret, path.read_text(), path.name)


class RunCredentialsTest(unittest.TestCase):
    def test_legacy_tokens_move_out_of_evidence_and_cleanup_removes_them(self):
        harness = scenes.ROOT / ".agents/skills/verify/scripts/verify.py"
        spec = importlib.util.spec_from_file_location("verify_harness", harness)
        verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkout"
            private = Path(directory) / "state"
            run = "core-redaction"
            with patch.object(verify, "ROOT", root), patch.dict("os.environ", XDG_STATE_HOME=str(private)):
                evidence = verify.run_dir(run) / "state.json"
                tokens = {"token": "synthetic-player", "token2": "synthetic-bystander"}
                evidence.write_text(json.dumps({"run": run, "db": "verify-" + run, "published": False, **tokens}))
                state = verify.load(run)
                self.assertEqual({key: state[key] for key in tokens}, tokens)
                self.assertEqual(verify.load(run), state)
                credential_file, = private.rglob("*.json")
                self.assertEqual(stat.S_IMODE(credential_file.stat().st_mode), 0o600)
                self.assertTrue(all(secret not in evidence.read_text() for secret in tokens.values()))
                verify.cleanup(type("Args", (), {"run": run})())
                self.assertFalse(credential_file.exists())
                self.assertTrue(evidence.exists())


if __name__ == "__main__":
    unittest.main()
