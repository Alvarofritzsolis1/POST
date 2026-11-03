from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.ops_import import parse_import, valid_rut
from app.ops_models import Contractor, ContractorWorksite, OpsChange, Worker, WorkerAssignment, Worksite
from app.security import hash_password


def _xlsx(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _legacy_bytes():
    return _xlsx([
        ["Código", "Nombre", "RUT", "Sep 2026 Cotizaciones", "Sep 2026 F30-1"],
        ["CT", "Pinturas del Sur", "12.345.678-5", "OK", "P"],
        ["", "Ana Pérez", "11.111.111-1", "P", "NA"],
    ])


def test_legacy_hierarchy_preview_and_rut():
    result = parse_import(_legacy_bytes(), "histórico.xlsx")
    assert [row["kind"] for row in result["rows"]] == ["contractor", "worker"]
    assert result["rows"][1]["contractor_rut"] == "12345678-5"
    assert result["summary"]["historical_marks"] == {"OK": 1, "P": 2, "NA": 1}
    assert result["summary"]["errors"] == 0
    contractor_meta = list(result["rows"][0]["historical_statuses_meta"].values())
    assert [item["period"] for item in contractor_meta] == ["2026-09", "2026-09"]
    assert [item["requirement"] for item in contractor_meta] == ["cotizaciones", "f30_1"]
    assert valid_rut("12.345.678-5")
    assert not valid_rut("12.345.678-9")


def test_flat_csv_does_not_reuse_employer_rut_as_worker_rut():
    source = ("tipo;nombre;rut;codigo_historico;rut_contratista\n"
              "empresa;Pinturas del Sur;12.345.678-5;CT;\n"
              "trabajador;Sin RUT;; ;12.345.678-5\n").encode()
    result = parse_import(source, "lista.csv")
    assert result["rows"][1]["kind"] == "worker"
    assert result["rows"][1]["rut"] == ""
    assert "RUT inválido o ausente" in result["rows"][1]["errors"]
    source_with_two_rut_columns = ("tipo;nombre;rut empresa;rut trabajador\n"
                                   "empresa;Pinturas del Sur;12.345.678-5;\n"
                                   "trabajador;Sin RUT;12.345.678-5;\n").encode()
    result = parse_import(source_with_two_rut_columns, "lista.csv")
    assert result["rows"][1]["rut"] == ""
    assert "RUT inválido o ausente" in result["rows"][1]["errors"]


def test_duplicate_and_bad_rut_visible_in_preview():
    source = ("tipo;nombre;rut;codigo_historico;rut_contratista\n"
              "empresa;Pinturas del Sur;12.345.678-5;CT;\n"
              "empresa;Pinturas del Sur;12.345.678-5;CT;\n"
              "trabajador;Ana Pérez;11.111.111-9;;12.345.678-5\n").encode()
    result = parse_import(source, "lista.csv")
    assert "repetida" in result["rows"][1]["warnings"][0]
    assert result["rows"][2]["errors"] == ["RUT inválido o ausente"]


def test_explicit_column_map_and_strict_rut():
    source = ("clase_legacy;persona_legacy;id_legacy;empresa_legacy\n"
              "empresa;Pinturas del Sur;12.345.678-5;\n"
              "trabajador;Ana Pérez;11.111.111-1;12.345.678-5\n").encode()
    result = parse_import(source, "lista.csv", {
        "kind": "clase_legacy", "name": "persona_legacy", "rut": "id_legacy",
        "contractor_rut": "empresa_legacy",
    })
    assert result["summary"]["errors"] == 0
    assert not valid_rut("abc12.345.678-5")


def test_repeated_month_columns_and_unknown_header_keep_provenance():
    source = _xlsx([
        ["tipo", "nombre", "rut", "2026-10 Cotizaciones", "2026-10 Cotizaciones", "Estado legado"],
        ["empresa", "Pinturas del Sur", "12.345.678-5", "OK", "P", "NA"],
    ])
    result = parse_import(source, "mensual.xlsx")
    row = result["rows"][0]
    assert len(row["historical_statuses"]) == 3
    meta = list(row["historical_statuses_meta"].values())
    assert [item["period"] for item in meta] == ["2026-10", "2026-10", None]
    assert [item["requirement"] for item in meta] == ["cotizaciones", "cotizaciones", None]
    assert any("No se reconoce el período" in warning for warning in row["warnings"])
    assert any("No se reconoce el requisito" in warning for warning in row["warnings"])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "a" * 96)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        org = Organization(name="Empresa de prueba")
        db.add(org)
        db.flush()
        user = User(org_id=org.id, email="admin@example.cl",
                    password_hash=hash_password("contrasena-segura-2026"), role="admin")
        site = Worksite(org_id=org.id, name="Lomas Verdes")
        db.add_all([user, site])
        db.flush()
        site_id = site.id

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as test_client:
            test_client.post("/api/v1/auth/login", json={"email": "admin@example.cl",
                                                    "password": "contrasena-segura-2026"})
            yield test_client, Session, site_id
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()


def _post(client, url, **kwargs):
    return client.post(url, headers={"X-CSRF-Token": client.cookies["galant_post_csrf"]}, **kwargs)


