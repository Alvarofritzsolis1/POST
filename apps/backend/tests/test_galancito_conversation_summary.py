"""Evidence-based Galancito contact briefs without real provider keys or Messenger access."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.galancito_conversation_summary import (
    brief_contains_private_data, safe_model_input, summarize_conversation, validate_ai_brief,
)


def lead(**overrides):
    fields = dict(
        display_name="Contacto sin nombre", name_opt_out=False,
        interest_type="service_offer", specialty="Carpintería",
        specialty_source="message", team_available=False, workers=None,
        experience="1 año", work_area="Coronel", availability="Mañana",
        company="", requirement_id=None,
        profile_sources={"specialty":{"source":"message","message_id":"remote-1",
                                      "at":"2026-11-19T14:00:00+00:00"}},
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def message(message_id, body, *, direction="inbound"):
    return SimpleNamespace(id=message_id, remote_id="remote-"+str(message_id),
                           body=body,direction=direction,
                           created_at=datetime(2026,11,19,14,0,tzinfo=timezone.utc),
                           updated_at=None)


def test_real_message_quotes_and_sources_instead_of_fabricated_information():
    data = summarize_conversation(lead(), [
        message(0,"hola"),
        message(1,"soy carpintero, trabajo solo hace 1 año"),
        message(2,"puedo empezar mañana en Coronel"),
        message(3,"Perfecto, gracias",direction="outbound"),
    ])
    assert data["message_count"] == 3
    assert len(data["evidence"]) == 2
    assert all(x["text"] != "hola" for x in data["evidence"])
    assert data["facts"][1]["source"] == "chat"
    assert "Carpintería" in data["summary"]
    assert not any(x["id"] == "3" for x in data["evidence"])
    assert "contratad" not in data["summary"].lower()


def test_no_details_is_not_misrepresented_as_a_complete_ai_profile():
    data = summarize_conversation(lead(
        specialty="", interest_type="unknown", team_available=None, workers=None,
        experience="",work_area="",availability="",
    ), [message(1,"HOAL"), message(2,"hola")])
    assert data["evidence"] == []
    assert "saludos" in data["summary"] or "breves" in data["summary"]
    assert not data["facts"]
    assert data["missing"]


def test_phones_and_private_messages_never_go_to_the_model():
    data = summarize_conversation(lead(), [
        message(1,"Mi celular es +56 9 8765 4321 y hago carpinteria"),
        message(2,"Hago carpinteria"),
    ])
    assert len(data["evidence"]) == 1
    prompt = safe_model_input(data)
    assert "+56" not in prompt
    assert "8765" not in prompt
    assert "carpinteria" in prompt.lower()


def test_ai_summary_requires_existing_evidence_and_rejects_unfounded_claims():
    data = summarize_conversation(lead(),[message(1,"Trabajo en carpintería, solo")])
    good = json.dumps({"summary":"Declara trabajar solo en carpintería; falta revisar disponibilidad.",
                       "evidence_ids":["1"]})
    assert validate_ai_brief(good, data)["source"] == "ia_con_evidencia"
    assert validate_ai_brief(json.dumps({
        "summary":"Declara carpintería y ofrece trabajo en la zona.",
        "evidence_ids":["inventado"]
    }),data) is None
    assert validate_ai_brief(json.dumps({
        "summary":"Tiene 99 trabajadores contratados y aprobados.",
        "evidence_ids":["1"]
    }),data) is None
    assert validate_ai_brief("No es JSON",data) is None


def test_fingerprint_changes_after_new_message_or_manual_correction():
    base = [message(1,"hago carpintería")]
    first = summarize_conversation(lead(),base)
    assert first["fingerprint"] != summarize_conversation(lead(),base+[
        message(2,"Tengo disponibilidad mañana")])["fingerprint"]
    assert first["fingerprint"] != summarize_conversation(
        lead(experience="4 años"),base)["fingerprint"]


def test_numeric_message_ids_never_block_a_safe_opted_in_summary():
    """A random UUID ending in 9+ decimal digits previously matched the RUT regex."""
    from app.galancito_triage import private_data

    data = summarize_conversation(lead(), [
        message("123456789", "Soy carpintero y trabajo solo"),
    ])
    prompt = safe_model_input(data)
    assert private_data(prompt)  # Reproduces the old false-positive JSON check.
    assert not brief_contains_private_data(data)  # Text-only screening must allow it.
    assert json.loads(prompt)["messages"][0]["id"] == "123456789"


def test_text_only_screen_still_rejects_sensitive_professional_fields():
    data = summarize_conversation(lead(work_area="mi dirección es Pasaje Privado 123"), [
        message("123456789", "Soy carpintero y trabajo solo"),
    ])
    assert brief_contains_private_data(data)
