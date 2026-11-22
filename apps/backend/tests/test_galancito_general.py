"""Unified Galancito: one routing surface, Qwen 4B, external privacy, permissions."""
from types import SimpleNamespace
from test_network import network, request_body
from app.galancito_general import QWEN_4B, general_intent, is_complex, external_safe, safe_generated, social_reply, needs_public_web


def test_unified_route_classifies_greetings_and_general_help():
    assert general_intent("HOLA COMO ESTAS") == "greeting"
    assert general_intent("¿Cuántas necesidades vigentes hay?") == "verified"
    assert general_intent("¿Qué versión tenemos y cómo está el VPS?") == "verified"
    assert general_intent("¿Dónde veo las publicaciones?") == "verified"
    assert general_intent("¿Cómo gestionar la documentación mensual?") == "advice"
    assert general_intent("¿Qué es el control de asistencia?") == "advice"
    assert general_intent("¿Qué significa una evaluación?") == "advice"
    assert general_intent("Explícame el programa para supervisores") == "advice"
    assert general_intent("¿Qué significa conversión comercial?") == "advice"
    assert general_intent("¿Cuánta RAM tiene el VPS?") == "verified"
    assert general_intent("Hola, equipo de Control de Contratistas: ¿cómo podemos mejorar la coordinación?") == "advice"
    assert general_intent("Hola, mi equipo está aquí. ¿En qué nos puedes ayudar?") == "advice"
    assert general_intent("¿Cómo puedo mejorar el seguimiento de candidatos?") == "advice"
    assert is_complex("Analiza los riesgos y compara estrategias de coordinación")
    assert not is_complex("Hola")
    assert not is_complex("Analiza esto por favor")
    assert not is_complex("Compara estos conceptos")
    assert not is_complex("¿Qué significa?" + " Me interesa conocer el significado del término." * 9)
    assert not is_complex("¿Cómo se hace una evaluación?")
    assert is_complex("Analiza y compara los riesgos, plazos y costos de distintos escenarios")
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
    # The general chat sets the API policy automatically for all requests;
    # only substantive complex public questions actually consume that API.
    simple = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": "¿Cómo mejorar el seguimiento?",
        "allow_external_ai": True,
    })
    assert simple.status_code == 200, simple.text
    assert simple.json()["external_used"] is False
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


def test_general_web_search_refuses_internal_business_context(network, monkeypatch):
    """Web search must apply the same privacy filter as external inference."""
    n = network
    sent = []
    monkeypatch.setattr("app.galancito_api.public_search",
                        lambda query: sent.append(query) or {
                            "searched_at": "2026-11-22T00:00:00+00:00",
                            "results": [{"title": "Fuente pública", "snippet": "Guía",
                                         "url": "https://www.ejemplo.cl/guia"}],
                        })
    for query in (
        "Investiga nuestras publicaciones en GALANT",
        "Analiza estrategias de Brisas de Junquillar",
        "Compara documentos de nuestros contratistas",
    ):
        response = n["send"](n["admin"], "/galancito/chat", {
            "area": "general", "message": query, "allow_web": True,
        })
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "local"
        assert "datos internos de GALANT" in response.json()["answer"]
    assert sent == []

    response = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": "Guía pública de seguridad en construcción Chile",
        "allow_web": True,
    })
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "public_web"
    assert sent == ["Guía pública de seguridad en construcción Chile"]


def test_legacy_chat_never_bills_external_for_simple_question_or_leaks_org_context(
        network, monkeypatch):
    """Old clients cannot bypass complex-only routing or send internal KPIs."""
    n = network
    calls = []
    monkeypatch.setattr("app.galancito_api.settings", lambda: SimpleNamespace(
        galancito_local_model="qwen3:1.7b", galancito_ai_provider="openai",
    ))
    monkeypatch.setattr("app.galancito_api.galancito_red_ai_available", lambda _cfg: True)
    monkeypatch.setattr("app.galancito_api.orchestration_available", lambda *_: False)
    monkeypatch.setattr("app.galancito_api.infer", lambda _db, fn, **_kw: fn())
    monkeypatch.setattr("app.galancito_api.generate_internal_text",
                        lambda _instructions, prompt, _length:
                        calls.append(prompt) or "Compara alternativas antes de decidir.")

    ordinary = n["send"](n["admin"], "/galancito/chat", {
        "area": "red_obras", "message": "Explica qué significa una planificación.",
        "allow_external_ai": True,
    })
    assert ordinary.status_code == 200, ordinary.text
    assert calls == []

    assert n["send"](n["a"], "/requirements", request_body(n)).status_code == 201
    complex_question = (
        "Analiza y compara estrategias de construcción para equilibrar "
        "los costos, plazos y riesgos de diferentes escenarios."
    )
    analyzed = n["send"](n["admin"], "/galancito/chat", {
        "area": "red_obras", "message": complex_question,
        "allow_external_ai": True,
    })
    assert analyzed.status_code == 200, analyzed.text
    assert len(calls) == 1
    assert complex_question in calls[0]
    assert "Brisas de Junquillar" not in calls[0]
    assert "Indicadores comprobables:" not in calls[0]
    assert "Necesidades publicadas" not in calls[0]


