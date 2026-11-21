"""Acceptance: internal report exports and consented web search are scoped and safe."""
from io import BytesIO
from zipfile import ZipFile
from urllib.parse import parse_qs, urlsplit
import json
import xml.etree.ElementTree as ET

import fitz
from openpyxl import load_workbook
import pytest

from test_network import network, request_body
from app.galancito_web import WebSearchUnavailable, public_query, public_search


def _post(n, user, route, body):
    return n["send"](user, "/galancito/" + route, body)


@pytest.mark.parametrize("kind", ["pdf", "xlsx", "docx"])
def test_internal_report_formats_are_real_and_private(network, kind):
    n = network
    requirement = request_body(n)
    assert n["send"](n["a"], "/requirements", requirement).status_code == 201
    q = "Informe de necesidades para Brisas de Junquillar"
    r = _post(n, n["admin"], "report", {"question": q, "kind": kind})
    assert r.status_code == 200, r.text[:500] if r.status_code != 200 else ""
    assert "attachment" in r.headers["content-disposition"]
    assert "no-store" in r.headers["cache-control"]
    assert len(r.content) > 200
    if kind == "pdf":
        with fitz.open(stream=r.content, filetype="pdf") as pdf:
            text = "\n".join(page.get_text() for page in pdf)
            assert "GALANT" in text
            assert "Necesidades vigentes: 1" in text
    elif kind == "xlsx":
        wb = load_workbook(BytesIO(r.content), data_only=True)
        sheet = wb.active
        assert sheet["A5"].value == "Resumen"
        assert "Necesidades vigentes: 1" in sheet["B5"].value
    else:
        with ZipFile(BytesIO(r.content)) as package:
            xml = package.read("word/document.xml")
            ET.fromstring(xml)  # actual parseable OOXML
            assert b"GALANT" in xml
            assert b"Necesidades vigentes: 1" in xml


def test_internal_reports_respect_site_scope_and_refuse_unsupported(network):
    n = network
    first = request_body(n)
    second = request_body(n)
    second["site_id"] = n["sites"][1]
    second["title"] = "Otra obra"
    assert n["send"](n["a"], "/requirements", first).status_code == 201
    assert n["send"](n["b"], "/requirements", second).status_code == 201
    r = _post(n, n["a"], "report", {
        "question": "Informe de necesidades", "kind": "xlsx",
    })
    assert r.status_code == 200
    sheet = load_workbook(BytesIO(r.content), data_only=True).active
    assert "Necesidades vigentes: 1" in sheet["B5"].value
    no_doc_access = _post(n, n["a"], "report", {
        "question": "Documentación de octubre 2026", "kind": "pdf",
    })
    assert no_doc_access.status_code == 422
    no_fake_research = _post(n, n["admin"], "report", {
        "question": "Busca en internet las normas", "kind": "pdf",
    })
    assert no_fake_research.status_code == 422


def test_public_web_requires_user_opt_in_and_protects_private_data(network, monkeypatch):
    n = network
    monkeypatch.setenv("GALANCITO_BRAVE_SEARCH_API_KEY", "synthetic-key-only")
    calls = []
    def fake_public_search(query):
        calls.append(query)
        return {"query": query, "searched_at": "2026-11-21T22:00:00+00:00",
                "results": [{"title": "Fuente oficial", "snippet": "Guía de referencia",
                             "url": "https://www.ejemplo.cl/norma"}]}
    monkeypatch.setattr("app.galancito_api.public_search", fake_public_search)
    status = n["admin"].get("/api/v1/network/galancito/status")
    assert status.status_code == 200
    assert status.json()["web_available"] is True
    no_opt_in = _post(n, n["admin"], "chat", {
        "area": "interno", "message": "Busca en internet normativa",
    })
    assert no_opt_in.status_code == 200
    assert not calls
    with_opt_in = _post(n, n["admin"], "chat", {
        "area": "interno", "message": "Normativa pública de construcción Chile", "allow_web": True,
    })
    assert with_opt_in.status_code == 200, with_opt_in.text
    assert calls == ["Normativa pública de construcción Chile"]
    assert "https://www.ejemplo.cl/norma" in with_opt_in.json()["answer"]
    assert with_opt_in.json()["reportable"] is False
    assert with_opt_in.json()["source"] == "public_web"


@pytest.mark.parametrize("query", [
    "RUT 12.345.678-5 para consulta",
    "contacta usuario@gmail.com",
    "mi contraseña es muy secreta",
    "token ABC-123 secreto",
    "escribe al +56 9 1234 5678",
])
def test_web_search_rejects_sensitive_questions(query):
    with pytest.raises(WebSearchUnavailable):
        public_query(query)


def test_public_search_never_follows_results_or_contacts_arbitrary_hosts(monkeypatch):
    monkeypatch.setenv("GALANCITO_BRAVE_SEARCH_API_KEY", "synthetic-key-only")
    class DummyResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, length):
            return json.dumps({"web": {"results": [
                {"title": "Oficial", "description": "Contenido público", "url": "https://gob.cl/guia"},
                {"title": "Inseguro", "description": "Omitir", "url": "http://127.0.0.1:8000/private"},
            ]}}).encode()
    class FakeOpener:
        def open(self, req, timeout):
            assert urlsplit(req.full_url).hostname == "api.search.brave.com"
            assert parse_qs(urlsplit(req.full_url).query)["q"] == ["normativa construcción Chile"]
            assert timeout == 5
            return DummyResponse()
    response = public_search("normativa construcción Chile", opener=FakeOpener())
    assert len(response["results"]) == 1
    assert response["results"][0]["url"] == "https://gob.cl/guia"


def test_spreadsheet_and_docx_escape_user_supplied_formulas_and_xml_controls():
    from app.galancito_reports import export_internal_report
    fake = {
        "title": "GALANT | Informe",
        "date": "2026-11-21",
        "scope": '=HYPERLINK("http://malicioso.example")',
        "summary": "Resumen confiable",
        "intent": "overview", "source": "Fuente autorizada",
        "limitations": "Observaciones" + chr(1) + " sin controles extraños",
    }
    excel = load_workbook(BytesIO(export_internal_report(fake, "xlsx")), data_only=False)
    assert excel.active["B3"].data_type == "s"
    assert excel.active["B3"].value.startswith("'=")
    with ZipFile(BytesIO(export_internal_report(fake, "docx"))) as package:
        xml = package.read("word/document.xml")
        ET.fromstring(xml)
        assert b"HYPERLINK" in xml
        assert b"\x01" not in xml


def test_external_search_does_not_send_private_worksite_names(network, monkeypatch):
    n = network
    monkeypatch.setenv("GALANCITO_BRAVE_SEARCH_API_KEY", "synthetic-key-only")
    calls = []
    monkeypatch.setattr("app.galancito_api.public_search",
                        lambda query: calls.append(query))
    denied = n["send"](n["admin"], "/galancito/chat", {
        "area": "interno",
        "message": "Investiga normativas de Brisas de Junquillar",
        "allow_web": True,
    })
    assert denied.status_code == 200, denied.text
    assert "datos internos de GALANT" in denied.json()["answer"]
    assert denied.json()["source"] == "local"
    assert not calls
