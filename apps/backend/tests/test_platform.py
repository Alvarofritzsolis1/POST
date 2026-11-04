"""Synthetic acceptance cases for shared organizations, bulk imports and monthly totals."""

from io import BytesIO
from datetime import date
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select, func
from app.main import app
from app.models import User
from app.ops_models import Contractor, Worker
from app.control_models import ContractRegister
from app.platform_models import ImportBatch
from test_control_api import login, create_company


def rut(n):
    s = sum(int(d) * f for d, f in zip(str(n)[::-1], (2, 3, 4, 5, 6, 7) * 3))
    check = 11 - s % 11
    return f"{n}-" + ("0" if check == 11 else "K" if check == 10 else str(check))


def excel(headers, rows):
    wb = Workbook()
    wb.active.append(headers)
    for r in rows:
        wb.active.append(r)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def review(client, headers, kind, rows):
    res = client.post(
        "/api/v1/ops/imports/bulk/review",
        headers=headers,
        json={"kind": kind, "rows": rows, "filename": "synthetic.xlsx"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def commit(client, headers, p, approve=True):
    return client.post(
        "/api/v1/ops/imports/bulk/commit",
        headers=headers,
        json={**p["input"], "token": p["token"], "approve_updates": approve},
    )


def test_two_independent_sessions_share_records_without_relogin(env):
    admin, sessions = env
    h = login(admin, "a@example.cl")
    sites = admin.get("/api/v1/ops/sites").json()
    site = sites[0]["id"]
    # Administrative creation necessarily inherits the current organization.
    created = admin.post(
        "/api/v1/admin/users",
        headers=h,
        json={
            "email": "ximena@example.cl",
            "password": "password-valid-2026",
            "role": "admin",
        },
    )
    assert created.status_code == 201, created.text
    with TestClient(app) as ximena:
        hx = login(ximena, "ximena@example.cl")
        assert ximena.get("/api/v1/ops/sites").json() == sites
        c = create_company(admin, h, site, "CT", "Compartida")
        assert (
            ximena.get("/api/v1/ops/contractors", params={"site_id": site}).json()[0][
                "contractor_id"
            ]
            == c["contractor_id"]
        )
        w = admin.post(
            "/api/v1/ops/workers",
            headers=h,
            json={
                "site_id": site,
                "contractor_id": c["contractor_id"],
                "name": "Persona sintética",
                "rut": rut(10000001),
            },
        ).json()
        assert (
            ximena.get("/api/v1/ops/workers", params={"site_id": site}).json()[0]["id"]
            == w["id"]
        )
        assert (
            ximena.patch(
                "/api/v1/ops/contractors/" + c["id"],
                headers=hx,
                json={"name": "Nombre actualizado"},
            ).status_code
            == 200
        )
        assert (
            admin.get("/api/v1/ops/contractors", params={"site_id": site}).json()[0][
                "name"
            ]
            == "Nombre actualizado"
        )
        payment = {
            "association_id": c["id"],
            "subject": w["id"],
            "period": "2026-11",
            "required_days": 30,
            "paid_days": 25,
            "confirmed": True,
        }
        assert (
            admin.put("/api/v1/ops/contributions", headers=h, json=payment).status_code
            == 200
        )
        assert (
            ximena.get(
                "/api/v1/ops/contributions",
                params={"period": "2026-11", "site_id": site},
            ).json()["rows"][0]["missing_days"]
            == 5
        )
        # Existing control module reads exactly the same persisted row.
        old = ximena.get(
            "/api/v1/control/contributions",
            params={"period": "2026-11", "site_id": site},
        ).json()
        assert old[0]["paid_days"] == 25
        assert (
            ximena.get(
                "/api/v1/ops/contributions", params={"period": "2026-11"}
            ).headers["cache-control"]
            == "no-store"
        )


def test_roles_isolation_and_preferences_persist(env):
    c, _ = env
    h = login(c, "a@example.cl")
    site = c.get("/api/v1/ops/sites").json()[0]["id"]
    record = create_company(c, h, site, "CT", "Solo organización A")
    profile = c.get("/api/v1/admin/profile").json()
    prefs = profile["preferences"]
    prefs["appearance"] = "dark"
    prefs["default_site"] = site
    assert c.put("/api/v1/admin/preferences", headers=h, json=prefs).status_code == 200
    assert c.get("/api/v1/admin/profile").json()["preferences"]["appearance"] == "dark"
    h = login(c, "c@example.cl")
    assert (
        c.post(
            "/api/v1/admin/users",
            headers=h,
            json={"email": "new@example.cl", "password": "password-valid-2026"},
        ).status_code
        == 403
    )
    assert (
        c.patch(
            "/api/v1/ops/contractors/" + record["id"],
            headers=h,
            json={"name": "No permitido"},
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/v1/ops/imports/bulk/review",
            headers=h,
            json={"kind": "contractors", "rows": [{"name": "x"}]},
        ).status_code
        == 403
    )
    h = login(c, "outside@example.cl")
    assert (
        c.get(
            "/api/v1/ops/contributions", params={"site_id": site, "period": "2026-11"}
        ).status_code
        == 404
    )
    assert (
        c.patch(
            "/api/v1/ops/contractors/" + record["id"],
            headers=h,
            json={"name": "No permitido"},
        ).status_code
        == 404
    )
    assert c.get("/api/v1/admin/profile").json()["preferences"]["appearance"] == "light"


def test_hundreds_of_companies_multiple_sites_repeat_and_external_ids(env):
    c, sessions = env
    h = login(c, "a@example.cl")
    sites = c.get("/api/v1/ops/sites").json()
    headers = [
        "ID",
        "OBRA",
        "ESPECIALIDAD",
        "NOMBRECONTRATISTA",
        "RUT",
        "COD",
        "ESTADO",
        "TELEFONO",
        "CORREO",
        "REPRESENTANTE LEGAL",
        "RUTR.LEGAL",
    ]
    rows = [
        [
            f"EXT-{n}",
            sites[n % 2]["name"],
            "Electricidad",
            f"Empresa sintética {n}",
            rut(20000000 + n),
            "CT",
            "ACTIVO",
            "",
            "",
            "",
            "",
        ]
        for n in range(300)
    ]
    content = excel(headers, rows)
    p = c.post(
        "/api/v1/ops/imports/bulk/preview",
        headers=h,
        files={"file": ("synthetic.xlsx", content)},
        data={"kind": "contractors"},
    ).json()
    assert p["summary"]["new"] == 300, p
    r = commit(c, h, p)
    assert r.status_code == 200, r.text
    p2 = c.post(
        "/api/v1/ops/imports/bulk/preview",
        headers=h,
        files={"file": ("synthetic.xlsx", content)},
        data={"kind": "contractors"},
    ).json()
    assert p2["summary"]["existing"] == 300, p2["summary"]
    assert commit(c, h, p2).status_code == 200
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Contractor)) == 300
        assert db.scalar(select(func.count()).select_from(ImportBatch)) == 1
        assert (
            db.scalar(select(Contractor)).nature == "unclassified"
        )  # COD alone never assigns CT.
    template = load_workbook(
        BytesIO(c.get("/api/v1/ops/imports/bulk/templates/contractors").content)
    )
    assert list(next(template.active.values)) == headers[:6] + ["NATURALEZA", "FRECUENCIA"] + headers[6:]


