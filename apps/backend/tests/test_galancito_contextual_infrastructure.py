"""Queue and storage tests. Semantic quality is evaluated with real Ollama."""
from datetime import timedelta

from sqlalchemy import func, select

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_contextual import Fragment, Turn, apply_declarations, supported_declarations
from app.models import utcnow
from test_facebook_crm import enable_messaging, incoming, network, no_real_meta_sender_actions


def configure(network, monkeypatch):
    org_id = enable_messaging(network, monkeypatch)
    for name, value in {
        "FACEBOOK_AI_ENABLED": "true", "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true", "GALANCITO_CONTEXTUAL_MESSENGER_ENABLED": "true",
    }.items():
        monkeypatch.setenv(name, value)
    settings.cache_clear()
    with network["Session"].begin() as db:
        db.add(FacebookLead(org_id=org_id, page_id=settings().facebook_page_id, psid="123456789012345",
                            ai_consent=True, ai_consent_provider="ollama", ai_consent_state="accepted"))
    return network["Session"]


def test_burst_replay_and_worker_restart(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "Instalo aislación acústica", mid="test-acoustic").status_code == 200
    assert incoming(network, "Nos movemos por Cabrero", mid="test-location").status_code == 200
    assert incoming(network, "Nos movemos por Cabrero", mid="test-location").status_code == 200
    assert not process_chat_next(sessions)
    with sessions.begin() as db:
        rows = list(db.scalars(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending")))
        assert len(rows) == 1
        assert db.scalar(select(func.count()).select_from(FacebookChatMessage).where(
            FacebookChatMessage.direction == "inbound")) == 2
        rows[0].state = "drafting"
        rows[0].updated_at = utcnow() - timedelta(seconds=160)

    observed = []
    def unavailable(context, fragments, **kwargs):
        observed.extend((item.message_id, item.text) for item in fragments)
        raise RuntimeError("Ollama is unavailable")
    monkeypatch.setattr("app.galancito_contextual.request_turn", unavailable)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *args: "test-meta-sent")
    assert process_chat_next(sessions)
    assert observed == [("test-acoustic", "Instalo aislación acústica"),
                        ("test-location", "Nos movemos por Cabrero")]
    assert not process_chat_next(sessions)


def test_new_inbound_invalidates_draft_before_meta(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "Hacemos sellos cortafuego", mid="test-first").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.updated_at = utcnow() - timedelta(seconds=2)

    def interrupted(context, fragments, **kwargs):
        assert incoming(network, "¿Dónde queda la obra?", mid="test-newer").status_code == 200
        raise RuntimeError("Ollama is unavailable")
    def unexpected(*args):
        raise AssertionError("The superseded outbound must not reach Meta")
    monkeypatch.setattr("app.galancito_contextual.request_turn", interrupted)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    assert process_chat_next(sessions)
    with sessions() as db:
        states = set(db.scalars(select(FacebookChatMessage.state).where(
            FacebookChatMessage.direction == "outbound")))
        assert "cancelled" in states
        assert "sent" not in states


def test_evidence_bounds_manual_fields_and_idempotence(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    at = utcnow()
    fragments = (Fragment("test-origin", at, "Somos de Chillán, somos cerca de 15 en la cuadrilla"),)
    raw = Turn(i="intake", q="none", r="Gracias por contarme.", d=[
        {"f": "origin", "v": "Penco", "e": "Somos de Chillán"},
        {"f": "origin", "v": "Chillán", "e": "Somos de Chillán"},
        {"f": "crew", "v": "cerca de 15 en la cuadrilla", "e": "somos cerca de 15 en la cuadrilla"},
    ])
    declarations = supported_declarations(raw, fragments)
    assert [declaration[1] for declaration in declarations] == ["Chillán", "cerca de 15 en la cuadrilla"]
    with sessions.begin() as db:
        lead = db.scalar(select(FacebookLead).with_for_update())
        lead.profile_sources = {"_declared_context": {"declared_origin": {
            "value": "Lota", "source": "manual", "at": at.isoformat(),
        }}}
        assert apply_declarations(db, lead, declarations) == 1
        assert apply_declarations(db, lead, declarations) == 0
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert lead.workers is None and lead.employee_count is None
        assert lead.profile_sources["_declared_context"]["declared_origin"]["value"] == "Lota"
        saved = lead.profile_sources["_declared_context"]["crew_size"]
        assert saved["message_id"] == "test-origin"
        assert saved["value"] == "cerca de 15 en la cuadrilla"

def test_questions_and_partial_counts_cannot_supply_profile_values():
    at = utcnow()
    fragments = (
        Fragment("test-price", at, "¿A cuánto pagan la pintura?"),
        Fragment("test-crew", at, "Somos más de 10 maestros"),
        Fragment("test-town", at, "Me puedo mover a Bulnes"),
    )
    draft = Turn(i="question", q="none", r="Lo confirma el equipo.", d=[
        {"f": "trade", "v": "pintura", "e": "pintura"},
        {"f": "crew", "v": "10 maestros", "e": "10 maestros"},
        {"f": "crew", "v": "Bulnes", "e": "Bulnes"},
        {"f": "crew", "v": "más de 10 maestros", "e": "más de 10 maestros"},
    ])
    assert [(field, value) for field, value, _ in supported_declarations(draft, fragments)] == [
        ("crew", "más de 10 maestros"),
    ]
