"""Pruebas INE: archivo inmutable, permisos mensuales y auditoría admin."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.network_models import NetworkMember, NetworkMembership
from app.ops_models import Worksite
from app.security import hash_password
from app import ine_api

PASSWORD = "INE-Synthetic-2026!"
ROOT = "/api/v1/ine"


def fake_source():
    wb = Workbook()
    ws = wb.active
    ws.title = "1"
    ws["C1"], ws["I1"] = "Enero ", "POR TERMINAR"
    for col, name in zip("CDEFGHI", ["Obras", "CCT", "CESP", "IND", "TH", "TM", "Total Obra"]):
        ws[f"{col}2"] = name
    ws["A3"], ws["C3"] = "SUPERVISOR UNO", "OBRA LOMAS VERDES"
    for c, value in zip("DEFGHI", [8, 2, 1, 35, 0, 46]):
        ws[f"{c}3"] = value
    ws["J3"] = 0.2
    ws["C4"] = "OBRA BRISAS DE JUNQUILLAR"
    ws["C5"], ws["D5"] = "TOTAL GENERAL", 11
    for c, value in zip("DEFGHI", [None, None, None, None, None, 0]):
        ws[f"{c}4"] = value
    nov = wb.create_sheet("11")
    nov["C1"], nov["I1"] = "NOVIEMBRE", "POR TERMINAR"
    nov["C2"], nov["D2"], nov["E2"], nov["F2"], nov["G2"], nov["H2"] = "Obras", "CCT", "CESP", "IND", "TH", "TM"
    nov["C3"] = "OBRA LOMAS VERDES"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET", "ine-suite-local-only-" * 8)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path / "files"))
    settings.cache_clear()
    monkeypatch.setattr(ine_api, "current_month", lambda: "2026-11")
    monkeypatch.setattr(ine_api, "previous_month", lambda: "2026-10")
    engine = create_engine("sqlite:///" + str(tmp_path / "ine.sqlite"), connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        org, other = Organization(name="GALANT INE"), Organization(name="Organización externa")
        db.add_all([org, other])
        db.flush()
        admin = User(org_id=org.id, email="admin@ine.test", role="admin", password_hash=hash_password(PASSWORD))
        supervisor = User(org_id=org.id, email="supervisor@ine.test", role="ine_supervisor", password_hash=hash_password(PASSWORD))
        foreign = User(org_id=other.id, email="foreign@ine.test", role="admin", password_hash=hash_password(PASSWORD))
        lomas = Worksite(org_id=org.id, name="Lomas Verdes")
        brisas = Worksite(org_id=org.id, name="Brisas de Junquillar")
        db.add_all([admin, supervisor, foreign, lomas, brisas])
        db.flush()
        db.add(NetworkMember(user_id=supervisor.id, name="Supervisor Uno"))
        db.add(NetworkMembership(user_id=supervisor.id, site_id=lomas.id, assigned_by=admin.id))
        lomas_id, brisas_id = lomas.id, brisas.id

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override
    clients = []

    def login(email):
        client = TestClient(app)
        clients.append(client)
        response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return client

    def call(client, method, path, **kwargs):
        return client.request(method, ROOT + path,
                              headers={"X-CSRF-Token": client.cookies.get("galant_post_csrf", "")}, **kwargs)

    source = fake_source()
    try:
        yield {
            "admin": login("admin@ine.test"), "supervisor": login("supervisor@ine.test"),
            "foreign": login("foreign@ine.test"), "call": call,
            "source": source, "lomas": lomas_id, "brisas": brisas_id,
        }
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        settings.cache_clear()


def test_import_keeps_original_byte_for_byte_and_transcribes_blank_values(context):
    ctx = context
    response = ctx["call"](ctx["admin"], "POST", "/import", files={
        "file": ("02 INE 2026.xlsx", ctx["source"],
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }, data={"year": "2026"})
    assert response.status_code == 200, response.text
    assert response.json()["sheets"] == 2
    assert response.json()["transcribed_rows"] == 3
    original = ctx["call"](ctx["admin"], "GET", "/original")
    assert original.status_code == 200
    assert original.content == ctx["source"]
    assert original.headers["X-Content-SHA256"] == sha256(ctx["source"]).hexdigest()
    january = ctx["call"](ctx["admin"], "GET", "/rows?period=2026-01").json()["rows"]
    lomas = next(row for row in january if row["source_row"] == 3)
    brisas = next(row for row in january if row["source_row"] == 4)
    assert (lomas["cct"], lomas["cesp"], lomas["ind"], lomas["th"], lomas["tm"]) == (8, 2, 1, 35, 0)
    assert lomas["source_percent"] == pytest.approx(0.2)
    assert (brisas["cct"], brisas["cesp"], brisas["ind"], brisas["th"], brisas["tm"]) == (None, None, None, None, None)
    assert ctx["call"](ctx["admin"], "POST", "/import", files={
        "file": ("otra.xlsx", ctx["source"], "application/octet-stream"),
    }).status_code == 409


def test_supervisor_only_current_or_previous_and_assigned_sites(context):
    ctx = context
    get = ctx["call"](ctx["supervisor"], "GET", "/rows?period=2026-11")
    assert get.status_code == 200
    items = get.json()["rows"]
    assert len(items) == 1
    assert items[0]["site_id"] == ctx["lomas"]
    values = {"version": 0, "site_id": ctx["lomas"], "period": "2026-11",
              "cct": 3, "cesp": 1, "ind": 0, "th": 11, "tm": 2}
    create = ctx["call"](ctx["supervisor"], "POST", "/rows", json=values)
    assert create.status_code == 201, create.text
    row = create.json()
    edit = ctx["call"](ctx["supervisor"], "PUT", "/rows/" + row["id"],
                       json={"version": 1, "cct": 4, "cesp": 1, "ind": 0, "th": 11, "tm": 2})
    assert edit.status_code == 200, edit.text
    assert edit.json()["version"] == 2
    assert ctx["call"](ctx["supervisor"], "POST", "/rows", json={
        **values, "period": "2026-09",
    }).status_code == 403
    assert ctx["call"](ctx["supervisor"], "POST", "/rows", json={
        **values, "site_id": ctx["brisas"],
    }).status_code == 403
    assert ctx["call"](ctx["supervisor"], "GET", "/history").status_code == 403
    assert ctx["call"](ctx["supervisor"], "GET", "/original").status_code == 403
    assert ctx["call"](ctx["supervisor"], "GET", "/api").status_code == 404


def test_admin_can_edit_any_period_and_only_admin_sees_changes(context):
    ctx = context
    all_years = {"version": 0, "site_id": ctx["brisas"], "period": "2024-02",
                 "cct": 1, "cesp": 0, "ind": 0, "th": 3, "tm": 0}
    created = ctx["call"](ctx["admin"], "POST", "/rows", json=all_years)
    assert created.status_code == 201, created.text
    response = ctx["call"](ctx["admin"], "PUT", "/rows/" + created.json()["id"],
                           json={"version": 1, "cct": 2, "cesp": 0, "ind": 0, "th": 3, "tm": 0})
    assert response.status_code == 200
    history = ctx["call"](ctx["admin"], "GET", "/history")
    assert history.status_code == 200
    changes = history.json()
    assert any(x["actor_name"] == "admin@ine.test" and x["previous"].get("cct") == 1
               and x["current"].get("cct") == 2 for x in changes)
    assert ctx["call"](ctx["foreign"], "GET", "/rows?period=2024-02").json()["rows"] == []
    assert ctx["call"](ctx["supervisor"], "PUT", "/rows/" + created.json()["id"],
                       json={"version": 2, "cct": 9, "cesp": 0, "ind": 0, "th": 3, "tm": 0}).status_code == 403
