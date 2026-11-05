"""GALANT 15.0.3 acceptance: the six-column import, COD and contract alerts."""
from datetime import timedelta
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select

from app.control_api import today
from app.ops_models import WorkerAssignment
from test_control_api import login, create_company
from test_platform import rut, excel


COLUMNS = ["NOMBRE CONTRATISTA", "NOMBRE TRABAJADOR", "RUT",
           "F.INGRESO", "F.TERMINO", "COD"]


def _preview(client, headers, site_id, values, cols=COLUMNS):
    return client.post(
        "/api/v1/ops/imports/bulk/preview",
        headers=headers,
        files={"file": ("trabajadores.xlsx", excel(cols, values))},
        data={"kind": "workers", "default_site": site_id},
    )


def test_six_column_template_codes_and_alerts(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    create_company(client, headers, site["id"], "CT", "Empresa COD")
    template = load_workbook(BytesIO(
        client.get("/api/v1/ops/imports/bulk/templates/workers").content))
    assert list(next(template.active.values)) == COLUMNS
    future = today() + timedelta(days=5)
    start = (today() - timedelta(days=90)).strftime("%d-%m-%Y")
    rows = [
        ["Empresa COD", "Juan con vencimiento", rut(18100001),
         start, future.strftime("%d-%m-%Y"), "TH"],
        ["Empresa COD", "Maria indefinida", rut(18100002),
         start, "INDEFINIDO", "TM"],
        ["Empresa COD", "Pedro finiquitado", rut(18100003),
         start, "INDEFINIDO", "F"],
    ]
    result = _preview(client, headers, site["id"], rows)
    assert result.status_code == 200, result.text
    preview = result.json()
    assert preview["summary"]["error"] == 0, preview["rows"]
    assert {row["row"]["worker_code"] for row in preview["rows"]} == {"TH", "TM", "F"}
    commit = client.post("/api/v1/ops/imports/bulk/commit", headers=headers,
                         json={**preview["input"], "token": preview["token"]})
    assert commit.status_code == 200, commit.text
    with sessions() as db:
        active = db.scalars(select(WorkerAssignment)).all()
        assert {a.imported_statuses["worker_code"] for a in active} == {"TH", "TM", "F"}
        assert sum(not a.active for a in active) == 1
    alerts = client.get("/api/v1/labor/contract-alerts", params={"site_id": site["id"]})
    assert alerts.status_code == 200, alerts.text
    by_name = {row["worker"]: row for row in alerts.json()["rows"]}
    assert by_name["Juan con vencimiento"]["state"] == "urgent"
    assert by_name["Juan con vencimiento"]["days_remaining"] == 5
    assert by_name["Maria indefinida"]["state"] == "indefinite"
    assert by_name["Pedro finiquitado"]["state"] == "inactive"
    # Editing F only changes operational activity, not legal termination evidence.
    assignment = by_name["Juan con vencimiento"]["assignment_id"]
    update = client.patch(f"/api/v1/labor/workers/{assignment}/code", headers=headers,
                          json={"worker_code": "F"})
    assert update.status_code == 200, update.text
    latest = client.get("/api/v1/labor/contract-alerts",
                        params={"site_id": site["id"]}).json()["rows"]
    assert next(item for item in latest if item["assignment_id"] == assignment)["state"] == "inactive"
    reactivate = client.patch(f"/api/v1/labor/workers/{assignment}/code", headers=headers,
                              json={"worker_code": "TH"})
    assert reactivate.status_code == 200, reactivate.text
    assert reactivate.json()["active"] is True
    assert _preview(client, headers, site["id"], rows).json()["summary"]["existing"] == 3


def test_six_columns_are_strict_and_code_must_be_valid(env):
    client, _ = env
    headers = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    create_company(client, headers, site["id"], "CT", "Empresa Estricta")
    start = (today() - timedelta(days=1)).strftime("%d-%m-%Y")
    row = ["Empresa Estricta", "Persona Uno", rut(18200001), start, "INDEFINIDO", "TH"]
    wrong = _preview(client, headers, site["id"], [row + ["extra"]], COLUMNS + ["TIPO"])
    assert wrong.status_code == 422
    no_site = _preview(client, headers, "", [row])
    assert no_site.status_code == 422
    invalid = _preview(client, headers, site["id"], [{*{}}]) if False else _preview(
        client, headers, site["id"], [row[:5] + ["XX"]])
    assert invalid.status_code == 200, invalid.text
    assert "COD de trabajador inválido" in str(invalid.json()["rows"][0]["errors"])
    empty_end = _preview(client, headers, site["id"], [row[:4] + ["", "TH"]])
    assert empty_end.status_code == 200
    assert "F.TERMINO obligatorio" in str(empty_end.json()["rows"][0]["errors"])
