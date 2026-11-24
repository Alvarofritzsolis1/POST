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
