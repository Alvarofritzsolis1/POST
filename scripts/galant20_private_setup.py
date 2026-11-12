"""One-time, encrypted GALANT 20 initialization over the existing SSH channel.

Used only from the temporary operations branch. Never print source bytes,
private keys, organization names, account identifiers, or personal fields.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from zipfile import ZipFile


EXPECTED_COMMIT = "a393a073e27849bf65e42a505f0e775bd9b77d60"
EXPECTED_SOURCE = "4f063b135d5e9c0d7f9806b57d1cd340bd2ecac78fed77345ffa7ccabbead292"
REPO = Path("/opt/galant-post")
COMPOSE = ["docker", "compose", "--env-file", ".env.preview", "-f", "docker-compose.preview.yml"]


def run(args, **kwargs):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        raise RuntimeError("La operación privada no se completó: " + args[0])
    return result.stdout


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError("Se requiere el usuario de despliegue autorizado")
    os.chdir(REPO)
    if run(["git", "rev-parse", "HEAD"]).decode().strip() != EXPECTED_COMMIT:
        raise RuntimeError("El checkout no corresponde al despliegue verificado")
    data = json.loads(base64.b64decode(sys.argv[1], validate=True))
    operation = data["operation"]
    ident = data["transfer_id"]
    if not re.fullmatch(r"[0-9a-f]{32}", ident):
        raise RuntimeError("Identificador de transferencia inválido")
    parent = REPO / ".galant20-private-transfer"
    if parent.is_symlink():
        raise RuntimeError("Directorio privado inválido")
    parent.mkdir(mode=0o700, exist_ok=True)
    folder = parent / ident
    if folder.is_symlink():
        raise RuntimeError("Transferencia privada inválida")
    if operation == "prepare_transfer":
        folder.mkdir(mode=0o700)
        run(["openssl", "req", "-x509", "-newkey", "rsa:3072", "-sha256", "-days", "1", "-nodes",
             "-keyout", str(folder / "key.pem"), "-out", str(folder / "certificate.pem"),
             "-subj", "/CN=GALANT-one-time-private-transfer"])
        print(json.dumps({"transfer_id": ident, "public_certificate": base64.b64encode(
            (folder / "certificate.pem").read_bytes()).decode()}))
        return
    if not folder.is_dir() or time.time() - folder.stat().st_ctime > 3600:
        raise RuntimeError("La transferencia no existe o ha expirado")
    if operation == "append_transfer":
        index, total = int(data["chunk_index"]), int(data["total_parts"])
        blob = data["chunk"]
        if not (1 <= total <= 10 and 0 <= index < total and 0 < len(blob) <= 46000):
            raise RuntimeError("Parte de transferencia inválida")
        base64.b64decode(blob, validate=True)
        part = folder / ("part-%02d" % index)
        if part.exists():
            if part.read_text() != blob:
                raise RuntimeError("La parte recibida no coincide con la almacenada")
        else:
            with part.open("x") as stream:
                stream.write(blob)
        print(json.dumps({"part": index + 1, "total_parts": total, "stored": True}))
        return
    if operation != "complete_transfer":
        raise RuntimeError("Operación desconocida")
    total = int(data["total_parts"])
    if not 1 <= total <= 10:
        raise RuntimeError("Número de partes inválido")
    encrypted = b"".join(base64.b64decode((folder / ("part-%02d" % n)).read_text(), validate=True)
                         for n in range(total))
    sealed = folder / "source.sealed"
    sealed.write_bytes(encrypted)
    plain = run(["openssl", "cms", "-decrypt", "-binary", "-inform", "DER", "-in", str(sealed),
                 "-inkey", str(folder / "key.pem")])
    with ZipFile(io.BytesIO(plain)) as bundle:
        if set(bundle.namelist()) != {"source.xlsx", "manifest.json"}:
            raise RuntimeError("Contenido de transferencia inesperado")
        if sum(entry.file_size for entry in bundle.infolist()) > 500000:
            raise RuntimeError("Transferencia demasiado grande")
        raw = bundle.read("source.xlsx")
        manifest = json.loads(bundle.read("manifest.json"))
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SOURCE:
        raise RuntimeError("El archivo no coincide con el adjunto autorizado")
    for field in ("org_id", "author_id"):
        if not re.fullmatch(r"[0-9a-f-]{36}", manifest[field]):
            raise RuntimeError("Alcance de organización inválido")
    backup = Path("/opt/galant-post-backups/20261112T112744Z")
    run(["sha256sum", "--check", "--status", "SHA256SUMS"], cwd=backup)
    source = folder / "source.xlsx"
    source.write_bytes(raw)
    target = "/tmp/galant20-source-" + ident + ".xlsx"
    writer = "import os,sys; fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); f=os.fdopen(fd,'wb'); f.write(sys.stdin.buffer.read()); f.close()"
    run(COMPOSE + ["exec", "-T", "api", "python", "-c", writer, target], input=raw)
    source_code = SETUP_CODE.encode()
    try:
        output = run(COMPOSE + ["exec", "-T", "api", "python", "-", target,
                               manifest["org_id"], manifest["author_id"], EXPECTED_SOURCE,
                               EXPECTED_COMMIT], input=source_code)
        receipt = json.loads(output)
    finally:
        run(COMPOSE + ["exec", "-T", "api", "rm", "-f", target])
        source.unlink(missing_ok=True)
    shutil.rmtree(folder)
    print(json.dumps(receipt, ensure_ascii=False))


SETUP_CODE = r'''
import hashlib, json, sys
from pathlib import Path
from sqlalchemy import select, func
from app.db import SessionLocal
from app.models import User
from app.ops_models import Worksite, Contractor, Worker, WorkerAssignment
from app.javiera_models import JavieraDossier, JavieraIssue, JavieraHistory
from app.javiera_v166_models import JavieraLocalDossier
from app.javiera_workbook_api import (head_for, write_revision, reset_plan, execute_reset,
                                     ResetInput, unarchived)
from app.javiera_workbook import repair_master, clean_master, inventory
from app.version import VERSION, SOURCE_COMMIT
assert VERSION == '20.0.0-rc1' and SOURCE_COMMIT == sys.argv[5]
raw = Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(raw).hexdigest() == sys.argv[4]
repaired, notes = repair_master(raw)
clean = clean_master(repaired)
before_inventory, after_inventory = inventory(raw), inventory(clean)
assert before_inventory['media'] == after_inventory['media'], 'Cambió un recurso gráfico'
with SessionLocal() as db:
    user = db.get(User, sys.argv[3])
    assert user and user.org_id == sys.argv[2] and user.role == 'admin' and user.enabled
    active_orgs = set(db.scalars(select(JavieraDossier.org_id)).all()) | set(
        db.scalars(select(JavieraLocalDossier.org_id)).all())
    assert active_orgs == {user.org_id}, 'El alcance ya no es una sola organización con documentos Javiera'
    head = head_for(db, user.org_id)
    assert head is None or not head.current_id, 'El maestro ya está configurado; no sobrescribir'
    models = (Worksite, Contractor, Worker, WorkerAssignment, User)
    before = {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(
        model.org_id == user.org_id)) for model in models}
    original = write_revision(db, user, raw,
        'Importación automatizada del adjunto por despliegue GALANT 20; sin aprobación profesional', 0)
    current = write_revision(db, user, clean,
        'Datos de ejemplo vaciados; original conservado. Inicialización del despliegue solicitado',
        original.revision, original)
    plan = reset_plan(db, user)
    receipt = execute_reset(ResetInput(plan_sha256=plan['sha256'],
        reason='Reinicio inicial de Javiera solicitado con GALANT 20; archivo reversible y respaldo verificado'), user, db)
    after = {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(
        model.org_id == user.org_id)) for model in models}
    assert before == after, 'Cambió un conteo operativo durante la inicialización'
    active = {kind: db.scalar(select(func.count()).select_from(model).where(
        model.org_id == user.org_id, unarchived(model, user.org_id, kind)))
        for kind, model in [('dossier', JavieraDossier), ('issue', JavieraIssue), ('history', JavieraHistory)]}
    assert not any(active.values())
    head = head_for(db, user.org_id)
    assert not head.publications and head.legacy_disabled
    print(json.dumps({'version': VERSION, 'commit': SOURCE_COMMIT, 'source_sha256': original.sha256,
        'clean_sha256': current.sha256, 'sheets': len(after_inventory['sheets']),
        'formulas': after_inventory['formula_count'], 'media_preserved': len(after_inventory['media']),
        'active': active, 'published': len(head.publications), 'legacy_disabled': head.legacy_disabled,
        'operational_counts_preserved': before == after, 'reset_backup_sha256': receipt['backup_sha256'],
        'archived': receipt['archived'], 'reversible': receipt['reversible']}))
'''


if __name__ == "__main__":
    main()
