"""Regression: a preview may never silently refer to a different source than issue.

Private workbooks are modeled with two immutable synthetic revisions. A live
published source is deliberately different from the active editing draft.
"""
from __future__ import annotations

import io
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.javiera_excel import LayoutError
from app.javiera_models import JavieraDossier
from app.javiera_workbook import digest, pack
from app.javiera_workbook_models import JavieraWorkbook, JavieraWorkbookHead
from app.models import User
from test_control_api import env
from test_javiera_full_workflow import _dossier
from test_javiera_workbook import prepare


def _two_workbooks(env, monkeypatch, tmp_path):
    client, sessions, headers, current = prepare(env, monkeypatch, tmp_path)
    dossier_id = _dossier(client, headers)
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        head = db.get(JavieraWorkbookHead, user.org_id)
        current_wb = db.get(JavieraWorkbook, head.current_id)
        original = db.get(JavieraWorkbook, current_wb.parent_id)
        assert original and original.id != current_wb.id
        head.publications = {"labor_contract": original.id}
        head.published_id = original.id
        db.commit()
        published_sha, draft_sha = original.sha256, current_wb.sha256
    return client, sessions, headers, dossier_id, published_sha, draft_sha


def test_document_preview_uses_exact_published_source_and_issue_rejects_change(
        env, monkeypatch, tmp_path):
    from app import javiera_api as api
    client, sessions, headers, dossier_id, published_sha, draft_sha = _two_workbooks(
        env, monkeypatch, tmp_path
    )
    seen = []
    monkeypatch.setattr(api, "evaluated", lambda *args, **kwargs: [{
        "code": "labor_contract", "can_preview": True, "can_issue": True,
        "missing_fields": [], "blocking_errors": [], "status": "LISTO_PARA_EMITIR",
    }])

    def record_pdf(raw, code, data, org, folder, preview, reference=None):
        seen.append({"sha": digest(raw), "preview": preview, "code": code})
        return b"%PDF-1.4\n%%EOF\n", {"cache_hit": False, "elapsed_ms": 4}

    monkeypatch.setattr(api, "cached_pdf", record_pdf)
    response = client.post("/api/v1/javiera/preview", headers=headers,
                           json={"dossier_id": dossier_id, "code": "labor_contract"})
    assert response.status_code == 200, response.text
    assert seen == [{"sha": published_sha, "preview": True, "code": "labor_contract"}]
    assert response.headers["x-galant-source-type"] == "workbook"
    assert response.headers["x-galant-preview-draft"] == "false"
    old_fingerprint = response.headers["x-galant-preview-fingerprint"]
    assert len(old_fingerprint) == 64
    preflight = client.post("/api/v1/javiera/eligibility/preflight", headers=headers,
        json={"dossier_id": dossier_id, "codes": ["labor_contract"]})
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["documents"][0]["preview_fingerprint"] == old_fingerprint
    assert seen[-1]["sha"] == published_sha

    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        head = db.get(JavieraWorkbookHead, user.org_id)
        latest = db.get(JavieraWorkbook, head.current_id)
        assert latest.sha256 == draft_sha
        head.publications = {"labor_contract": latest.id}
        head.published_id = latest.id
        db.commit()
    denied = client.post("/api/v1/javiera/issue", headers=headers, json={
        "dossier_id": dossier_id, "code": "labor_contract",
        "expected_preview_fingerprint": old_fingerprint,
    })
    assert denied.status_code == 409, denied.text
    assert "cambió" in str(denied.json()).lower()
    # Nothing was emitted, and no PDF generator ran on the changed template.
    assert len(seen) == 2


def test_source_fingerprint_changes_when_dossier_data_or_source_changes(env, monkeypatch, tmp_path):
    from app.javiera_api import document_source_fingerprint
    client, sessions, headers, dossier_id, _, _ = _two_workbooks(
        env, monkeypatch, tmp_path
    )
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        head = db.get(JavieraWorkbookHead, user.org_id)
        source = db.get(JavieraWorkbook, head.publications["labor_contract"])
        record = db.get(JavieraDossier, dossier_id)
        first = document_source_fingerprint("workbook", source, record)
        record.data = {**record.data, "role": "OTRO CARGO QA"}
        second = document_source_fingerprint("workbook", source, record)
        assert first != second


def test_revisions_cannot_replace_original_images(env, monkeypatch, tmp_path):
    from app.javiera_workbook_api import write_revision
    client, sessions, headers, current = prepare(env, monkeypatch, tmp_path)
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        current_wb = db.get(JavieraWorkbook, current["id"])
        original = open(current_wb.path, "rb").read()
        with ZipFile(io.BytesIO(original)) as archive:
            media_path = next(x for x in archive.namelist() if x.startswith("xl/media/"))
            altered = pack(archive, {media_path: archive.read(media_path) + b"corrupt-qa"})
        with pytest.raises(LayoutError, match="imagen|Imagen"):
            write_revision(db, user, altered, "Editar imagen sin autorización",
                           current_wb.revision, current_wb)
