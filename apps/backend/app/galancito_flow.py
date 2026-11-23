"""Safe Galancito consent and simple guided messaging for Chilean trades.

No user's private Messenger content is sent to an external AI before clear consent.
Text parsing is intentionally narrow to avoid treating casual phrases as permission.
"""
import unicodedata
import re

ASSISTANT_NAME = "Galancito"
AI_PERMISSION_QUESTION = (
    "¡Hola! Soy Galancito de Red de Obras. "
    "Para orientarte con IA de OpenAI necesito procesar tus mensajes. "
    "¿Me autorizas? Responde sí o no; si prefieres, te atiende una persona."
)
AI_PERMISSION_REASK = (
    "Para responderte usando IA necesito tu permiso. "
    "¿Autorizas que use IA de OpenAI con estos mensajes? Escribe SÍ o NO. "
    "También puedes hablar con una persona."
)
AI_PERMISSION_DECLINED = (
    "Entendido, no usaré IA con tus mensajes. "
    "Una persona de GALANT podrá ayudarte. No necesitas enviar documentos por aquí."
)


def _legacy_permission_question(provider: str, repeat: bool = False) -> str:
    """Recognize prompts already delivered before the wording changed."""
    if provider == "team":
        opening = "" if repeat else "¡Hola! Soy Galancito de Red de Obras. "
        return (opening + "Puedo orientarte usando los proveedores de IA externos "
                "configurados para este servicio. ¿Me autorizas a procesar allí "
                "tus mensajes? Responde sí o no. También puede atenderte una persona.")
    if provider == "ollama":
        if repeat:
            return ("¿Me autorizas a usar IA local de GALANT "
                    "para responderte? Tu mensaje se procesa en nuestro servidor. "
                    "Escribe SÍ o NO. Si prefieres, te atiende una persona.")
        return ("Hola, te habla Galancito de GALANT. "
                "¿Me autorizas a utilizar IA local para responderte? "
                "Tus mensajes se procesan en nuestro servidor, sin OpenAI. "
                "Responde SÍ o NO; también puedes hablar con una persona.")
    return AI_PERMISSION_REASK if repeat else AI_PERMISSION_QUESTION


def permission_question(provider: str, repeat: bool = False) -> str:
    if provider == "ollama":
        request = ("Si te acomoda, puedo revisar tu consulta con la IA de GALANT en nuestro servidor. ¿Me autorizas?"
                   if repeat else "Puedo usar la IA local de GALANT. Tu mensaje se procesa en nuestro servidor. ¿Me autorizas?")
    else:
        service = "los proveedores de IA externos de GALANT" if provider == "team" else "la IA de OpenAI"
        request = (f"Para responderte con IA tendría que compartir estos mensajes con {service}. ¿Me autorizas?"
                   if repeat else f"Puedo revisar tu consulta con {service}. ¿Me autorizas a compartir tus mensajes?")
    return request + " Si prefieres, te puede atender alguien del equipo."


def _plain(message: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", message.lower())
                             if not unicodedata.combining(c)).split()).strip(" .!¿?¡")


def consent_decision(message: str) -> bool | None:
    value = " ".join(re.sub(r"[,;]+", " ", _plain(message)).split())
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
        return "¿En qué te puedo ayudar con Red de Obras?"
    # No añadir prefijos repetitivos; el consentimiento se informa por separado.
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

_NUMBERED_MENU = re.compile(
    r"\(\s*\d{1,2}\s*\)|(?:^|[\s:])\d{1,2}\)\s*|(?:^|\n)\s*\d{1,2}\.\s+"
    r"|\b(?:responde|escribe|elige|marca|pulsa)\s+(?:el\s+)?(?:n[uú]mero\s+)?\d{1,2}\b",
    re.I,
)


def numbered_menu(text: str) -> bool:
    """Detect choice labels while allowing dates and declared quantities."""
    return bool(_NUMBERED_MENU.search(text))


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
        return "Para revisar esos datos, solicita orientación de administración por un canal seguro."
    if numbered_menu(clean):
        return "Cuéntame con tus palabras y seguimos."
    return galancito_prefix(clean)


def grounded_reply(draft: str, supplied: str) -> str | None:
    """Bounded guard, not a general proof of factuality: reject new numbers/URLs."""
    text = _plain(draft)
    reference = _plain(supplied)
    referenced_topics = (r"\b(?:prestamos?|bancos?|creditos?)\b", r"\bformularios?\b")
    if any(re.search(topic, text) and not re.search(topic, reference) for topic in referenced_topics):
        return None
    if re.search(r"\b(?:ya estas contratado|te contratamos|te adjudicamos|contratacion garantizada|ingreso garantizado)\b", text):
        return None
    if re.search(r"(?<!no )\b(?:tenemos (?:un )?(?:cupos?|vacantes?)|"
                 r"te conseguimos (?:una )?(?:pega|vacante)|"
                 r"tu ficha (?:ya )?(?:esta|quedo) (?:aprobada|verificada)|"
                 r"te confirmo (?:el cupo|la contratacion))\b", text):
        return None
    if set(re.findall(r"\d+", _NUMBERED_MENU.sub(" ", draft))) - set(re.findall(r"\d+", supplied)):
        return None
    if any(url not in supplied for url in re.findall(r"https?://\S+", draft)):
        return None
    if re.search(r"\b(?:envia|manda|adjunta|sube|entrega)(?:me|nos)?\s+(?:tu |una |el |la )?"
                 r"(?:rut|cedula|contrasena|clave unica|documento de identidad)\b", text):
        return None
    return safe_ai_reply(draft)


def consented_for(lead, provider: str) -> bool:
    return bool(provider != "disabled" and lead.ai_consent and
                lead.ai_consent_provider == provider and lead.ai_consent_state == (
                    "accepted_team" if provider == "team" else "accepted"))


def set_permission_request(lead, provider: str, *, repeat=False) -> str:
    lead.ai_consent = False
    lead.ai_consent_provider = provider
    lead.ai_consent_state = "requested_team" if provider == "team" else "requested"
    return permission_question(provider, repeat=repeat)


def is_permission_prompt(lead, message: str) -> bool:
    provider = lead.ai_consent_provider
    return bool(provider and message in {
        permission_question(provider), permission_question(provider, repeat=True),
        _legacy_permission_question(provider), _legacy_permission_question(provider, repeat=True),
    })


def explain_permission(lead, message: str, previous: str) -> str | None:
    if (_plain(message) in {"no entiendo", "no comprendo", "no cacho", "que significa eso",
                            "que quieres decir", "no entendi", "no entiendo lo del permiso"}
            and is_permission_prompt(lead, previous)):
        return "Podemos seguir por acá. Cuéntame qué necesitas y vemos cómo ayudarte."
    return None


def apply_permission_reply(lead, message: str, delivered_prompt: str) -> bool | None:
    """Treat a bare yes/no as consent only when it answers the permission prompt."""
    if wants_human(message) or _plain(message) in {"no autorizo", "no acepto usar ia"}:
        result = False
    elif (lead.ai_consent_state in {"requested", "requested_team"} and
          is_permission_prompt(lead, delivered_prompt)):
        result = consent_decision(message)
    else:
        return None
    if result is True:
        lead.ai_consent = True
        lead.ai_consent_state = "accepted_team" if lead.ai_consent_provider == "team" else "accepted"
    elif result is False:
        lead.ai_consent = False
        lead.ai_consent_state = "declined"
        lead.ai_consent_provider = ""
    return result
