"""Email intake must be voluntary, grounded, and excluded from model prompts."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.galancito_contact_email import (
    email_shared_by_sender, remember_shared_email, redact_email_for_intake,
)
from app.galancito_contact_profile import contact_profile
from app.galancito_phone import phone_question_when_agreed


def lead(**overrides):
    values = dict(
        display_name="Empresa Constructora", company="", interest_type="service_offer",
        specialty="Carpintería", specialty_source="message", team_available=False,
        workers=1, experience="llevo como 1 año", work_area="San Pedro de la Paz",
        availability="mañana", contact_phone="", contact_email="", phone_source="",
        email_source="", email_shared_at=None, email_opt_out=False, phone_opt_out=False,
        phone_requested_at=None, profile_sources={}, name_opt_out=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_email_only_when_intentionally_shared():
    assert email_shared_by_sender("Mi correo es Maestro.Test+1@Ejemplo.cl") == "maestro.test+1@ejemplo.cl"
    assert email_shared_by_sender("maestro@ejemplo.cl") == "maestro@ejemplo.cl"
    assert email_shared_by_sender("maestro@ejemplo.cl", "¿Qué correo usas?") == "maestro@ejemplo.cl"
    assert email_shared_by_sender("un ejemplo: ejemplo@dominio.cl") is None
    assert email_shared_by_sender("el correo de un tercero es persona@ejemplo.cl") is None
    assert email_shared_by_sender("uno@ejemplo.cl y dos@ejemplo.cl") is None
    assert "maestro@ejemplo.cl" not in redact_email_for_intake("soy carpintero mi correo maestro@ejemplo.cl")


def test_email_is_persisted_only_when_provided_and_not_manual_override():
    person = lead()
    moment = datetime.now(timezone.utc)
    assert remember_shared_email(person, "Te dejo mi correo: contacto@obra.cl", "", at=moment)
    assert person.contact_email == "contacto@obra.cl"
    assert person.email_source == "message"
    assert person.email_shared_at == moment
    person.email_source = "manual"
    assert not remember_shared_email(person, "mi correo es otro@obra.cl", "", at=moment)
    assert person.contact_email == "contacto@obra.cl"
    assert not remember_shared_email(lead(), "por favor no quiero dar mi correo", "", at=moment)
    other = lead()
    remember_shared_email(other, "Prefiero seguir por Messenger", "¿Cuál correo?", at=moment)
    assert other.email_opt_out


def test_profiles_are_readable_without_hiding_missing_contact():
    person = lead()
    profile = contact_profile(person)
    assert "Empresa Constructora ofrece servicios de Carpintería" in profile["summary"]
    assert "Disponibilidad declarada: «mañana»" in profile["summary"]
    assert "no ha compartido teléfono ni correo" in profile["summary"]
    assert profile["percent"] < 100
    assert profile["field_states"]["contact_email"] == "pendiente"
    assert profile["contact_state"] == "solo_messenger"
    person.contact_email = "contacto@obra.cl"
    profile = contact_profile(person)
    assert "correo" in profile["summary"]
    assert profile["field_states"]["contact_email"] == "confirmado_por_declaracion"
    assert profile["contact_state"] == "canal_voluntario"
    assert phone_question_when_agreed(person, "Me pueden llamar") is None
