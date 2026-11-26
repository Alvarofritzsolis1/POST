"""Conversation-level Messenger regressions, not synthetic learning claims.

Run the real signed webhook, database queue and worker with Meta/Ollama stubbed.
No production PSID, access token or customer message is sent from these tests.
"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_intake import small_talk_reply
from app.galancito_triage import analyze
from test_facebook_crm import enable_messaging, incoming, seed_historical_permission
from test_network import network


@pytest.mark.parametrize("greeting", [
    "hola buenos dias", "Hola, buenos días!", "hola buenas tardes",
    "hola buenas noches", "hola buen dia", "muy buenos dias",
    "hola como estas", "holaaa", "buenas noches",
])
def test_chilean_greetings_are_local_and_need_no_model(greeting):
    assert analyze(greeting).intent == "greeting"
    assert small_talk_reply(greeting)


@pytest.mark.parametrize("message", [
    "Hola, necesito carpinteros", "Hola, quiero postular a una obra",
    "Hola, buenos días, ¿cuánto pagan en esa obra?",
    "Hola buenas tardes, mi número es +56900000000",
])
def test_mixed_greetings_preserve_the_actual_request(message):
    assert analyze(message).intent != "greeting"


def _local_messenger(n, monkeypatch):
    enable_messaging(n, monkeypatch)
    for key, value in {
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_CONTEXTUAL_MESSENGER_ENABLED": "false",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "FACEBOOK_AI_ENABLED": "true",
        "FACEBOOK_AI_AUTO_REPLY_ENABLED": "true",
        "FACEBOOK_AI_API_KEY": "",
    }.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()


def _contact(n):
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    return n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()


def test_seen_job_post_asks_for_notice_without_permission_or_assumed_trade(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    replies = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: replies.append(args[2]) or f"synthetic-job-{len(replies)}")
    assert incoming(n, "Hola", "posting-hello").status_code == 200
    assert process_chat_next(n["Session"])
    assert incoming(n, "Vi una postulacion de trabajo", "posting-interest").status_code == 200
    assert process_chat_next(n["Session"])
    assert replies[-1].startswith("Claro, te ayudo.")
    assert "autorizas" not in replies[-1] and "Galancito" not in replies[-1]
    assert incoming(n, "De pintura en Coronel", "posting-trade").status_code == 200
    assert process_chat_next(n["Session"])
    lead = _contact(n)["lead"]
    assert not lead["specialty"]
    assert not lead["work_area"]
    assert lead["ai_consent_state"] == "not_requested"


def test_screenshot_greeting_gets_help_without_permission_or_inference(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    replies = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: replies.append(args[2]) or f"synthetic-delivered-{len(replies)}")
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No inference for greeting")))
    assert incoming(n, "hola buenos dias", "screenshot-greeting").status_code == 200
    first = _contact(n)
    assert first["lead"]["ai_consent_state"] == "not_requested"
    assert first["messages"][-1]["state"] == "pending"
    assert "autoriz" not in first["messages"][-1]["body"].lower()
    assert "en qué te puedo ayudar" in first["messages"][-1]["body"].lower()
    assert process_chat_next(n["Session"])
    assert len(replies) == 1
    assert "en qué te puedo ayudar" in replies[0].lower()
    assert not any(phrase in replies[0].lower() for phrase in (
        "atención automática", "asistente virtual", "soy un bot", "soy galancito",
        "ia local", "openai", "autoriza"
    ))

    assert incoming(n, "hola buenas tardes", "second-greeting").status_code == 200
    assert process_chat_next(n["Session"])
    assert len(replies) == 2
    assert not any(phrase in replies[1].lower() for phrase in (
        "atención automática", "asistente virtual", "soy un bot", "soy galancito",
        "ia local", "openai"
    ))
    assert _contact(n)["lead"]["ai_consent_state"] == "not_requested"


def test_identity_question_is_answered_truthfully_not_as_human(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: sent.append(a[2]) or f"synthetic-identity-{len(sent)}")
    assert incoming(n, "¿Eres una IA o una persona?", "explicit-identity").status_code == 200
    detail = _contact(n)
    assert detail["lead"]["ai_consent_state"] == "not_requested"
    assert process_chat_next(n["Session"])
    assert len(sent) == 1
    assert "ia" in sent[0].lower() or "inteligencia artificial" in sent[0].lower()
    assert "soy humano" not in sent[0].lower()


def test_complex_question_resumes_after_historical_permission_and_real_worker(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    replies, model_contexts = [], []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: replies.append(a[2]) or f"synthetic-delivered-{len(replies)}")
    assert incoming(n, "hola buenos dias", "resume-hi").status_code == 200
    assert process_chat_next(n["Session"])
    seed_historical_permission(n)
    assert incoming(n, "si", "resume-consent").status_code == 200
    assert _contact(n)["lead"]["ai_consent_state"] == "accepted"
    assert incoming(n, "¿Cuáles son los requisitos para postular?", "resume-q").status_code == 200

    from app import facebook_ai
    monkeypatch.setattr(facebook_ai, "generate_local_text",
                        lambda instructions, prompt, limit: (
                            model_contexts.append(prompt) or
                            "Te puedo orientar con los pasos generales. ¿Qué trabajo realizas?"))
    assert process_chat_next(n["Session"])
    assert len(replies) == 2
    assert len(model_contexts) == 1
    assert "requisitos" in model_contexts[0].lower()
    assert "autorizas" not in model_contexts[0].lower()
    assert "respuesta confirmada" not in replies[-1].lower()
    assert "qué trabajo" in replies[-1].lower()
    assert _contact(n)["lead"]["needs_support"] is False


def test_legacy_greeting_consent_never_claims_model_outage(network, monkeypatch):
    """A previous release may already have sent a permission prompt for 'hola'."""
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *a: sent.append(a[2]) or f"synthetic-delivered-{len(sent)}")
    assert incoming(n, "hola buenos dias", "legacy-greeting").status_code == 200
    first = _contact(n)
    lead_id = first["lead"]["id"]
    with n["Session"].begin() as db:
        for row in db.scalars(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead_id,
                FacebookChatMessage.direction == "outbound")):
            row.state = "cancelled"
    seed_historical_permission(n)
    assert incoming(n, "si", "legacy-consent").status_code == 200
    assert _contact(n)["lead"]["ai_consent_state"] == "accepted"
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("No inference after an old greeting")))
    assert process_chat_next(n["Session"])
    assert "respuesta confirmada" not in sent[-1].lower()
    assert "equipo" not in sent[-1].lower()
    assert "ayudar" in sent[-1].lower() or "necesitas" in sent[-1].lower()
    assert _contact(n)["lead"]["needs_support"] is False


@pytest.mark.parametrize("message", [
    "Vi una postulación de trabajo",
    "Me interesa el anuncio de trabajo",
    "Vengo por un aviso de pega",
])
def test_real_job_ad_messages_use_existing_application_router_not_ai(
        network, monkeypatch, message):
    n = network
    _local_messenger(n, monkeypatch)
    delivered = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: delivered.append(args[2]) or f"job-{len(delivered)}")
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("No language-model call for ordinary published-ad intent")))
    assert incoming(n, message, "real-job-ad").status_code == 200
    detail = _contact(n)
    assert detail["lead"]["ai_consent_state"] == "not_requested"
    assert detail["messages"][-1]["state"] == "pending"
    assert process_chat_next(n["Session"])
    assert len(delivered) == 1
    assert "aviso" in delivered[0].lower()
    assert not any(term in delivered[0].lower() for term in
                   ("soy galancito", "te habla galancito", "autorizas", "openai"))
    assert not _contact(n)["lead"]["specialty"]


@pytest.mark.parametrize("message,expected", [
    ("¿Cuánto pagan?", "pago depende"),
    ("¿Hay pega?", "equipo de cada obra"),
    ("Necesito ayuda", "qué trabajo"),
])
def test_short_employment_questions_do_not_trigger_technical_consent(
        network, monkeypatch, message, expected):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or f"faq-{len(sent)}")
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("Short generic question must stay local")))
    assert incoming(n, message, "faq-real").status_code == 200
    assert _contact(n)["lead"]["ai_consent_state"] == "not_requested"
    assert process_chat_next(n["Session"])
    assert len(sent) == 1 and expected in sent[0].lower()
    assert "galancito" not in sent[0].lower()
    assert "autorizas" not in sent[0].lower()


def test_messenger_identity_is_transparent_without_unprompted_assistant_name():
    from app.galancito_intake import identity_reply, natural_messenger_reply
    from app.galancito_flow import safe_ai_reply
    own_identity = identity_reply("¿Eres IA?")
    assert "asistente de IA" in own_identity
    assert "Galancito" not in own_identity
    result = natural_messenger_reply(
        "Soy Galancito, el asistente de IA de GALANT. Claro, puedo ayudarte con el aviso.")
    assert result == "Claro, puedo ayudarte con el aviso."
    useful = safe_ai_reply("Te ayudo con el aviso. ¿Qué oficio era? ¿En qué comuna?")
    assert useful.startswith("Te ayudo con el aviso.")
    assert useful.count("?") == 1
    options = safe_ai_reply("¿Buscas empleo (1) u ofreces servicios (2)?")
    assert "Buscas empleo" in options
    assert "(1)" not in options and "(2)" not in options


def test_contractor_crew_count_and_conditional_capacity_are_kept(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or f"synthetic-crew-{len(sent)}")

    for index, message in enumerate((
        "Hola, soy contratista de pintura",
        "Tengo una cuadrilla somos 4 que necesita hacer",
        "Según el presupuesto se puede contratar más personas",
    )):
        assert incoming(n, message, f"crew-{index}").status_code == 200
        process_chat_next(n["Session"])

    detail = _contact(n)["lead"]
    assert detail["specialty"] == "Pintura"
    assert detail["workers"] == 4
    assert detail["team_available"] is True
    assert detail["has_employees"] is None
    with n["Session"]() as db:
        lead = db.get(FacebookLead, detail["id"])
        context = lead.profile_sources["_declared_context"]
        assert context["crew_expandable"]["value"] is True
    assert "cuántas personas" not in " ".join(sent).lower()


def test_trade_in_a_colloquial_ad_reference_does_not_fill_the_profile(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or f"synthetic-ad-reference-{len(sent)}")

    message = "Buenas noches te hablo por la publicación de contratista pintor"
    assert incoming(n, message, "ad-reference").status_code == 200
    assert process_chat_next(n["Session"])
    detail = _contact(n)["lead"]
    assert not detail["specialty"] and detail["profile"]["notice_trade"] == "Pintura"
    assert sent == ["Gracias por escribir por el aviso de pintura. ¿Ofreces servicios de pintura como contratista?"]

    # Recover the same interest from a conversation received before this version.
    with n["Session"].begin() as db:
        lead = db.get(FacebookLead, detail["id"])
        lead.profile_sources = {"_declared_context": {}}
    repaired = n["send"](n["admin"], f'/facebook/leads/{detail["id"]}/refresh-profile', {})
    assert repaired.status_code == 200
    assert repaired.json()["profile"]["notice_trade"] == "Pintura"
    assert not repaired.json()["specialty"]
    assert not process_chat_next(n["Session"])

    assert incoming(n, "Sí po", "ad-confirmation").status_code == 200
    assert process_chat_next(n["Session"])
    detail = _contact(n)["lead"]
    assert detail["specialty"] == "Pintura" and detail["interest_type"] == "service_offer"
    assert sent[-1] == "¿En qué comuna puedes trabajar?"


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("consented", [False, True])
def test_colloquial_worksite_payment_requires_verified_terms(network, monkeypatch, approved, consented):
    from app.galancito_knowledge import search_value
    from app.galancito_knowledge_models import Knowledge

    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or f"synthetic-terms-{len(sent)}")
    message = "Y la pega es a trató"
    answer = "El aviso de práctica indica pago por jornada."
    assert incoming(n, "Vi un aviso para trabajar", "terms-ad").status_code == 200
    assert process_chat_next(n["Session"])
    assert len(sent) == 1 and "aviso" in sent[0].lower()
    with n["Session"].begin() as db:
        lead = db.scalar(select(FacebookLead))
        if consented:
            lead.ai_consent = True
            lead.ai_consent_state = "accepted"
            lead.ai_consent_provider = "ollama"
        if approved:
            title = "Modalidad de pago del aviso"
            db.add(Knowledge(org_id=lead.org_id, updated_by=n["a_user"]["id"], title=title,
                             kind="faq", scope="messenger", content=answer, phrases=[message],
                             status="approved", search_text=search_value(title, answer, [message])))
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *_args: pytest.fail("Las condiciones del aviso requieren una respuesta aprobada"))

    assert incoming(n, message, "terms-question").status_code == 200
    assert process_chat_next(n["Session"]) is approved
    assert not process_chat_next(n["Session"])
    lead = _contact(n)["lead"]
    assert lead["needs_support"] is (not approved)
    assert lead["ai_paused"] is (not approved)
    assert lead["ai_consent_state"] == ("accepted" if consented else "not_requested")
    assert sent[1:] == ([answer] if approved else [])


@pytest.mark.parametrize("message", [
    "Yo trabajo a trato", "Realizo trabajos por obra vendida o mano de obra",
    "La pega es a trato y quedé conforme", "Somos 4 maestros a jornada",
    "A todo esto, ¿se paga por avance?",
])
def test_worksite_payment_questions_do_not_swallow_offer_terms(message):
    from app.galancito_triage import worksite_details_question

    assert not worksite_details_question(message)


@pytest.mark.parametrize("answer, value, state", [
    ("Sí po", True, "confirmado_por_declaracion"),
    ("Todavía no", False, "confirmado_por_declaracion"),
    ("Prefiero no responder", None, "rechazado_por_usuario"),
])
def test_galilea_question_is_asked_once_and_saved_with_evidence(network, monkeypatch, answer, value, state):
    from app.galancito_intake import GALILEA_QUESTION, acceptable_intake_draft
    from app.galancito_memory import profile_facts

    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or f"synthetic-galilea-{len(sent)}")
    assert incoming(n, "Buenas tardes", "galilea-greeting").status_code == 200
    assert process_chat_next(n["Session"])
    with n["Session"].begin() as db:
        lead = db.scalar(select(FacebookLead))
        lead.interest_type = "service_offer"
        lead.specialty = "Pintura"
        lead.team_available, lead.workers = True, 4
        lead.experience = "5 años"
        lead.work_area = "Coronel"
        lead.work_communes = ["Coronel"]

    assert incoming(n, "Puedo partir mañana", "galilea-availability").status_code == 200
    assert process_chat_next(n["Session"])
    assert sent[-1] == GALILEA_QUESTION
    if value is True:
        assert incoming(n, "No cacho", "galilea-clarify").status_code == 200
        assert process_chat_next(n["Session"])
        assert "alguna vez en una obra de Galilea" in sent[-1]
    assert incoming(n, answer, "galilea-answer").status_code == 200
    assert process_chat_next(n["Session"])
    assert sent.count(GALILEA_QUESTION) == 1

    detail = _contact(n)["lead"]
    profile = detail["profile"]
    experience = profile["declared_context"]["worked_at_galilea"]
    assert experience["value"] is value
    assert experience["state"] == state and experience["message_id"] == "galilea-answer"
    assert "Experiencia previa en Galilea" not in profile["missing"]
    assert profile["galilea_experience"] == {
        True: "Sí, declarado", False: "No, declarado", None: "Prefirió no responder",
    }[value]
    assert detail["documents_state"] == "unverified"
    with n["Session"]() as db:
        facts = profile_facts(db.get(FacebookLead, detail["id"]))
    assert not acceptable_intake_draft("¿Has trabajado en Galilea?", facts)
    assert not acceptable_intake_draft("¿Has trabajado alguna vez en una obra de Galilea?", facts)


@pytest.mark.parametrize("message", [
    "Vengo por el aviso de una obra de Galilea",
    "Mi cuadrilla conoce a alguien que trabajó en Galilea",
    "¿Trabajaron en Galilea?",
    "Si trabajé en Galilea tendría que revisar los papeles",
    "Quiero trabajar en Galilea",
    "Sí",
])
def test_galilea_history_needs_a_personal_declaration_or_a_direct_question(message):
    from types import SimpleNamespace

    from app.galancito_memory import remember_declared_context
    from app.models import utcnow

    lead = SimpleNamespace(profile_sources={})
    assert not remember_declared_context(lead, message, "", remote_id="synthetic", at=utcnow())
    assert not lead.profile_sources


def test_number_with_whatsapp_label_completes_the_contact_without_triggering_handoff(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or "synthetic-whatsapp-reply")

    intro = "Buenas noches, le dejo mi número de contacto para que me dé más información, gracias"
    assert incoming(n, intro, "whatsapp-introduction").status_code == 200
    assert not process_chat_next(n["Session"])
    assert not _contact(n)["lead"]["needs_support"]

    assert incoming(n, "912345678 WhatsApp", "whatsapp-number").status_code == 200
    assert process_chat_next(n["Session"])
    assert not process_chat_next(n["Session"])
    detail = _contact(n)["lead"]
    assert detail["contact_phone"] == "+56912345678"
    assert detail["profile"]["declared_context"]["preferred_contact"]["value"] == "whatsapp"
    assert not detail["needs_support"] and not detail["ai_paused"]
    assert sent == ["Gracias por dejar tu WhatsApp. ¿De qué aviso o trabajo necesitas más información?"]

    with n["Session"].begin() as db:
        lead = db.get(FacebookLead, detail["id"])
        lead.contact_phone, lead.profile_sources = "", {}
    recovered = n["send"](n["admin"], f'/facebook/leads/{detail["id"]}/recover-contact', {})
    assert recovered.json()["contact_phone"] == "+56912345678"
    assert recovered.json()["profile"]["declared_context"]["preferred_contact"]["value"] == "whatsapp"
    assert not process_chat_next(n["Session"])


def test_vague_additional_services_are_visible_until_the_contact_names_them(network, monkeypatch):
    n = network
    _local_messenger(n, monkeypatch)
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: sent.append(args[2]) or f"synthetic-trades-{len(sent)}")

    assert incoming(n, "Realizo pintura pero también de todo un poco", "trades-unspecified").status_code == 200
    assert process_chat_next(n["Session"])
    detail = _contact(n)["lead"]
    assert detail["specialty"] == "Pintura" and detail["trades"] == ["Pintura"]
    assert detail["profile"]["additional_services_pending"] is True
    assert "Servicios adicionales por precisar" in detail["profile"]["missing"]
    assert "¿Qué otros trabajos" in sent[-1]

    assert incoming(n, "Hago también gasfitería y carpintería", "trades-specified").status_code == 200
    assert process_chat_next(n["Session"])
    detail = _contact(n)["lead"]
    assert detail["specialty"] == "Pintura"
    assert set(detail["trades"]) == {"Pintura", "Gasfitería", "Carpintería"}
    assert detail["profile"]["additional_services_pending"] is False
    assert "¿Qué otros trabajos" not in sent[-1]
