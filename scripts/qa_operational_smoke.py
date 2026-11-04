#!/usr/bin/env python3
"""End-to-end operational checks against isolated synthetic GALANT QA only."""
from __future__ import annotations

import csv
import http.cookiejar
import io
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request


BASE = "http://127.0.0.1:18612"
PASSWORD = os.environ.get("QA_SMOKE_PASSWORD", "")


class API:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, path, data=None, method="GET", form=None):
        headers = {"Cache-Control": "no-store"}
        payload = None
        if form is not None:
            boundary = "GALANTQA" + secrets.token_hex(12)
            chunks = []
            for key, (filename, content, mimetype) in form.items():
                chunks.extend([
                    ("--" + boundary + "\r\n").encode(),
                    (f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                     f"Content-Type: {mimetype}\r\n\r\n").encode(),
                    content, b"\r\n",
                ])
            chunks.append(("--" + boundary + "--\r\n").encode())
            payload = b"".join(chunks)
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif data is not None:
            payload = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        if method not in {"GET", "HEAD"}:
            csrf = next((c.value for c in self.jar if c.name == "galant_post_csrf"), "")
            if csrf:
                headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(BASE + "/api/v1" + path, data=payload,
                                         method=method, headers=headers)
        with self.http.open(request, timeout=30) as response:
            body = response.read()
            if "application/vnd.openxmlformats" in response.headers.get("Content-Type", ""):
                return body
            return json.loads(body)

    def login(self, email):
        return self.request("/auth/login", {"email": email, "password": PASSWORD}, "POST")


def rut(number: int) -> str:
    weights = (2, 3, 4, 5, 6, 7)
    total = sum(int(x) * weights[i % 6] for i, x in enumerate(reversed(str(number))))
    dv = 11 - total % 11
    return str(number) + "-" + ("0" if dv == 11 else "K" if dv == 10 else str(dv))


def expect_denied(api: API, path: str, status: int, payload=None, method="GET"):
    try:
        api.request(path, payload, method=method)
    except urllib.error.HTTPError as err:
        assert err.code == status, f"Unexpected HTTP {err.code} (expected {status})"
    else:
        raise AssertionError(f"Una cuenta sin permisos pudo acceder: {path}")


