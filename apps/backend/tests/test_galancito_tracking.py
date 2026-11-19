"""Galancito Ads + Red de Obras pipeline: grounded, auditable, privacy-safe."""
from datetime import date

from app.config import settings
from app.facebook_crm_models import FacebookLead
from app.galancito_triage import classify_lead, dashboard
from app.models import utcnow
from test_facebook_crm import enable_messaging, incoming
from test_network import network, request_body


def test_tracking_requires_admin_and_shows_uncertainty_without_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="ola soy gasfite", mid="m-tr-1").status_code == 200
    response = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento")
    assert response.status_code == 200, response.text
    worklist = response.json()
    assert worklist["total"] == 1
    assert worklist["unlinked"] == 1
    assert worklist["rows"][0]["category"] == "Por confirmar"
    assert worklist["rows"][0]["category_source"] == "sin_datos"
    assert worklist["rows"][0]["human_review_required"] is True
    assert n["a"].get("/api/v1/network/facebook/galancito/seguimiento").status_code == 403


def test_followup_deadline_and_note_persist_and_dont_approve_candidate(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, mid="m-tr-2").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    result = n["send"](n["admin"], "/facebook/leads/" + lead["id"], {
        "follow_up_on": "2020-01-01",
        "follow_up_note": "Hablar con residente antes de asignar",
        "specialty": "Gasfitería",
        "status": "contacting",
    }, "PATCH")
    assert result.status_code == 200, result.text
    assert result.json()["follow_up_note"] == "Hablar con residente antes de asignar"
    assert result.json()["follow_up_on"] == "2020-01-01"
    assert result.json()["status"] == "contacting"
    worklist = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()
    assert worklist["overdue"] == 1
    assert worklist["urgent"] == 1
    row = worklist["rows"][0]
    assert row["stage"] == "Seguimiento vencido"
    assert row["category_source"] == "declarada"
    assert row["follow_up_on"] == "2020-01-01"
    assert row["suggestion_only"] is True
    assert n["send"](n["a"], "/facebook/leads/" + lead["id"],
                     {"follow_up_note": "forged"}, "PATCH").status_code == 403
    assert n["send"](n["admin"], "/facebook/leads/" + lead["id"],
                     {"follow_up_note": "a" * 300}, "PATCH").status_code == 422


def test_auto_category_uses_only_consented_messages_and_approved_guides(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    for k, v in {
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "FACEBOOK_AI_ENABLED": "true",
        "FACEBOOK_AI_AUTO_REPLY_ENABLED": "true",
        "FACEBOOK_AI_API_KEY": "",
    }.items():
        monkeypatch.setenv(k, v)
    settings.cache_clear()
    guide = {
        "trade": "Gasfitería", "aliases": ["gasfiter", "maestro sanitario"],
        "explanation": "Instala y repara cañerías", "document_guidance": [],
        "approved": True,
    }
    assert n["send"](n["admin"], "/facebook/guides/gasfiteria", guide, "PUT").status_code == 200
    assert incoming(n, text="ola soy gasfiter", mid="m-cat-1").status_code == 200
    before = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()
    assert before["rows"][0]["category"] == "Por confirmar"
    assert incoming(n, text="¿Cuáles son los requisitos para postular?", mid="m-cat-permission").status_code == 200
    requested = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert requested["ai_consent_state"] == "requested"
    assert incoming(n, text="sí", mid="m-cat-2").status_code == 200
    after = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()
    assert after["rows"][0]["category"] == "Gasfitería"
    assert after["rows"][0]["category_source"] == "sugerida"
    assert after["rows"][0]["status"] == "new"
    settings.cache_clear()


def test_analisis_no_auto_changes_and_ollama_requires_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="soy carpintero", mid="m-triage-1").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    calls = []
    monkeypatch.setattr("app.facebook_crm.generate_triage_note",
                        lambda text: calls.append(text) or "Revisar especialidad con el residente.")
    before = n["send"](n["admin"], "/facebook/leads/" + lead["id"] + "/galancito/analyze")
    assert before.status_code == 200, before.text
    assert before.json()["source"] == "reglas"
    assert before.json()["changes_applied"] is False
    assert not calls
    assert n["a"].post("/api/v1/network/facebook/leads/" + lead["id"] +
                       "/galancito/analyze").status_code == 403
    # Authorized consent arrives through webhook, never by forging admin fields.
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "true")
    settings.cache_clear()
    # The first contact was received before the assistant was enabled.
    # Another message triggers the permission request, then yes grants consent.
    assert incoming(n, text="Hola de nuevo", mid="m-triage-2").status_code == 200
    assert incoming(n, text="Sí", mid="m-triage-3").status_code == 200
    after = n["send"](n["admin"], "/facebook/leads/" + lead["id"] + "/galancito/analyze")
    assert after.status_code == 200
    assert after.json()["source"] == "ia_local"
    assert after.json()["ai_note"]
    assert len(calls) == 1
    assert after.json()["changes_applied"] is False
    saved = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()
    assert saved["lead"]["status"] == "new"
    settings.cache_clear()


def test_local_ad_draft_grounded_in_real_requirement_not_auto_published(network, monkeypatch):
    n = network
    requirement = request_body(n)
    requirement["title"] = "Carpintería interior, obra de prueba"
    requirement["specialty"] = "Carpintería"
    requirement["publish_to_facebook"] = False
    made = n["send"](n["a"], "/requirements", requirement)
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    settings.cache_clear()
    monkeypatch.setattr("app.facebook_ai.generate_ad_opening",
                        lambda title, trade: "Buscamos especialistas en Carpintería")
    draft = n["send"](n["admin"], "/facebook/requirements/" + rid + "/ad-draft")
    assert draft.status_code == 200, draft.text
    assert draft.json()["source"] == "ia_local"
    assert "Dotación estimada:" in draft.json()["draft"]
    assert "Carpintería" in draft.json()["draft"]
    assert "Inicio estimado:" in draft.json()["draft"]
    assert draft.json()["published"] is False
    assert draft.json()["requires_review"] is True
    unsafe = lambda title, trade: "Carpintería, sueldo $999999 asegurado"
    monkeypatch.setattr("app.facebook_ai.generate_ad_opening", unsafe)
    rejected = n["send"](n["admin"], "/facebook/requirements/" + rid + "/ad-draft")
    assert rejected.status_code == 200 and rejected.json()["source"] == "template"
    assert "$999999" not in rejected.json()["draft"]
    settings.cache_clear()
