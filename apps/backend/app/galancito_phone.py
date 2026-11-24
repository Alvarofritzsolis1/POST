"""Local handling of voluntarily shared Chilean mobile numbers for coordination.

Phone numbers are not professional scoring criteria, are never passed to
external models, and must not be inferred from arbitrary strings in chat.
"""
import re
from datetime import datetime, timedelta, timezone

PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?56[\s.-]?)?9[\s.-]?\d{4}[\s.-]?\d{4}(?!\d)")
SHARING = re.compile(
    r"(?i)(?:mi\s+(?:n[uú]mero|celular|tel[eé]fono|w(?:hats)?app)"
    r"|(?:te|les)\s+(?:dejo|paso|env[ií]o)\s+(?:mi\s+)?(?:n[uú]mero|celular|tel[eé]fono|w(?:hats)?app)?"
    r"|(?:ll[aá]m[ae]me|pueden\s+llamarme)\s+(?:al\s+)?"
    r"|(?:cont[aá]ct[ae]me|escr[ií]banme)\s+(?:al\s+)?"
    r"|(?:n[uú]mero|celular|tel[eé]fono|w(?:hats)?app)\s*[:=])"
)
COORDINATE = re.compile(
    r"(?i)\b(?:me\s+pueden\s+llamar|pueden\s+llamarme|ll[aá]m[ae]me|"
    r"nos\s+(?:podemos\s+)?(?:llamar|hablar\s+por\s+tel[eé]fono)|"
    r"coordin(?:amos|emos)\s+por\s+(?:tel[eé]fono|w(?:hats)?app)|"
    r"quiero\s+(?:dejar|dar|pasar)\s+mi\s+n[uú]mero)\b"
)
DECLINED = re.compile(
    r"(?i)(?:no\s+(?:quiero|deseo|voy\s+a)\s+(?:dar|pasar|enviar|compartir)"
    r"|prefiero\s+(?:seguir|hablar)\s+por\s+(?:aqu[ií]|messenger))"
)
QUESTION = ("Podemos seguir conversando por Messenger. Si te acomoda "
            "coordinar por otra vía, también puedes dejar un número de celular "
            "o un correo. Es totalmente opcional.")


def normalize_mobile(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if re.fullmatch(r"(?:56)?9\d{8}", digits):
        return "+56" + (digits[2:] if digits.startswith("56") else digits)
    return None


def phone_shared_by_sender(message: str, last_question: str = "") -> str | None:
    """Only a number intentionally shared for contact, not an incidental example."""
    if not isinstance(message, str) or len(message) > 3500:
        return None
    if re.search(r"(?i)\b(?:ejemplo|ficticio|formato|no\s+es\s+mi\s+n[uú]mero)\b", message):
        return None
    candidates = list(PHONE_PATTERN.finditer(message))
    if len(candidates) != 1:
        return None
    match = candidates[0]
    phone = normalize_mobile(match.group())
    if not phone:
        return None
    # A standalone number is an intentional reply even without the old prompt.
    standalone = not re.sub(r"[\d\s+().\-]", "", message).strip()
    asked = bool(re.search(r"(?i)\b(?:tel[eé]fono|celular|n[uú]mero|w(?:hats)?app)\b", last_question))
    context = SHARING.search(message[:match.start()])
    return phone if standalone or asked or context else None


def phone_declined(message: str, last_question: str) -> bool:
    return bool((DECLINED.search(message) or message.strip().casefold() in {"no", "paso", "prefiero no", "no gracias"}) and
                re.search(r"(?i)\b(?:tel[eé]fono|celular|n[uú]mero|w(?:hats)?app)\b", last_question))


def phone_question_when_agreed(lead, message: str, *, at: datetime | None = None) -> str | None:
    """Only on a clear contact-coordination request; never on mere job interest."""
    if (getattr(lead, "contact_phone", "") or getattr(lead, "contact_email", "")
            or getattr(lead, "phone_opt_out", False) or getattr(lead, "email_opt_out", False)
            or not COORDINATE.search(message or "")):
        return None
    now = at or datetime.now(timezone.utc)
    requested = getattr(lead, "phone_requested_at", None)
    if requested:
        if requested.tzinfo is None:
            requested = requested.replace(tzinfo=timezone.utc)
        if requested >= now - timedelta(days=7):
            return None
    return QUESTION


def remember_shared_phone(lead, message: str, last_question: str, *, at: datetime) -> bool:
    """Persist only explicitly shared phones; never overwrite operator-verified data."""
    if phone_declined(message, last_question):
        lead.phone_opt_out = True
        return False
    number = phone_shared_by_sender(message, last_question)
    if not number:
        return False
    if lead.contact_phone == number:
        return False
    if getattr(lead, "phone_source", "") == "manual" and lead.contact_phone:
        return False
    lead.contact_phone = number
    lead.phone_source = "message"
    lead.phone_shared_at = at
    lead.phone_opt_out = False
    return True


def redact_mobile_for_intake(message: str) -> str:
    """Preserve non-sensitive trade statements without passing phone digits onward."""
    return PHONE_PATTERN.sub("[teléfono reservado]", message or "")
