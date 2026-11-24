"""Real Messenger routing regressions for workers with little digital experience.

Tests exercise conversational progress, explicit declarations and human takeover,
not synthetic claims about model intelligence or employment availability.
"""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.facebook_crm_models import FacebookLead
from app.facebook_worksite_reply import application_reply, digital_help_reply
from app.galancito_escalation import flag_for_human
from app.galancito_flow import wants_human
from app.galancito_triage import (
    ASK_APPLICATION, ASK_APPLICATION_LINK, ASK_APPLICATION_INTEREST,
    ASK_APPLICATION_OWN, referring_to_application,
)
from test_facebook_crm import incoming
from test_messenger_conversation_regression import _local_messenger, _contact
from test_network import network


def _app(message, prior=""):
    lead = SimpleNamespace(org_id="synthetic-organization", page_id="synthetic-page")
    return application_reply(None, lead, message, prior_prompt=prior, notices=[])


@pytest.mark.parametrize("initial", [
    "Vi una postulación de trabajo",
    "vi un aviso",
    "lei un aviso",
    "me interesa una publicacion",
    "vengo por una oferta de trabajo",
    "quiero postular",
])
def test_job_ads_start_with_simple_question_no_links(initial):
    reply = _app(initial)
    assert reply == ASK_APPLICATION
    assert "link" not in reply.lower()
    assert "Galancito" not in reply


@pytest.mark.parametrize("answer,trade", [
    ("De gasfiter", "gasfitería"),
    ("de gasfite", "gasfitería"),
    ("de gafiter", "gasfitería"),
    ("Era de carpintreo", "carpintería"),
    ("de sodador", "soldadura"),
    ("de electricito", "electricidad"),
    ("el de albañir", "albañilería"),
    ("de pintur", "pintura"),
    ("de seramista", "cerámica"),
    ("uno de tabiques", "tabiquería"),
    ("de impermiabilizacion", "impermeabilización"),
    ("de enfierador", "enfierradura"),
])
def test_short_typo_trade_answers_advance_without_a_link(answer, trade):
    reply = _app(answer, ASK_APPLICATION)
    assert trade in reply.lower()
    assert reply.endswith(ASK_APPLICATION_INTEREST)
    assert "link" not in reply.lower()
    assert "enlace" not in reply.lower()


@pytest.mark.parametrize("answer", [
    "no tengo link", "no se copiar", "no se mandar el link",
    "no se usar facebook", "no tengo facebook", "no entiendo el enlace",
])
def test_digital_difficulty_does_not_force_human_handoff_or_link(answer):
    result = _app(answer, ASK_APPLICATION)
    assert result == ASK_APPLICATION_LINK
    assert referring_to_application(result)
    assert _app("de gasfiter", result).endswith(ASK_APPLICATION_INTEREST)


@pytest.mark.parametrize("answer", [
    "no se", "no recuerdo", "no me acuerdo", "nose", "no cacho",
])
def test_forgotten_ad_does_not_dead_end(answer):
    reply = _app(answer, ASK_APPLICATION)
    assert "seguir igual" in reply
    assert reply.endswith(ASK_APPLICATION_INTEREST)


@pytest.mark.parametrize("answer", [
    "yo", "yo solo", "yo no mas", "pa mi", "solo yo", "para mi",
    "quiero trabajar", "busco pega",
])
def test_job_seeker_short_roles_ask_if_advertised_trade_is_their_own(answer):
    prior = "Ah, era un aviso de gasfitería. " + ASK_APPLICATION_INTEREST
    reply = _app(answer, prior)
    assert reply == ASK_APPLICATION_OWN + "gasfitería?"
    assert referring_to_application(reply)