def test_generated_complex_analysis_can_use_step_lists_but_no_invented_metrics():
    steps = "1. Revisar alternativas de coordinación.\n2. Comparar riesgos y plazos."
    checked = safe_generated(steps, question="Analiza estrategias de coordinación")
    assert checked is not None
    assert checked.startswith("- Revisar alternativas")
    assert "- Comparar riesgos" in checked
    assert safe_generated("La obra tiene 28 trabajadores.", question="Analiza estrategias") is None


def test_general_chat_non_operational_questions_avoid_database_lookups(network, monkeypatch):
    """Common explanations do not trigger expensive internal metrics retrieval."""
    n = network
    seen = []
    monkeypatch.setattr("app.galancito_general_runtime.internal_reply",
                        lambda *args, **kwargs: seen.append(args) or ("no esperado", "overview"))
    monkeypatch.setattr("app.galancito_general_runtime.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=True, galancito_local_model=QWEN_4B,
    ))
    monkeypatch.setattr("app.galancito_general_runtime.generate_local_text",
                        lambda *_args, **_kwargs: "La planificación organiza el trabajo.")
    monkeypatch.setattr("app.galancito_general_runtime.infer",
                        lambda _db, fn, **_kwargs: fn())
    response = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": "¿Qué significa planificación?",
    })
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "ollama_4b"
    assert seen == []


def test_legacy_simple_intents_do_not_sync_external_services(network, monkeypatch):
    n = network
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No external provider sync for deterministic chat")
    monkeypatch.setattr("app.galancito_api.sync_org_global_lightning", forbidden)
    for message in (
        "¿Cómo postulo a una obra?",
        "¿Cómo funciona Red de Obras?",
        "Quiero publicar una necesidad",
    ):
        result = n["send"](n["admin"], "/galancito/chat", {
            "area": "red_obras", "message": message,
            "allow_external_ai": True,
        })
        assert result.status_code == 200, result.text
        assert result.json()["source"] == "local"


def test_internal_legacy_intents_do_not_misread_program_or_conversion(network):
    n = network
    for question in ("Explícame un programa de actividades",
                     "¿Qué significa conversión de candidatos?"):
        reply = n["send"](n["admin"], "/galancito/chat", {
            "area": "interno", "message": question,
        })
        assert reply.status_code == 200, reply.text
        assert reply.json()["intent"] not in {"metrics", "version"}


def test_social_group_greeting_understands_context_without_claiming_camera(network, monkeypatch):
    """A live group introduction must not trigger SQL facts, AI or Internet."""
    n = network
    def no_inference(*_args, **_kwargs):
        raise AssertionError("A social greeting should never consume model/API tokens")
    monkeypatch.setattr("app.galancito_general_runtime.internal_reply", no_inference)
    monkeypatch.setattr("app.galancito_general_runtime.generate_local_text", no_inference)
    monkeypatch.setattr("app.galancito_api.public_search", no_inference)
    question = "Hola Galancito, te estamos viendo con mi equipo de Control de Contratistas."
    reply = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": question,
        "allow_external_ai": True, "auto_web": True,
    })
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["source"] == "local"
    assert result["intent"] == "social_context"
    assert "equipo de Control de Contratistas" in result["answer"]
    assert "documentación" in result["answer"]
    assert "los veo" not in result["answer"].lower()
    assert result["external_used"] is False


def test_social_context_never_swallow_authorized_operational_question():
    assert social_reply("Hola, estamos con el equipo de Control de Contratistas") is not None
    assert social_reply("Hola equipo, ¿cuántas necesidades siguen pendientes?") is None
    assert social_reply("Hola, con mi equipo estamos reunidos: revisa los contratistas") is None
    assert social_reply("Hola, equipo, mi RUT es 12.345.678-5") is None
    assert social_reply("Hola, equipo de control de contratistas, ¿cómo podemos mejorar?") is None
    assert social_reply("Hola, soy trabajador por mi cuenta") is None


def test_automatic_web_intent_is_public_and_conservative():
    assert needs_public_web("Busca en internet la normativa de subcontratación chilena")
    assert needs_public_web("¿Cuál es la normativa vigente de subcontratación en Chile?")
    assert needs_public_web("¿Cuáles son las últimas noticias del Ministerio del Trabajo?")
    assert needs_public_web("¿Quién es el presidente de Chile?")
    assert needs_public_web("¿Cuál es el dólar hoy?")
    assert not needs_public_web("Hola Galancito, te estamos viendo con mi equipo de control de contratistas")
    assert not needs_public_web("¿Cuántas publicaciones están pendientes en mi obra?")
    assert not needs_public_web("Explícame qué es una ley")
    assert not needs_public_web("No busques en internet. Explícame qué es una ley")


