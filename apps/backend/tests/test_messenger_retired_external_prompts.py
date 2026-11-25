"""Regression for the real 2026-11-25 Messenger incident."""
from types import SimpleNamespace
import pytest

from app import facebook_ai
from app.galancito_flow import (
    apply_permission_reply, external_permission_prompt,
    wants_human,
)


@pytest.mark.parametrize("text", [
    "Alguien del equipo porfi", "alguien del equipo porfa",
    "Prefiero alguien del equipo", "con alguien del equipo por favor",
])
def test_human_request_short_chilean_replies(text):
    assert wants_human(text)


@pytest.mark.parametrize("provider", ["team", "openai"])
def test_retired_external_prompt_does_not_authorize_a_bare_yes(provider):
    service = "los proveedores de IA externos de GALANT" if provider == "team" else "la IA de OpenAI"
    prompt = f"¿Me autorizas a compartir tus mensajes con {service}?"
    assert external_permission_prompt(prompt)
    lead = SimpleNamespace(ai_consent=False, ai_consent_provider=provider,
        ai_consent_state="requested_team" if provider == "team" else "requested")
    assert apply_permission_reply(lead, "Sí", prompt) is None
    assert not lead.ai_consent


@pytest.mark.parametrize("provider", ["team", "openai"])
@pytest.mark.parametrize("local", [True, False])
def test_unconsented_external_route_uses_local_or_disabled(monkeypatch, provider, local):
    monkeypatch.setattr(facebook_ai, "messenger_ai_source", lambda *_: provider)
    cfg = SimpleNamespace(facebook_ai_provider="ollama" if local else "openai",
                          galancito_local_ai_enabled=local)
    lead = SimpleNamespace(org_id="test", ai_consent=False,
                           ai_consent_provider="", ai_consent_state="not_requested")
    assert facebook_ai.messenger_contact_ai_source(None, lead, cfg) == (
        "ollama" if local else "disabled")
    lead.ai_consent = True
    lead.ai_consent_provider = provider
    lead.ai_consent_state = "accepted_team" if provider == "team" else "accepted"
    assert facebook_ai.messenger_contact_ai_source(None, lead, cfg) == provider


@pytest.mark.parametrize("message", [
    "Hola me daría más información por la publicación que le comenté porfavor",
    "Quiero más información sobre el aviso",
    "Me da detalles de la publicación",
])
def test_information_about_publication_is_recognized(message):
    from app.galancito_triage import asks_about_application
    from app.facebook_worksite_reply import application_reply
    assert asks_about_application(message)
    lead = SimpleNamespace(org_id="test", page_id="test")
    assert application_reply(None, lead, message, notices=[]) == (
        "Claro, te ayudo. ¿De qué trabajo era el aviso?")


def test_crew_size_colloquial_singular():
    from app.galancito_triage import analyze
    from app.galancito_intake import _team_update
    text = "Somos 4 persona pero pueden ser mas"
    assert analyze(text).workers == 4
    lead = SimpleNamespace(team_available=None, workers=None)
    _team_update(lead, "somos 4 persona | pueden ser mas", "")
    assert lead.workers == 4 and lead.team_available is True


@pytest.mark.parametrize("message", ["Y el numero es 912345678", "El teléfono es 912345678"])
def test_voluntary_phone_continuation(message):
    from app.galancito_phone import phone_shared_by_sender
    assert phone_shared_by_sender(message) == "+56912345678"
    assert phone_shared_by_sender("El número de otro trabajador es 912345678") is None


def test_origin_reply_continues_without_assuming_work_area():
    from app.galancito_intake import next_intake_reply, _commune_update
    facts = {"workers": 4, "team_available": True, "contact_available": True}
    reply = next_intake_reply("Hola de san pedro", facts, "¿De donde es usted?")
    assert reply == "Perfecto, gracias. ¿Qué tipo de trabajos realizan?"
    lead = SimpleNamespace(work_communes=[], work_area="")
    _commune_update(lead, "Hola de san pedro", "de donde es usted")
    assert not lead.work_area


def test_smart_sheet_preserves_crew_flexibility_and_origin_with_evidence():
    from datetime import datetime, timezone
    from app.galancito_memory import remember_declared_context
    from app.galancito_contact_profile import contact_profile
    from app.galancito_conversation_summary import summarize_conversation
    lead = SimpleNamespace(profile_sources={}, workers=4, team_available=True,
                           contact_phone="+56900000000", work_area="")
    now = datetime.now(timezone.utc)
    assert remember_declared_context(lead, "Somos cuatro personas, pero podemos sumar mas",
                                      "", remote_id="crew", at=now)
    assert remember_declared_context(lead, "Hola de san pedro", "¿De donde es usted?",
                                      remote_id="origin", at=now)
    profile = contact_profile(lead)
    assert profile["declared_context"]["crew_expandable"]["value"] is True
    assert profile["declared_context"]["declared_origin"]["value"] == "San Pedro"
    assert "cantidad adicional no confirmada" in profile["summary"]
    assert "No equivale a zona de trabajo confirmada" in profile["summary"]
    assert lead.work_area == ""
    summary = summarize_conversation(lead, [])
    context = {fact["key"]: fact for fact in summary["facts"]}
    assert context["crew_expandable"]["source_message_id"] == "crew"
    assert context["declared_origin"]["source_message_id"] == "origin"
    assert "work_area" not in context
    assert remember_declared_context(lead, "No podemos sumar mas", "", remote_id="correction", at=now)
    assert contact_profile(lead)["declared_context"]["crew_expandable"]["value"] is False
    assert not remember_declared_context(lead, "Podemos sumar mas", "", remote_id="older", at=now, historical=True)