@pytest.mark.parametrize("answer", ["tengo cuadrilla", "con mi gente", "tengo empresa", "somos varios"])
def test_small_contractor_offering_services_is_not_treated_as_job_seeker(answer):
    # Company vocabulary must not imply employees are legally verified.
    prior = "Ah, era un aviso de gasfitería. " + ASK_APPLICATION_INTEREST
    reply = _app(answer, prior)
    assert reply and "ofreces tus servicios" in reply
    assert "comuna" in reply


def test_trade_is_only_confirmed_after_person_says_it_is_their_own():
    prior = "Ah, era un aviso de gasfitería. " + ASK_APPLICATION_INTEREST
    followup = _app("yo solo", prior)
    assert followup == ASK_APPLICATION_OWN + "gasfitería?"
    assert _app("sí", followup).endswith("¿En qué comuna puedes trabajar?")
    assert "no voy a asumir" in _app("no", followup)


@pytest.mark.parametrize("previous,answer,expected", [
    (ASK_APPLICATION, "No tengo link", "no necesitas mandar"),
    (ASK_APPLICATION_LINK, "No se copiar enlace", "no necesitas enlaces"),
    (ASK_APPLICATION, "No lo se", "seguir igual"),
    ("Ah, era un aviso de pintura. " + ASK_APPLICATION_INTEREST,
     "No entiendo", "te explico"),
])
def test_gentle_non_technical_guidance(previous, answer, expected):
    assert expected in _app(answer, previous).lower()


@pytest.mark.parametrize("human_phrase", [
    "quiero hablar con una persona",
    "quiero hablar con alguien del equipo",
    "quiero que me atienda alguien",
    "me puede atender una persona",
])
def test_explicit_human_requests_are_recognized(human_phrase):
    assert wants_human(human_phrase)


def test_signed_messenger_conversation_retains_context_and_never_claims_own_trade(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: sent.append(a[2]) or "message-" + str(len(sent)))
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("Simple postulation needs no model")))
    for i, message in enumerate([
        "Vi una postulacion de trabajo", "DE GASFITER", "yo solo", "si"
    ], 1):
        assert incoming(n, message, f"simple-{i}").status_code == 200
        assert process_chat_next(n["Session"])
    assert len(sent) == 4
    assert "¿De qué trabajo era el aviso?" in sent[0]
    assert "gasfitería" in sent[1].lower()
    assert sent[1].endswith(ASK_APPLICATION_INTEREST)
    assert sent[2] == ASK_APPLICATION_OWN + "gasfitería?"
    assert "¿En qué comuna puedes trabajar?" in sent[3]
    lead = _contact(n)["lead"]
    assert lead["interest_type"] == "employment"
    assert lead["specialty"] == "Gasfitería"
    assert lead["ai_consent_state"] == "not_requested"
    assert not lead["needs_support"]


def test_advert_only_does_not_falsely_fill_the_persons_trade(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: "sent-" + a[2][:10])
    for i, message in enumerate(["Vi una postulacion de trabajo", "De pintura en Coronel"], 1):
        assert incoming(n, message, f"quoted-{i}").status_code == 200
        assert process_chat_next(n["Session"])
    lead = _contact(n)["lead"]
    assert not lead["specialty"]
    assert not lead["work_area"]
    assert not lead["needs_support"]


def test_explicit_handoff_stops_ai_and_one_operator_action_resumes_it(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: sent.append(a[2]) or "sent-" + str(len(sent)))
    assert incoming(n, "hola", "human-first").status_code == 200
    assert process_chat_next(n["Session"])
    assert incoming(n, "quiero hablar con una persona", "human-second").status_code == 200
    lead = _contact(n)["lead"]
    assert lead["needs_support"] is True
    assert lead["ai_paused"] is True
    assert lead["ai_consent_state"] == "not_requested"
    assert process_chat_next(n["Session"])
    assert "persona" in sent[-1].lower()
    assert incoming(n, "Hola, necesito ayuda", "human-third").status_code == 200
    assert not process_chat_next(n["Session"])
    assert n["send"](
        n["admin"], "/facebook/leads/" + lead["id"],
        {"needs_support": False, "ai_paused": False}, method="PATCH").status_code == 200
    after = _contact(n)["lead"]
    assert not after["needs_support"] and not after["ai_paused"]
    assert after["ai_consent_state"] == "not_requested"
    assert incoming(n, "hola", "human-resumed").status_code == 200
    assert process_chat_next(n["Session"])
    assert "hola" in sent[-1].lower() or "te leo" in sent[-1].lower()


