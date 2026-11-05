"""Deterministic regression test for PostgreSQL temporary initdb readiness."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / "wait-for-final-postgres.sh"


class TestPostgresInitRace(unittest.TestCase):
    def run_scenario(self, scenario):
        with tempfile.TemporaryDirectory(prefix="galant-pg-ready-") as tmp:
            root = Path(tmp)
            docker = root / "docker"
            docker.write_text(
                """#!/usr/bin/env bash
set -Eeuo pipefail
case "$1" in
  exec)
    case "$3" in
      sh)
        echo "pid-check" >> "$EVENTS"
        if [[ "$SCENARIO" == "never_ready" ]]; then exit 1; fi
        count=0
        [[ -e "$COUNTER" ]] && count="$(cat "$COUNTER")"
        count=$((count + 1))
        printf '%s' "$count" > "$COUNTER"
        # Simula un postmaster transitorio que responde a pg_isready,
        # pero cuyo PID 1 sigue siendo el entrypoint de initdb.
        if (( count < 3 )); then exit 1; fi
        exit 0
        ;;
      psql)
        echo "sql-check" >> "$EVENTS"
        printf '1\\n'
        exit 0
        ;;
    esac
    ;;
  logs)
    echo "fake diagnostic" >&2
    exit 0
    ;;
esac
echo "Unexpected docker command: $*" >&2
exit 90
""", encoding="utf-8"
            )
            sleep = root / "sleep"
            sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for p in (docker, sleep):
                p.chmod(0o700)
            env = {
                **os.environ,
                "PATH": str(root) + os.pathsep + os.environ.get("PATH", ""),
                "SCENARIO": scenario,
                "EVENTS": str(root / "events"),
                "COUNTER": str(root / "counter"),
            }
            result = subprocess.run(
                ["bash", str(SCRIPT), "fake-restore-db", "galant_restore", "galant_restore"],
                env=env, capture_output=True, text=True, timeout=10, check=False
            )
            events = (root / "events").read_text(encoding="utf-8").splitlines()
            return result, events

    def test_does_not_accept_temporary_init_server(self):
        result, events = self.run_scenario("ready_later")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["pid-check", "pid-check", "pid-check", "sql-check"])
        self.assertIn("definitivo listo", result.stdout)

    def test_aborts_without_final_server(self):
        result, events = self.run_scenario("never_ready")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(events, ["pid-check"] * 60)
        self.assertIn("se cancela", result.stderr)


if __name__ == "__main__":
    unittest.main()