def test_hundreds_workers_blank_columns_dates_types_and_history(env):
    c, sessions = env
    h = login(c, "a@example.cl")
    site = c.get("/api/v1/ops/sites").json()[0]
    company = create_company(c, h, site["id"], "CT", "Constructora sintética")
    headers = [
        "NOMBRE CONTRATISTA",
        None,
        "NOMBRE TRABAJADOR",
        "RUT",
        "F.INGRESO",
        "F.TERMINO",
        "CONTRATO",
        "TIPO",
    ]
    rows = [
        [
            "Constructora sintetica",
            "ignorar",
            f"Persona {n}",
            rut(10000000 + n),
            "01/09/2026",
            "",
            f"EXT-{n}",
            "INDEFINIDO" if n % 2 else "POR OBRA",
        ]
        for n in range(300)
    ]
    content = excel(headers, rows)

    def preview():
        r = c.post(
            "/api/v1/ops/imports/bulk/preview",
            headers=h,
            files={"file": ("workers.xlsx", content)},
            data={"kind": "workers", "default_site": site["id"]},
        )
        assert r.status_code == 200, r.text
        return r.json()

    p = preview()
    assert p["summary"]["error"] == 0, p["rows"][0]
    assert commit(c, h, p).status_code == 200
    p = preview()
    assert p["summary"]["existing"] == 300, p["rows"][0]
    assert commit(c, h, p).status_code == 200
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Worker)) == 300
        assert db.scalar(select(func.count()).select_from(ContractRegister)) == 300
    # Finish a project contract then rehire in a later episode without replacing it.
    first = {**p["input"]["rows"][0], "end_date": "30/09/2026"}
    changed = review(c, h, "workers", [first])
    r = commit(c, h, changed)
    assert r.status_code == 200, r.text
    new = {
        **first,
        "start_date": "01/11/2026",
        "end_date": "",
        "contract_type": "POR OBRA",
    }
    r = commit(c, h, review(c, h, "workers", [new]))
    assert r.status_code == 200, r.text
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContractRegister)) == 301
        assert (
            db.scalar(
                select(func.count())
                .select_from(ContractRegister)
                .where(ContractRegister.end_date == date(2026, 9, 30))
            )
            == 1
        )
        assert db.scalar(select(ContractRegister).where(
            ContractRegister.end_date == date(2026, 9, 30))).status == "active"


