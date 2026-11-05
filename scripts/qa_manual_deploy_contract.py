"""Guardrails for safe GALANT manual + version-gated auto deployments."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
manual = (ROOT / ".github/workflows/galant-deploy-manual.yml").read_text(encoding="utf-8")
auto = (ROOT / ".github/workflows/deploy-preview.yml").read_text(encoding="utf-8")
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

# El camino automático NO debe modificar el contrato del botón manual.
# Solo una nueva versión de main (incremento de backend/frontend/lockfile)
# puede acceder a secretos de GALANT-VPS, una vez que la CI reutilizable termina.
auto_header = auto.split("\npermissions:", 1)[0]
assert re.search(r"(?m)^on:\s*$", auto_header)
assert re.search(r"(?m)^  push:\s*$", auto_header)
assert re.search(r"(?m)^    branches: \[main\]$", auto_header)
assert not re.search(r"(?m)^  (pull_request|workflow_run|workflow_dispatch|schedule):", auto_header)
assert "needs: comprobar_version" in auto
assert "scripts/check_auto_release.py" in auto
assert "github.event.before" in auto and "github.sha" in auto
assert "uses: ./.github/workflows/ci.yml" in auto
assert "needs: [comprobar_version, pruebas]" in auto
assert "needs.comprobar_version.outputs.deploy == 'true'" in auto
assert "needs.pruebas.result == 'success'" in auto
assert "github.ref == 'refs/heads/main'" in auto
assert "environment:" in auto and "name: GALANT-VPS" in auto
assert "group: galant-post-vps-preview" in auto and "cancel-in-progress: false" in auto
assert "VPS_SSH_KEY" in auto and "VPS_KNOWN_HOSTS" in auto
assert "StrictHostKeyChecking=yes" in auto and "IdentitiesOnly=yes" in auto
assert "git ls-remote origin refs/heads/main" in auto
assert "scripts/update-preview.sh" in auto
assert "GALANT_DEPLOY_DIR=/opt/galant-post bash" in auto
assert "POST_AUTODEPLOY_ENABLED" not in auto
assert "POST_DEPLOY_SSH_KEY" not in auto

print("GALANT: despliegue manual intacto y automático con versión/CI/SSH/rollback verificados.")
