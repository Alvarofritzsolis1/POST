"""Safe Galancito consent and simple guided messaging for Chilean trades.

No user's private Messenger content is sent to an external AI before clear consent.
Text parsing is intentionally narrow to avoid treating casual phrases as permission.
"""
import unicodedata
import re

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
    "Entendido. Soy Galancito y no usaré IA con tus mensajes. "
    "Una persona de GALANT podrá ayudarte. No necesitas enviar documentos por aquí."
)


def permission_question(provider: str, repeat: bool = False) -> str:
    """Explain where messages are processed before seeking explicit consent."""
    if provider == "ollama":
        if repeat:
            return ("Soy Galancito. ¿Me autorizas a usar IA local de GALANT "
                    "para responderte? Tu mensaje se procesa en nuestro servidor. "
                    "Escribe SÍ o NO. Si prefieres, te atiende una persona.")
        return ("Hola, soy Galancito, asistente virtual de GALANT. "
                "¿Me autorizas a utilizar IA local para responderte? "
                "Tus mensajes se procesan en nuestro servidor, sin OpenAI. "
                "Responde SÍ o NO; también puedes hablar con una persona.")
    return AI_PERMISSION_REASK if repeat else AI_PERMISSION_QUESTION


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



def wants_human(message: str) -> bool:
    """Explicit stop requests are honored even after prior AI consent."""
    value = _plain(message)
    phrases = {
        "no quiero ia", "sin ia", "no usar ia", "no mas ia",
        "prefiero persona", "quiero una persona", "quiero hablar con alguien",
        "hablar con humano", "atencion humana", "deten el bot",
        "detener bot", "parar bot", "deja de responder", "no mas bot",
        "retirar consentimiento", "revoco mi autorizacion",
        "quiero hablar con una persona", "hablar con administracion",
        "quiero hablar con administracion", "quiero un humano", "humano",
    }
    return any(value == phrase or value.startswith(phrase + " ") for phrase in phrases)

def safe_ai_reply(draft: str) -> str:
    """Reject unsafe external output before it reaches a contractor in Messenger."""
    clean = draft.strip()[:550]
    normalized = _plain(clean)
    forbidden = (
        r"(envia|manda|adjunta|sube|entrega)(me|nos)? (tu |una |el |la )?"
        r"(rut|cedula|contrasena|clave unica|documento de identidad)",
        r"(ya estas contratado|te contratamos|ya estas habilitado|te adjudicamos)",
        r"(paga primero|paga una comision|depositame)",
    )
    if not clean or clean.count("?") > 1 or any(re.search(p, normalized) for p in forbidden):
        return ("Soy Galancito, asistente virtual de GALANT. "
                "Para revisar esos datos, solicita orientación de administración por un canal seguro.")
    return galancito_prefix(clean)


def grounded_reply(draft: str, supplied: str) -> str | None:
    """Bounded guard, not a general proof of factuality: reject new numbers/URLs."""
    text = _plain(draft)
    if re.search(r"\b(?:ya estas contratado|te contratamos|te adjudicamos|contratacion garantizada|ingreso garantizado)\b", text):
        return None
    if set(re.findall(r"\d+", draft)) - set(re.findall(r"\d+", supplied)):
        return None
    if any(url not in supplied for url in re.findall(r"https?://\S+", draft)):
        return None
    if re.search(r"\b(?:envia|manda|adjunta|sube|entrega)(?:me|nos)?\s+(?:tu |una |el |la )?"
                 r"(?:rut|cedula|contrasena|clave unica|documento de identidad)\b", text):
        return None
    return safe_ai_reply(draft)
