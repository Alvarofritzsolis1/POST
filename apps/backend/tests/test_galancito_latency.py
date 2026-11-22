"""Prevent idle queue sleeps and unnecessary reads from delaying greetings."""
import pytest
from sqlalchemy import event
from app import network_facebook
from app.config import settings
from test_network import network as network


def test_idle_messenger_polls_after_one_second(monkeypatch):
    monkeypatch.delenv("FACEBOOK_WORKER_POLL_SECONDS", raising=False)
    settings.cache_clear()
    monkeypatch.setattr(network_facebook, "stopping", False)
    monkeypatch.setattr(network_facebook.signal, "signal", lambda *args: None)
    rounds, sleeps = [], []
    def chat():
        rounds.append(len(sleeps))
        if len(rounds) == 2:
            network_facebook.stop()
        return False
    monkeypatch.setattr("app.facebook_chat_worker.process_chat_next", chat)
    monkeypatch.setattr(network_facebook, "process_manual_next", lambda: False)
    monkeypatch.setattr(network_facebook, "process_next", lambda: False)
    monkeypatch.setattr(network_facebook.time, "sleep", sleeps.append)
    network_facebook.main()
    assert len(rounds) == 2
    assert sum(sleeps) == pytest.approx(1.0)
    settings.cache_clear()


def test_greeting_does_not_read_business_data_or_infer(network, monkeypatch):
    n = network
    statements = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    def forbidden(*args, **kwargs):
        raise AssertionError("Greeting must not call inference or retrieval")
    monkeypatch.setattr("app.galancito_api.generate_internal_text", forbidden)
    monkeypatch.setattr("app.galancito_api.retrieve", forbidden)
    event.listen(n["engine"], "before_cursor_execute", observe)
    try:
        response = n["send"](n["admin"], "/galancito/chat", {"message": "hola"})
    finally:
        event.remove(n["engine"], "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "local" and response.json()["run_id"]
    assert not any(table in sql for sql in statements for table in (
        "network_requirements", "network_capacities", "network_coordinations",
        "network_awards", "facebook_trade_guides", "galancito_knowledge", "facebook_leads"))


def test_legacy_eight_second_limit_no_longer_aborts_4b_inference(monkeypatch):
    from app import galancito_local
    monkeypatch.setenv("GALANCITO_TIMEOUT_SECONDS", "24")
    settings.cache_clear()
    monkeypatch.setattr(galancito_local, "available_memory_mb", lambda: 8000)
    timeouts = []
    def offline(request, timeout):
        timeouts.append(timeout)
        raise TimeoutError()
    monkeypatch.setattr(galancito_local._opener, "open", offline)
    try:
        with pytest.raises(RuntimeError):
            galancito_local.generate_local_text("Galancito", "consulta")
        assert timeouts == [24.0]
    finally:
        settings.cache_clear()


def test_administrative_help_does_not_turn_into_unsupplied_loan_advice():
    from app.galancito_flow import grounded_reply
    assert grounded_reply("La administración te da el préstamo si cumples las condiciones.",
                          "Explica cómo pedir ayuda a administración de la obra") is None
