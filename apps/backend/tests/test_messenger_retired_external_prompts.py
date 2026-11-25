"""Regression for the real 2026-11-25 Messenger incident."""
from types import SimpleNamespace
import pytest

from app import facebook_ai
from app.galancito_flow import (
    apply_permission_reply, external_permission_prompt, permission_question,
    wants_human,
)


@pytest.mark.parametrize("text", [
    "Alguien del equipo porfi", "alguien del equipo porfa",
    "Prefiero alguien del equipo", "con alguien del equipo por favor",
])
def test_human_request_short_chilean_replies(text):
    assert wants_human(text)


@pytest.mark.parametrize("provider", ["team", "openai"])
@pytest.mark.parametrize("repeat", [False, True])
def test_retired_external_prompt_does_not_authorize_a_bare_yes(provider, repeat):
    prompt = permission_question(provider, repeat)
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
