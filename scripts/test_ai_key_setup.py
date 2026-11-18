"""Synthetic tests: provisioning never leaks/rotates a Fernet key."""
import base64
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("ensure-ai-key.py")
NAME = "AI_CREDENTIAL_ENCRYPTION_KEY"


def call(env_file: Path):
    env = dict(os.environ)
    env.pop(NAME, None)
    return subprocess.run([sys.executable, str(SCRIPT), str(env_file)],
                          text=True, capture_output=True, env=env, check=False)


class SecretSetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="galant-ai-bootstrap-")
        self.addCleanup(self.temp.cleanup)
        self.env_file = Path(self.temp.name) / ".env.preview"
        self.env_file.write_text("APP_SECRET=synthetic-only\nPOSTGRES_PASSWORD=fake\n", encoding="utf-8")
        self.env_file.chmod(0o600)

    def secret(self):
        matches = re.findall(r"^AI_CREDENTIAL_ENCRYPTION_KEY=(.+)$",
                             self.env_file.read_text(), re.MULTILINE)
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(base64.urlsafe_b64decode(matches[0])), 32)
        return matches[0]

    def test_generates_once_without_printing_it(self):
        first = call(self.env_file)
        self.assertEqual(first.returncode, 0, first.stderr)
        value = self.secret()
        self.assertNotIn(value, first.stdout + first.stderr)
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o600)
        second = call(self.env_file)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.secret(), value)
        self.assertIn("conservada", second.stdout)

    def test_blank_entry_is_fixed_and_other_values_preserved(self):
        self.env_file.write_text(self.env_file.read_text() + NAME + "=\n", encoding="utf-8")
        self.assertEqual(call(self.env_file).returncode, 0)
        self.assertEqual(self.env_file.read_text().count("POSTGRES_PASSWORD=fake"), 1)
        self.secret()

    def test_invalid_existing_key_is_never_rotated(self):
        self.env_file.write_text(self.env_file.read_text() + NAME + "=invalid-existing-key\n")
        old = self.env_file.read_text()
        result = call(self.env_file)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.env_file.read_text(), old)
        self.assertNotIn("invalid-existing-key", result.stdout + result.stderr)

    def test_duplicate_definitions_are_rejected(self):
        self.env_file.write_text(self.env_file.read_text() + NAME + "=\n" + NAME + "=\n")
        self.assertNotEqual(call(self.env_file).returncode, 0)

    def test_simultaneous_runs_keep_one_key(self):
        env = dict(os.environ)
        env.pop(NAME, None)
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), str(self.env_file)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=env) for _ in range(4)]
        for proc in procs:
            stdout, stderr = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0, stderr)
        self.secret()

    def test_missing_env_fails_closed(self):
        self.env_file.unlink()
        self.assertNotEqual(call(self.env_file).returncode, 0)


if __name__ == "__main__":
    unittest.main()
