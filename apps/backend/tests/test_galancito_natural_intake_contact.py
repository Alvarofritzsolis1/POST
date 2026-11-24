"""Regression cases derived from an observed practice failure; no live contacts."""
from app.galancito_intake import (
    acceptable_intake_draft,
    model_intake_candidate,
    next_intake_reply,
)
from app.galancito_triage import quick_reply


def complete(**changes):
    return {
        "specialty": "Hormigonado",
        "interest_type": "service_offer",
        "team_available": False,
        "workers": 1,
        "experience": "5 años",
        "work_area": "San Pedro de la Paz",
        "availability": "mañana",
        "display_name": "Maestro de prueba",
        "turn_changed": True,
        **changes,
    }


def test_short_answer_does_not_narrate_profile():
    facts = complete(experience="")
    reply = next_intake_reply("solo", facts, "¿Trabajas solo o puedes venir con otras personas?")
    assert reply == "¿Cuánto tiempo llevas en ese oficio?"
    assert model_intake_candidate("solo", facts, "", reply)
    assert acceptable_intake_draft("¿Cuánto tiempo llevas haciendo ese trabajo?", facts)
    assert not acceptable_intake_draft("Gracias, me queda clara la cantidad de personas. ¿Cuánto tiempo llevas?", facts)


def test_offer_contact_once_at_ready_stage():
    prior = "¿Cómo te llamas?"
    reply = next_intake_reply("Maestro de prueba", complete(), prior)
    assert "tu celular" in reply
    assert "seguimos por aquí" in reply
    for flag in ("contact_available", "contact_declined", "contact_offered"):
        assert "celular" not in next_intake_reply("Maestro de prueba", complete(**{flag: True}), prior)


def test_reject_repeat_of_known_information():
    assert not acceptable_intake_draft("¿En qué comuna puedes trabajar?", complete())
    assert not acceptable_intake_draft("¿Me dejas tu celular?", complete(contact_available=True))
    assert not acceptable_intake_draft("Gracias, quedó anotado.", complete())


def test_job_advert_first():
    assert quick_reply("hola vi un trabajo") == "¡Hola! ¿Qué trabajo viste?"


def test_model_may_choose_any_missing_field_not_scripted_field():
    facts = complete(experience="", work_area="")
    question = "¿Cuánto tiempo llevas en ese oficio?"
    assert acceptable_intake_draft("¿Cuánta experiencia tienes?", facts, question)
    assert acceptable_intake_draft("¿En qué comuna puedes trabajar?", facts, question)
    assert not acceptable_intake_draft("¿Me cuentas más?", facts, question)


def test_advert_does_not_declare_own_trade():
    from app.galancito_triage import asks_about_application, referring_to_application
    from app.galancito_links import trade_declarations
    assert asks_about_application("hola vi un trabajo de hormigon")
    assert referring_to_application("¡Hola! ¿Qué trabajo viste?")
    assert not trade_declarations("vi un trabajo de hormigon", allow_bare=True)


def test_optional_phone_refusal_is_not_a_new_intake_answer():
    from app.galancito_phone import phone_declined
    assert phone_declined("no gracias", "¿Me dejas tu celular?")
    assert not phone_declined("no", "¿Trabajas solo?")


def test_curated_example_is_context_not_verbatim_reply():
    from app.galancito_knowledge import conversation_example
    assert not conversation_example("solo")
    assert "Criterio:" in conversation_example("solo", "¿Trabajas solo?")


def test_interruption_can_be_answered_without_intake_question():
    facts = complete(experience="", work_area="")
    prior = "¿Cuánto tiempo llevas en ese oficio?"
    assert acceptable_intake_draft("El pago depende del acuerdo con la obra. ¿Qué aviso viste?",
        facts, prior, message="pero cuanto pagan")
    assert acceptable_intake_draft("El monto depende del trabajo y aún no está confirmado.",
        facts, prior, message="¿Cuánto pagan?")
    assert model_intake_candidate("cuanto pagan", facts, prior, None)
    assert not acceptable_intake_draft("Perfecto.", facts, prior, message="5 años")


