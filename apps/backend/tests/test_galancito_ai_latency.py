"""Synthetic routing tests: external APIs are never contacted."""
from types import SimpleNamespace

from app import ai_gateway
from app.ai_models import AIConnection, AIOrchestration


def _connection(id, name):
    return SimpleNamespace(
        id=id, name=name, org_id="org-1", provider="groq",
        model="llama-3.1-8b-instant", enabled=True,
        last_status="verified", encrypted_key="encrypted-in-test",
    )


def _usage(id, duration, status="success"):
    return SimpleNamespace(connection_id=id, duration_ms=duration, status=status)


class FakeDB:
    def __init__(self, connections, samples, *, fallback=True):
        self.connections = connections
        self.samples = samples
        self.policy = SimpleNamespace(
            enabled=True, task_routes={"messenger": "primary"},
            fallback_enabled=fallback, review_enabled=False,
            monthly_token_limit=0,
        )

    def get(self, model, key):
        return self.policy if model is AIOrchestration else None

    def scalars(self, query):
        sql = str(query)
        if "FROM ai_connections" in sql:
            return self.connections
        if "FROM ai_usage" in sql:
            return self.samples
        raise AssertionError("Unexpected table in routing test")


def test_messenger_primary_preserved_and_low_latency_backup_first(monkeypatch):
    """The configured primary goes first; only approved/verified backups follow."""
    primary = _connection("primary", "Primary")
    slow = _connection("slow", "Slow backup")
    fast = _connection("fast", "Fast backup")
    samples = ([_usage("slow", 5000) for _ in range(4)] +
               [_usage("fast", 900) for _ in range(4)])
    db = FakeDB([slow, primary, fast], samples)
    calls = []

    def fake_run(_db, conn, *, task, instructions, prompt,
                 max_output_tokens, timeout):
        calls.append((conn.id, timeout))
        assert task == "messenger"
        assert 0 < timeout <= 5
        if conn.id == "primary":
            raise ai_gateway.AIServiceError("unavailable")
        return "Claro, dime qué necesitas."

    monkeypatch.setattr(ai_gateway, "run_connection", fake_run)
    monkeypatch.setattr(ai_gateway, "within_budget", lambda *a: True)
    answer = ai_gateway.orchestrated_text(
        db, "org-1", task="messenger",
        instructions="Respuesta natural", prompt="Hola, necesito ayuda",
        max_output_tokens=160,
    )
    assert answer == "Claro, dime qué necesitas."
    assert [item[0] for item in calls] == ["primary", "fast"]
    assert calls[1][1] <= 3.0


def test_fallback_requires_opt_in(monkeypatch):
    primary = _connection("primary", "Primary")
    fallback = _connection("backup", "Backup")
    db = FakeDB([fallback, primary], [], fallback=False)
    calls = []

    def failing(_db, conn, **kwargs):
        calls.append(conn.id)
        raise ai_gateway.AIServiceError("unavailable")

    monkeypatch.setattr(ai_gateway, "run_connection", failing)
    monkeypatch.setattr(ai_gateway, "within_budget", lambda *a: True)
    answer = ai_gateway.orchestrated_text(
        db, "org-1", task="messenger",
        instructions="Atiende a la persona",
        prompt="Hola", max_output_tokens=120,
    )
    assert answer is None
    assert calls == ["primary"]


def test_unverified_provider_never_joins_fallback(monkeypatch):
    primary = _connection("primary", "Primary")
    unverified = _connection("unsafe", "No verificada")
    unverified.last_status = "error"
    db = FakeDB([unverified, primary], [], fallback=True)
    calls = []

    def failing(_db, conn, **kwargs):
        calls.append(conn.id)
        raise ai_gateway.AIServiceError("unavailable")

    monkeypatch.setattr(ai_gateway, "run_connection", failing)
    monkeypatch.setattr(ai_gateway, "within_budget", lambda *a: True)
    ai_gateway.orchestrated_text(
        db, "org-1", task="messenger",
        instructions="Responde con cuidado", prompt="Hola",
        max_output_tokens=120,
    )
    assert calls == ["primary"]


def test_transient_failure_keeps_verified_connection_for_next_message(monkeypatch):
    conn = _connection("primary", "Primary")
    conn.price_input_per_million = None
    conn.price_output_per_million = None
    conn.last_checked_at = None

    class FakeUsageDB:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

        def flush(self):
            pass

    db = FakeUsageDB()

    def unavailable(*args, **kwargs):
        raise ai_gateway.AIServiceError("No se pudo contactar al proveedor")

    monkeypatch.setattr(ai_gateway, "invoke", unavailable)
    import pytest
    with pytest.raises(ai_gateway.AIServiceError):
        ai_gateway.run_connection(
            db, conn, task="messenger", instructions="help",
            prompt="Hola", timeout=2,
        )
    assert conn.last_status == "verified"
    assert len(db.added) == 1 and db.added[0].status == "error"

    def bad_credentials(*args, **kwargs):
        raise ai_gateway.AIServiceError("Autenticación rechazada", requires_reverify=True)

    monkeypatch.setattr(ai_gateway, "invoke", bad_credentials)
    with pytest.raises(ai_gateway.AIServiceError):
        ai_gateway.run_connection(
            db, conn, task="messenger", instructions="help",
            prompt="Hola", timeout=2,
        )
    assert conn.last_status == "error"