def test_automatic_web_requires_session_authorization_and_remains_private(network, monkeypatch):
    n = network
    queries = []
    monkeypatch.setattr("app.galancito_api.public_search",
                        lambda query: queries.append(query) or {
                            "searched_at": "2026-11-22T00:00:00+00:00",
                            "results": [{"title": "Sitio público", "snippet": "Referencia de ejemplo",
                                         "url": "https://www.ejemplo.cl/publico"}],
                        })
    question = "¿Cuál es la normativa vigente de subcontratación en Chile?"
    authorized = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": question, "auto_web": True,
    })
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["source"] == "public_web"
    assert queries == [question]
    # Session opt-in never makes routine/private messages public.
    for query in (
        "Hola equipo, estamos reunidos para revisar la documentación",
        "¿Cuántos contratistas tenemos pendientes en Brisas de Junquillar?",
    ):
        answer = n["send"](n["admin"], "/galancito/chat", {
            "area": "general", "message": query, "auto_web": True,
        })
        assert answer.status_code == 200, answer.text
        assert answer.json()["source"] != "public_web"
    assert queries == [question]
    private = n["send"](n["admin"], "/galancito/chat", {
        "area": "general",
        "message": "Busca en internet la normativa para Brisas de Junquillar",
        "auto_web": True,
    })
    assert private.status_code == 200, private.text
    assert private.json()["source"] == "local"
    assert queries == [question]
    assert "datos internos de GALANT" in private.json()["answer"]


def test_group_followup_is_sent_to_local_4b_with_prior_context(network, monkeypatch):
    n = network
    prompts = []
    monkeypatch.setattr("app.galancito_general_runtime.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=True, galancito_local_model=QWEN_4B,
    ))
    monkeypatch.setattr("app.galancito_general_runtime.infer",
                        lambda _db, fn, **_kwargs: fn())
    monkeypatch.setattr("app.galancito_general_runtime.generate_local_text",
                        lambda _instructions, prompt, **_kwargs:
                        prompts.append(prompt) or "Pueden revisar primero el estado documental.")
    reply = n["send"](n["admin"], "/galancito/chat", {
        "area": "general", "message": "¿En qué nos puedes ayudar?",
        "history": [{"role": "user", "text":
                     "Hola Galancito, te estamos viendo con mi equipo de Control de Contratistas"}],
    })
    assert reply.status_code == 200, reply.text
    assert reply.json()["source"] == "ollama_4b"
    assert len(prompts) == 1
    assert "equipo de Control de Contratistas" in prompts[0]
    assert "¿En qué nos puedes ayudar?" in prompts[0]


def test_live_qwen4b_probe_requires_actual_model_identity(network, monkeypatch):
    """Configuration and the word OK cannot falsely certify a different model."""
    from app.galancito_local import last_timings

    n = network
    monkeypatch.setattr("app.galancito_api.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=True, galancito_local_model=QWEN_4B,
    ))
    monkeypatch.setattr("app.galancito_api.installed_model_status", lambda _name: True)
    monkeypatch.setattr("app.galancito_api.model_status",
                        lambda: {"state": "available", "loaded": True})
    monkeypatch.setattr("app.galancito_api.infer", lambda _db, fn, **kw: fn())

    def model_response(name):
        def run(*_args, **_kwargs):
            last_timings.set({"response_model": name, "eval_count": 2})
            return "OK"
        return run

    monkeypatch.setattr("app.galancito_api.generate_local_text", model_response("qwen3:1.7b"))
    wrong = n["send"](n["admin"], "/galancito/diagnostic", {})
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["status"] == "wrong_response_model"
    assert wrong.json()["responsive"] is False
    assert wrong.json()["response_model"] == "qwen3:1.7b"

    monkeypatch.setattr("app.galancito_api.generate_local_text", model_response(QWEN_4B))
    correct = n["send"](n["admin"], "/galancito/diagnostic", {})
    assert correct.status_code == 200, correct.text
    assert correct.json()["status"] == "ok"
    assert correct.json()["responsive"] is True
    assert correct.json()["installed"] is True
    assert correct.json()["loaded"] is True
    assert correct.json()["response_model"] == QWEN_4B

    monkeypatch.setattr("app.galancito_api.generate_local_text", model_response(None))
    unverified = n["send"](n["admin"], "/galancito/diagnostic", {})
    assert unverified.status_code == 200, unverified.text
    assert unverified.json()["status"] == "model_identity_unverified"
    assert unverified.json()["responsive"] is False


def test_absent_qwen4b_diagnostic_does_not_generate_or_download(network, monkeypatch):
    n = network
    monkeypatch.setattr("app.galancito_api.settings", lambda: SimpleNamespace(
        galancito_local_ai_enabled=True, galancito_local_model=QWEN_4B,
    ))
    monkeypatch.setattr("app.galancito_api.installed_model_status", lambda _name: False)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Missing model must not initiate generation or download")
    monkeypatch.setattr("app.galancito_api.generate_local_text", forbidden)
    absent = n["send"](n["admin"], "/galancito/diagnostic", {})
    assert absent.status_code == 200, absent.text
    assert absent.json()["status"] == "not_installed"
    assert absent.json()["installed"] is False
    assert absent.json()["responsive"] is False
    denied = n["send"](n["a"], "/galancito/diagnostic", {})
    assert denied.status_code == 403