def test_detected_unresolved_case_also_pauses_and_requires_operator_resume(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    assert incoming(n, "hola", "human-detected").status_code == 200
    lead_id = _contact(n)["lead"]["id"]
    with n["Session"].begin() as db:
        from sqlalchemy import select
        lead = db.get(FacebookLead, lead_id)
        flag_for_human(db, lead, "El modelo no pudo verificar condiciones del aviso")
    lead = _contact(n)["lead"]
    assert lead["needs_support"] and lead["ai_paused"]
    assert "verificar" in lead["support_reason"]
    result = n["send"](
        n["admin"], "/facebook/leads/" + lead_id,
        {"ai_paused": False, "needs_support": False}, method="PATCH")
    assert result.status_code == 200
    lead = _contact(n)["lead"]
    assert not lead["needs_support"] and not lead["ai_paused"]
    assert lead["support_reason"] == ""


@pytest.mark.parametrize("message", ["no cacho", "no entiendo", "nose", "no me acuerdo"])
def test_confused_reply_to_an_ad_is_clarified_before_escalating(message):
    from app.facebook_onboarding import assistance_signal
    assert assistance_signal(message, prior_prompt=ASK_APPLICATION) is None
    assert _app(message, ASK_APPLICATION) is not None


def test_real_webhook_does_not_handoff_after_a_single_no_cacho(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: sent.append(a[2]) or "sent-" + str(len(sent)))
    for i, msg in enumerate(["Vi una postulacion de trabajo", "No cacho"], 1):
        assert incoming(n, msg, f"clarify-{i}").status_code == 200
        assert process_chat_next(n["Session"])
    assert len(sent) == 2 and "seguir igual" in sent[-1].lower()
    lead = _contact(n)["lead"]
    assert not lead["needs_support"] and not lead["ai_paused"]


def test_human_handoff_is_not_a_revocation_of_accepted_ai_permission():
    from app.galancito_flow import apply_permission_reply
    lead = SimpleNamespace(ai_consent=True, ai_consent_state="accepted",
                           ai_consent_provider="ollama")
    assert apply_permission_reply(lead, "quiero hablar con una persona", "") is None
    assert lead.ai_consent is True
    assert lead.ai_consent_state == "accepted"
    assert lead.ai_consent_provider == "ollama"
    # A conscious refusal is different: operator cannot override consent.
    assert apply_permission_reply(lead, "no quiero IA", "") is False
    assert not lead.ai_consent
    assert lead.ai_consent_state == "declined"
    assert lead.ai_consent_provider == ""


@pytest.mark.parametrize("answer", ["pa mi no mas", "para mí mismo", "pami", "que me contraten", "con contrato"])
def test_contextual_role_survives_clarifications_and_legacy_question(answer):
    from app.galancito_triage import ASK_APPLICATION_ROLE_CLARIFY, application_role
    for prior in (ASK_APPLICATION_INTEREST, ASK_APPLICATION_ROLE_CLARIFY,
                  "¿El trabajo lo buscas para ti o para tu equipo?"):
        assert application_role(answer, prior) == "employment"
        assert _app(answer, prior) and "oficio" in _app(answer, prior)
    assert application_role(answer, "¿En qué comuna puedes trabajar?") is None
    assert application_role("solo", ASK_APPLICATION_INTEREST) is None
    assert application_role("no tengo gente", ASK_APPLICATION_INTEREST) is None
    assert application_role("¿para mi?", ASK_APPLICATION_INTEREST) is None
