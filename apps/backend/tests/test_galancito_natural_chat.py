"""Regresiones de estilo/latencia lógica de Messenger sin llamadas reales a Meta."""
from app.galancito_intake import small_talk_reply, natural_messenger_reply
from app.galancito_flow import permission_question, safe_ai_reply
from app.galancito_triage import quick_reply


def test_generated_intro_from_the_old_template_is_removed():
    assert natural_messenger_reply("Hola, te habla Galancito de GALANT. ¿Qué aviso viste?") == "¿Qué aviso viste?"


def test_local_small_talk_answers_without_model():
    assert "gracias" in small_talk_reply("hola como estas").lower()
    assert small_talk_reply("¿Cómo estás?") is not None
    assert small_talk_reply("ola") is not None
    assert small_talk_reply("Soy carpintero y tengo una consulta") is None


def test_no_repetitive_virtual_assistant_introduction():
    for turns in (0, 1, 3):
        msg = natural_messenger_reply(
            "Soy Galancito, asistente virtual de GALANT. Perfecto, ¿en qué comuna trabajas?",
            turns,
        )
        assert msg.startswith("Perfecto")
        assert "asistente virtual" not in msg.lower()
    assert "asistente virtual" not in safe_ai_reply("Claro, cuéntame." ).lower()
    assert "asistente virtual" not in quick_reply("hola").lower()


def test_ai_consent_remains_explicit():
    question = permission_question("team")
    assert "IA" in question
    assert "autorizas" in question.lower()
    assert "externos" in question.lower()
    assert "asistente virtual" not in question.lower()
    assert "IA local" in permission_question("ollama")
