"""Synthetic acceptance coverage for the admin configuration center.

Documents are registered and reviewed manually: these tests never upload files.
Each case starts from an isolated database and uses the real cookie/CSRF guards.
"""
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Document, Organization, User
from app.network_models import NetworkMember
from app.ops_models import Contractor, ContractorWorksite, MonthlyDocument
from app.platform_models import UserPreferences
from app.security import hash_password


ROOT = "/api/v1/admin/configuration"
PASSWORD = "configuration-test-password-2026"


@pytest.fixture
def config_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET", "configuration-tests-" * 8)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite:///" + str(tmp_path / "configuration.sqlite"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    digest = hash_password(PASSWORD)
    with sessions.begin() as db:
        main = Organization(name="Organización de prueba")
        foreign = Organization(name="Otra organización")
        db.add_all([main, foreign])
        db.flush()
        users = {}
        for name, role, org in [
            ("admin", "admin", main),
            ("second", "admin", main),
            ("administrative", "administrative", main),
            ("resident", "resident", main),
            ("outside", "admin", foreign),
        ]:
            row = User(org_id=org.id, email=name + "@example.cl", role=role,
                       password_hash=digest)
            db.add(row)
            db.flush()
            users[name] = row.id
            db.add(NetworkMember(user_id=row.id, name="Responsable " + name))
            db.add(UserPreferences(user_id=row.id, values={"name": "Responsable " + name}))
        org_id, outside_id = main.id, foreign.id

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield {"client": client, "sessions": sessions, "users": users,
                   "org_id": org_id, "outside_id": outside_id, "engine": engine}
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()


def sign_in(client, who="admin"):
    response = client.post("/api/v1/auth/login", json={
        "email": who + "@example.cl", "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies["galant_post_csrf"]}


def company(client, headers, site_id, code="CT", name="Contratista sintético"):
    response = client.post("/api/v1/ops/contractors", headers=headers, json={
        "name": name, "site_id": site_id, "historical_code": code,
        "nature": "independent" if code == "CI" else "with_workers",
        "frequency": "sporadic" if code == "ESP" else "fixed",
        "contract_status": "active",
    })
    assert response.status_code == 201, response.text
    return response.json()


def assert_ok(response, expected=200):
    assert response.status_code == expected, response.text
    return response.json()


def current_month():
    return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m")


def shift_month(period, months):
    year, month = map(int, period.split("-"))
    ordinal = year * 12 + month - 1 + months
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


def bootstrap(client):
    return assert_ok(client.get(ROOT + "/bootstrap"))


def document_type(client, headers, name="Certificado sintético de prueba"):
    return assert_ok(client.post(ROOT + "/catalog", headers=headers, json={
        "name": name, "description": "Documento de aceptación sintético",
        "category": "operational", "level": "contractor", "frequency": "monthly",
    }), 201)


def rule(document_id, period=None, **overrides):
    return {
        "document_type_id": document_id, "scope": "general", "required": True,
        "association_ids": [], "frequency": "monthly",
        "period_start": period or current_month(), "period_end": None,
        "due_day": None, "due_month_offset": 1,
        "reason": "Configuración sintética verificada por administrador",
        "retroactive": False, **overrides,
    }


def apply_rule(client, headers, body):
    preview = assert_ok(client.post(ROOT + "/rules/preview", headers=headers, json=body))
    response = client.post(ROOT + "/rules/apply", headers=headers, json={
        **body, "preview_token": preview["preview_token"], "confirm": True,
    })
    return assert_ok(response)


def summary(client, periods=None, **params):
    return assert_ok(client.get(ROOT + "/summary", params={
        "periods": periods or current_month(), **params,
    }))


def obligation(data, association_id, code, period=None):
    matches = [row for row in data["obligations"] if
               row["association_id"] == association_id and row["code"] == code
               and (period is None or row["period"] == period)]
    assert len(matches) == 1, matches
    return matches[0]


def review(client, headers, association, document, state="approved", notes="Revisión manual sintética"):
    return client.put(ROOT + "/reviews", headers=headers, json={
        "association_id": association["id"], "period": current_month(),
        "document_type_id": document["id"], "state": state, "notes": notes,
    })


def test_configuration_routes_require_admin_and_do_not_offer_uploads(config_env):
    client = config_env["client"]
    routes = {path: operations for path, operations in app.openapi()["paths"].items()
              if path.startswith(ROOT)}
    assert len(routes) >= 8, "Configuration routes must actually be registered"
    assert not any("upload" in path for path in routes)
    for template, operations in routes.items():
        if "get" in operations:
            path = re.sub(r"\{[^}]+\}", "nonexistent", template)
            assert client.get(path).status_code == 401
    for role in ("administrative", "resident"):
        headers = sign_in(client, role)
        for template, operations in routes.items():
            path = re.sub(r"\{[^}]+\}", "nonexistent", template)
            for method in set(operations) & {"get", "post", "put", "patch", "delete"}:
                response = client.request(method, path, headers=headers,
                                          json={} if method != "get" else None)
                assert response.status_code == 403, (role, method, path, response.text)
    headers = sign_in(client)
    assert len(bootstrap(client)["catalog"]) >= 14
    assert client.get(ROOT + "/bootstrap").headers["cache-control"] == "no-store"
    assert client.post(ROOT + "/catalog", json={"name": "Sin CSRF"}).status_code == 403


def test_porteria_required_for_all_categories_worksites_and_new_sites(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    sites = assert_ok(client.get("/api/v1/ops/sites"))
    companies = [company(client, headers, site["id"], code, f"{code} {site['name']}")
                 for site in sites for code in ("CT", "ESP", "CI")]
    fresh = assert_ok(client.post("/api/v1/admin/sites", headers=headers,
                                 json={"name": "Nueva obra sintética"}), 201)
    companies.append(company(client, headers, fresh["id"], "CI", "CI en nueva obra"))
    data = summary(client)
    for row in companies:
        item = obligation(data, row["id"], "porteria")
        assert item["required"] is True, item
        assert item["state"] in {"missing", "overdue"}, item
        assert item["rule_source"], "Every obligation must identify its rule source"
    assert data["summary"]["porteria_pending"] == len(companies)
    # The initial rollout must not silently invent old obligations.
    historic = summary(client, shift_month(current_month(), -1))
    assert not any(row["required"] for row in historic["obligations"] if row["code"] == "porteria")


def test_catalog_normalizes_accents_case_spacing_and_persists(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    created = document_type(client, headers, "Certificado Único de Prueba")
    duplicate = client.post(ROOT + "/catalog", headers=headers, json={
        "name": "  CERTIFICADO UNICO DE PRUEBA  ",
    })
    assert duplicate.status_code == 409, duplicate.text
    assert len([row for row in bootstrap(client)["catalog"] if row["id"] == created["id"]]) == 1


def test_preview_requires_confirmation_is_bound_to_payload_and_is_atomic(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    document = document_type(client, headers)
    body = rule(document["id"], scope="association", association_ids=[ct["id"]])
    preview = assert_ok(client.post(ROOT + "/rules/preview", headers=headers, json=body))
    initial = summary(client)
    assert not any(row["required"] for row in initial["obligations"] if row["code"] == document["code"])
    unconfirmed = client.post(ROOT + "/rules/apply", headers=headers,
                             json={**body, "preview_token": preview["preview_token"], "confirm": False})
    assert unconfirmed.status_code in {409, 422}, unconfirmed.text
    tampered = client.post(ROOT + "/rules/apply", headers=headers, json={
        **body, "required": False, "preview_token": preview["preview_token"], "confirm": True,
    })
    assert tampered.status_code == 409, tampered.text
    assert_ok(client.post(ROOT + "/rules/apply", headers=headers, json={
        **body, "preview_token": preview["preview_token"], "confirm": True,
    }))
    assert obligation(summary(client), ct["id"], document["code"])["required"] is True


def test_rule_hierarchy_general_category_site_individual_exception(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    document = document_type(client, headers)
    apply_rule(client, headers, rule(document["id"]))
    assert obligation(summary(client), ct["id"], document["code"])["required"] is True
    apply_rule(client, headers, rule(document["id"], scope="category", category="CT", required=False))
    assert obligation(summary(client), ct["id"], document["code"])["required"] is False
    apply_rule(client, headers, rule(document["id"], scope="site", site_id=site))
    assert obligation(summary(client), ct["id"], document["code"])["required"] is True
    apply_rule(client, headers, rule(document["id"], scope="association", association_ids=[ct["id"]]))
    individual = obligation(summary(client), ct["id"], document["code"])
    assert individual["required"] is True
    apply_rule(client, headers, rule(document["id"], scope="exception", association_ids=[ct["id"]],
                                    required=False, period_end=current_month()))
    exception = obligation(summary(client), ct["id"], document["code"])
    assert exception["required"] is False
    assert exception["rule_id"] != individual["rule_id"]
    assert exception["rule_source"] != individual["rule_source"]


def test_category_cannot_silently_exempt_porteria_and_reason_must_be_nonblank(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ci = company(client, headers, site, "CI")
    porteria = next(row for row in bootstrap(client)["catalog"] if row["code"] == "porteria")
    disabled = client.post(ROOT + "/rules/preview", headers=headers, json=rule(
        porteria["id"], scope="category", category="CI", required=False,
    ))
    assert disabled.status_code == 422, disabled.text
    blank = client.post(ROOT + "/rules/preview", headers=headers, json=rule(
        porteria["id"], scope="exception", association_ids=[ci["id"]], required=False,
        period_end=current_month(), reason="   ",
    ))
    assert blank.status_code == 422, blank.text
    apply_rule(client, headers, rule(porteria["id"], scope="exception", association_ids=[ci["id"]],
                                    required=False, period_end=current_month(),
                                    reason="Exención mensual autorizada y justificada"))
    assert obligation(summary(client), ci["id"], "porteria")["required"] is False


def test_manual_incomplete_delivery_is_never_missing_and_reuses_monthly_source(config_env):
    client, sessions = config_env["client"], config_env["sessions"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    porteria = next(row for row in bootstrap(client)["catalog"] if row["code"] == "porteria")
    before = summary(client)
    assert_ok(review(client, headers, ct, porteria, "incomplete", "Faltan jornadas por contrastar"))
    data = summary(client)
    item = obligation(data, ct["id"], "porteria")
    assert item["state"] == "incomplete"
    assert item["document_id"] is None
    assert item["reviewed_by"] == "Responsable admin"
    assert data["summary"]["incomplete"] == before["summary"]["incomplete"] + 1
    assert data["summary"]["missing"] == before["summary"]["missing"] - 1
    assert data["summary"]["delivery"] > before["summary"]["delivery"]
    assert_ok(review(client, headers, ct, porteria))
    assert obligation(summary(client), ct["id"], "porteria")["state"] == "approved"
    with sessions() as db:
        reviews = db.scalars(select(MonthlyDocument).where(
            MonthlyDocument.association_id == ct["id"],
            MonthlyDocument.period == current_month(), MonthlyDocument.kind == "porteria",
            MonthlyDocument.document_id.is_(None),
        )).all()
        assert len(reviews) == 1
        assert reviews[0].review_status == "approved"


@pytest.mark.parametrize("state", ["not_applicable", "exempt", "no_movements"])
def test_exclusions_require_auditable_justification(config_env, state):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    document = document_type(client, headers)
    apply_rule(client, headers, rule(document["id"]))
    before = summary(client)["summary"]
    blank = review(client, headers, ct, document, state, "   ")
    assert blank.status_code == 422, blank.text
    assert_ok(review(client, headers, ct, document, state, "Verificación administrativa documentada sin movimientos"))
    after = summary(client)
    assert obligation(after, ct["id"], document["code"])["state"] == state
    assert after["summary"]["required"] == before["required"] - 1
    events = assert_ok(client.get(ROOT + "/audit"))
    assert events
    assert "@example.cl" not in str(events)
    assert "Responsable admin" in str(events)


def test_multiperiod_totals_use_weighted_denominators_and_future_rules_preserve_history(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    first = document_type(client, headers, "Primer documento sintético")
    second = document_type(client, headers, "Segundo documento sintético")
    apply_rule(client, headers, rule(first["id"]))
    assert_ok(review(client, headers, ct, first))
    historic_before = summary(client)
    next_period = shift_month(current_month(), 1)
    apply_rule(client, headers, rule(second["id"], next_period))
    historic_after = summary(client)
    assert historic_after["summary"] == historic_before["summary"]
    assert obligation(historic_after, ct["id"], first["code"])["state"] == "approved"
    data = summary(client, current_month() + "," + next_period)
    expected_required = sum(row["required"] for row in data["by_period"])
    expected_approved = sum(row["approved"] for row in data["by_period"])
    assert data["summary"]["required"] == expected_required
    assert data["summary"]["approved"] == expected_approved
    assert data["summary"]["compliance"] == pytest.approx(100 * expected_approved / expected_required, abs=0.02)
    unweighted = sum(row["compliance"] or 0 for row in data["by_period"]) / len(data["by_period"])
    assert abs(data["summary"]["compliance"] - unweighted) > 0.01


def test_retroactive_changes_require_explicit_flag_and_preview(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    assert_ok(client.get("/api/v1/ops/sites"))
    document = document_type(client, headers)
    body = rule(document["id"], shift_month(current_month(), -1))
    denied = client.post(ROOT + "/rules/preview", headers=headers, json=body)
    assert denied.status_code == 422, denied.text
    preview = assert_ok(client.post(ROOT + "/rules/preview", headers=headers,
                                   json={**body, "retroactive": True}))
    assert preview["historical"]


def test_foreign_identifiers_reject_whole_bulk_and_preview_stale_revision(config_env):
    client = config_env["client"]
    own_headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    own = company(client, own_headers, site)
    document = document_type(client, own_headers)
    outside_headers = sign_in(client, "outside")
    foreign_site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    foreign = company(client, outside_headers, foreign_site, name="Contratista externo")
    assert client.get(ROOT + "/contractors/" + own["id"]).status_code == 404
    assert client.get(ROOT + "/summary", params={"periods": current_month(), "site_id": site}).status_code == 404
    own_headers = sign_in(client)
    body = rule(document["id"], scope="association", association_ids=[own["id"], foreign["id"]])
    denied = client.post(ROOT + "/rules/preview", headers=own_headers, json=body)
    assert denied.status_code == 404, denied.text
    assert not any(row["required"] for row in summary(client)["obligations"] if row["code"] == document["code"])
    valid = rule(document["id"], scope="association", association_ids=[own["id"]])
    preview = assert_ok(client.post(ROOT + "/rules/preview", headers=own_headers, json=valid))
    # A concurrent catalog modification invalidates the reviewable impact.
    document_type(client, own_headers, "Documento agregado entre vista previa y confirmación")
    stale = client.post(ROOT + "/rules/apply", headers=own_headers, json={
        **valid, "preview_token": preview["preview_token"], "confirm": True,
    })
    assert stale.status_code == 409, stale.text


def test_manual_reviews_are_shared_with_second_admin_and_legacy_matrix(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    porteria = next(row for row in bootstrap(client)["catalog"] if row["code"] == "porteria")
    with TestClient(app) as second:
        sign_in(second, "second")
        assert obligation(summary(second), ct["id"], "porteria")["state"] == "missing"
        assert_ok(review(client, headers, ct, porteria))
        assert obligation(summary(second), ct["id"], "porteria")["state"] == "approved"
        old_matrix = assert_ok(second.get("/api/v1/control/matrix", params={
            "site_id": site, "period": current_month(),
        }))
        row = next(row for row in old_matrix["contractors"] if row["association_id"] == ct["id"])
        gate = next(req for req in row["requirements"] if req["kind"] == "porteria")
        assert gate["applicable"] is True
        assert gate["state"] == "approved"


def test_configuration_migration_is_additive_idempotent_and_preserves_evidence(config_env):
    from app.migrations import v13_1_0

    client, sessions = config_env["client"], config_env["sessions"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    with sessions.begin() as db:
        document = Document(org_id=config_env["org_id"], user_id=config_env["users"]["admin"],
                            original_name="evidencia-historica-sintetica.pdf",
                            storage_path="/nonexistent/synthetic-private-file", sha256="a" * 64)
        db.add(document)
        db.flush()
        record = MonthlyDocument(org_id=config_env["org_id"], association_id=ct["id"],
                                 contractor_id=ct["contractor_id"], period="2026-09",
                                 kind="porteria", document_id=document.id,
                                 review_status="observed", notes="Evidencia histórica preservada",
                                 created_by=config_env["users"]["admin"])
        db.add(record)
        db.flush()
        document_id, record_id = document.id, record.id
    with sessions.begin() as db:
        before = {table.name: db.scalar(select(func.count()).select_from(table))
                  for table in (Contractor.__table__, ContractorWorksite.__table__,
                                Document.__table__, MonthlyDocument.__table__)}
        v13_1_0.upgrade(db)
    with sessions.begin() as db:
        v13_1_0.upgrade(db)
    with sessions() as db:
        after = {table.name: db.scalar(select(func.count()).select_from(table))
                 for table in (Contractor.__table__, ContractorWorksite.__table__,
                               Document.__table__, MonthlyDocument.__table__)}
        assert before == after
        assert db.get(Document, document_id).original_name == "evidencia-historica-sintetica.pdf"
        assert db.get(MonthlyDocument, record_id).notes == "Evidencia histórica preservada"


def test_period_inputs_are_bounded_and_empty_denominator_is_not_fictitious_compliance(config_env):
    client = config_env["client"]
    sign_in(client)
    assert summary(client)["summary"]["compliance"] is None
    assert summary(client)["summary"]["required"] == 0
    assert client.get(ROOT + "/summary", params={"periods": "2026-13"}).status_code == 422
    months = ",".join(shift_month("2020-01", number) for number in range(61))
    assert client.get(ROOT + "/summary", params={"periods": months}).status_code == 422


def test_transcribed_gate_movements_detect_reviewable_differences_only_with_evidence(config_env):
    from app.v81_models import CalendarEntry, CalendarWeek

    client, sessions = config_env["client"], config_env["sessions"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    bootstrap(client)
    period = current_month()
    unknown = {"association_id": ct["id"], "period": period,
               "worker_name": "Persona no registrada", "worker_rut": "11111111-1",
               "movement_date": period + "-03", "notes": "Movimiento transcrito de control externo"}
    created = assert_ok(client.post(ROOT + "/gate-movements", headers=headers, json=unknown), 201)
    data = summary(client)
    alerts = [row for row in data["alerts"] if row["key"].startswith("gate:")]
    assert len(alerts) == 1
    assert "sin registro de trabajador" in alerts[0]["reason"]
    assert "no es incumplimiento definitivo" in alerts[0]["action"]
    duplicate = client.post(ROOT + "/gate-movements", headers=headers, json=unknown)
    assert duplicate.status_code == 409, duplicate.text

    worker = assert_ok(client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site, "contractor_id": ct["contractor_id"],
        "name": "Persona registrada", "rut": "22222222-2",
    }), 201)
    known = {**unknown, "worker_name": worker["name"], "worker_rut": worker["rut"]}
    assert_ok(client.post(ROOT + "/gate-movements", headers=headers, json=known), 201)
    before = summary(client)
    assert not any("Posible diferencia entre portería y asistencia" in row["reason"] for row in before["alerts"]), \
        "A missing/uncompleted attendance week is insufficient evidence for a mismatch"
    with sessions.begin() as db:
        week = CalendarWeek(org_id=config_env["org_id"], association_id=ct["id"],
                            period=period, week_number=1, start_date=date.fromisoformat(period + "-01"),
                            end_date=date.fromisoformat(period + "-07"), state="complete",
                            entered_by=config_env["users"]["admin"], updated_by=config_env["users"]["admin"])
        db.add(week)
        db.flush()
        week_id = week.id
    discrepancy = summary(client)
    possible = [row for row in discrepancy["alerts"] if "Posible diferencia entre portería y asistencia" in row["reason"]]
    assert len(possible) == 1
    assert possible[0]["priority"] == "normal"
    assert discrepancy["summary"] == before["summary"], "A movement discrepancy must not automatically reject a document"
    with sessions.begin() as db:
        db.add(CalendarEntry(org_id=config_env["org_id"], week_id=week_id,
                             worker_assignment_id=worker["id"], signed_dates=[period + "-03"],
                             updated_by=config_env["users"]["admin"]))
    assert not any("Posible diferencia entre portería y asistencia" in row["reason"]
                   for row in summary(client)["alerts"])


def test_worker_level_rules_count_people_and_validate_review_subject(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    sites = assert_ok(client.get("/api/v1/ops/sites"))
    ct = company(client, headers, sites[0]["id"])
    document = assert_ok(client.post(ROOT + "/catalog", headers=headers, json={
        "name": "Certificado personal sintético", "level": "worker", "frequency": "monthly",
    }), 201)
    people = [assert_ok(client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": sites[0]["id"], "contractor_id": ct["contractor_id"],
        "name": "Trabajador sintético " + str(number),
    }), 201) for number in range(2)]
    other_ct = company(client, headers, sites[1]["id"], name="Contratista en otra obra")
    outsider = assert_ok(client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": sites[1]["id"], "contractor_id": other_ct["contractor_id"],
        "name": "Persona ajena a la asociación",
    }), 201)
    apply_rule(client, headers, rule(document["id"], scope="association", association_ids=[ct["id"]]))
    data = summary(client)
    people_obligations = [row for row in data["obligations"] if row["association_id"] == ct["id"]
                          and row["document_type_id"] == document["id"]]
    assert len(people_obligations) == 2
    assert {row["subject"] for row in people_obligations} == {person["id"] for person in people}
    payload = {"association_id": ct["id"], "period": current_month(),
               "document_type_id": document["id"], "state": "approved", "notes": "Control personal manual"}
    denied = client.put(ROOT + "/reviews", headers=headers, json={**payload, "subject": outsider["id"]})
    assert denied.status_code in {404, 422}, denied.text
    assert_ok(client.put(ROOT + "/reviews", headers=headers, json={**payload, "subject": people[0]["id"]}))
    after = summary(client)
    assert after["summary"]["required"] == data["summary"]["required"]
    assert after["summary"]["approved"] == data["summary"]["approved"] + 1
    approved = [row for row in after["obligations"] if row["document_type_id"] == document["id"]
                and row["state"] == "approved"]
    assert len(approved) == 1
    assert approved[0]["subject"] == people[0]["id"]


def test_quarterly_rules_respect_effective_interval_and_real_deadlines(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    document = document_type(client, headers)
    period = current_month()
    apply_rule(client, headers, rule(document["id"], period, frequency="quarterly",
                                    period_end=shift_month(period, 4), due_day=31, due_month_offset=1))
    periods = [shift_month(period, offset) for offset in range(6)]
    data = summary(client, ",".join(periods))
    flags = [obligation(data, ct["id"], document["code"], month)["required"] for month in periods]
    assert flags == [True, False, False, True, False, False]
    first = obligation(data, ct["id"], document["code"], period)
    deadline = date.fromisoformat(first["due_date"])
    assert deadline.strftime("%Y-%m") == shift_month(period, 1)
    assert deadline.day in {28, 29, 30, 31}, "End-of-month deadlines must be clamped to a valid day"


def test_reviewing_existing_monthly_evidence_keeps_original_visible(config_env):
    client, sessions = config_env["client"], config_env["sessions"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    porteria = next(row for row in bootstrap(client)["catalog"] if row["code"] == "porteria")
    with sessions.begin() as db:
        original = Document(org_id=config_env["org_id"], user_id=config_env["users"]["admin"],
                            original_name="porteria-original-sintetica.pdf", storage_path="/synthetic/not-read",
                            sha256="b" * 64)
        db.add(original)
        db.flush()
        record = MonthlyDocument(org_id=config_env["org_id"], association_id=ct["id"],
                                 contractor_id=ct["contractor_id"], period=current_month(),
                                 kind="porteria", document_id=original.id, review_status="pending",
                                 created_by=config_env["users"]["admin"])
        db.add(record)
        db.flush()
        original_id, record_id = original.id, record.id
    assert obligation(summary(client), ct["id"], "porteria")["state"] == "submitted"
    assert_ok(review(client, headers, ct, porteria, "incomplete", "Original recibido, faltan antecedentes"))
    observed = obligation(summary(client), ct["id"], "porteria")
    assert observed["state"] == "incomplete"
    assert observed["document_id"] == original_id
    assert observed["original_name"] == "porteria-original-sintetica.pdf"
    assert_ok(review(client, headers, ct, porteria))
    approved = obligation(summary(client), ct["id"], "porteria")
    assert approved["state"] == "approved"
    assert approved["document_id"] == original_id
    with sessions() as db:
        rows = db.scalars(select(MonthlyDocument).where(
            MonthlyDocument.association_id == ct["id"], MonthlyDocument.period == current_month(),
            MonthlyDocument.kind == "porteria",
        )).all()
        assert len(rows) == 1, "A manual review must update the received record rather than hide it behind a new row"
        assert rows[0].id == record_id
        assert db.get(Document, original_id).sha256 == "b" * 64


def test_preactivation_history_preserves_legacy_evaluability_denominator(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    company(client, headers, site)
    old_month = shift_month(current_month(), -1)
    before = assert_ok(client.get("/api/v1/control/matrix", params={"site_id": site, "period": old_month}))
    bootstrap(client)
    after = summary(client, old_month, site_id=site)
    assert before["summary"]["applicable"] == 0
    assert after["summary"]["required"] == before["summary"]["applicable"]
    assert after["summary"]["compliance"] is None


def test_porteria_monthly_default_cannot_be_weakened_by_annual_frequency(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    gate = next(row for row in bootstrap(client)["catalog"] if row["code"] == "porteria")
    for scope in ("general", "category", "site", "association"):
        proposed = rule(gate["id"], scope=scope, frequency="annual", category="CT" if scope == "category" else None,
                        site_id=site if scope == "site" else None,
                        association_ids=[ct["id"]] if scope == "association" else [])
        response = client.post(ROOT + "/rules/preview", headers=headers, json=proposed)
        assert response.status_code == 422, (scope, response.text)


def test_legacy_manual_endpoint_uses_new_catalog_statuses_and_shared_counts(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    document = document_type(client, headers, "Documento revisable desde matriz existente")
    apply_rule(client, headers, rule(document["id"]))
    response = client.post("/api/v1/control/reviews", headers=headers, json={
        "association_id": ct["id"], "period": current_month(), "kind": document["code"],
        "status": "incomplete", "notes": "Documento entregado, revisión parcial desde flujo actual",
    })
    assert response.status_code == 200, response.text
    data = summary(client)
    assert obligation(data, ct["id"], document["code"])["state"] == "incomplete"
    matrix = assert_ok(client.get("/api/v1/control/matrix", params={"site_id": site, "period": current_month()}))
    row = next(row for row in matrix["contractors"] if row["association_id"] == ct["id"])
    custom = next(item for item in row["requirements"] if item["kind"] == document["code"])
    assert custom["state"] == "incomplete"
    assert custom["applicable"] is True
    assert matrix["summary"]["applicable"] == data["summary"]["required"]
    assert matrix["summary"]["approved"] == data["summary"]["approved"]
    assert matrix["summary"]["compliance"] == data["summary"]["compliance"]


def test_builtin_worker_alias_and_original_are_shared_with_new_reviews(config_env):
    from app.platform_models import DocumentReview

    client, sessions = config_env["client"], config_env["sessions"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    worker = assert_ok(client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site, "contractor_id": ct["contractor_id"], "name": "Persona con contrato previo",
    }), 201)
    contract = next(row for row in bootstrap(client)["catalog"] if row["code"] == "contrato_trabajo")
    apply_rule(client, headers, rule(contract["id"], frequency="monthly"))
    with sessions.begin() as db:
        original = Document(org_id=config_env["org_id"], user_id=config_env["users"]["admin"],
                            original_name="contrato-historico-sintetico.pdf", storage_path="/synthetic/not-read",
                            sha256="c" * 64)
        db.add(original)
        db.flush()
        legacy = DocumentReview(org_id=config_env["org_id"], association_id=ct["id"],
                                subject=worker["id"], period=current_month(), requirement="Contrato",
                                state="approved", document_id=original.id,
                                reviewed_by=config_env["users"]["admin"], observation="Contrato previo validado")
        db.add(legacy)
        db.flush()
        original_id = original.id
    observed = obligation(summary(client), ct["id"], "contrato_trabajo")
    assert observed["state"] == "approved"
    assert observed["document_id"] == original_id
    assert observed["original_name"] == "contrato-historico-sintetico.pdf"
    assert_ok(client.put(ROOT + "/reviews", headers=headers, json={
        "association_id": ct["id"], "period": current_month(), "subject": worker["id"],
        "document_type_id": contract["id"], "state": "incomplete", "notes": "Falta firma verificada en contrato previo",
    }))
    after = obligation(summary(client), ct["id"], "contrato_trabajo")
    assert after["state"] == "incomplete"
    assert after["document_id"] == original_id
    with sessions() as db:
        rows = db.scalars(select(DocumentReview).where(
            DocumentReview.association_id == ct["id"], DocumentReview.subject == worker["id"],
            DocumentReview.period == current_month(), DocumentReview.requirement.in_(["Contrato", "contrato_trabajo"]),
        )).all()
        assert len(rows) == 1, "Canonical and legacy names represent one logical review"


def test_porteria_start_is_previewed_versioned_and_can_be_explicitly_backdated(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    bootstrap(client)
    period = current_month()
    previous, following = shift_month(period, -1), shift_month(period, 1)
    before_history = summary(client, previous)
    body = {"period_start": following, "reason": "Programación del inicio según acuerdo administrativo", "retroactive": False}
    preview = assert_ok(client.post(ROOT + "/porteria-start/preview", headers=headers, json=body))
    assert preview["effective_from_period"] == period
    assert obligation(summary(client), ct["id"], "porteria")["required"] is True
    tampered = client.post(ROOT + "/porteria-start/apply", headers=headers, json={
        **body, "period_start": shift_month(period, 2), "preview_token": preview["preview_token"], "confirm": True,
    })
    assert tampered.status_code == 409, tampered.text
    assert_ok(client.post(ROOT + "/porteria-start/apply", headers=headers, json={
        **body, "preview_token": preview["preview_token"], "confirm": True,
    }))
    assert obligation(summary(client), ct["id"], "porteria")["required"] is False
    assert obligation(summary(client, following), ct["id"], "porteria")["required"] is True
    assert summary(client, previous)["summary"] == before_history["summary"]
    assert bootstrap(client)["settings"]["porteria_start_period"] == following

    historical_body = {"period_start": previous, "reason": "Corrección histórica solicitada y revisada por administrador",
                       "retroactive": False}
    assert client.post(ROOT + "/porteria-start/preview", headers=headers, json=historical_body).status_code == 422
    historical_body["retroactive"] = True
    historical_preview = assert_ok(client.post(ROOT + "/porteria-start/preview", headers=headers, json=historical_body))
    assert historical_preview["historical"] is True
    assert any(change["to_required"] for change in historical_preview["changes"] if change["period"] == previous)
    assert_ok(client.post(ROOT + "/porteria-start/apply", headers=headers, json={
        **historical_body, "preview_token": historical_preview["preview_token"], "confirm": True,
    }))
    assert obligation(summary(client, previous), ct["id"], "porteria")["required"] is True
    assert bootstrap(client)["settings"]["porteria_start_period"] == previous


def test_historical_obligations_survive_category_and_worker_changes(config_env, monkeypatch):
    from app import configuration_service as service
    from app.ops_models import WorkerAssignment
    client, sessions = config_env["client"], config_env["sessions"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    worker = assert_ok(client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site, "contractor_id": ct["contractor_id"], "name": "Persona histórica",
    }), 201)
    bootstrap(client)
    document = assert_ok(client.post(ROOT + "/catalog", headers=headers, json={
        "name": "Certificado individual histórico", "level": "worker",
    }), 201)
    period = current_month()
    apply_rule(client, headers, rule(document["id"], scope="category", category="CT"))
    assert_ok(client.put(ROOT + "/reviews", headers=headers, json={
        "association_id": ct["id"], "period": period, "subject": worker["id"],
        "document_type_id": document["id"], "state": "approved", "notes": "Validado por responsable",
    }))
    before = summary(client, period)
    with sessions.begin() as db:
        db.get(ContractorWorksite, ct["id"]).historical_code = "CI"
        db.get(WorkerAssignment, worker["id"]).active = False
    monkeypatch.setattr(service, "current_period", lambda: shift_month(period, 1))
    after = summary(client, period)
    for key in ("required", "approved", "compliance"):
        assert before["summary"][key] == after["summary"][key]
    historic = obligation(after, ct["id"], document["code"], period)
    assert historic["subject"] == worker["id"]
    assert historic["category"] == "CT"
    assert historic["state"] == "approved"
    proposed = rule(document["id"], period, scope="association", association_ids=[ct["id"]],
                    required=False, retroactive=True)
    apply_rule(client, headers, proposed)
    corrected = summary(client, period)
    assert obligation(corrected, ct["id"], document["code"], period)["required"] is False
    assert obligation(corrected, ct["id"], "porteria", period)["required"] is True


def test_a_rule_can_be_revised_after_reviewing_its_overlap(config_env):
    client = config_env["client"]
    headers = sign_in(client)
    site = assert_ok(client.get("/api/v1/ops/sites"))[0]["id"]
    ct = company(client, headers, site)
    document = document_type(client, headers)
    apply_rule(client, headers, rule(document["id"]))
    apply_rule(client, headers, rule(document["id"], required=False, reason="Se reemplaza la regla tras revisar el impacto"))
    assert obligation(summary(client), ct["id"], document["code"])["required"] is False
