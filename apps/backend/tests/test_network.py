"""Operational acceptance and negative authorization tests on SQLite and PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.network_models import NetworkAward, NetworkCapacity, NetworkToken
from app.network_service import today
from app.ops_models import Contractor, ContractorWorksite, OpsChange, Worksite
from app.security import hash_password

PASSWORD = "Network-synthetic-test-2026"
ROOT = "/api/v1/network"


@pytest.fixture(params=["sqlite", "postgres"])
def network(request, monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET", "network-test-only-" * 8)
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("SECURE_COOKIES", "false")
    monkeypatch.setenv("SMTP_HOST", "")
    settings.cache_clear()
    from app.network_accounts import attempts

    attempts.clear()
    schema, base = None, None
    if request.param == "postgres":
        if not os.environ.get("TEST_DATABASE_URL"):
            pytest.skip("Requiere PostgreSQL de prueba")
        schema = "network_test_" + uuid4().hex
        base = create_engine(os.environ["TEST_DATABASE_URL"])
        with base.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            os.environ["TEST_DATABASE_URL"],
            connect_args={"options": "-csearch_path=" + schema},
        )
    else:
        engine = create_engine(
            "sqlite:///" + str(tmp_path / "network.db"),
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def fk_on(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        org = Organization(name="Red de Obras · ensayo sintético")
        other = Organization(name="Organización ajena")
        db.add_all([org, other])
        db.flush()
        hashed = hash_password(PASSWORD)
        admin = User(
            org_id=org.id,
            email="admin@network.example.cl",
            role="admin",
            password_hash=hashed,
        )
        outsider = User(
            org_id=other.id,
            email="outside@network.example.cl",
            role="admin",
            password_hash=hashed,
        )
        db.add_all([admin, outsider])
        sites = [
            Worksite(org_id=org.id, name=n)
            for n in ["Brisas de Junquillar", "Lomas Verdes", "Cumbre de Lomas Verdes"]
        ]
        db.add_all(sites)
        companies = [
            Contractor(org_id=org.id, name=n, rut=r, nature="with_workers")
            for n, r in [
                ("Carpintería A SpA", "76123456-0"),
                ("Carpintería B SpA", "77234567-1"),
            ]
        ]
        db.add_all(companies)
        db.flush()
        for site in sites:
            for company in companies:
                db.add(
                    ContractorWorksite(
                        org_id=org.id, worksite_id=site.id, contractor_id=company.id
                    )
                )
        site_ids, company_ids = [s.id for s in sites], [c.id for c in companies]

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override
    clients = []

    def login(email, password=PASSWORD):
        client = TestClient(app)
        clients.append(client)
        r = client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert r.status_code == 200, r.text
        return client

    admin_client = login("admin@network.example.cl")

    def send(client, path, body=None, method="POST"):
        return client.request(
            method,
            ROOT + path,
            json=body,
            headers={"X-CSRF-Token": client.cookies.get("galant_post_csrf", "")},
        )

    def resident(name, site):
        email = name.lower().replace(" ", ".") + "@network.example.cl"
        result = send(
            admin_client,
            "/users",
            {"name": name, "email": email, "role": "resident", "site_ids": [site]},
        )
        assert result.status_code == 201, result.text
        data = result.json()
        token = data["activation_path"].split("=", 1)[1]
        activated = admin_client.post(
            "/api/v1/auth/network-password", json={"token": token, "password": PASSWORD}
        )
        assert activated.status_code == 200, activated.text
        return login(email), data["user"], token

    a, a_user, token = resident("Residente A", site_ids[0])
    b, b_user, _ = resident("Residente B", site_ids[1])
    c, c_user, _ = resident("Residente C", site_ids[2])
    try:
        yield {
            "admin": admin_client,
            "a": a,
            "b": b,
            "c": c,
            "a_user": a_user,
            "b_user": b_user,
            "c_user": c_user,
            "token": token,
            "send": send,
            "sites": site_ids,
            "companies": company_ids,
            "Session": Session,
            "login": login,
            "dialect": request.param,
            "engine": engine,
        }
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.clear()
        engine.dispose()
        if base is not None:
            with base.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            base.dispose()
        settings.cache_clear()


def request_body(n, items=3, draft=False):
    start = today() + timedelta(days=12)
    end = start + timedelta(days=10)
    return {
        "site_id": n["sites"][0],
        "specialty": "Carpintería",
        "title": "Carpinteros para terminaciones",
        "description": "Observación privada de la obra",
        "workers": 3,
        "priority": "high",
        "start_date": str(start),
        "end_date": str(end),
        "deadline": str(start),
        "state": "draft" if draft else "published",
        "client_key": str(uuid4()),
        "items": [
            {
                "name": "Puertas " + str(i),
                "quantity": 100,
                "unit": "un",
                "start_date": str(start),
                "end_date": str(end),
            }
            for i in range(items)
        ],
    }


def requirement(n, items=3):
    r = n["send"](n["a"], "/requirements", request_body(n, items))
    assert r.status_code == 201, r.text
    return r.json()


def capacity(n, **changes):
    start = today() + timedelta(days=12)
    body = {
        "site_id": n["sites"][1],
        "contractor_id": n["companies"][0],
        "specialty": "carpinteria",
        "situation": "few_pending",
        "workers": 3,
        "available_date": str(start),
        "mode": "total",
        "client_key": str(uuid4()),
        "pending_items": [
            {
                "name": "Puertas pendientes",
                "quantity": 5,
                "unit": "un",
                "end_date": str(start - timedelta(days=1)),
            }
        ],
        **changes,
    }
    r = n["send"](n["b"], "/capacities", body)
    assert r.status_code == 201, r.text
    return r.json()


def award_body(n, req, quantity, company=0, **changes):
    return {
        "item_id": req["items"][0]["id"],
        "contractor_id": n["companies"][company],
        "quantity": quantity,
        "start_date": req["start_date"],
        "end_date": req["end_date"],
        "client_key": str(uuid4()),
        **changes,
    }


def test_invitation_scope_and_legacy_modules(network):
    n = network
    for path in [
        "/documents",
        "/dashboard",
        "/ops/sites",
        "/admin/users",
        "/control/matrix?site_id=x&period=2026-11",
        "/labor/workers",
        "/ops/overview?period=2026-11",
    ]:
        assert n["a"].get("/api/v1" + path).status_code == 403
    assert n["a"].get(ROOT + "/profile").json()["role"] == "resident"
    assert (
        n["a"]
        .post(
            "/api/v1/auth/network-password",
            json={"token": n["token"], "password": PASSWORD},
        )
        .status_code
        == 400
    )
    assert n["send"](n["a"], "/users", {}).status_code == 403
    assert (
        n["send"](
            n["a"], "/profile", {"name": "Residente", "role": "admin"}, "PUT"
        ).status_code
        == 422
    )
    assert n["admin"].get("/api/v1/documents").status_code == 200
    assert n["admin"].get("/api/v1/ops/sites").status_code == 200
    assert n["a"].get(ROOT + "/overview").status_code == 200
    assert (
        n["send"](
            n["admin"],
            "/users",
            {"name": "Duplicado", "email": "ADMIN@network.example.cl", "role": "admin"},
        ).status_code
        == 409
    )


def test_shared_publications_and_unlimited_items(network):
    n = network
    req = requirement(n, 7)
    assert len(req["items"]) == 7
    shared = n["b"].get(ROOT + "/requirements/" + req["id"]).json()
    assert shared["description"] == "" and not shared["editable"]
    body = request_body(n)
    body["site_id"] = n["sites"][1]
    assert n["send"](n["a"], "/requirements", body).status_code == 403
    body = request_body(n, draft=True)
    draft = n["send"](n["a"], "/requirements", body).json()
    assert n["b"].get(ROOT + "/requirements/" + draft["id"]).status_code == 404
    cap = capacity(n)
    assert (
        n["a"].get(ROOT + "/capacities/" + cap["id"]).json()["contractor"]
        == "Carpintería A SpA"
    )
    outside = n["login"]("outside@network.example.cl")
    assert outside.get(ROOT + "/requirements/" + req["id"]).status_code == 404
    assert outside.get(ROOT + "/capacities/" + cap["id"]).status_code == 404


def test_explainable_matching_contact_and_notifications(network):
    n = network
    req = requirement(n)
    cap = capacity(n)
    matches = n["a"].get(ROOT + "/matches").json()["rows"]
    assert len(matches) == 1 and matches[0]["score"] >= 90
    assert matches[0]["capacity"]["availability"] == "estimated"
    assert any("requiere coordinación" in reason for reason in matches[0]["reasons"])
    body = {"match_id": matches[0]["id"]}
    first = n["send"](n["a"], "/coordinations", body)
    assert first.status_code == 201, first.text
    coord = first.json()
    assert n["send"](n["b"], "/coordinations", body).json()["id"] == coord["id"]
    assert n["send"](n["c"], "/coordinations", body).status_code == 403
    conversation = coord["conversation_id"]
    assert (
        n["c"].get(ROOT + "/conversations/" + conversation + "/messages").status_code
        == 403
    )
    message = {"body": "Revisemos fechas y disponibilidad", "client_key": str(uuid4())}
    sent = n["send"](n["a"], "/conversations/" + conversation + "/messages", message)
    assert sent.status_code == 201, sent.text
    assert (
        n["send"](
            n["a"], "/conversations/" + conversation + "/messages", message
        ).json()["id"]
        == sent.json()["id"]
    )
    received = n["b"].get(ROOT + "/conversations/" + conversation + "/messages").json()
    assert len(received["rows"]) == 1 and len(received["participants"]) == 2
    assert n["b"].get(ROOT + "/overview").json()["unread_messages"] == 1
    path = (
        "/conversations/" + conversation + "/read?last_message_id=" + sent.json()["id"]
    )
    assert n["send"](n["b"], path).status_code == 200
    assert n["b"].get(ROOT + "/overview").json()["unread_messages"] == 0
    assert any(
        "Nuevo mensaje" in notice["title"]
        for notice in n["b"].get(ROOT + "/notifications").json()["rows"]
    )
    assert (
        n["send"](
            n["a"],
            "/coordinations/" + coord["id"],
            {"state": "approved", "version": 1},
            "PATCH",
        ).status_code
        == 409
    )
    for state in ["contacted", "evaluating"]:
        r = n["send"](
            n["a"],
            "/coordinations/" + coord["id"],
            {"state": state, "version": coord["version"]},
            "PATCH",
        )
        assert r.status_code == 200, r.text
        coord = r.json()
    assert (
        n["send"](
            n["a"],
            "/coordinations/" + coord["id"],
            {"state": "confirmed", "version": coord["version"]},
            "PATCH",
        ).status_code
        == 403
    )


def test_partial_awards_excess_revocation_history_and_document_gate(network):
    n = network
    req = requirement(n)
    first_body = award_body(n, req, 60)
    assert n["send"](n["a"], "/awards", first_body).status_code == 403
    first = n["send"](n["admin"], "/awards", first_body)
    assert first.status_code == 201, first.text
    first = first.json()
    assert (
        first["contractor"] == "Carpintería A SpA"
        and first["clearance"]["state"] == "pending"
    )
    assert n["send"](n["admin"], "/awards", first_body).json()["id"] == first["id"]
    assert (
        n["send"](n["admin"], "/awards", {**first_body, "quantity": 61}).status_code
        == 409
    )
    detail = n["a"].get(ROOT + "/requirements/" + req["id"]).json()
    assert detail["items"][0]["awarded"] == 60 and detail["items"][0]["pending"] == 40
    assert detail["items"][0]["executed"] == 0
    assert (
        n["send"](n["admin"], "/awards", award_body(n, req, 41, 1)).status_code == 409
    )
    second = n["send"](n["admin"], "/awards", award_body(n, req, 40, 1))
    assert second.status_code == 201, second.text
    detail = n["a"].get(ROOT + "/requirements/" + req["id"]).json()
    assert detail["items"][0]["pending"] == 0 and len(detail["items"][0]["awards"]) == 2
    assert detail["items"][0]["execution"] == "pending"
    assert (
        n["send"](
            n["admin"],
            "/awards/" + first["id"],
            {
                "state": "ready",
                "executed": 0,
                "version": 1,
                "reason": "Revisión documental",
            },
            "PATCH",
        ).status_code
        == 409
    )
    revoke = {
        "state": "revoked",
        "executed": 0,
        "version": 1,
        "reason": "Reemplazo autorizado del contratista",
    }
    assert (
        n["send"](n["admin"], "/awards/" + first["id"], revoke, "PATCH").status_code
        == 200
    )
    detail = n["a"].get(ROOT + "/requirements/" + req["id"]).json()
    assert detail["items"][0]["pending"] == 60
    with n["Session"]() as db:
        assert db.get(NetworkAward, first["id"]).state == "revoked"
        assert any(
            r.changes.get("reason") == revoke["reason"]
            for r in db.scalars(select(OpsChange))
        )
    assert n["b"].get(ROOT + "/history/" + req["id"]).status_code == 403
    assert n["a"].get(ROOT + "/history/" + req["id"]).json()["total"] >= 4
    assert n["a"].get(ROOT + "/overview").json()["partial_items"] == 1


def test_session_revocation_suspend_reenable_and_permission_changes(network):
    n = network
    target = n["a_user"]
    body = {
        k: target[k]
        for k in ["name", "title", "role", "enabled", "site_ids", "can_award"]
    }
    body["enabled"] = False
    assert (
        n["send"](n["admin"], "/users/" + target["id"], body, "PATCH").status_code
        == 200
    )
    assert n["a"].get(ROOT + "/profile").status_code == 401
    body["enabled"] = True
    assert (
        n["send"](n["admin"], "/users/" + target["id"], body, "PATCH").status_code
        == 200
    )
    assert n["a"].get(ROOT + "/profile").status_code == 401
    reauth = n["login"](target["email"])
    body["site_ids"] = [n["sites"][2]]
    assert (
        n["send"](n["admin"], "/users/" + target["id"], body, "PATCH").status_code
        == 200
    )
    assert reauth.get(ROOT + "/profile").status_code == 401


def test_draft_edit_versions_and_formal_amendment(network):
    n = network
    body = request_body(n, items=4)
    req = n["send"](n["a"], "/requirements", body).json()
    assert (
        n["send"](n["a"], "/requirements/" + req["id"], body, "PUT").status_code == 409
    )
    body.update(
        {
            "version": req["version"],
            "reason": "Se ajusta programación",
            "items": req["items"],
        }
    )
    body["items"] = [
        {k: i[k] for k in ["id", "name", "quantity", "unit", "start_date", "end_date"]}
        for i in reversed(req["items"])
    ]
    changed = n["send"](n["a"], "/requirements/" + req["id"], body, "PUT")
    assert changed.status_code == 200, changed.text
    assert changed.json()["items"][0]["id"] == req["items"][-1]["id"]
    amend = {"quantity": 120, "reason": "Ampliación formal de veinte unidades"}
    assert (
        n["send"](
            n["a"], "/items/" + req["items"][0]["id"] + "/amend", amend
        ).status_code
        == 403
    )
    assert (
        n["send"](
            n["admin"], "/items/" + req["items"][0]["id"] + "/amend", amend
        ).status_code
        == 200
    )


def test_concurrent_administrators_cannot_overallocate(network):
    n = network
    if n["dialect"] != "postgres":
        pytest.skip("La concurrencia de producción requiere bloqueo PostgreSQL")
    req = requirement(n, 1)
    other = n["login"]("admin@network.example.cl")

    def send(client):
        return n["send"](client, "/awards", award_body(n, req, 60))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, [n["admin"], other]))
    assert sorted(r.status_code for r in responses) == [201, 409]
    detail = n["a"].get(ROOT + "/requirements/" + req["id"]).json()
    assert detail["items"][0]["awarded"] == 60 and detail["items"][0]["pending"] == 40


def test_attachment_privacy_validation_and_calendar(network):
    from test_api import pdf_bytes

    n = network
    req = requirement(n)
    client = n["a"]
    headers = {"X-CSRF-Token": client.cookies.get("galant_post_csrf")}
    result = client.post(
        ROOT + "/attachments",
        files={"file": ("plano.pdf", pdf_bytes(), "application/pdf")},
        data={"requirement_id": req["id"]},
        headers=headers,
    )
    assert result.status_code == 201, result.text
    file_id = result.json()["id"]
    assert client.get(ROOT + "/attachments/" + file_id + "/file").status_code == 200
    assert n["b"].get(ROOT + "/attachments/" + file_id + "/file").status_code == 403
    invalid = client.post(
        ROOT + "/attachments",
        files={"file": ("plano.exe", b"bad", "application/octet-stream")},
        data={"requirement_id": req["id"]},
        headers=headers,
    )
    assert invalid.status_code == 415
    events = client.get(
        ROOT + "/calendar", params={"start": req["start_date"], "end": req["end_date"]}
    )
    assert events.status_code == 200 and any(
        e["id"] == req["id"] for e in events.json()
    )


def test_capacity_expiry_normalized_filters_renewal_and_conflicts(network):
    n = network
    req = requirement(n)
    cap = capacity(n, availability="confirmed")
    assert n["a"].get(ROOT + "/requirements?specialty=carpinteria").json()["total"] == 1
    assert n["a"].get(ROOT + "/capacities?specialty=Carpintería").json()["total"] == 1
    assert n["a"].get(ROOT + "/matches?capacity_id=" + cap["id"]).json()["total"] == 1
    with n["Session"].begin() as db:
        db.get(NetworkCapacity, cap["id"]).expires_on = today() - timedelta(days=1)
    assert n["a"].get(ROOT + "/matches").json()["total"] == 0
    assert (
        n["send"](
            n["a"], "/capacities/" + cap["id"] + "/renew", {"version": 1}
        ).status_code
        == 403
    )
    renewed = n["send"](n["b"], "/capacities/" + cap["id"] + "/renew", {"version": 1})
    assert renewed.status_code == 200, renewed.text
    first = n["send"](
        n["admin"], "/awards", award_body(n, req, 20, capacity_id=cap["id"], workers=3)
    )
    assert first.status_code == 201, first.text
    conflict = award_body(n, req, 20, capacity_id=cap["id"], workers=1)
    assert n["send"](n["admin"], "/awards", conflict).status_code == 409
    conflict.update(
        {
            "acknowledge_conflict": True,
            "conflict_reason": "Cuadrilla adicional confirmada por origen",
        }
    )
    assert n["send"](n["admin"], "/awards", conflict).status_code == 201
    assert n["a"].get(ROOT + "/matches").json()["total"] == 0


def test_documentary_clearance_is_per_destination_and_controls_execution(network):
    from test_api import pdf_bytes

    n = network
    admin = n["admin"]
    req = requirement(n, 1)
    period = req["start_date"][:7]
    with n["Session"]() as db:
        source_link = db.scalar(
            select(ContractorWorksite).where(
                ContractorWorksite.worksite_id == n["sites"][1],
                ContractorWorksite.contractor_id == n["companies"][0],
            )
        ).id
    headers = {"X-CSRF-Token": admin.cookies.get("galant_post_csrf")}
    doc = admin.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("respaldo.pdf", pdf_bytes(), "application/pdf")},
    ).json()
    for kind in [
        "cotizaciones",
        "f30_1",
        "liquidaciones",
        "asistencia",
        "declaracion_jurada",
        "anticipos",
        "porteria",
    ]:
        linked = admin.post(
            "/api/v1/ops/monthly-documents",
            headers=headers,
            json={
                "association_id": source_link,
                "period": period,
                "kind": kind,
                "document_id": doc["id"],
            },
        )
        assert linked.status_code == 201, linked.text
        reviewed = admin.patch(
            "/api/v1/ops/monthly-documents/" + linked.json()["id"],
            headers=headers,
            json={
                "review_status": "approved",
                "notes": "Revisado por responsable autorizado",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
    path = (
        ROOT
        + "/contractors/"
        + n["companies"][0]
        + "/clearance?period="
        + period
        + "&site_id="
    )
    assert admin.get(path + n["sites"][1]).json()["state"] == "enabled"
    assert admin.get(path + n["sites"][0]).json()["state"] == "pending"
    award = n["send"](admin, "/awards", award_body(n, req, 100)).json()
    assert (
        n["send"](
            admin,
            "/awards/" + award["id"],
            {
                "state": "ready",
                "executed": 0,
                "version": 1,
                "reason": "No heredar la habilitación de otra obra",
            },
            "PATCH",
        ).status_code
        == 409
    )


def test_award_revision_frees_remaining_quantity_and_keeps_traceability(network):
    n = network
    req = requirement(n, 1)
    award = n["send"](n["admin"], "/awards", award_body(n, req, 100)).json()
    revision = {
        "quantity": 60,
        "start_date": award["start_date"],
        "end_date": award["end_date"],
        "version": 1,
        "reason": "Se distribuye el saldo entre dos contratistas",
    }
    assert (
        n["send"](n["a"], "/awards/" + award["id"] + "/revise", revision).status_code
        == 403
    )
    changed = n["send"](n["admin"], "/awards/" + award["id"] + "/revise", revision)
    assert changed.status_code == 200, changed.text
    assert (
        n["a"].get(ROOT + "/requirements/" + req["id"]).json()["items"][0]["pending"]
        == 40
    )
    assert (
        n["send"](n["admin"], "/awards", award_body(n, req, 40, 1)).status_code == 201
    )
    with n["Session"]() as db:
        revision_event = db.scalar(
            select(OpsChange).where(OpsChange.entity_type == "network_award_revision")
        )
        assert revision_event.changes["from"]["quantity"] == 100
        assert revision_event.changes["to"]["quantity"] in ("60", 60)


def test_reset_token_expiry_csrf_and_preferences(network):
    n = network
    assert n["a"].post(ROOT + "/requirements", json=request_body(n)).status_code == 403
    body = {"name": "Residente B", "title": "Residente", "notifications": False}
    assert n["send"](n["b"], "/profile", body, "PUT").status_code == 200
    before = n["b"].get(ROOT + "/notifications").json()["total"]
    requirement(n)
    assert n["b"].get(ROOT + "/notifications").json()["total"] == before
    link = n["send"](n["admin"], "/users/" + n["a_user"]["id"] + "/access-link").json()
    with n["Session"].begin() as db:
        token = db.scalar(
            select(NetworkToken).where(
                NetworkToken.user_id == n["a_user"]["id"],
                NetworkToken.used_at.is_(None),
            )
        )
        token.expires_at = token.expires_at - timedelta(days=3)
    assert (
        n["admin"]
        .post(
            "/api/v1/auth/network-password",
            json={
                "token": link["activation_path"].split("=", 1)[1],
                "password": PASSWORD,
            },
        )
        .status_code
        == 400
    )


def test_migration_from_existing_schema_is_additive_and_reopen_preserves_data(network):
    from app.cli import migrate
    from app.platform_models import SchemaVersion

    n = network
    with n["Session"]() as db:
        original_users = {
            (u.id, u.email, u.password_hash, u.role) for u in db.scalars(select(User))
        }
        original_sites = {(s.id, s.name) for s in db.scalars(select(Worksite))}
    future_tables = [
        t for t in Base.metadata.sorted_tables if t.name.startswith("network_")
    ]
    Base.metadata.drop_all(n["engine"], tables=list(reversed(future_tables)))
    for _ in range(2):
        with n["Session"].begin() as db:
            migrate(db)
    n["engine"].dispose()
    with n["Session"]() as db:
        assert {
            (u.id, u.email, u.password_hash, u.role) for u in db.scalars(select(User))
        } == original_users
        assert {(s.id, s.name) for s in db.scalars(select(Worksite))} == original_sites
        assert set(db.scalars(select(SchemaVersion.version))) == {"0.6.0-rc1", "0.7.0", "8.1.0", "13.1.0_documentary_configuration", "16.0.0", "16.0.1_excel_pdf_reviews", "16.6.0_independent_documental", "20.0.0_excel_master_workspace"}
    assert n["admin"].get(ROOT + "/overview").status_code == 200


def test_report_identifies_contractors_and_respects_worksite_scope(network):
    n = network
    req = requirement(n, 1)
    assert n["send"](n["admin"], "/awards", award_body(n, req, 60)).status_code == 201
    report = n["a"].get(ROOT + "/report")
    assert report.status_code == 200
    assert "Carpintería A SpA" in report.text and "Instalación" not in report.text
    assert "Saldo pendiente" in report.text and ";60.0;40.0;0.0;" in report.text
    assert "Carpintería A SpA" not in n["b"].get(ROOT + "/report").text


def test_legacy_admin_route_cannot_remove_both_administrators_concurrently(network):
    n = network
    if n["dialect"] != "postgres":
        pytest.skip("La administración concurrente requiere PostgreSQL")
    admin = n["admin"]
    invitation = n["send"](
        admin,
        "/users",
        {
            "name": "Segundo administrador",
            "email": "admin2@network.example.cl",
            "role": "admin",
        },
    )
    assert invitation.status_code == 201, invitation.text
    invited = invitation.json()
    token = invited["activation_path"].split("=", 1)[1]
    assert (
        admin.post(
            "/api/v1/auth/network-password", json={"token": token, "password": PASSWORD}
        ).status_code
        == 200
    )
    other = n["login"]("admin2@network.example.cl")
    first_id = admin.get(ROOT + "/profile").json()["id"]

    def disable(pair):
        actor, target = pair
        return actor.patch(
            "/api/v1/admin/users/" + target,
            json={"role": "admin", "enabled": False},
            headers={"X-CSRF-Token": actor.cookies.get("galant_post_csrf")},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(disable, [(admin, invited["user"]["id"]), (other, first_id)])
        )
    assert sorted(r.status_code for r in responses) == [200, 401]
    with n["Session"]() as db:
        assert (
            len(
                db.scalars(
                    select(User).where(
                        User.role == "admin",
                        User.enabled.is_(True),
                        User.org_id == db.get(User, first_id).org_id,
                    )
                ).all()
            )
            == 1
        )


def test_v8_global_feed_retains_origin_and_overview_scope(network):
    """A resident sees all published worksites, never a viewer-dependent site name."""
    n = network
    first = requirement(n, items=1)
    second_body = request_body(n, items=1)
    second_body["site_id"] = n["sites"][1]
    second_body["title"] = "Pintura en Lomas Verdes"
    second = n["send"](n["b"], "/requirements", second_body)
    assert second.status_code == 201, second.text
    second = second.json()

    for client in (n["a"], n["b"], n["c"]):
        rows = client.get(ROOT + "/requirements").json()["rows"]
        sites = {r["id"]: (r["site_id"], r["site"]) for r in rows}
        assert sites[first["id"]] == (n["sites"][0], "Brisas de Junquillar")
        assert sites[second["id"]] == (n["sites"][1], "Lomas Verdes")
        assert client.get(ROOT + "/overview").json()["requirements"] == 2
    assert n["c"].get(ROOT + "/overview?mine=true").json()["requirements"] == 0
    assert n["a"].get(ROOT + "/overview?mine=true").json()["requirements"] == 1

    move = request_body(n, items=1)
    move["site_id"] = n["sites"][1]
    move["version"] = first["version"]
    move["reason"] = "Cambiar arbitrariamente de obra"
    changed = n["send"](
        n["admin"], "/requirements/" + first["id"], move, "PUT"
    )
    assert changed.status_code == 409
    original = n["c"].get(ROOT + "/requirements/" + first["id"]).json()
    assert original["site_id"] == n["sites"][0]
    assert original["site"] == "Brisas de Junquillar"


def test_v8_readable_history_excludes_raw_audit_payload(network):
    n = network
    req = requirement(n, items=2)
    visible = n["a"].get(ROOT + "/history/" + req["id"])
    assert visible.status_code == 200
    entry = visible.json()["rows"][0]
    assert entry["title"] == "Requerimiento creado"
    assert entry["actor"] == "Residente A"
    assert "changes" not in entry and "kind" not in entry
    assert any(
        d["label"] == "Obra" and d["after"] == "Brisas de Junquillar"
        for d in entry["details"]
    )
    assert "client_key" not in str(entry) and "site_id" not in str(entry)

    # El evento técnico sigue persistido, aunque la respuesta operativa sea legible.
    with n["Session"]() as db:
        raw = db.scalar(
            select(OpsChange).where(
                OpsChange.entity_type == "network_requirement",
                OpsChange.entity_id == req["id"],
            )
        )
        assert "client_key" in raw.changes["to"]
    assert n["b"].get(ROOT + "/history/" + req["id"]).status_code == 403


def test_v8_same_site_resident_cannot_edit_another_authors_publication(network):
    n = network
    req = requirement(n, items=1)
    person = n["b_user"]
    change_user = {
        k: person[k]
        for k in ["name", "title", "role", "enabled", "site_ids", "can_award"]
    }
    change_user["site_ids"] = [n["sites"][0]]
    update = n["send"](
        n["admin"], "/users/" + person["id"], change_user, "PATCH"
    )
    assert update.status_code == 200, update.text
    neighbor = n["login"](person["email"])
    shared = neighbor.get(ROOT + "/requirements/" + req["id"]).json()
    assert shared["site_id"] == n["sites"][0]
    assert shared["editable"] is False

    edit = request_body(n, items=1)
    edit["version"] = req["version"]
    edit["reason"] = "Intento de edición ajena"
    response = n["send"](
        neighbor, "/requirements/" + req["id"], edit, "PUT"
    )
    assert response.status_code == 403