def test_invalid_rows_observations_updates_and_stale_previews(env):
    c, _ = env
    h = login(c, "a@example.cl")
    site = c.get("/api/v1/ops/sites").json()[0]
    base = {
        "site": site["name"],
        "name": "Empresa",
        "rut": rut(20000001),
        "external_id": "EXT-1",
    }
    p = review(
        c, h, "contractors", [base, {**base, "rut": "12345678-9", "site": "NO EXISTE"}]
    )
    assert p["summary"]["error"] == 1
    assert commit(c, h, p).status_code == 422
    assert c.get("/api/v1/ops/contractors", params={"site_id": site["id"]}).json() == []
    obs = c.post("/api/v1/ops/imports/bulk/observations", headers=h, json=p["input"])
    book = load_workbook(BytesIO(obs.content))
    assert "RUT inválido" in str(list(book.active.values)[2])
    p = review(c, h, "contractors", [base])
    assert commit(c, h, p).status_code == 200
    p = review(c, h, "contractors", [{**base, "name": "Nombre nuevo"}])
    assert p["summary"]["updatable"] == 1
    assert commit(c, h, p, False).status_code == 422
    company = c.get("/api/v1/ops/contractors", params={"site_id": site["id"]}).json()[0]
    assert (
        c.patch(
            "/api/v1/ops/contractors/" + company["id"],
            headers=h,
            json={"name": "Edición concurrente"},
        ).status_code
        == 200
    )
    assert commit(c, h, p).status_code == 409
    tampered = {
        **p["input"],
        "rows": [{**base, "name": "Alterado"}],
        "token": p["token"],
        "approve_updates": True,
    }
    assert (
        c.post("/api/v1/ops/imports/bulk/commit", headers=h, json=tampered).status_code
        == 422
    )


def test_weighted_averages_coverage_rates_excel_and_persistent_review(env):
    c, sessions = env
    h = login(c, "a@example.cl")
    site = c.get("/api/v1/ops/sites").json()[0]["id"]
    a = create_company(c, h, site, "CT", "A")
    b = create_company(c, h, site, "CT", "B")
    for company, days in [(a, 30), (b, 10), (b, 20), (b, None)]:
        w = c.post(
            "/api/v1/ops/workers",
            headers=h,
            json={
                "site_id": site,
                "contractor_id": company["contractor_id"],
                "name": "Sintético " + str(days),
            },
        ).json()
        assert (
            c.put(
                "/api/v1/ops/contributions",
                headers=h,
                json={
                    "association_id": company["id"],
                    "subject": w["id"],
                    "period": "2026-11",
                    "required_days": 30,
                    "paid_days": days,
                    "confirmed": days is not None,
                },
            ).status_code
            == 200
        )
    data = c.get("/api/v1/ops/contributions", params={"period": "2026-11"}).json()
    assert data["summary"]["average_paid_days"] == 20  # (30+10+20)/3, not (30+15)/2
    page = c.get(
        "/api/v1/ops/contributions",
        params={"period": "2026-11", "limit": 1, "offset": 1},
    ).json()
    assert (
        len(page["rows"]) == 1
        and page["total"] == 4
        and page["summary"]["denominator"] == 3
    )
    assert data["summary"]["denominator"] == 3
    assert data["summary"]["without_information"] == 1
    assert data["summary"]["estimated_retention"] == 30 * 4950
    assert (
        c.post(
            "/api/v1/admin/rates",
            headers=h,
            json={"effective_from": "2026-12-01", "daily_clp": 6000},
        ).status_code
        == 201
    )
    # Rates are snapshotted in established controls. New period takes the new rate.
    row = data["rows"][0]
    assert (
        c.put(
            "/api/v1/ops/contributions",
            headers=h,
            json={
                "association_id": row["association_id"],
                "subject": row["subject"],
                "period": "2026-12",
                "required_days": 30,
                "paid_days": 29,
            },
        ).status_code
        == 200
    )
    dec = c.get("/api/v1/ops/contributions", params={"period": "2026-12"}).json()
    assert (
        next(r for r in dec["rows"] if r["subject"] == row["subject"])[
            "estimated_retention"
        ]
        == 6000
    )
    review_body = {
        "association_id": a["id"],
        "period": "2026-11",
        "requirement": "Cotizaciones",
        "state": "approved",
        "observation": "Revisado manualmente",
    }
    assert (
        c.put("/api/v1/ops/document-reviews", headers=h, json=review_body).status_code
        == 200
    )
    matrix = c.get(
        "/api/v1/ops/document-reviews", params={"period": "2026-11", "site_id": site}
    ).json()
    assert (
        next(
            r
            for r in matrix
            if r["subject"] == "contractor"
            and r["association_id"] == a["id"]
            and r["requirement"] == "Cotizaciones"
        )["state"]
        == "approved"
    )
    original = c.get(
        "/api/v1/control/matrix", params={"period": "2026-11", "site_id": site}
    ).json()
    assert original["contractors"][0]["requirements"][0]["state"] == "approved"
    report = c.get("/api/v1/ops/contributions/report", params={"period": "2026-11"})
    assert report.status_code == 200, report.text
    book = load_workbook(BytesIO(report.content))
    assert (
        "Consolidado" in book.sheetnames and "Promedios y cobertura" in book.sheetnames
    )
    assert len(book.worksheets) == 3
    assert (
        c.get("/api/v1/ops/contributions", params={"period": "2026-10"}).json()[
            "summary"
        ]["without_information"]
        == 4
    )


