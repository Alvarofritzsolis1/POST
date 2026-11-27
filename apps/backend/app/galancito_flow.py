"""Safe Galancito consent and simple guided messaging for Chilean trades.

No user's private Messenger content is sent to an external AI before clear consent.
Text parsing is intentionally narrow to avoid treating casual phrases as permission.
"""
import unicodedata
import re
from hashlib import sha256

ASSISTANT_NAME = "Galancito"
AI_PERMISSION_DECLINED = (
    "Entendido, no usaré IA con tus mensajes. "
    "Una persona de GALANT podrá ayudarte. No necesitas enviar documentos por aquí."
)

# Exact fingerprints of the four notices previously delivered for Ollama.
# Only a reply to one of those delivered texts can still complete that opt-in.
_PREVIOUS_LOCAL_NOTICE_HASHES = frozenset({
    "63f00411ea902cc500576f0582cf8264793d757512c41d9b3347ffce798ede09",
    "d28a4a388f1fc8a006d1b29ddd91533a2d54bafc5b25360db2a8c9684f372715",
    "5974f4b251022c2b3b9c4ecf6af67427ed37e1a5deb452a1b1ece06a5bf1f80e",
    "9627fa3a79fef9a8b45f1e65b5bcce5aaf1400c3f97a4d1a3a99619cff47cbf0",
})


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
    value = " ".join(re.sub(r"[,;]+", " ", _plain(message)).split())
    phrases = {
        "no quiero ia", "sin ia", "no usar ia", "no mas ia",
        "prefiero persona", "quiero una persona", "quiero hablar con alguien",
        "hablar con humano", "hablar con un humano", "quiero hablar con un humano",
        "atencion humana", "prefiero atencion humana", "deten el bot",
        "detener bot", "parar bot", "deja de responder", "no mas bot",
        "retirar consentimiento", "revoco mi autorizacion",
        "quiero hablar con una persona", "hablar con administracion",
        "quiero hablar con administracion", "quiero un humano", "humano",
        "me puede atender una persona", "me atiende una persona",
        "quiero que me atienda alguien", "necesito que me atienda una persona",
        "quiero que me atienda una persona", "pasame con una persona", "necesito alguien del equipo",
        "quiero hablar con alguien del equipo", "quiero hablar con una persona real",
        "necesito una persona real", "necesito hablar con una persona", "necesito hablar con un humano",
        "me pueden pasar con alguien", "quiero atencion de una persona",
        "quiero hablar con un trabajador del equipo",
        "alguien del equipo", "una persona del equipo", "prefiero alguien del equipo",
        "prefiero a alguien del equipo", "con alguien del equipo", "una persona porfi",
        "alguien del equipo por favor", "alguien del equipo porfa",
        "que me atienda alguien del equipo", "mejor alguien del equipo",
    }
    return (any(value == phrase or value.startswith(phrase + " ") for phrase in phrases)
            or bool(re.fullmatch(r"(?:hay|habra) (?:alguien|una persona) que me "
                                 r"(?:pueda|puede) (?:ayudar|atender)(?: por favor)?", value))
            or bool(re.fullmatch(r"(?:(?:de lo anterior|para esto|en ese caso) )?(?:prefiero|me gustaria) "
                                 r"hablar con (?:una persona(?: real)?|alguien del equipo)(?: por favor)?", value)))

_NUMBERED_MENU = re.compile(
    r"\(\s*\d{1,2}\s*\)|(?:^|[\s:])\d{1,2}\)\s*|(?:^|\n)\s*\d{1,2}\.\s+"
    r"|\b(?:responde|escribe|elige|marca|pulsa)\s+(?:el\s+)?(?:n[uú]mero\s+)?\d{1,2}\b",
    re.I,
)


def numbered_menu(text: str) -> bool:
    """Detect choice labels while allowing dates and declared quantities."""
    return bool(_NUMBERED_MENU.search(text))


