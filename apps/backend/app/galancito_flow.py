"""Safe Galancito consent and simple guided messaging for Chilean trades.

No user's private Messenger content is sent to an external AI before clear consent.
Text parsing is intentionally narrow to avoid treating casual phrases as permission.
"""
import unicodedata

ASSISTANT_NAME = "Galancito"
AI_PERMISSION_QUESTION = (
    "Hola, soy Galancito, asistente virtual de GALANT. "
    "Puedo ayudarte con IA de OpenAI, que procesará tus mensajes para responderte. "
    "¿Me autorizas? Responde SÍ o NO. Si no, te atiende una persona."
)
AI_PERMISSION_REASK = (
    "Soy Galancito. Para responderte usando IA necesito tu permiso. "
    "¿Autorizas que use IA de OpenAI con estos mensajes? Escribe SÍ o NO. "
    "También puedes hablar con una persona."
)
AI_PERMISSION_DECLINED = (
    "Entendido. Soy Galancito y no usaré IA externa con tus mensajes. "
    "Una persona de GALANT podrá ayudarte. No necesitas enviar documentos por aquí."
)


def _plain(message: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", message.lower())
                             if not unicodedata.combining(c)).split()).strip(" .!¿?¡")


def consent_decision(message: str) -> bool | None:
    value = _plain(message)
    if value in {
        "si", "sí", "si autorizo", "autorizo", "si acepto",
        "acepto", "de acuerdo", "estoy de acuerdo", "acepto usar ia",
        "autorizo usar ia", "si por favor", "sí por favor",
    }:
        return True
    if value in {
        "no", "no autorizo", "no acepto", "prefiero persona",
        "quiero hablar con alguien", "humano", "hablar con persona",
        "no gracias", "no quiero ia",
    }:
        return False
    return None


def galancito_prefix(message: str) -> str:
    line = message.strip()
    if not line:
        return "Soy Galancito, asistente virtual de GALANT. ¿Qué trabajo haces?"
    if "galancito" not in line.lower():
        return ("Soy Galancito, asistente virtual de GALANT. " + line)[:650]
    return line[:650]