# Run the same acceptance scenarios on PostgreSQL when explicitly configured.
import os
from uuid import uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.db import Base, get_db
from app.models import Organization
from app.security import hash_password


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "s" * 96)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    url = os.getenv("PLATFORM_TEST_DATABASE_URL")
    schema = "platform_test_" + uuid4().hex
    if url:
        admin_engine = create_engine(url)
        with admin_engine.begin() as db:
            db.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        a, b = Organization(name="Principal"), Organization(name="Separada")
        db.add_all([a, b])
        db.flush()
        for email, org, role in [
            ("a@example.cl", a, "admin"),
            ("b@example.cl", a, "admin"),
            ("c@example.cl", a, "resident"),
            ("outside@example.cl", b, "admin"),
        ]:
            db.add(
                User(
                    email=email,
                    org_id=org.id,
                    role=role,
                    password_hash=hash_password("password-valid-2026"),
                )
            )

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()
        if url:
            with admin_engine.begin() as db:
                db.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin_engine.dispose()


def test_cli_link_requires_plan_backup_and_no_operational_data(
    env, monkeypatch, capsys
):
    import sys
    from app import cli

    client, sessions = env
    monkeypatch.setattr(cli, "SessionLocal", sessions)
    argv = [
        "galant",
        "link-user",
        "--email",
        "outside@example.cl",
        "--admin-email",
        "a@example.cl",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with sessions() as db:
        original = db.scalar(
            select(User).where(User.email == "outside@example.cl")
        ).org_id
    cli.main()
    assert "Plan:" in capsys.readouterr().out
    with sessions() as db:
        assert (
            db.scalar(select(User).where(User.email == "outside@example.cl")).org_id
            == original
        )
    monkeypatch.setattr(sys, "argv", argv + ["--apply"])
    with pytest.raises(SystemExit, match="respaldo"):
        cli.main()
    h = login(client, "outside@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    create_company(client, h, site, "CT", "Información que no debe moverse")
    with pytest.raises(SystemExit, match="registros"):
        cli.main()


def test_ambiguous_worker_match_overlapping_dates_and_unknown_type(env):
    c, _ = env
    h = login(c, "a@example.cl")
    site = c.get("/api/v1/ops/sites").json()[0]
    a = create_company(c, h, site["id"], "CT", "EMPRESA DUPLICADA")
    # Existing legacy companies may differ only in accents / punctuation.
    b = create_company(c, h, site["id"], "CT", "Empresa Duplicáda")
    row = {
        "site": site["name"],
        "contractor_name": "Empresa duplicada",
        "name": "Persona Sintética",
        "rut": rut(12340000),
        "start_date": "01/10/2026",
        "contract_type": "indefinido",
    }
    p = review(c, h, "workers", [row])
    assert "ambiguo" in str(p["rows"][0]["errors"])
    p = review(c, h, "workers", [{**row, "contract_type": "DESCONOCIDO"}])
    assert "Tipo de contrato desconocido" in str(p["rows"][0]["errors"])
    # Overlaps must be detected before a single row is committed.
    p = review(c, h, "workers", [row, {**row, "start_date": "02/10/2026"}])
    assert "superpuestas" in str(p["rows"][1]["errors"])
