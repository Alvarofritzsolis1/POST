"""Regression gates for the Core Intelligence audit; no live contact data."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.facebook_crm_models import FacebookLead, FacebookChatMessage
from app.facebook_refresh_policy import refresh_retry_allowed
from app.galancito_flow import messenger_model_authorized
from app.galancito_training import summarize
from app.galancito_contextual import memory_text
from test_facebook_crm import enable_messaging, incoming, network, no_real_meta_sender_actions


def local_config(**overrides):
    values = dict(facebook_local_processing_authorized=True,
                  facebook_ai_enabled=True, facebook_ai_provider="ollama",
                  galancito_local_ai_enabled=True, facebook_org_id="tenant",
                  facebook_page_id="page")
    return SimpleNamespace(**(values | overrides))


def contact(**overrides):
    values = dict(ai_consent=False, ai_consent_state="not_requested",
                  ai_consent_provider="", ai_paused=False, needs_support=False,
                  org_id="tenant", page_id="page")
    return SimpleNamespace(**(values | overrides))


@pytest.mark.parametrize("overrides", [
    {"ai_consent_state": "declined"}, {"ai_paused": True}, {"needs_support": True},
    {"org_id": "other"}, {"page_id": "other"}, {"ai_consent_state": "requested"},
])
def test_local_policy_respects_privacy(overrides):
    assert not messenger_model_authorized(local_config(), contact(**overrides), "ollama")


def test_local_policy_never_grants_external_permission():
    lead = contact()
    assert messenger_model_authorized(local_config(), lead, "ollama")
    assert not messenger_model_authorized(local_config(), lead, "team")
    assert not messenger_model_authorized(local_config(), lead, "openai")
    assert not messenger_model_authorized(local_config(facebook_local_processing_authorized=False), lead, "ollama")
    assert not messenger_model_authorized(local_config(facebook_ai_provider="openai"), lead, "ollama")
    assert lead.ai_consent is False and lead.ai_consent_state == "not_requested"


@pytest.mark.parametrize("error", [
    "Meta rechazó la solicitud (HTTP 400 · código Meta 10).",
    "Meta rechazó la solicitud (HTTP 400 · código Meta 100 / subcódigo 33).",
    "Meta rechazó la solicitud (HTTP 400 · código Meta 190).",
])
def test_permanent_errors_do_not_auto_retry(error):
    now = datetime.now(timezone.utc)
    assert not refresh_retry_allowed("failed", error, now - timedelta(days=10), now)
    assert refresh_retry_allowed("done", "", now, now)


def test_transient_refresh_cooldown():
    now = datetime.now(timezone.utc)
    assert not refresh_retry_allowed("failed", "TimeoutError", now - timedelta(seconds=25), now)
    assert refresh_retry_allowed("failed", "TimeoutError", now - timedelta(minutes=15), now)
    assert not refresh_retry_allowed("pending", "", now, now)
    assert not refresh_retry_allowed("uncertain", "", now, now)


def test_training_score_is_full_case_pass_rate():
    from app.galancito_training_eval import WEIGHTS
    metrics = {"passed": 42, "failed": 58, "turns": 100,
               "judged_turns": 100, "dimensions": {key: 98 for key in WEIGHTS}}
    result = summarize(metrics)
    assert result["score"] == 42
    assert result["score_basis"] == "synthetic_case_pass_rate"
    assert result["dimension_score"] == 98
    assert summarize({})["score"] is None


def test_memory_prior_question_is_preserved_with_long_facts():
    facts = {"specialty": "Pintura", "experience": "8 años", "trades": ["x" * 100] * 30,
             "declared_context": {"worked_at_galilea": False}}
    context, count = memory_text(facts, [], [], "¿Cuánto tiempo llevas en el oficio?", [], None)
    assert len(context) <= 1650 and count == 0
    assert "¿Cuánto tiempo llevas en el oficio?" in context
    import json
    line = next(line for line in context.splitlines() if line.startswith("Ficha acumulada: "))
    parsed = json.loads(line.removeprefix("Ficha acumulada: "))
    assert parsed["specialty"] == "Pintura"
    assert parsed["experience"] == "8 años"


def test_new_contact_queues_local_model_without_fabricating_consent(network, monkeypatch):
    enable_messaging(network, monkeypatch)
    for key, value in {
        "FACEBOOK_AI_ENABLED": "true",
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "GALANCITO_CONTEXTUAL_MESSENGER_ENABLED": "true",
        "FACEBOOK_LOCAL_PROCESSING_AUTHORIZED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()
    try:
        assert incoming(network, "Instalo aislación acústica", mid="core-local-first").status_code == 200
        with network["Session"]() as db:
            lead = db.scalar(select(FacebookLead).where(FacebookLead.psid == "123456789012345"))
            assert lead is not None and lead.ai_consent is False
            assert lead.ai_consent_state == "not_requested"
            row = db.scalar(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.direction == "outbound",
                FacebookChatMessage.state == "ai_pending"))
            assert row is not None
    finally:
        settings.cache_clear()


def test_approximate_crew_is_known_without_inventing_exact_count():
    from app.galancito_intake import conversation_fields, pending_professional_questions
    facts = {"interest_type": "service_offer", "specialty": "Pintura",
             "team_available": True, "workers": None,
             "declared_context": {"crew_size": "más de 10 maestros"}}
    assert conversation_fields(facts)["workers"]
    assert "workers" not in pending_professional_questions(facts)
    assert facts["workers"] is None


def test_volunteered_professional_duration_preserves_approximation():
    from app.galancito_intake import apply_intake
    from test_galancito_curriculum_20 import blank_lead
    lead = blank_lead()
    apply_intake(lead, "Soy contratista hace más de 8 años", "")
    assert lead.experience == "más de 8 años"


def test_distinct_master_and_contractor_experience():
    from app.galancito_intake import apply_intake
    from test_galancito_curriculum_20 import blank_lead
    lead = blank_lead()
    apply_intake(lead, "Yo voy maestro yesero hace más de 15 años. Y contratista y con gente a cargo más de 8 años.", "")
    assert "15 años" in lead.experience and "8 años" in lead.experience


def test_recovery_preview_rolls_back_and_preserves_manual_fields(network, monkeypatch):
    from app.models import utcnow
    from app.facebook_crm_models import FacebookLeadTrace, FacebookLeadTrade
    org_id = enable_messaging(network, monkeypatch)
    at = utcnow()
    with network["Session"].begin() as db:
        lead = FacebookLead(org_id=org_id, page_id=settings().facebook_page_id,
                            psid="123456789012345", specialty="Electricidad",
                            profile_sources={"specialty": {"source": "manual"},
                                             "availability": {"source": "manual"}})
        db.add(lead)
        db.flush()
        ident = lead.id
        db.add_all([
            FacebookChatMessage(org_id=org_id, lead_id=ident, page_id=lead.page_id,
                                remote_id="recover-past-intake", direction="inbound",
                                state="received", body="Soy contratista hace más de 8 años",
                                created_at=at, updated_at=at),
            FacebookChatMessage(org_id=org_id, lead_id=ident, page_id=lead.page_id,
                                remote_id="recover-past-availability", direction="inbound",
                                state="received", body="Estoy disponible desde mañana",
                                created_at=at + timedelta(seconds=1),
                                updated_at=at + timedelta(seconds=1)),
        ])
    base = f"/facebook/leads/{ident}/refresh-profile"
    preview = network["send"](network["admin"], base + "?dry_run=true", {})
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["dry_run"] and data["messages_examined"] == 2
    assert data["changes"]["experience"]["after"] == "más de 8 años"
    assert data["evidence"]["experience"] == "recover-past-intake"
    assert "specialty" not in data["changes"] and "availability" not in data["changes"]
    with network["Session"]() as db:
        lead = db.get(FacebookLead, ident)
        assert not lead.experience and lead.specialty == "Electricidad" and not lead.availability
        assert not list(db.scalars(select(FacebookLeadTrace).where(FacebookLeadTrace.lead_id == ident)))
        assert not list(db.scalars(select(FacebookLeadTrade).where(FacebookLeadTrade.lead_id == ident)))
    applied = network["send"](network["admin"], base, {})
    assert applied.status_code == 200, applied.text
    assert applied.json()["experience"] == "más de 8 años"
    assert applied.json()["specialty"] == "Electricidad" and not applied.json()["availability"]
    repeated = network["send"](network["admin"], base + "?dry_run=true", {})
    assert repeated.status_code == 200
    assert repeated.json()["changes"] == {}


@pytest.mark.parametrize("known_name,opt_out,expected", [
    ("Interesado de Facebook", False, "Nombre Ejemplo"),
    ("Nombre Manual", False, "Nombre Manual"),
    ("Interesado de Facebook", True, "Interesado de Facebook"),
])
def test_explicit_recovery_restores_only_cleared_non_refused_name(
        network, monkeypatch, known_name, opt_out, expected):
    from app.models import utcnow
    from app.galancito_memory import apply_messenger_message
    org_id = enable_messaging(network, monkeypatch)
    with network["Session"].begin() as db:
        lead = FacebookLead(org_id=org_id, page_id=settings().facebook_page_id,
                            psid="123456789012345", display_name=known_name,
                            name_opt_out=opt_out,
                            profile_sources={"display_name": {"source": "manual"},
                                             "name_opt_out": {"source": "manual"}})
        db.add(lead)
        db.flush()
        apply_messenger_message(db, lead, "Nombre Ejemplo", "¿Cuál es tu nombre?",
                                remote_id="synthetic-name-evidence", at=utcnow(), replay=True)
        assert lead.display_name == expected
        assert lead.name_opt_out is opt_out


def test_contextual_reply_topics_exclude_persisted_and_new_fields():
    from app.galancito_contextual import _pending_reply_topics, Fragment
    from app.models import utcnow
    fragment = Fragment("synthetic-field", utcnow(), "Puedo empezar mañana")
    facts = {"experience": "7 años", "work_communes": ["Los Ángeles"],
             "availability": "", "field_states": {}}
    assert _pending_reply_topics(facts, []) == {"availability": "disponibilidad para empezar"}
    assert _pending_reply_topics(facts, [("availability", "mañana", fragment)]) == {}
    facts["field_states"]["availability"] = "rechazado_por_usuario"
    assert _pending_reply_topics(facts, []) == {}