def retired_privacy_warning(message: str) -> bool:
    """Retire the generic privacy script, not the underlying data protection."""
    text = _plain(message or "")
    return ("no compartas datos personales ni contrasenas" in text
            or "para revisarlos, solicita un canal seguro" in text
            or "para revisar esos datos, solicita orientacion de administracion por un canal seguro" in text)


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
    if not clean or retired_privacy_warning(clean) or any(re.search(p, normalized) for p in forbidden):
        return "¿Qué necesitas resolver de tu consulta?"
    if numbered_menu(clean):
        # Keep helpful advice; only remove numbered-choice markers.
        clean = re.sub(r"\(\s*\d{1,2}\s*\)", "", clean)
        clean = re.sub(r"(?m)^\s*\d{1,2}[.)]\s*", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if numbered_menu(clean) or not clean:
            return "¿Me cuentas un poco más para orientarte?"
    if clean.count("?") > 1:
        # One question at a time, without deleting the useful answer.
        clean = clean.split("?", 1)[0].strip() + "?"
    return galancito_prefix(clean)


def grounded_reply(draft: str, supplied: str) -> str | None:
    """Bounded guard, not a general proof of factuality: reject new numbers/URLs."""
    text = _plain(draft)
    reference = _plain(supplied)
    if retired_permission_prompt(draft) or retired_privacy_warning(draft):
        return None
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


def messenger_model_authorized(cfg, lead, provider: str) -> bool:
    """Local processing policy is distinct from provider-specific consent.

    Explicit refusal and human takeover always prevail. The deployment flag
    is deliberately false by default and scoped to the configured Meta tenant.
    Never mutate a contact's recorded consent or use it for an external API.
    """
    if (getattr(lead, "ai_paused", False) or getattr(lead, "needs_support", False)
            or lead.ai_consent_state == "declined"):
        return False
    if consented_for(lead, provider):
        return True
    return bool(
        provider == "ollama"
        and getattr(cfg, "facebook_local_processing_authorized", False)
        and getattr(cfg, "facebook_ai_enabled", False)
        and getattr(cfg, "facebook_ai_provider", "") == "ollama"
        and getattr(cfg, "galancito_local_ai_enabled", False)
        and getattr(cfg, "facebook_org_id", None)
        and getattr(lead, "org_id", None) == cfg.facebook_org_id
        and getattr(cfg, "facebook_page_id", None)
        and getattr(lead, "page_id", None) == cfg.facebook_page_id
        and lead.ai_consent_state == "not_requested"
    )


def external_permission_prompt(message: str) -> bool:
    """Recognize retired notices for external providers, never grant consent."""
    value = _plain(message)
    return ("autoriz" in value or "permiso" in value) and (
        "proveedores de ia externos" in value or "ia de openai" in value)


def retired_permission_prompt(message: str) -> bool:
    """Block the former automatic permission notices and generated equivalents."""
    value = _plain(message)
    return external_permission_prompt(message) or (
        ("autoriz" in value or "permiso" in value)
        and ("ia local" in value or ("ia de galant" in value and "servidor" in value)))


def is_permission_prompt(lead, message: str) -> bool:
    if lead.ai_consent_provider == "ollama":
        return sha256(message.encode()).hexdigest() in _PREVIOUS_LOCAL_NOTICE_HASHES
    return lead.ai_consent_provider in {"team", "openai"} and external_permission_prompt(message)


def explain_permission(lead, message: str, previous: str) -> str | None:
    if (_plain(message) in {"no entiendo", "no comprendo", "no cacho", "que significa eso",
                            "que quieres decir", "no entendi", "no entiendo lo del permiso"}
            and is_permission_prompt(lead, previous)):
        return "Podemos seguir por acá. Cuéntame qué necesitas y vemos cómo ayudarte."
    return None


def apply_permission_reply(lead, message: str, delivered_prompt: str) -> bool | None:
    """Treat a bare yes/no as consent only when it answers the permission prompt."""
    value = _plain(message)
    explicit_revocation = value in {
        "no autorizo", "no acepto usar ia", "no quiero ia", "sin ia",
        "no usar ia", "no mas ia", "no mas bot",
        "retirar consentimiento", "revoco mi autorizacion",
    }
    if explicit_revocation:
        result = False
    elif wants_human(message):
        # Human handoff pauses automation but does NOT revoke an earlier,
        # explicitly accepted provider consent. The person can return later.
        return None
    elif (lead.ai_consent_state in {"requested", "requested_team"} and
          is_permission_prompt(lead, delivered_prompt)):
        result = consent_decision(message)
        if result is True and external_permission_prompt(delivered_prompt):
            return None
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
