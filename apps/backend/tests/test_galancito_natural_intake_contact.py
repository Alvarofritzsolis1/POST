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


def test_rewrite_must_keep_question_semantics():
    facts = complete(experience="", work_area="")
    question = "¿Cuánto tiempo llevas en ese oficio?"
    assert acceptable_intake_draft("¿Cuánta experiencia tienes?", facts, question)
    assert not acceptable_intake_draft("¿En qué comuna puedes trabajar?", facts, question)
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
