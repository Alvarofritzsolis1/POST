"""Pruebas de autorización para actualizar GALANT sin intervención manual."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

GATE = Path(__file__).resolve().parent / "check_auto_release.py"


def command(*args, cwd: Path):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def versions(root: Path, v: str):
    files = {
        "apps/backend/app/version.py": f'VERSION = "{v}"\n',
        "apps/frontend/package.json": json.dumps({"version": v}),
        "apps/frontend/package-lock.json": json.dumps({"version": v, "packages": {"": {"version": v}}}),
    }
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class AutoDeployGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="galant-release-gate-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        command("git", "init", "-q", "-b", "main", cwd=self.root)
        command("git", "config", "user.email", "qa@example.test", cwd=self.root)
        command("git", "config", "user.name", "GALANT QA", cwd=self.root)
        versions(self.root, "15.0.4-rc1")
        self.base = self.commit()
        self.output = self.root / "github-output.txt"

    def commit(self):
        command("git", "add", ".", cwd=self.root)
        command("git", "commit", "-qm", "test commit", cwd=self.root)
        return command("git", "rev-parse", "HEAD", cwd=self.root)

    def gate(self, head):
        return subprocess.run(
            [sys.executable, str(GATE), "--base", self.base, "--head", head,
             "--github-output", str(self.output)],
            cwd=self.root, text=True, capture_output=True, check=False
        )

    def test_new_synchronized_version_deploys(self):
        versions(self.root, "15.0.5-rc1")
        head = self.commit()
        result = self.gate(head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deploy=true", self.output.read_text())
        self.assertIn("15.0.4-rc1 -> 15.0.5-rc1", result.stdout)

    def test_other_main_pushes_do_not_deploy(self):
        (self.root / "README.md").write_text("Only documentation\n")
        head = self.commit()
        result = self.gate(head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deploy=false", self.output.read_text())

    def test_incomplete_version_is_rejected(self):
        (self.root / "apps/backend/app/version.py").write_text('VERSION = "15.0.5-rc1"\n')
        head = self.commit()
        result = self.gate(head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Versión incompleta", result.stderr)
        self.assertFalse(self.output.exists())

    def test_mismatched_version_is_rejected(self):
        versions(self.root, "15.0.5-rc1")
        (self.root / "apps/frontend/package-lock.json").write_text(
            json.dumps({"version": "15.0.6-rc1", "packages": {"": {"version": "15.0.6-rc1"}}})
        )
        head = self.commit()
        result = self.gate(head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no coinciden", result.stderr)

    def test_older_release_is_rejected(self):
        versions(self.root, "15.0.3-rc1")
        head = self.commit()
        result = self.gate(head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no creciente", result.stderr)

    def test_untrusted_target_sha_is_rejected(self):
        versions(self.root, "15.0.5-rc1")
        self.commit()
        result = self.gate("0" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD no coincide", result.stderr)


if __name__ == "__main__":
    unittest.main()