def test_import_requires_confirmed_mapping_and_preserves_origin(client):
    http, Session, site_id = client
    preview = _post(http, "/api/v1/ops/imports/preview",
                    files={"file": ("historico.xlsx", _legacy_bytes())},
                    data={"site_id": site_id})
    assert preview.status_code == 200, preview.text
    body = {"site_id": site_id, "rows": preview.json()["rows"],
            "source_format": "excel", "preview_token": preview.json()["preview_token"]}
    missing = _post(http, "/api/v1/ops/imports/commit", json=body)
    assert missing.status_code == 422
    with Session() as db:
        assert db.scalar(select(Contractor)) is None
    body["historical_status_mapping"] = {
        "OK": "historical_approved", "P": "historical_pending",
        "NA": "historical_not_applicable",
    }
    response = _post(http, "/api/v1/ops/imports/commit", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["created_contractors"] == 1
    assert response.json()["created_workers"] == 1
    assert response.json()["historical_statuses_count"] == 4
    with Session() as db:
        contractor = db.scalar(select(Contractor))
        association = db.scalar(select(ContractorWorksite))
        worker = db.scalar(select(Worker))
        assignment = db.scalar(select(WorkerAssignment))
        assert contractor.rut == "12345678-5"
        assert worker.rut == "11111111-1"
        assert association.historical_code == "CT"
        assert assignment.contractor_id == contractor.id
        assert {item["origin"] for item in assignment.imported_statuses.values()} == {"excel"}
        assert {item["validation"] for item in association.imported_statuses.values()} == {"pending"}
        assert {item["period"] for item in association.imported_statuses.values()} == {"2026-09"}
        assert {item["requirement"] for item in association.imported_statuses.values()} == {"cotizaciones", "f30_1"}
        assert all(item["source_header"].startswith("Sep 2026") for item in association.imported_statuses.values())
        assert db.scalars(select(OpsChange)).first() is not None
    repeated = _post(http, "/api/v1/ops/imports/commit", json=body)
    assert repeated.status_code == 200
    assert repeated.json()["created_contractors"] == 0
    assert repeated.json()["created_workers"] == 0
    assert repeated.json()["historical_statuses_count"] == 0


def test_commit_rejects_unpreviewed_rows_and_invalid_classification(client):
    http, Session, site_id = client
    preview = _post(http, "/api/v1/ops/imports/preview",
                    files={"file": ("historico.xlsx", _legacy_bytes())},
                    data={"site_id": site_id}).json()
    body = {"site_id": site_id, "source_format": "excel", "preview_token": preview["preview_token"],
            "rows": preview["rows"],
            "historical_status_mapping": {"OK": "historical_approved", "P": "historical_pending",
                                          "NA": "historical_not_applicable"}}
    body["rows"][0]["row_id"] = "invented-row"
    assert _post(http, "/api/v1/ops/imports/commit", json=body).status_code == 422
    body["rows"] = preview["rows"]
    body["rows"][0]["nature"] = "cualquier cosa"
    result = _post(http, "/api/v1/ops/imports/commit", json=body)
    assert result.status_code == 422
    with Session() as db:
        assert db.scalar(select(Contractor)) is None


def test_import_atomic_when_worker_employer_missing(client):
    http, Session, site_id = client
    source = ("tipo;nombre;rut;codigo_historico;rut_contratista\n"
              "empresa;Pinturas del Sur;12.345.678-5;CT;\n"
              "trabajador;Ana Pérez;11.111.111-1;;9.876.543-3\n").encode()
    preview = _post(http, "/api/v1/ops/imports/preview",
                    files={"file": ("historico.csv", source)}, data={"site_id": site_id}).json()
    response = _post(http, "/api/v1/ops/imports/commit",
                     json={"site_id": site_id, "rows": preview["rows"], "source_format": "csv",
                           "preview_token": preview["preview_token"]})
    assert response.status_code == 422
    with Session() as db:
        assert db.scalar(select(Contractor)) is None


def test_independent_with_worker_is_rejected_atomically(client):
    http, Session, site_id = client
    source = ("tipo;nombre;rut;codigo_historico;rut_contratista;naturaleza\n"
              "empresa;Pinturas del Sur;12.345.678-5;CI;;independiente\n"
              "trabajador;Ana Pérez;11.111.111-1;;12.345.678-5;\n").encode()
    preview = _post(http, "/api/v1/ops/imports/preview",
                    files={"file": ("historico.csv", source)}, data={"site_id": site_id}).json()
    assert preview["summary"]["errors"] == 0
    result = _post(http, "/api/v1/ops/imports/commit", json={
        "site_id": site_id, "rows": preview["rows"], "source_format": "csv",
        "preview_token": preview["preview_token"],
    })
    assert result.status_code == 422
    with Session() as db:
        assert db.scalar(select(Contractor)) is None


def test_templates_are_downloadable(client):
    http, _, _ = client
    for kind in ("contractors", "workers", "monthly"):
        result = http.get(f"/api/v1/ops/imports/templates/{kind}")
        assert result.status_code == 200
        assert result.content.startswith(b"PK\x03\x04")
        if kind == "monthly":
            workbook = load_workbook(BytesIO(result.content), read_only=True)
            assert len(next(workbook.active.iter_rows(values_only=True))) == 12
            workbook.close()