def main():
    if not PASSWORD:
        raise SystemExit("Falta QA_SMOKE_PASSWORD (solo credencial sintética)")
    admin = API()
    reviewer = API()
    viewer = API()
    outside = API()
    admin.login("qa-admin@example.test")
    reviewer.login("qa-reviewer@example.test")
    viewer.login("qa-viewer@example.test")
    outside.login("qa-outside@example.test")

    sites = admin.request("/ops/sites")
    assert len(sites) >= 3
    site_id = next(s["id"] for s in sites if s["name"] == "Concepción")
    other_id = next(s["id"] for s in sites if s["name"] == "Lomas Verdes")
    period = "2026-09"
    name = "QA CONTRATOS Y COTIZACIONES SPA"
    company = admin.request("/ops/contractors", {
        "site_id": site_id, "name": name, "rut": rut(12345678),
        "nature": "with_workers", "frequency": "fixed", "historical_code": "CT",
    }, method="POST")
    assignment = company["id"]
    worker = admin.request("/ops/workers", {
        "site_id": site_id, "contractor_id": company["contractor_id"],
        "name": "Trabajador Sintético Prueba", "rut": rut(87654321),
    }, method="POST")
    # Confirm data is visible to both internal accounts.
    qs = "?site_id=" + site_id
    assert any(c["id"] == assignment for c in reviewer.request("/ops/contractors" + qs))
    assert len(reviewer.request("/ops/workers?site_id=" + site_id
        + "&contractor_id=" + company["contractor_id"])) >= 1
    # Another worksite must not inherit this contractor's month.
    assert not any(c["id"] == assignment for c in admin.request("/ops/contractors?site_id=" + other_id))

    rec = reviewer.request("/control/contributions", {
        "association_id": assignment, "period": period,
        "worker_assignment_id": worker["id"], "attendance_days": 25,
        "required_days": 25, "paid_days": 23, "payment_confirmed": True,
        "daily_rate": 4950, "justification": "", "notes": "QA pago manual",
        "review_status": "pending", "retention_status": "proposed",
    }, method="PUT")
    assert rec["missing_days"] == 2, rec
    assert float(rec["retention_suggested"]) == 9900, rec
    from_admin = admin.request("/control/contributions?period=" + period + "&site_id=" + site_id)
    assert any(x["id"] == rec["id"] and x["missing_days"] == 2 for x in from_admin)
    confirm_payload = {
        "association_id": assignment, "period": period,
        "worker_assignment_id": worker["id"], "attendance_days": 25,
        "required_days": 25, "paid_days": 23, "payment_confirmed": True,
        "daily_rate": 4950, "justification": "", "notes": "Confirmación sintética",
        "review_status": "approved", "retention_status": "confirmed",
    }
    confirmed = admin.request("/control/contributions", confirm_payload, method="PUT")
    assert confirmed["retention_status"] == "confirmed"
    changed = reviewer.request("/control/contributions", {
        **confirm_payload, "paid_days": 24, "retention_status": "proposed",
    }, method="PUT")
    assert changed["review_status"] == "pending"
    assert changed["retention_status"] == "proposed"
    assert changed["missing_days"] == 1
    assert float(changed["retention_suggested"]) == 4950
    expect_denied(admin, "/control/contributions", 422, {
        **confirm_payload, "required_days": 24, "paid_days": 24,
    }, "PUT")

    independent = admin.request("/ops/contractors", {
        "site_id": site_id, "name": "QA INDEPENDIENTE",
        "rut": rut(13579246), "nature": "independent",
        "frequency": "sporadic", "historical_code": "CI",
    }, method="POST")
    independent_paid = admin.request("/control/contributions", {
        "association_id": independent["id"], "period": period,
        "worker_assignment_id": None, "attendance_days": None,
        "required_days": None, "paid_days": None,
        "payment_confirmed": True,
    }, method="PUT")
    assert independent_paid["retention_suggested"] is None
    matrix = reviewer.request("/control/matrix?site_id=" + site_id + "&period=" + period)
    ci = next(c for c in matrix["contractors"] if c["association_id"] == independent["id"])
    assert next(r for r in ci["requirements"] if r["kind"] == "anticipos")["applicable"] is False
    # Un requisito condicional no se puede aprobar antes de definirlo.
    unknown_requirement = {
        "association_id": assignment, "period": period, "kind": "porteria",
        "status": "approved", "notes": "",
    }
    expect_denied(admin, "/control/reviews", 422, unknown_requirement, "POST")
    rule = admin.request("/control/applicability", {
        "association_id": assignment, "period": period, "kind": "porteria",
        "applicable": True, "justification": "Requisito QA de control de acceso",
    }, method="PUT")
    assert rule["applicable"] is True
    manual = admin.request("/control/reviews", unknown_requirement, method="POST")
    assert manual["status"] == "approved"

    # Calendar, contract and reminders are real API records, not local UI cache.
    calendar = admin.request("/control/admin/calendar", {
        "worksite_id": site_id, "period": "2026-10", "kind": "cotizaciones",
        "request_date": "2026-10-31", "due_date": "2026-11-20",
        "alert_date": "2026-11-18",
    }, method="PUT")
    assert calendar["period"] == "2026-10"
    contract = admin.request("/control/admin/contracts", {
        "association_id": assignment, "contract_type": "fixed_term",
        "worker_assignment_id": worker["id"],
        "start_date": "2026-09-01", "end_date": "2026-11-12",
        "status": "active", "notes": "Vigencia QA",
    }, method="POST")
    assert contract["end_date"] == "2026-11-12"

    activity = admin.request("/control/activity", {
        "association_id": assignment, "period": period,
        "status": "no_movements", "reason": "Caso de contradicción sintética",
    }, method="PUT")
    assert activity["status"] == "no_movements"
    tasks = reviewer.request("/control/admin/tasks?site_id=" + site_id)
    assert any(t["kind"] == "review_continuity" for t in tasks)
    alerts = admin.request("/control/admin/alerts?site_id=" + site_id)
    assert any(a["kind"] == "movement_conflict" for a in alerts["alerts"])
    assert admin.request("/control/admin/offboarding?site_id=" + site_id) == []

    # Contract import with an existing contract and a newly added amendment.
    csv_data = io.StringIO()
    writer = csv.writer(csv_data, delimiter=";")
    writer.writerow(["RUT contratista", "RUT trabajador", "Tipo contrato",
                     "Fecha inicio", "Fecha término", "Tipo registro",
                     "Fecha anexo", "Referencia", "Estado contrato", "Observaciones"])
    writer.writerow([rut(12345678), rut(87654321), "Plazo fijo", "01/09/2026",
                     "12/11/2026", "Contrato", "", "BASE-001", "Activo", "QA"])
    writer.writerow([rut(12345678), rut(87654321), "Plazo fijo", "01/09/2026",
                     "30/11/2026", "Anexo", "02/11/2026", "ANEXO-QA-001", "Activo", "QA"])
    # FormData requires site_id as a text field, included by file interface below.
    boundary = "GALANTQA" + secrets.token_hex(12)
    pieces = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="site_id"\r\n\r\n{site_id}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="contratos.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode(),
        csv_data.getvalue().encode(), b"\r\n", f"--{boundary}--\r\n".encode(),
    ]
    csrf = next(c.value for c in admin.jar if c.name == "galant_post_csrf")
    req = urllib.request.Request(BASE + "/api/v1/control/import/contracts/preview",
        data=b"".join(pieces),method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "X-CSRF-Token": csrf})
    with admin.http.open(req, timeout=30) as response:
        preview = json.load(response)
    assert preview["summary"]["errors"] == 0, preview
    committed = admin.request("/control/import/contracts/commit", {
        "site_id": site_id, "rows": preview["rows"],
        "preview_token": preview["preview_token"],
    }, method="POST")
    assert committed["amendments"] == 1 and committed["created"] == 0, committed
    again = admin.request("/control/import/contracts/commit", {
        "site_id": site_id, "rows": preview["rows"],
        "preview_token": preview["preview_token"],
    }, method="POST")
    assert again["unchanged"] == 2, again

    # Reports are generated from persistent data, with separate worksite detail.
    summary = reviewer.request("/control/reports/overview?period=" + period)
    assert summary["totals"]["ct"] >= 1 and summary["totals"]["ci"] >= 1
    graph = reviewer.request("/control/reports/analytics?period=" + period)
    assert graph["distribution"]["ct"] >= 1
    trend = reviewer.request("/control/reports/trends?period=" + period + "&months=2")
    assert len(trend["series"]) == 2
    xlsx = reviewer.request("/control/reports/cotizaciones.xlsx?period=" + period)
    assert xlsx[:2] == b"PK" and len(xlsx) > 350
    xlsx2 = reviewer.request("/control/reports/mensual.xlsx?period=" + period)
    assert xlsx2[:2] == b"PK" and len(xlsx2) > 350

    # Second QA admin verifies shared operational state; Resident has only Red de Obras.
    expect_denied(viewer, "/control/matrix?site_id=" + site_id + "&period=" + period, 403)
    expect_denied(viewer, "/control/reviews", 403, {
        "association_id": assignment, "period": period,
        "kind": "f30_1", "status": "approved", "notes": ""
    }, "POST")
    expect_denied(outside, "/control/matrix?site_id=" + site_id + "&period=" + period, 404)
    print("QA operational flows verified: three worksites, CT/CI, worker, retentions, calendar, contracts, Excel import, XLSX, alerts, permissions")


if __name__ == "__main__":
    main()