def test_model_can_offer_contact_before_name_or_experience():
    facts = complete(experience="", display_name="Contacto sin nombre")
    assert acceptable_intake_draft("¿Me dejas tu número para coordinar? Si prefieres, seguimos por aquí.",
        facts, "¿Cuánto tiempo llevas en ese oficio?")
    assert not acceptable_intake_draft("¿Me dejas tu número para coordinar? Si prefieres, seguimos por aquí.",
        complete(contact_declined=True))
    assert not acceptable_intake_draft("¿Me dejas tu número para coordinar? Si prefieres, seguimos por aquí.",
        complete(work_area=""))
    assert not acceptable_intake_draft("¿Me dejas tu número?", facts)


def test_free_order_questions_keep_interpretable_short_replies():
    from app.galancito_intake import intake_question_fields, conversation_context
    facts = complete(experience="", work_area="", availability="")
    assert intake_question_fields("¿Dónde puedes trabajar?") == {"work_communes"}
    assert intake_question_fields("¿Cuándo puedes partir?") == {"availability"}
    assert intake_question_fields("¿Cuántos maestros pueden venir?") == {"workers"}
    context = conversation_context(facts)
    assert "sin orden obligatorio" in context
    assert "work_communes" in context and "availability" in context


def test_shared_messenger_context_redacts_contact_and_keeps_complete_evidence():
    from types import SimpleNamespace
    from app.galancito_memory import messenger_context
    facts = complete(contact_available=True, display_name="Nombre privado", experience="")
    turns = [SimpleNamespace(body="Mi correo es maestro@example.com", direction="inbound"),
             SimpleNamespace(body="¿En qué comuna puedes trabajar?", direction="outbound")]
    evidence = [{"id": "reference", "version": 1, "kind": "faq",
                 "content": "El pago depende de la obra.", "title": "Pago"}]
    context, included = messenger_context("¿Cuánto pagan?", facts, "¿Cuándo puedes partir?",
                                          turns, evidence)
    assert "Consulta actual: ¿Cuánto pagan?" in context
    assert "El pago depende de la obra." in context
    assert "Nombre privado" not in context and "maestro@example.com" not in context
    assert "sin orden obligatorio" in context
    assert len(context) <= 3000 and included >= 1


def test_contact_is_not_completion_and_model_may_choose_relevant_missing_field():
    from app.galancito_intake import contact_followup_reply, model_contact_question, contact_pending_questions
    from app.galancito_phone import CONTACT_ACK
    facts = complete(specialty="Gasfitería", team_available=None, workers=None, contact_available=True)
    prior = "¿Me dejas tu celular?"
    assert set(contact_pending_questions(facts, prior)) == {"team_available"}
    assert contact_followup_reply(CONTACT_ACK, facts, prior).endswith("¿Trabajas solo o puedes venir con otras personas?")
    assert model_contact_question("¿Trabajas solo o puedes llevar gente?", facts, prior)
    assert model_contact_question("¿En qué comuna puedes trabajar?", facts, prior) is None
    assert model_contact_question("¿Me dejas tu celular?", facts, prior) is None
    assert model_contact_question("Gracias, listo.", facts, prior) is None
    assert model_contact_question("¿En qué comuna puedes trabajar?", {**facts, "work_area": ""}, prior)
    assert set(contact_pending_questions({**facts, "team_available": True}, prior)) == {"workers"}
    assert contact_followup_reply(CONTACT_ACK, {**facts, "team_available": False, "workers": 1}, prior) == CONTACT_ACK
    assert contact_followup_reply(CONTACT_ACK, {**facts, "team_available": True, "workers": 3}, prior) == CONTACT_ACK
    assert contact_followup_reply(CONTACT_ACK, {**facts, "field_states": {"team_available": "rechazado_por_usuario"}}, prior) == CONTACT_ACK
    assert contact_followup_reply(CONTACT_ACK, {**facts, "interest_type": "employment"}, prior) == CONTACT_ACK
