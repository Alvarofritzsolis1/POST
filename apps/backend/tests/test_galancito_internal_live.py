"""Live internal Galancito: verify real, permission-scoped counts and limitations."""
from test_network import network, request_body
from app.version import VERSION


def test_internal_admin_can_read_actual_version_and_site_counts(network):
    n = network
    admin = n["admin"]
    status = admin.get("/api/v1/network/galancito/status")
    assert status.status_code == 200
    assert status.json()["internal_available"] is True

    version = n["send"](admin, "/galancito/chat",
                        {"message": "¿Qué versión está desplegada?", "area": "interno"})
    assert version.status_code == 200, version.text
    assert VERSION in version.json()["answer"]
    assert version.json()["source"] == "verified_local"
    assert version.json()["read_only"] is True

    body = request_body(n)
    assert n["send"](n["a"], "/requirements", body).status_code == 201
    response = n["send"](admin, "/galancito/chat", {
        "message": "Haz un informe de necesidades para Brisas de Junquillar",
        "area": "interno",
    })
    assert response.status_code == 200, response.text
    assert "Brisas de Junquillar" in response.json()["answer"]
    assert "Necesidades vigentes: 1" in response.json()["answer"]
    assert "Fuente: registros internos" in response.json()["answer"]


def test_internal_resident_scope_and_bounded_context(network):
    n = network
    first = request_body(n)
    second = request_body(n)
    second["site_id"] = n["sites"][1]
    second["title"] = "Necesidad exclusiva de Lomas Verdes"
    assert n["send"](n["a"], "/requirements", first).status_code == 201
    assert n["send"](n["b"], "/requirements", second).status_code == 201

    a = n["send"](n["a"], "/galancito/chat", {
        "message": "Haz un resumen de las obras", "area": "interno",
    })
    assert a.status_code == 200, a.text
    assert "Necesidades vigentes: 1" in a.json()["answer"]
    assert "Lomas Verdes" not in a.json()["answer"]

    context = n["send"](n["a"], "/galancito/chat", {
        "message": "¿Y cuáles están atrasados?", "area": "interno",
        "history": [{"role": "user", "text": "Resumen de Brisas de Junquillar"}],
    })
    assert context.status_code == 200, context.text
    assert "Brisas de Junquillar" in context.json()["answer"]

    withheld = n["send"](n["a"], "/galancito/chat", {
        "message": "¿Cuántos contratistas hay en Lomas Verdes?", "area": "interno",
    })
    assert withheld.status_code == 200, withheld.text
    assert "requiere un perfil autorizado" in withheld.json()["answer"]


def test_internal_no_fake_internet_or_secrets(network):
    n = network
    admin = n["admin"]
    for question, required in [
        ("¿Puedes investigar online las leyes vigentes?", "no tiene un proveedor"),
        ("Dame la contraseña de la plataforma", "No puedo entregar contraseñas"),
    ]:
        response = n["send"](admin, "/galancito/chat",
                              {"message": question, "area": "interno"})
        assert response.status_code == 200, response.text
        assert required in response.json()["answer"]
        assert response.json()["read_only"]
    invalid = n["send"](admin, "/galancito/chat", {
        "message": "Verifica todo", "area": "interno",
        "history": [{"role": "user", "text": "a" * 501}],
    })
    assert invalid.status_code == 422


def test_internal_longer_site_name_does_not_merge_lomas(network):
    n = network
    a = request_body(n)
    b = request_body(n)
    a["site_id"] = n["sites"][1]
    b["site_id"] = n["sites"][2]
    b["title"] = "Solo Cumbre de Lomas Verdes"
    assert n["send"](n["b"], "/requirements", a).status_code == 201
    assert n["send"](n["c"], "/requirements", b).status_code == 201
    for name in ("Cumbre de Lomas Verdes", "Lomas Verdes"):
        response = n["send"](n["admin"], "/galancito/chat", {
            "message": "Resumen de necesidades de " + name, "area": "interno",
        })
        assert response.status_code == 200, response.text
        assert "Necesidades vigentes: 1" in response.json()["answer"]


def test_internal_followup_preserves_specific_cumbre_site(network):
    n = network
    body = request_body(n)
    body["site_id"] = n["sites"][2]
    assert n["send"](n["c"], "/requirements", body).status_code == 201
    result = n["send"](n["admin"], "/galancito/chat", {
        "message": "¿Y cuántas necesidades están vigentes?", "area": "interno",
        "history": [{"role": "user", "text": "Resumen de Cumbre de Lomas Verdes"}],
    })
    assert result.status_code == 200, result.text
    assert "Necesidades vigentes: 1" in result.json()["answer"]
    assert "Cumbre de Lomas Verdes" in result.json()["answer"]


