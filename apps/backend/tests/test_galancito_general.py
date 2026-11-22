"""Unified Galancito: one routing surface, Qwen 4B, external privacy, permissions."""
from types import SimpleNamespace
from test_network import network, request_body
from app.galancito_general import QWEN_4B, general_intent, is_complex, external_safe


def test_unified_route_classifies_greetings_and_general_help():
    assert general_intent("HOLA COMO ESTAS") == "greeting"
    assert general_intent("¿Cuántas necesidades vigentes hay?") == "verified"
    assert general_intent("¿Cómo puedo mejorar el seguimiento de candidatos?") == "advice"
    assert is_complex("Analiza los riesgos y compara estrategias de coordinación")
    assert not is_complex("Hola")
    assert not external_safe("Analiza las obras de Brisas de Junquillar",
                             internal_names=("Brisas de Junquillar",))
    assert not external_safe("mi RUT es 12.345.678-5")


def test_unified_read_only_greeting_and_real_site_scope(network):
    n = network
    assert n["send"](n["a"], "/requirements", request_body(n)).status_code == 201
    greeting = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": "HOLA COMO ESTAS",
    })
    assert greeting.status_code == 200, greeting.text
    assert greeting.json()["intent"] == "greeting"
    assert greeting.json()["source"] == "local"

    result = n["send"](n["a"], "/galancito/chat", {
        "area": "general", "message": "¿Cuántas necesidades vigentes hay en Brisas de Junquillar?",
    })
    assert result.status_code == 200, result.text
    assert "Necesidades vigentes: 1" in result.json()["answer"]
    assert result.json()["source"] == "verified_local"
    denied = n["send"](n["b"], "/galancito/chat", {
        "area": "general", "message": "Resumen de necesidades de Brisas de Junquillar",
    })
    assert denied.status_code == 200
    assert "No tienes permiso" in denied.json()["answer"]


def test_unified_general_advice_requires_4b_not_legacy_1_7(network, monkeypatch):
    n = network
    calls = []
    monkeypatch.setattr("app.galancito_general_runtime.external_ready", lambda *_: False)
    monkeypatch.setattr("app.galancito_general_runtime.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=True, galancito_local_model="qwen3:1.7b",
    ))
    monkeypatch.setattr("app.galancito_general_runtime.generate_local_text",
                        lambda *a, **kw: calls.append(a) or "Revisa las necesidades.")
    result = n["send"](n["admin"], "/galancito/chat", {
        "area": "general",
        "message": "¿Cómo puedo mejorar el seguimiento de candidatos?",
    })
    assert result.status_code == 200, result.text
    assert result.json()["source"] == "fallback"
    assert not calls

    monkeypatch.setattr("app.galancito_general_runtime.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=True, galancito_local_model=QWEN_4B,
    ))
    monkeypatch.setattr("app.galancito_general_runtime.infer",
                        lambda _db, fn, **_kwargs: fn())
    good = n["send"](n["admin"], "/galancito/chat", {
        "area": "general",
        "message": "¿Cómo puedo mejorar el seguimiento de candidatos?",
    })
    assert good.status_code == 200, good.text
    assert good.json()["source"] == "ollama_4b"
    assert good.json()["answer"] == "Revisa las necesidades."
    assert calls


def test_unified_complex_api_is_opted_in_and_never_exposes_private_org_names(network, monkeypatch):
    n = network
    external = []
    monkeypatch.setattr("app.galancito_general_runtime.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=False, galancito_local_model="qwen3:1.7b",
    ))
    monkeypatch.setattr("app.galancito_general_runtime.external_ready", lambda _db, user: user.role == "admin")
    monkeypatch.setattr("app.galancito_general_runtime.infer",
                        lambda _db, fn, **kwargs: fn())
    monkeypatch.setattr("app.galancito_general_runtime.orchestrated_text",
                        lambda _db, _org, **kwargs:
                        external.append(kwargs["prompt"]) or
                        "Puedes comparar el tiempo de respuesta y evaluar distintos escenarios de coordinación.")
    question = "Analiza y compara las estrategias para coordinar equipos, riesgos y plazos en la construcción."
    opted = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": question, "allow_external_ai": True,
    })
    assert opted.status_code == 200, opted.text
    assert opted.json()["source"] == "external_api"
    assert opted.json()["external_used"] is True
    assert len(external) == 1
    not_opted = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": question, "allow_external_ai": False,
    })
    assert not_opted.status_code == 200
    assert not_opted.json()["external_used"] is False
    assert len(external) == 1
    private = n["send"](n["admin"], "/galancito/chat", {
        "area": "general",
        "message": "Analiza y compara las estrategias de Brisas de Junquillar",
        "allow_external_ai": True,
    })
    assert private.status_code == 200
    assert private.json()["external_used"] is False
    assert len(external) == 1
    resident = n["send"](n["a"], "/galancito/chat", {
        "area": "general", "message": question, "allow_external_ai": True,
    })
    assert resident.status_code == 200
    assert resident.json()["external_used"] is False


def test_general_synthetic_practice_400_cases_without_production_data():
    from app.galancito_internal_training import (
        INTERNAL_CATEGORIES, internal_case, evaluate_internal,
    )
    config = {"profile": "interno", "suite": "reference", "level": 3,
              "cases": 400, "cycles": 1, "seed": 1}
    assert len(INTERNAL_CATEGORIES) == 20
    cases = [internal_case(config, position) for position in range(400)]
    assert len({item.id for item in cases}) == 400
    assert {item.category for item in cases} == set(INTERNAL_CATEGORIES)
    failures = [item.id for item in cases if not evaluate_internal(item)["passed"]]
    assert failures == [], failures[:10]


def test_general_howto_documents_is_not_an_internal_document_count():
    assert general_intent("¿Qué documentos necesita un contratista para ingresar?") == "advice"
    assert general_intent("¿Cómo publicar una necesidad en Facebook?") == "advice"
    assert general_intent("¿Cuántas publicaciones están pendientes?") == "verified"


def test_general_rejects_private_business_context_before_external_routing():
    for message in (
        "Analiza nuestras publicaciones y recomienda cómo mejorar los contactos",
        "Compara nuestros contratistas y las necesidades de mis obras",
        "Investiga qué pasa con mis registros en GALANT",
    ):
        assert not external_safe(message)
    assert external_safe("Compara estrategias de coordinación en la construcción chilena")
