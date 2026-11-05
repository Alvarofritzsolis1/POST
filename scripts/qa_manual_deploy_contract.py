"""Guardrails for manual-only production deployment (standard library only)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
manual = (ROOT / ".github/workflows/galant-deploy-manual.yml").read_text(encoding="utf-8")
updater = (ROOT / "scripts/update-preview.sh").read_text(encoding="utf-8")

# The ordinary CI cannot deploy; a manual workflow reuses all its tests.
assert "  workflow_call:" in ci, "CI must be callable from the manual workflow"
assert not re.search(r"(?m)^  deploy-vps:", ci), "Push/PR CI cannot contain a deploy job"
assert not re.search(r"(?m)^  desplegar:", ci), "Push/PR CI cannot contain a deploy job"

header = manual.split("\npermissions:", 1)[0]
assert re.search(r"(?m)^on:\s*$", header), "Manual workflow has no on: section"
assert re.search(r"(?m)^  workflow_dispatch:\s*$", header), "Only a manual event is allowed"
assert not re.search(r"(?m)^  (push|pull_request|schedule|workflow_call):", header), (
    "A production deployment must never run automatically"
)
assert "uses: ./.github/workflows/ci.yml" in manual
assert "needs: pruebas" in manual
assert "github.ref == 'refs/heads/main'" in manual
assert "github.event_name == 'workflow_dispatch'" in manual
assert "environment:" in manual and "GALANT-VPS" in manual
assert "cancel-in-progress: false" in manual
assert "StrictHostKeyChecking=yes" in manual and "IdentitiesOnly=yes" in manual
assert "VPS_SSH_KEY" in manual and "VPS_KNOWN_HOSTS" in manual
assert 'git ls-remote origin refs/heads/main' in manual
assert "GALANT_DEPLOY_DIR=/opt/galant-post bash" in manual

for control in ("backup-preview.sh", "verify-restore-preview.sh",
                "migrate-db --verified-backup-sha256", 'trap rollback EXIT',
                'wait_for_health "$target_ref"'):
    assert control in updater, f"Missing deployment safety control: {control}"

print("GALANT: manual-only deployment contract, CI, SSH and rollback safeguards verified.")
