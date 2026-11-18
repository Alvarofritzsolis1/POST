"""Synthetic tests for curriculum, small-contractor interviews and live inbox.
No real Messenger messages or production records are used.
"""
from datetime import datetime, timedelta, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest

from sqlalchemy import select

from app.facebook_crm_models import FacebookLead
from app.galancito_intake import apply_intake, next_intake_reply, natural_messenger_reply, needs_deeper_response
from app.galancito_contact_profile import contact_profile
from app.galancito_triage import analyze, private_data
from app.models import User
from test_network import network


def blank_lead(**changes):
    values = dict(
        entity_type="unknown", interest_type="unknown", specialty="",
        specialty_source="message", team_available=None, workers=None,
        has_employees=None, experience="", work_area="", availability="",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def respond(lead, question: str, reply: str) -> str | None:
    apply_intake(lead, reply, question)
    return next_intake_reply(reply, vars(lead), question)


def test_small_contractor_with_misspellings_and_one_number_answers():
    lead = blank_lead()
    next_question = respond(lead, "", "ola soy carpintreo")
    assert lead.specialty == "Carpintería"
    assert "cuenta (1)" in next_question
    next_question = respond(lead, next_question, "1")
    assert lead.interest_type == "service_offer"
    assert "Trabajas solo" in next_question
    next_question = respond(lead, next_question, "2")
    assert lead.team_available is True
    assert "Cuántas personas" in next_question
    next_question = respond(lead, next_question, "4")
    assert lead.workers == 4
    assert "Cuánto tiempo" in next_question
    next_question = respond(lead, next_question, "3 años")
    assert "3 años" in lead.experience
    next_question = respond(lead, next_question, "coronel")
    assert lead.work_area.lower() == "coronel"
    assert "Desde cuándo" in next_question
    last = respond(lead, next_question, "mañana")
    assert lead.availability == "mañana"
    assert "registré" in last
    assert lead.entity_type == "unknown"  # No assumed company or employees.
    assert lead.has_employees is None


def test_independent_works_alone_without_automatic_company_or_legal_employees():
    lead = blank_lead()
    question = respond(lead, "", "yo soy sodador")
    assert lead.specialty == "Soldadura"
    question = respond(lead, question, "1")
    question = respond(lead, question, "1")
    assert lead.interest_type == "service_offer"
    assert lead.team_available is False
    assert lead.workers == 1
    assert lead.has_employees is None
    assert "experiencia" not in question.lower() or "tiempo" in question.lower()


def test_worker_is_not_a_contractor_and_human_requests_interrupt_intake():
    lead = blank_lead()
    question = respond(lead, "", "busco pega de pintor")
    assert lead.interest_type == "employment"
    assert lead.entity_type == "individual"
    assert lead.specialty == "Pintura"
    assert "Trabajas solo" in question
    assert next_intake_reply("quiero hablar con una persona", vars(lead), question) is None


@pytest.mark.parametrize("message, specialty", [
    ("ola soy gasfite", "Gasfitería"), ("soi carpintreo", "Carpintería"),
    ("soy sodador", "Soldadura"), ("soy eletricista", "Electricidad"),
    ("soy albanir", "Albañilería"), ("trabajo en tabiques", "Tabiquería"),
    ("hago impermiabilizacion", "Impermeabilización"),
    ("soy enfierador", "Enfierradura"),
])
def test_construction_trade_aliases(message, specialty):
    assert analyze(message).specialty == specialty


def test_do_not_store_private_data_or_replace_manually_verified_specialty():
    lead = blank_lead(specialty="Carpintería", specialty_source="manual")
    apply_intake(lead, "soy pintor")
    assert lead.specialty == "Carpintería"
    apply_intake(lead, "mi contraseña: ejemplo")
    assert lead.experience == ""
    assert private_data("mi RUT 12.345.678-5")
    apply_intake(lead, "12.345.678-5", "¿En qué comuna puedes trabajar?")
    assert lead.work_area == ""


def test_curriculum_20_requires_admin_approval_and_is_idempotent(network):
    n = network
    progress_url = "/api/v1/network/galancito/knowledge-curriculum/progress"
    assert n["a"].get(progress_url).status_code == 403
    before = n["admin"].get(progress_url).json()
    assert before["total"] == 20 and before["approved"] == 0
    imported = n["send"](n["admin"], "/galancito/knowledge-curriculum", {})
    assert imported.status_code == 201, imported.text
    assert imported.json()["created"] == 20
    repeat = n["send"](n["admin"], "/galancito/knowledge-curriculum", {})
    assert repeat.status_code == 201 and repeat.json()["created"] == 0
    pending = n["admin"].get(progress_url).json()
    assert pending["percent"] == 0 and pending["pending"] == 20
    assert n["send"](n["admin"], "/galancito/knowledge-curriculum/approve",
                     {"confirm": False}).status_code == 422
    accepted = n["send"](n["admin"], "/galancito/knowledge-curriculum/approve",
                         {"confirm": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["approved_now"] == 20
    assert n["admin"].get(progress_url).json()["percent"] == 100
    answered = n["send"](n["admin"], "/galancito/chat",
                         {"message": "para que sirve galant"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["source"] == "knowledge"
    outside = n["login"]("outside@network.example.cl")
    assert outside.get(progress_url).json()["approved"] == 0
    assert n["send"](n["a"], "/galancito/knowledge-curriculum", {}).status_code == 403


def test_live_today_contacts_only_for_authorized_admin(network):
    n = network
    santiago = ZoneInfo("America/Santiago")
    midday = datetime.combine(datetime.now(santiago).date(), time(hour=12), tzinfo=santiago)
    old = midday - timedelta(days=1)
    with n["Session"].begin() as db:
        org = db.scalar(select(User.org_id).where(User.email == "admin@network.example.cl"))
        outside = db.scalar(select(User.org_id).where(User.email == "outside@network.example.cl"))
        for idx, (owner, when, name) in enumerate([
            (org, midday, "Empresa de prueba"), (org, midday, "Contacto sin nombre"),
            (org, old, "Mensaje antiguo"), (outside, midday, "Contacto de otro cliente")
        ]):
            db.add(FacebookLead(
                org_id=owner, page_id="synthetic-page", psid="synthetic-contact-" + str(idx),
                display_name=name, last_inbound_at=when.astimezone(timezone.utc),
            ))
    reply = n["send"](n["admin"], "/galancito/chat", {"message": "quien me hablo hoy"})
    assert reply.status_code == 200, reply.text
    answer = reply.json()["answer"]
    assert reply.json()["source"] == "live"
    assert "Empresa de prueba" in answer and "Contacto sin nombre" in answer
    assert "Mensaje antiguo" not in answer
    assert "Contacto de otro cliente" not in answer
    restricted = n["send"](n["a"], "/galancito/chat", {"message": "quien me hablo hoy"})
    assert restricted.status_code == 200
    assert "Empresa de prueba" not in restricted.json()["answer"]


def test_each_contact_has_own_progress_and_summary():
    first = blank_lead()
    second = blank_lead()
    assert contact_profile(first)["percent"] == 0
    prompt = next_intake_reply("hola", vars(first)) or ""
    assert "Qué trabajo" in prompt
    prompt = respond(first, prompt, "soi carpintero")
    assert first.specialty == "Carpintería"
    assert contact_profile(first)["percent"] > 0
    assert contact_profile(second)["percent"] == 0
    prompt = respond(first, prompt, "1")
    prompt = respond(first, prompt, "2")
    assert "Personas que pueden acudir" in contact_profile(first)["missing"]
    assert contact_profile(first)["total"] == 7
    prompt = respond(first, prompt, "3")
    assert first.workers == 3
    summary = contact_profile(first)["summary"]
    assert "Carpintería" in summary and "3 persona" in summary
    assert "Pendiente de validación" in summary
    assert contact_profile(second)["summary"] != summary


def test_chat_questions_do_not_fabricate_a_trade():
    lead = blank_lead()
    apply_intake(lead, "¿buscan pintores?")
    assert lead.specialty == ""
    apply_intake(lead, "soy pintor, ¿tienen pega?")
    assert lead.specialty == "Pintura"
    assert lead.interest_type == "unknown"


def test_local_profile_progress_is_not_employment_approval():
    lead = blank_lead(
        interest_type="service_offer", specialty="Pintura", team_available=False,
        workers=1, experience="4 años", work_area="Coronel", availability="mañana")
    profile = contact_profile(lead)
    assert profile["percent"] == 100
    assert profile["completed"] == profile["total"]
    assert "validación" in profile["summary"]
    assert not hasattr(lead, "documents_state")


def test_human_conversational_style_without_repeated_bot_introductions():
    lead = blank_lead()
    answer = respond(lead, "", "ola soi gasfite")
    assert "gasfitería" in answer.lower()
    assert answer.count("?") == 1
    assert "Soy Galancito" not in answer
    first = natural_messenger_reply(answer, 0)
    second = natural_messenger_reply(answer, 1)
    assert first.startswith("Soy Galancito")
    assert "Soy Galancito" not in second
    assert len(second) < 550


def test_optional_name_does_not_block_or_fake_identity():
    lead = blank_lead(display_name="Interesado de Facebook", name_opt_out=False)
    lead.interest_type = "service_offer"
    lead.specialty = "Pintura"
    lead.team_available = False
    lead.workers = 1
    lead.experience = "2 años"
    lead.work_area = "Coronel"
    lead.availability = "desde mañana"
    question = next_intake_reply("mañana", vars(lead), "¿Desde cuándo podrías comenzar?")
    assert "prefieres" in question
    final = respond(lead, question, "paso")
    assert lead.name_opt_out is True
    assert lead.display_name == "Interesado de Facebook"
    assert "registré" in final


def test_opt_in_name_and_professional_data_are_separate():
    lead = blank_lead(display_name="Interesado de Facebook", name_opt_out=False)
    apply_intake(lead, "me llamo Luis", "")
    assert lead.display_name == "Luis"
    apply_intake(lead, "¿hay electricistas?")
    assert lead.specialty == ""


@pytest.mark.parametrize("question", [
    "¿tienen pega?", "¿cuanto pagan?", "¿puedo postular?",
    "¿necesitan maestros?", "¿que papeles?",
])
def test_short_informal_questions_get_deeper_answers(question):
    assert needs_deeper_response(question)


@pytest.mark.parametrize("reply", ["1", "2", "sí", "no", "hola"])
def test_simple_intake_choices_do_not_consume_external_model(reply):
    assert not needs_deeper_response(reply)
