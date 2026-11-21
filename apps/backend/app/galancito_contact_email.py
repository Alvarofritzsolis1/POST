"""Capture only contact email addresses intentionally shared in Messenger.

Never infer an email from company name, never use it to score a person, and
never send contact details to an LLM. The original chat retains the evidence.
"""
import re
from datetime import datetime

EMAIL = re.compile(r"(?<![\w@])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,24}(?![\w@])", re.I)
CUE = re.compile(
    r"(?i)\b(?:mi\s+(?:correo|mail|email|e-mail)|"
    r"(?:te|les|le)\s+(?:dejo|paso|env[ií]o|comparto)\s+(?:mi\s+)?(?:correo|mail|email|e-mail)?|"
    r"(?:puedes|pueden|me\s+pueden)\s+(?:escribir|contactar)\s+(?:a|al|por)\b|"
    r"(?:correo|mail|email|e-mail)\s*[:=])"
)
REFUSAL = re.compile(
    r"(?i)\b(?:no\s+(?:quiero|deseo|voy a)\s+(?:dar|pasar|entregar|compartir)\s+"
    r"(?:mi\s+)?(?:correo|mail|email|e-mail)|"
    r"prefiero\s+(?:seguir|hablar)\s+(?:por\s+)?(?:messenger|aqu[ií]))\b"
)


def email_shared_by_sender(message: str, last_question: str = "") -> str | None:
    if not isinstance(message, str) or len(message) > 3500:
        return None
    if re.search(r"(?i)\b(?:ejemplo|ficticio|prueba|no\s+es\s+mi\s+(?:correo|mail))\b", message):
        return None
    matches = list(EMAIL.finditer(message))
    if len(matches) != 1:
        return None
    candidate = matches[0].group().lower()
    if len(candidate) > 254 or ".." in candidate or candidate.startswith("."):
        return None
    standalone = message.strip().lower() == candidate
    asked = bool(re.search(r"(?i)\b(?:correo|mail|email|e-mail)\b", last_question))
    if not (standalone or asked or CUE.search(message)):
        return None
    return candidate


def remember_shared_email(lead, message: str, last_question: str, *, at: datetime) -> bool:
    if REFUSAL.search(message) and not EMAIL.search(message):
        lead.email_opt_out = True
        return False
    value = email_shared_by_sender(message, last_question)
    if not value or (lead.email_source == "manual" and lead.contact_email):
        return False
    if lead.contact_email == value:
        return False
    lead.contact_email = value
    lead.email_source = "message"
    lead.email_shared_at = at
    lead.email_opt_out = False
    return True


def redact_email_for_intake(message: str) -> str:
    return EMAIL.sub("[correo reservado]", message or "")
