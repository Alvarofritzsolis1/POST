from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.facebook_ai import messenger_ai_source, messenger_external_fallback_enabled
from app.galancito_hybrid import select_response

CONTEXT = "Consulta: ¿Qué significa postular?\nReferencia aprobada: Postular es expresar interés por un trabajo."
ANSWER = "Postular es decir que te interesa un trabajo."


def test_local_success_does_not_spend_api_tokens():
    external = Mock(return_value=ANSWER)
    assert select_response(lambda: ANSWER, external, CONTEXT, allow_external=True) == (ANSWER, "local_model")
    external.assert_not_called()


@pytest.mark.parametrize("draft", [None, "", "No sé qué responder.", "No tengo información suficiente.", "Ya estás contratado."])
def test_api_receives_same_knowledge_only_when_local_cannot_answer(draft):
    external = Mock(return_value=ANSWER)
    assert select_response(lambda: draft, external, CONTEXT, allow_external=True) == (ANSWER, "external_fallback")
    external.assert_called_once()


def test_api_timeout_does_not_invent():
    external = Mock(side_effect=TimeoutError)
    assert select_response(lambda: None, external, CONTEXT, allow_external=True) == (None, "unresolved")


def test_external_requires_permission_even_if_local_fails():
    external = Mock(return_value=ANSWER)
    assert select_response(lambda: None, external, CONTEXT) == (None, "unresolved")
    external.assert_not_called()


def test_safe_local_question_prevents_unnecessary_external_call():
    external = Mock(return_value=ANSWER)
    assert select_response(lambda: None, external, CONTEXT, allow_external=True,
        local_fallback="¿En qué comuna puedes trabajar?") == ("¿En qué comuna puedes trabajar?", "guided_fallback")
    external.assert_not_called()


def test_external_cannot_invent_hiring_or_numbers():
    assert select_response(lambda: None, lambda: "Ya estás contratado.", CONTEXT,
        allow_external=True) == (None, "unresolved")
    assert select_response(lambda: None, lambda: "Te pagan 800000 pesos.", CONTEXT,
        allow_external=True) == (None, "unresolved")


def test_privacy_gate_stops_both_callbacks():
    local, external = Mock(), Mock()
    assert select_response(local, external, "mi contraseña: ejemplo", allow_external=True) == (None, "private")
    local.assert_not_called()
    external.assert_not_called()


def test_route_stays_local_first_when_api_budget_runs_out(monkeypatch):
    cfg = SimpleNamespace(facebook_ai_enabled=True, facebook_ai_provider="ollama",
        galancito_local_ai_enabled=True, galancito_local_model="qwen3.5:2b-q4_K_M")
    policy = SimpleNamespace(enabled=True, fallback_enabled=True, task_routes={"messenger": "route"})
    db = Mock()
    db.get.return_value = policy
    monkeypatch.setattr("app.facebook_ai.orchestration_available", lambda *args: False)
    assert messenger_ai_source(db, "org", cfg) == "team"
    assert not messenger_external_fallback_enabled(db, "org", cfg)
    policy.fallback_enabled = False
    assert messenger_ai_source(db, "org", cfg) == "ollama"
