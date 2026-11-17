"""Synthetic teaching/approval/tenant isolation, informal Spanish and safe fallback."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from threading import Event
from zipfile import ZipFile

import fitz
import pytest
from sqlalchemy import select, text

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.galancito_triage import analyze, quick_reply
from app.galancito_knowledge import retrieve
from app.galancito_knowledge_models import AssistantRun
from app.galancito_knowledge_api import extract_document
from app.galancito_flow import grounded_reply
from app.models import User
from app import galancito_local
from app.galancito_runtime import infer
from test_network import network as network, request_body
from test_facebook_crm import enable_messaging, incoming

CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("galancito_evaluation.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"] + "-" + c["message"])
def test_informal_spanish_evaluation(case):
    result = analyze(case["message"])
    assert result.intent == case["intent"]
    assert result.entity_type == case["entity_type"]
    assert result.specialty == case["specialty"]
    if "workers" in case:
        assert result.workers == case["workers"]
    answer = quick_reply(case["message"])
    if answer:
        assert len(answer) <= 650
        assert answer.count("?") <= 1
        assert "Galancito" in answer
        assert "contratación garantizada" not in answer


def knowledge(n, **kwargs):
    body = dict(title="Coordinación demostración", kind="correction", scope="red_obras",
                phrases=["orientación demostración"], content="Soy Galancito. Coordina primero una revisión con administración.")
    body.update(kwargs)
    response = n["send"](n["admin"], "/galancito/knowledge", body)
    assert response.status_code == 201, response.text
    return response.json(), body


def approve(n, row, state="approved"):
    response = n["send"](n["admin"], f'/galancito/knowledge/{row["id"]}/state',
                         {"version": row["version"], "state": state})
    assert response.status_code == 200, response.text
    return response.json()


def chat(n, message="orientación demostración"):
    response = n["send"](n["admin"], "/galancito/chat", {"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def test_learning_only_after_approval_edit_and_deactivation(network, monkeypatch):
    n = network
    monkeypatch.setenv("GALANCITO_AI_ENABLED", "false")
    settings.cache_clear()
    row, body = knowledge(n)
    assert row["status"] == "pending"
    assert chat(n)["source"] != "knowledge"
    approved = approve(n, row)
    learned = chat(n)
    assert learned["source"] == "knowledge"
    assert body["content"] == learned["answer"]
    assert learned["references"][0]["version"] == approved["version"]
    stale = n["send"](n["admin"], f'/galancito/knowledge/{row["id"]}/state', {"version": row["version"], "state": "disabled"})
    assert stale.status_code == 409
    body["content"] = "Soy Galancito. Usa el procedimiento corregido por administración."
    changed = n["send"](n["admin"], f'/galancito/knowledge/{row["id"]}', {**body, "version": approved["version"]}, "PUT")
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "pending"
    assert chat(n)["source"] != "knowledge"
    updated = approve(n, changed.json())
    assert body["content"] == chat(n)["answer"]
    approve(n, updated, "disabled")
    assert chat(n)["source"] != "knowledge"
    versions = n["admin"].get(f'/api/v1/network/galancito/knowledge/{row["id"]}/versions').json()
    assert len(versions) == 5
    assert versions[-1]["snapshot"]["content"] != versions[0]["snapshot"]["content"]


def test_knowledge_roles_tenants_and_channels(network):
    n = network
    row, body = knowledge(n)
    outside = n["login"]("outside@network.example.cl")
    assert n["a"].get("/api/v1/network/galancito/knowledge").status_code == 403
    assert n["send"](n["a"], "/galancito/knowledge", body).status_code == 403
    assert outside.get("/api/v1/network/galancito/knowledge").json() == []
    assert n["send"](outside, f'/galancito/knowledge/{row["id"]}/state', {"version": 1, "state": "approved"}).status_code == 404
    approve(n, row)
    with n["Session"]() as db:
        admin = db.scalar(select(User).where(User.email == "admin@network.example.cl"))
        assert retrieve(db, admin.org_id, "orientación demostración", "red_obras")
        assert not retrieve(db, admin.org_id, "orientación demostración", "messenger")
        other = db.scalar(select(User).where(User.email == "outside@network.example.cl"))
        assert not retrieve(db, other.org_id, "orientación demostración", "red_obras")


def test_explicit_feedback_proposes_pending_correction_without_storing_chat(network):
    n = network
    result = chat(n)
    _, body = knowledge(n, title="Otro conocimiento")
    response = n["send"](n["admin"], f'/galancito/runs/{result["run_id"]}/feedback',
                         {"rating": "incorrect", "correction": body})
    assert response.status_code == 200, response.text
    assert response.json()["proposal"]["status"] == "pending"
    assert chat(n)["source"] != "knowledge"
    approve(n, response.json()["proposal"])
    assert chat(n)["source"] == "knowledge"
    assert n["send"](n["a"], f'/galancito/runs/{result["run_id"]}/feedback', {"rating": "useful"}).status_code == 404
    with n["Session"]() as db:
        run = db.get(AssistantRun, result["run_id"])
        assert run.feedback == "incorrect"
        assert not hasattr(run, "message") and not hasattr(run, "answer")


def test_examples_are_pending_idempotent_and_privacy_checked(network):
    n = network
    result = n["send"](n["admin"], "/galancito/knowledge-examples")
    assert result.status_code == 201, result.text
    assert result.json()["created"] == 12
    assert n["send"](n["admin"], "/galancito/knowledge-examples").json()["created"] == 0
    rows = n["admin"].get("/api/v1/network/galancito/knowledge").json()
    assert all(r["status"] == "pending" for r in rows)
    for change in ({"title": "   "}, {"content": "RUT 12.345.678-5"}, {"phrases": ["clave unica: secreto"]}):
        bad = n["send"](n["admin"], "/galancito/knowledge", {"title": "Prueba", "content": "Contenido ejemplo", **change})
        assert bad.status_code == 422


def test_document_import_never_autoapproves(network):
    n = network
    uri = "/api/v1/network/galancito/knowledge-import"
    response = n["admin"].post(uri, files={"file": ("guia.txt", b"Procedimiento de ejemplo para revision.", "text/plain")},
                             headers={"X-CSRF-Token": n["admin"].cookies.get("galant_post_csrf", "")})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["scope"] == "red_obras"
    with fitz.open() as doc:
        doc.new_page().insert_text((20, 50), "Synthetic approved procedure draft")
        assert "Synthetic" in extract_document(doc.tobytes(), ".pdf")
    out = BytesIO()
    with ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Guia sintetica.</w:t></w:r></w:p></w:document>')
    assert "Guia" in extract_document(out.getvalue(), ".docx")
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        extract_document(b"invalid", ".docx")


def test_quick_responses_never_invoke_model_and_unknown_query_falls_back(network, monkeypatch):
    n = network
    for k,v in {"GALANCITO_AI_ENABLED": "true", "GALANCITO_AI_PROVIDER": "ollama", "GALANCITO_LOCAL_AI_ENABLED": "true"}.items():
        monkeypatch.setenv(k,v)
    settings.cache_clear()
    calls = []
    def failing(*args):
        calls.append(args)
        raise RuntimeError("offline")
    monkeypatch.setattr("app.galancito_api.generate_internal_text", failing)
    for case in CASES:
        if quick_reply(case["message"]):
            assert chat(n, case["message"])["source"] == "local"
    assert not calls
    assert chat(n, "Consulta compleja sobre coordinación")['source'] == "fallback"
    assert len(calls) == 1
    assert chat(n, "mi RUT es 12.345.678-5")["notice"]
    assert len(calls) == 1


def test_postgres_shared_gate_and_migration_are_idempotent(network):
    n = network
    from app.migrations.v20_7_5_galancito_learning import upgrade
    with n["engine"].begin() as conn:
        upgrade(conn); upgrade(conn)
    if n["dialect"] != "postgres":
        return
    with n["Session"].begin() as first, n["Session"].begin() as second:
        assert first.scalar(text("SELECT pg_try_advisory_xact_lock(2075001)"))
        with pytest.raises(RuntimeError, match="ocupado"):
            infer(second, lambda: "must not run")
    with n["Session"].begin() as db:
        assert infer(db, lambda: "available") == "available"


def test_local_metrics_config_timeout_and_bounded_concurrency(monkeypatch):
    monkeypatch.setenv("GALANCITO_KEEP_ALIVE", "2m")
    monkeypatch.setenv("GALANCITO_NUM_PREDICT", "60")
    settings.cache_clear()
    monkeypatch.setattr(galancito_local, "available_memory_mb", lambda: 8000)
    entered, finish = Event(), Event()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, length):
            return json.dumps({"message": {"content": "Hola"}, "load_duration": 2_000_000,
                               "prompt_eval_duration": 3_000_000, "eval_duration": 5_000_000}).encode()
    def fake(req, timeout):
        payload = json.loads(req.data)
        assert payload["keep_alive"] == "2m" and payload["options"]["num_predict"] == 60
        assert payload["think"] is False and timeout <= 24
        entered.set(); assert finish.wait(5)
        return Response()
    monkeypatch.setattr(galancito_local._opener, "open", fake)
    with ThreadPoolExecutor(max_workers=3) as pool:
        running = pool.submit(galancito_local.generate_local_text, "System", "Hello")
        assert entered.wait(5)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="ocupado"):
                galancito_local.generate_local_text("System", "Hello")
        finish.set(); assert running.result() == "Hola"
    settings.cache_clear()


def test_memory_pressure_unloads_without_inference(monkeypatch):
    monkeypatch.setattr(galancito_local, "available_memory_mb", lambda: 100)
    payloads = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(galancito_local._opener, "open", lambda req, **kwargs: payloads.append(json.loads(req.data)) or Response())
    with pytest.raises(RuntimeError, match="memoria"):
        galancito_local.generate_local_text("System", "Hello")
    assert payloads == [{"model": "qwen3:1.7b", "keep_alive": 0}]


@pytest.mark.parametrize("unsafe", ["Sueldo $999999", "Te contratamos", "Envía tu RUT", "Visita https://inventada.example"])
def test_generated_facts_and_promises_are_rejected(unsafe):
    assert grounded_reply(unsafe, "No hay datos comerciales confirmados.") is None


def test_messenger_revocation_during_inference_prevents_sending(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    for k,v in {"FACEBOOK_AI_AUTO_REPLY_ENABLED": "true", "FACEBOOK_AI_ENABLED": "true",
                "FACEBOOK_AI_PROVIDER": "ollama", "GALANCITO_LOCAL_AI_ENABLED": "true"}.items():
        monkeypatch.setenv(k,v)
    settings.cache_clear()
    assert incoming(n, text="Explícame una coordinación compleja", mid="intro").status_code == 200
    sent=[]
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *a: sent.append(a) or "sent-1")
    assert process_chat_next(n["Session"])
    assert incoming(n, text="sí", mid="consent").status_code == 200
    def revoke(*args):
        assert incoming(n, text="no quiero IA", mid="revocation").status_code == 200
        return "Soy Galancito. Respuesta pendiente."
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", revoke)
    assert process_chat_next(n["Session"])
    assert len(sent) == 1


def test_messenger_preserves_facts_without_creating_a_contractor(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="busco pega de carpintero", mid="worker").status_code == 200
    first = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert first["entity_type"] == "individual" and first["specialty"] == "Carpintería"
    assert incoming(n, text="tengo 4 trabajadores disponibles", mid="team").status_code == 200
    updated = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert updated["workers"] == 4 and updated["specialty"] == "Carpintería"
    answer = quick_reply("tengo 4 trabajadores disponibles", known=updated)
    assert "cuántas" not in answer and "Qué trabajo" not in answer


def test_live_red_data_uses_public_fields_and_excludes_private_notes(network, monkeypatch):
    n = network
    body = request_body(n)
    assert n["send"](n["a"], "/requirements", body).status_code == 201
    for k,v in {"GALANCITO_AI_ENABLED": "true", "GALANCITO_AI_PROVIDER": "ollama",
                "GALANCITO_LOCAL_AI_ENABLED": "true"}.items():
        monkeypatch.setenv(k,v)
    settings.cache_clear()
    def generate(instructions, supplied, limit):
        assert body["title"] in supplied
        assert '"workers": 3' in supplied
        assert body["description"] not in supplied
        assert "disponibilidad_declarada" in supplied and "adjudicaciones" in supplied
        return "Soy Galancito. Las necesidades publicadas requieren revisión del equipo."
    monkeypatch.setattr("app.galancito_api.generate_internal_text", generate)
    assert chat(n, "Explica cómo organizar una coordinación de servicios")["source"] == "ai"


def test_only_approved_administrative_aliases_are_understood(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    guide = {"trade": "Terminaciones especiales", "aliases": ["terminero"],
             "explanation": "Orientación para terminaciones.", "approved": False}
    assert n["send"](n["admin"], "/facebook/guides/terminaciones", guide, "PUT").status_code == 200
    assert incoming(n, text="soy terminero", mid="draft-alias").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert not lead["specialty"]
    guide["approved"] = True
    assert n["send"](n["admin"], "/facebook/guides/terminaciones", guide, "PUT").status_code == 200
    assert incoming(n, text="soy terminero", mid="approved-alias").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["specialty"] == "Terminaciones especiales"


def test_refusal_cancels_permission_question_that_has_not_been_sent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    for k,v in {"FACEBOOK_AI_AUTO_REPLY_ENABLED": "true", "FACEBOOK_AI_ENABLED": "true",
                "FACEBOOK_AI_PROVIDER": "ollama", "GALANCITO_LOCAL_AI_ENABLED": "true"}.items():
        monkeypatch.setenv(k,v)
    settings.cache_clear()
    assert incoming(n, text="hola", mid="ask-consent").status_code == 200
    assert incoming(n, text="no", mid="refuse-immediately").status_code == 200
    sent=[]
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *args: sent.append(args[2]) or "refused-message")
    assert process_chat_next(n["Session"])
    assert len(sent) == 1 and "autorizas" not in sent[0]
    assert "no usaré IA" in sent[0]


def test_tracking_preserves_manual_trade_when_new_messages_offer_another(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="soy carpintero", mid="message-trade").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["specialty"] == "Carpintería" and lead["specialty_source"] == "message"
    pending = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()
    assert pending["rows"][0]["category_source"] == "sin_datos"
    update = n["send"](n["admin"], "/facebook/leads/" + lead["id"], {
        "specialty": "Gasfitería", "follow_up_on": "2026-11-18",
        "follow_up_note": "Confirmar con el residente",
    }, "PATCH")
    assert update.status_code == 200, update.text
    assert incoming(n, text="soy pintor", mid="another-trade").status_code == 200
    saved = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["lead"]
    assert saved["specialty"] == "Gasfitería" and saved["specialty_source"] == "manual"
    assert saved["follow_up_note"] == "Confirmar con el residente"
    tracking = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()
    assert tracking["rows"][0]["category_source"] == "declarada"


def test_learning_migration_adds_trade_origin_to_20_7_4_records(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="hola", mid="old-contact").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert n["send"](n["admin"], "/facebook/leads/" + lead["id"], {
        "specialty": "Pintura", "follow_up_note": "Seguimiento histórico",
    }, "PATCH").status_code == 200
    from app.migrations.v20_7_5_galancito_learning import upgrade
    with n["engine"].begin() as conn:
        conn.execute(text("ALTER TABLE facebook_leads DROP COLUMN specialty_source"))
        upgrade(conn)
        upgrade(conn)
    saved = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["lead"]
    assert saved["specialty"] == "Pintura" and saved["specialty_source"] == "manual"
    assert saved["follow_up_note"] == "Seguimiento histórico"