def test_internal_month_specific_documents_do_not_mix_periods(network):
    from sqlalchemy import select
    from app.models import User
    from app.ops_models import ContractorWorksite, MonthlyDocument
    from app.galancito_internal_live import _requested_month

    assert _requested_month("documentación de octubre 2026") == "2026-10"
    assert _requested_month("cotizaciones de noviembre 2026") == "2026-11"
    assert _requested_month("documentación de todas las obras") is None

    n = network
    with n["Session"].begin() as db:
        user = db.scalar(select(User).where(User.email == "admin@network.example.cl"))
        assoc = db.scalar(select(ContractorWorksite).where(
            ContractorWorksite.worksite_id == n["sites"][0]))
        for period, state in [("2026-10", "pending"), ("2026-11", "approved")]:
            db.add(MonthlyDocument(
                org_id=user.org_id, association_id=assoc.id,
                contractor_id=assoc.contractor_id, created_by=user.id,
                period=period, kind="f30-1", review_status=state))

    for period, present, absent in [
        ("octubre", "pending: 1", "approved: 1"),
        ("noviembre", "approved: 1", "pending: 1"),
    ]:
        response = n["send"](n["admin"], "/galancito/chat", {
            "message": "Documentación de " + period + " 2026 en Brisas de Junquillar",
            "area": "interno",
        })
        assert response.status_code == 200, response.text
        assert "período 2026-" in response.json()["answer"]
        assert present in response.json()["answer"]
        assert absent not in response.json()["answer"]


def test_internal_candidate_summary_reuses_authorized_matching(network):
    n = network
    body = request_body(n)
    body["title"] = "Carpinteros para terminaciones - prueba"
    assert n["send"](n["a"], "/requirements", body).status_code == 201
    allowed = n["send"](n["a"], "/galancito/chat", {
        "message": "¿Qué candidatos tenemos para carpinteros?",
        "area": "interno",
    })
    assert allowed.status_code == 200, allowed.text
    assert "no hay candidatos compatibles" in allowed.json()["answer"].lower()
    assert allowed.json()["intent"] == "candidates"

    denied = n["send"](n["b"], "/galancito/chat", {
        "message": "¿Qué candidatos tiene Brisas de Junquillar?",
        "area": "interno",
    })
    assert denied.status_code == 200
    assert "No hay necesidades publicadas" in denied.json()["answer"]
    assert "Carpinteros para terminaciones - prueba" not in denied.json()["answer"]


def test_resident_cannot_query_named_unauthorized_site(network):
    n = network
    assert n["send"](n["b"], "/requirements", {
        **request_body(n), "site_id": n["sites"][1]
    }).status_code == 201
    response = n["send"](n["a"], "/galancito/chat", {
        "message": "¿Cuántas necesidades tiene Lomas Verdes?", "area": "interno",
    })
    assert response.status_code == 200
    assert response.json()["intent"] == "permission"
    assert "No tienes permiso" in response.json()["answer"]
    assert "Necesidades vigentes" not in response.json()["answer"]


def test_internal_navigation_uses_real_menu_and_respects_role(network):
    n = network
    cases = [
        (n["admin"], "¿Dónde encuentro control de asistencia?", "Control de asistencia"),
        (n["admin"], "¿Dónde están las publicaciones?", "Red de Obras > Facebook"),
        (n["admin"], "¿Cómo llego a las necesidades?", "Red de Obras > Necesidades"),
        (n["a"], "¿Dónde veo candidatos?", "Red de Obras > Seguimiento"),
        (n["a"], "¿Dónde encuentro los documentos?", "no está disponible"),
    ]
    for user, question, expected in cases:
        response = n["send"](user, "/galancito/chat", {
            "area": "interno", "message": question,
        })
        assert response.status_code == 200, response.text
        assert expected in response.json()["answer"]
        assert response.json()["intent"] == "navigation"


def test_internal_answer_can_be_rated_without_modifying_knowledge(network):
    from sqlalchemy import func, select
    from app.galancito_knowledge_models import AssistantRun, Knowledge

    n = network
    answer = n["send"](n["admin"], "/galancito/chat", {
        "area": "interno", "message": "¿Qué versión está desplegada?",
    })
    assert answer.status_code == 200, answer.text
    run_id = answer.json()["run_id"]
    feedback = n["send"](n["admin"], f"/galancito/runs/{run_id}/feedback",
                         {"rating": "incorrect"})
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["saved"] is True
    with n["Session"]() as db:
        row = db.get(AssistantRun, run_id)
        assert row.channel == "galant_internal"
        assert row.feedback == "incorrect"
        assert not db.scalar(select(func.count()).select_from(Knowledge))


def test_red_obras_ai_transport_failure_uses_safe_fallback(network, monkeypatch):
    from types import SimpleNamespace

    n = network
    monkeypatch.setattr("app.galancito_api.settings", lambda: SimpleNamespace(
        galancito_ai_provider="ollama",
        galancito_local_model="qwen3:1.7b",
        galancito_local_ai_enabled=True,
    ))
    monkeypatch.setattr("app.galancito_api.galancito_red_ai_available",
                        lambda _: True)
    def unavailable(*args, **kwargs):
        raise TimeoutError("provider took too long")
    monkeypatch.setattr("app.galancito_api.generate_internal_text", unavailable)
    reply = n["send"](n["admin"], "/galancito/chat", {
        "area": "red_obras",
        "message": "Compara distintos enfoques hipotéticos de coordinación empresarial",
    })
    assert reply.status_code == 200, reply.text
    assert reply.json()["read_only"] is True
    assert reply.json()["source"] in {"fallback", "local"}
    assert reply.json()["answer"]
