"""Phone coordination is optional, explicit and kept out of external-model facts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.galancito_phone import (
    QUESTION, normalize_mobile, phone_shared_by_sender, remember_shared_phone,
    phone_declined, phone_question_when_agreed, redact_mobile_for_intake,
)

def contact(**kwargs):
    values = dict(contact_phone="", phone_source="", phone_shared_at=None,
                  phone_requested_at=None, phone_opt_out=False)
    values.update(kwargs)
    return SimpleNamespace(**values)

def test_normalizes_chilean_mobiles_and_rejects_landlines_and_arbitrary_digits():
    assert normalize_mobile("+56 9 8765 4321") == "+56987654321"
    assert normalize_mobile("987654321") == "+56987654321"
    assert normalize_mobile("56 9 8765 4321") == "+56987654321"
    assert normalize_mobile("223456789") is None
    assert normalize_mobile("1234567890") is None

def test_only_intentionally_shared_numbers_are_extracted():
    assert phone_shared_by_sender("mi WhatsApp es +56 9 8765 4321") == "+56987654321"
    assert phone_shared_by_sender("te dejo mi numero 987654321") == "+56987654321"
    assert phone_shared_by_sender("987654321") == "+56987654321"
    assert phone_shared_by_sender("me pueden contactar al 987654321", "¿Tu número?") == "+56987654321"
    assert phone_shared_by_sender("Ejemplo: +56 9 8765 4321") is None
    assert phone_shared_by_sender("Hay 2 personas y fecha 2026-11-19") is None
    assert phone_shared_by_sender("Llamaron al 987654321 de otra persona") is None
    assert phone_shared_by_sender("987654321 o 912345678") is None

def test_avoid_repeated_or_unrequested_phone_prompts():
    moment = datetime(2026, 11, 19, tzinfo=timezone.utc)
    assert phone_question_when_agreed(contact(), "Me pueden llamar", at=moment) == QUESTION
    assert phone_question_when_agreed(contact(), "Tengo experiencia en carpinteria", at=moment) is None
    assert phone_question_when_agreed(contact(phone_requested_at=moment), "Me pueden llamar", at=moment) is None
    assert phone_question_when_agreed(contact(phone_opt_out=True), "Me pueden llamar", at=moment) is None
    assert phone_question_when_agreed(contact(contact_phone="+56987654321"), "Me pueden llamar", at=moment) is None
    assert phone_question_when_agreed(contact(phone_requested_at=moment-timedelta(days=8)),
                                     "Me pueden llamar", at=moment) == QUESTION

def test_persist_only_voluntary_phone_never_replace_manual_verified_value():
    timestamp = datetime(2026,11,19,tzinfo=timezone.utc)
    lead = contact()
    assert remember_shared_phone(lead, "Mi celular es 987654321", "", at=timestamp)
    assert lead.contact_phone == "+56987654321"
    assert lead.phone_source == "message"
    assert lead.phone_shared_at == timestamp
    assert not remember_shared_phone(lead, "987654321", "", at=timestamp)
    lead.phone_source="manual"
    assert not remember_shared_phone(lead, "912345678", "", at=timestamp)
    assert lead.contact_phone == "+56987654321"

def test_phone_opt_out_applies_only_to_phone_question():
    lead = contact()
    assert not phone_declined("Prefiero hablar por Messenger", "¿Qué oficio haces?")
    assert phone_declined("Prefiero hablar por Messenger", QUESTION)
    assert not remember_shared_phone(lead, "Prefiero hablar por Messenger", QUESTION,
                                     at=datetime.now(timezone.utc))
    assert lead.phone_opt_out


def test_redacts_number_without_discarding_professional_details():
    text = redact_mobile_for_intake("Soy gasfiter y hago pintura, mi celular es +56 9 8765 4321")
    assert "gasfiter" in text and "pintura" in text
    assert "+56 9" not in text and "8765 4321" not in text


def test_phone_ack_only_for_committed_matching_contact():
    from app.galancito_phone import confirmed_phone_reply, CONTACT_ACK
    lead = contact(contact_phone="+56987654321")
    assert confirmed_phone_reply(lead, "+569 87654321") == CONTACT_ACK
    assert confirmed_phone_reply(lead, "+56 9 8765 4321") == CONTACT_ACK
    assert confirmed_phone_reply(lead, "+56912345678") is None
    assert confirmed_phone_reply(contact(), "+56987654321") is None
    assert "87654321" not in CONTACT_ACK
