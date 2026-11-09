"""Version 17: guided XLSX installation and strictly scoped, real human review."""
from sqlalchemy import func, select
from app.config import settings
from app.javiera_models import JavieraExcelLayout, JavieraReviewerAuthorization, JavieraSignoff
from app.models import User
from app.network_schemas import AccountInput
from app.ops_models import Contractor, Worker, WorkerAssignment
from app.security import hash_password
from test_control_api import env, login
from test_javiera_excel_layout import sample_xlsx

BASE="/api/v1/javiera/v17"


def _import(client, headers, raw=None):
    source=raw or sample_xlsx()
    return client.post(BASE+"/library/import", headers=headers, files={
        "file":("GALANT_PLANTILLAS_SINTETICAS.xlsx",source,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_guided_ten_sheet_import_is_private_idempotent_and_documentary_only(env, tmp_path, monkeypatch):
    client, sessions=env
    monkeypatch.setenv("DOCUMENT_DIR",str(tmp_path))
    settings.cache_clear()
    admin=login(client,"a@example.cl")
    with sessions() as db:
        before={cls.__name__:db.scalar(select(func.count(cls.id))) for cls in (
            Worker, Contractor, WorkerAssignment)}
    result=_import(client,admin)
    assert result.status_code==200,result.text
    assert result.json()["status"]=="imported_as_draft"
    assert result.json()["created"]==10
    library=client.get(BASE+"/library").json()
    assert library["imported"]==10
    assert library["published"]==0
    assert library["awaiting_review"]==10
    assert len(library["documents"])==10
    assert all(not x["ready"] for x in library["documents"])
    assert any(x["sheet"]=="REGLAMENTO INTERNO" for x in library["documents"])
    repeated=_import(client,admin)
    assert repeated.status_code==200,repeated.text
    assert repeated.json()["status"]=="already_imported"
    assert repeated.json()["created"]==0
    with sessions() as db:
        after={cls.__name__:db.scalar(select(func.count(cls.id))) for cls in (
            Worker, Contractor, WorkerAssignment)}
        assert db.scalar(select(func.count(JavieraExcelLayout.id)))==10
    assert before==after
    # An entirely different organization cannot see source layouts or files.
    login(client,"outside@example.cl")
    foreign=client.get(BASE+"/library")
    assert foreign.status_code==200
    assert foreign.json()["imported"]==0


def test_document_reviewer_can_sign_and_publish_but_has_no_operational_access(env, tmp_path, monkeypatch):
    client,sessions=env
    monkeypatch.setenv("DOCUMENT_DIR",str(tmp_path))
    settings.cache_clear()
    author=login(client,"a@example.cl")
    assert _import(client,author).status_code==200
    with sessions.begin() as db:
        admin=db.scalar(select(User).where(User.email=="b@example.cl"))
        reviewer=User(org_id=admin.org_id,email="reviewer17@example.cl",
                      role="doc_reviewer",password_hash=hash_password("password-valid-2026"))
        db.add(reviewer)
        db.flush()
        reviewer_id=reviewer.id
    admin=login(client,"b@example.cl")
    grant=client.put("/api/v1/javiera/admin/reviews/reviewers",headers=admin,json={
        "user_id":reviewer_id,"specialty":"prevencion",
        "designation":"Persona responsable de validación de prevención de riesgos.",
        "active":True})
    assert grant.status_code==200,grant.text
    reviewer_header=login(client,"reviewer17@example.cl")
    assert client.get("/api/v1/ops/sites").status_code==403
    assert client.get(BASE+"/library").status_code==403
    assert client.get("/api/v1/javiera/v166/history").status_code==403
    queue=client.get(BASE+"/review/queue")
    assert queue.status_code==200,queue.text
    q=queue.json()
    assert q["authorized"]
    assert q["scopes"]==["prevencion"]
    assert len(q["documents"])==6
    layout=next(x for x in q["documents"] if x["code"]=="internal_rules_receipt")
    assert layout["sheet"]=="REGLAMENTO INTERNO"
    first=client.post(BASE+"/review/layouts/"+layout["id"]+"/decision",
        headers=reviewer_header,json={
            "expected_revision":layout["revision"],"verdict":"approved",
            "checklist":{key:True for key in layout["checks"]},
            "comments":"He revisado el contenido de ejemplo y las referencias normativas de la hoja original."
        })
    assert first.status_code==200,first.text
    assert first.json()["published"]
    with sessions() as db:
        doc=db.get(JavieraExcelLayout,layout["id"])
        assert doc.state=="approved"
        assert doc.reviewer_id==reviewer_id
        signed=db.scalar(select(JavieraSignoff).where(JavieraSignoff.resource_id==layout["id"]))
        assert signed and signed.reviewer_id==reviewer_id
    repeat=client.post(BASE+"/review/layouts/"+layout["id"]+"/decision",
        headers=reviewer_header,json={
            "expected_revision":layout["revision"],"verdict":"approved",
            "checklist":{key:True for key in layout["checks"]},
            "comments":"Se ha vuelto a revisar la misma versión del documento preventivo."
        })
    assert repeat.status_code==409
    assert client.get(BASE+"/review/queue").json()["documents"]
    labor=next(r for r in client.get(BASE+"/review/queue").json()["documents"]
               if r["code"]=="pts_receipt")
    assert labor["specialty"]=="prevencion"


def test_reviewer_cannot_approve_own_work_even_when_granted(env, tmp_path, monkeypatch):
    client,sessions=env
    monkeypatch.setenv("DOCUMENT_DIR",str(tmp_path))
    settings.cache_clear()
    writer=login(client,"a@example.cl")
    assert _import(client,writer).status_code==200
    with sessions.begin() as db:
        author=db.scalar(select(User).where(User.email=="a@example.cl"))
        admin=db.scalar(select(User).where(User.email=="b@example.cl"))
        db.add(JavieraReviewerAuthorization(
            org_id=author.org_id,user_id=author.id,delegated_by=admin.id,
            specialty="prevencion",designation="Control profesional de versión documental.",
            active=True))
    own=client.get(BASE+"/review/queue")
    assert own.status_code==200
    assert own.json()["authorized"]
    assert own.json()["documents"]==[]
    with sessions() as db:
        layout=db.scalar(select(JavieraExcelLayout).where(
            JavieraExcelLayout.code=="internal_rules_receipt"))
    response=client.post(BASE+"/review/layouts/"+layout.id+"/decision",
        headers=writer,json={
            "expected_revision":layout.revision,"verdict":"approved",
            "checklist":{k:True for k in (
                "riesgos_reales_de_la_actividad","matriz_y_medidas_de_control",
                "puestos_sustancias_y_entorno","eventos_capacitaciones_y_epp",
                "coherencia_con_ds44")},
            "comments":"Revisión de la hoja original con todos los criterios preventivos declarados."})
    assert response.status_code==403


def test_reviewer_account_has_no_site_assignment_requirement():
    data=AccountInput(name="Profesional documental",email="revisor17@example.cl",
                      role="doc_reviewer",site_ids=[],enabled=True)
    assert data.site_ids==[]
