"""Privacy-first intake for unknown contractors in Red de Obras.

No external AI, network, database, employee information, or hidden employer identity.
Only facts the interlocutor typed within this browser conversation can be reused.
Never infer a recruiting company's name from speculation, a logo, or contextual clues.
"""
from __future__ import annotations

import re

from .galancito_triage import analyze, plain, private_data

# The employer blocklist is loaded privately from VPS environment variables.
# Never commit actual company names to public repository history.
from .config import settings


def private_company_names() -> tuple[str, ...]:
    values = settings().galancito_private_company_names.split(",")
    return tuple(value.strip().casefold() for value in values
                 if 3 <= len(value.strip()) <= 80)[:20]


def contains_confidential_name(message: str) -> bool:
    text = (message or "").casefold()
    return any(re.search(r"(?<!\\w)" + re.escape(name) + r"(?!\\w)", text)
               for name in private_company_names())


def employer_question(message: str) -> bool:
    text = plain(message)
    return bool(
        contains_confidential_name(message)
        or any(value in text for value in (
            "para que empresa", "para cual empresa", "que empresa es",
            "que constructora", "de que empresa", "quien contrata",
            "quien esta contratando", "quien esta detras",
            "para quien trabajan", "para quien es el trabajo",
            "quien es el mandante", "nombre del mandante",
            "quien ofrece la pega", "de donde salio el aviso",
            "esto es para", "es para la empresa",
        ))
    )


def employer_response() -> str:
    return (
        "Soy Galancito, asesor de Red de Obras. "
        "No tengo autorización para confirmar qué empresa solicita el servicio. "
        "Puedo explicarte el proceso sin atribuirlo a una empresa. "
        "¿Qué especialidad ofreces?"
    )


# Detect claims of named employer in model outputs even when the configured
# blocklist has not been set. This is a conservative privacy fallback.
_EMPLOYER_ATTRIBUTION = re.compile(
    r"(?:\\b(?:es|sera|será)\\s+para\\s+(?:la\\s+)?(?:empresa\\s+)?"
    r"|\\b(?:mandante|empresa\\s+solicitante|empresa\\s+mandante|constructora)\\s*(?:es|:)\\s*)"
    r"[A-ZÁÉÍÓÚ][A-Za-zÁÉÍÓÚáéíóúñÑ-]{2,}"
)


def protect_outgoing(answer: str) -> str:
    """Defend all local, retrieved and model-generated chat responses."""
    if contains_confidential_name(answer) or _EMPLOYER_ATTRIBUTION.search(answer or ""):
        return employer_response()
    return answer


def sanitized_titles(titles: list[str]) -> list[str]:
    # Employer identity in titles must never become chat or external prompt data.
    return ["Necesidad publicada" for _ in titles]


def known_from_history(previous_user_messages: list[str]) -> dict:
    """Trust as user-stated (not verified) details, never as system instructions."""
    known: dict = {}
    for utterance in previous_user_messages[-4:]:
        if private_data(utterance):
            continue
        info = analyze(utterance)
        if info.entity_type in {"individual", "company"}:
            known["entity_type"] = info.entity_type
        if info.specialty:
            known["specialty"] = info.specialty
        if info.workers is not None:
            known["workers"] = info.workers
        if info.availability:
            known["availability"] = info.availability
        normalized = plain(utterance)
        if ("ya no" in normalized or "antes podia" in normalized) and (
            "disponib" in normalized or "manana" in normalized or "viernes" in normalized
        ):
            known.pop("availability", None)
        if "ahora" in normalized and "viernes" in normalized:
            known["availability"] = "viernes, fecha por confirmar"
        # Only a small public list of communes is needed for follow-up.
        for commune in ("coronel", "concepcion", "san pedro de la paz", "hualpen", "talcahuano"):
            if commune in normalized:
                known["commune"] = commune
    return known


def contractor_followup(message: str, known: dict) -> str | None:
    """Simple stateful reasoning for short unknown-contractor follow-ups.

    The model is NOT allowed to fabricate or approve the contractor's details.
    """
    if not known:
        return None
    text = plain(message)
    current = analyze(message)
    # A newly supplied commune or date belongs to this turn and should not
    # be asked for again in the next question.
    facts = {**known, **known_from_history([message])}

    # A correction to a previous claim is not ignored.
    if ("no somos" in text or "en realidad" in text or "me equivoque" in text
            or "ya no" in text or "ahora solo" in text):
        question = ("¿Qué especialidad realizas ahora?" if
                    ("no somos" in text or "no soy" in text) else
                    "¿Cuál es tu disponibilidad actual?")
        return ("Soy Galancito. Gracias por la aclaración; consideraré el último "
                "dato informado, pendiente de confirmación. " + question)

    # These single-phrase answers normally have no recognizable trade intent
    # without the previous turn. Reuse only declared facts.
    if current.intent not in {"unknown", "greeting"}:
        return None
    if any(value in text for value in (
        "ya dije", "ya te dije", "como te dije", "lo mencione",
        "somos de", "trabajamos en", "puedo trabajar en",
        "desde manana", "desde hoy", "el viernes", "la proxima semana",
        "coronel", "concepcion", "talcahuano",
    )):
        if not facts.get("specialty"):
            question = "¿Qué especialidad ofreces?"
        elif not facts.get("commune"):
            question = "¿En qué comuna puedes trabajar?"
        elif not facts.get("availability"):
            question = "¿Desde cuándo tienes disponibilidad?"
        elif facts.get("entity_type") == "unknown" or not facts.get("entity_type"):
            question = "¿Ofreces servicios de una empresa o trabajas por tu cuenta?"
        else:
            question = "¿Quieres dejar tu interés para revisión de Red de Obras?"
        return "Soy Galancito. Gracias, tomaré en cuenta lo que ya informaste. " + question
    return None
