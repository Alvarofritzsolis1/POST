"""Local answers to Messenger questions about a published worksite."""
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .facebook_crm_models import FacebookChatMessage
from .galancito_knowledge import exact_answer, retrieve
from .galancito_triage import (
    ASK_APPLICATION, ASK_APPLICATION_LINK, ASK_APPLICATION_INTEREST, ASK_APPLICATION_OWN,
    ASK_APPLICATION_ROLE_CLARIFY, ambiguous_application_role, application_role, application_role_question,
    analyze, asks_about_application, is_pure_greeting, plain, private_data, referring_to_application,
    worksite_details_question, ASK_CONTRACTOR_TRADE, TRADE_CONFIRMATIONS, contractor_trade_question,
)
from .network_models import NetworkFacebookPost, NetworkRequirement
from .models import utcnow
from .network_service import today
from .ops_models import Worksite
from .galancito_links import advertised_trade, trade_terms

ASK_WORKSITE = "¿Cuál obra viste? Mándame el nombre o el link del aviso."
ASK_PROJECT = "Claro. ¿Recuerdas el nombre de la obra, el trabajo o la comuna del aviso?"

_LOCATION = re.compile(
    r"\b(?:(?:donde|dnde) (?:q(?:u?e)d[ao]|esta|se ubica|se encuentra|ubico|es|seria)|"
    r"en (?:que|q) (?:comuna|sector|ciudad)|cual es la (?:direccion|ubicacion)|"
    r"(?:pasas|mandas|envias|dices) la (?:direccion|ubicacion))\b"
)
_TOPIC = re.compile(r"\b(?:obra|obras|aviso|faena|proyecto|pega|trabajo|puesto|convocatoria)\b")
_PROJECT = re.compile(
    r"\b(?:(?:me|nos) (?:dice[sn]?|indica[sn]?|cuenta[sn]?) (?:cual es )?(?:el proyecto|la obra|la faena)|"
    r"cual (?:es|era|seria) (?:el proyecto|la obra|la faena)|"
    r"de que (?:proyecto|obra|faena) se trata)\b"
)
_BARE = re.compile(r"(?:(?:y|hola|ola|buenas|disculpa) )*"
                   r"(?:(?:donde|dnde) (?:(?:q(?:u?e)d[ao]|esta|es|seria)(?: ubicad[ao])?)|"
                   r"en (?:que|q) comuna|(?:la )?(?:ubicacion|direccion)(?: porfa)?)")
_POST_LINK = re.compile(
    r"https?://(?:(?:www|m)\.)?facebook\.com/(?:"
    r"(?P<key>[0-9]+_[0-9]+)\b|[^/\s]+/posts/(?P<post>[0-9]+)\b|"
    r"(?:story|permalink)\.php\?(?:[^\s#]*&)?story_fbid=(?P<story>[0-9]+)\b)", re.I
)


def is_worksite_location(message: str) -> bool:
    value = plain(message)
    return bool(_BARE.fullmatch(value) or (
        _TOPIC.search(value) and (_LOCATION.search(value) or re.match(r"^(?:la )?(?:direccion|ubicacion) ", value))
    ))


def is_worksite_question(message: str) -> bool:
    return is_worksite_location(message) or bool(_PROJECT.search(plain(message)))


def _matches_public_notice(message, notices):
    normalized = f" {plain(message)} "
    links = {next(part for part in match.groups() if part) for match in _POST_LINK.finditer(message)}
    if links:
        return [row for row in notices if row.post_id in links or row.post_id.rsplit("_", 1)[-1] in links]
    return [row for row in notices if any(
        f" {label} " in normalized
        for label in (plain(row.site_name), plain(row.title))
        if label and label not in {"obra", "proyecto", "aviso", "faena"}
    )]


def published_notices(db, org_id, page_id):
    notices = db.execute(
        select(Worksite.name.label("site_name"), NetworkRequirement.title, NetworkFacebookPost.post_id)
        .select_from(NetworkFacebookPost)
        .join(NetworkRequirement, NetworkRequirement.id == NetworkFacebookPost.requirement_id)
        .join(Worksite, Worksite.id == NetworkRequirement.site_id)
        .where(NetworkFacebookPost.org_id == org_id,
               NetworkFacebookPost.page_id == page_id,
               NetworkFacebookPost.state == "published",
               NetworkFacebookPost.post_id.is_not(None),
               NetworkRequirement.org_id == org_id,
               NetworkRequirement.state == "published",
               NetworkRequirement.deadline >= today(),
               Worksite.org_id == org_id)
        .order_by(NetworkFacebookPost.updated_at.desc()).limit(100)
    ).all()
    return [row for row in notices if re.fullmatch(r"[0-9]+_[0-9]+", row.post_id)]


def _simple_digital_help(message: str) -> bool:
    value = plain(message)
    return any(term in value for term in (
        "no tengo link", "no tengo enlace", "no se mandar", "no se copiar",
        "no se usar facebook", "no tengo facebook", "que es un link",
        "que es el enlace", "no cacho el link", "no entiendo el enlace",
        "no se de eso", "no se como mandar el aviso", "no puedo mandar",
    ))


def digital_help_reply(message: str, prior_prompt: str = "") -> str | None:
    """Help people who cannot copy a link; no model or technical training needed."""
    if private_data(message) or not _simple_digital_help(message):
        return None
    if referring_to_application(prior_prompt):
        return None  # Preserve the original job-ad context in application_reply.
    return ASK_APPLICATION_LINK


def application_reply(db: Session, lead, message: str, prior_prompt: str = "", *, notices=None) -> str | None:
    """Advance a real conversation, not a Facebook link-gathering script.

    An advert's trade is not the applicant's verified profession.
    """
    follow_up = referring_to_application(prior_prompt)
    asks = asks_about_application(message)
    if (not (asks or follow_up) or private_data(message) or is_pure_greeting(message)
            or worksite_details_question(message)):
        return None
    norm = plain(message)
    info = analyze(message)
    if info.intent in {"human", "restricted"}:
        return None
    if follow_up and not asks and "?" in message and not _simple_digital_help(message):
        return None  # The person is asking a new question; let its router answer.
    contractor_trade = contractor_trade_question(prior_prompt)
    if prior_prompt.startswith(ASK_APPLICATION_OWN) or contractor_trade:
        if norm in TRADE_CONFIRMATIONS:
            return "¿En qué comuna puedes trabajar?" if not getattr(lead, "work_area", None) else None
        if norm in {"no", "no es mi oficio", "no trabajo en eso", "todavia no"}:
            if contractor_trade:
                return "Entiendo. ¿Qué necesitas saber del aviso?"
            return "Está bien, no voy a asumir tu oficio. ¿Qué trabajo realizas?"
        return None
    if application_role_question(prior_prompt):
        role = application_role(message, prior_prompt)
        if role == "employment":
            trades = trade_terms(prior_prompt)
            if len(trades) == 1:
                return ASK_APPLICATION_OWN + trades[0].lower() + "?"
            return "Entiendo, quieres postular tú. ¿Qué oficio realizas?"
        if role == "service_offer":
            return ("¿En qué comuna puedes trabajar?" if getattr(lead, "specialty", None) else
                    "¿Qué trabajos haces por tu cuenta?")
        if role == "both":
            return ("Entiendo, te interesan las dos opciones. ¿Trabajas solo o puedes venir con otras personas?"
                    if getattr(lead, "specialty", None) else "Entiendo, te interesan las dos opciones. ¿Qué trabajo realizas?")
        if norm in {"no entiendo", "que significa", "no cacho", "como es eso", "solo", "sola", "solito", "solita"}:
            if plain(prior_prompt).endswith(plain(ASK_APPLICATION_ROLE_CLARIFY)):
                return "No hay problema, podemos seguir sin aclarar eso ahora. ¿Qué trabajo realizas?"
            trades = trade_terms(prior_prompt)
            context = ("El aviso era de " + trades[0].lower() + ". ") if len(trades) == 1 else ""
            return "Te explico: " + context + ASK_APPLICATION_ROLE_CLARIFY
        # A personal answer identifies who wants work, not contractual modality.
        # Ask once in simpler language, preserving the advertised trade as context.
        if (plain(prior_prompt).endswith(plain(ASK_APPLICATION_ROLE_CLARIFY))
                and ambiguous_application_role(message, prior_prompt)):
            trades = trade_terms(prior_prompt)
            context = ("El aviso era de " + trades[0].lower() + ". ") if len(trades) == 1 else ""
            return context + "¿Buscas un empleo con contrato?"
        # If a person volunteers an occupational fact, do not force an unrelated role menu.
        if any(p in norm for p in ("soy ", "soi ", "trabajo ", "hago ", "me dedico ")):
            return None
        if plain(prior_prompt).endswith(plain(ASK_APPLICATION_ROLE_CLARIFY)):
            return "Podemos dejar ese dato pendiente. ¿Qué trabajo realizas?"
        trades = trade_terms(prior_prompt)
        context = ("El aviso era de " + trades[0].lower() + ". ") if len(trades) == 1 else ""
        return context + ASK_APPLICATION_ROLE_CLARIFY
    if _simple_digital_help(message):
        # Reassure; after repeated difficulty, keep helping instead of looping.
        if prior_prompt == ASK_APPLICATION_LINK:
            return "Está bien, no necesitas enlaces. " + ASK_APPLICATION_INTEREST
        return ASK_APPLICATION_LINK
    if follow_up and norm in {"no se", "no recuerdo", "no me acuerdo", "no lo tengo",
                              "no tengo", "no lo se", "ni idea", "nose", "no cacho"}:
        return "Está bien, podemos seguir igual. " + ASK_APPLICATION_INTEREST
    notices = published_notices(db, lead.org_id, lead.page_id) if notices is None else notices
    matches = _matches_public_notice(message, notices)
    if len(matches) == 1:
        notice = matches[0]
        # A verified match is useful; do not force a link or a confirmation loop.
        return ("Encontré un aviso de " + notice.title[:95] + " en " + notice.site_name[:70] +
                ". " + ASK_APPLICATION_INTEREST)[:550]
    if follow_up:
        trades = trade_terms(message)
        if len(trades) == 1:
            return f"Ah, era un aviso de {trades[0].lower()}. {ASK_APPLICATION_INTEREST}"
    elif ad_trade := advertised_trade(message):
        trade = ad_trade.lower()
        acknowledgement = f"Gracias por escribir por el aviso de {trade}."
        if plain(getattr(lead, "specialty", None) or "") == plain(ad_trade):
            return acknowledgement + " ¿Qué necesitas saber del aviso?"
        if re.search(r"\bcontratistas?\b", norm):
            return f"{acknowledgement} {ASK_CONTRACTOR_TRADE}{trade} como contratista?"
        return f"{acknowledgement} {ASK_APPLICATION_INTEREST}"
    if len(matches) > 1:
        return "Encontré varios avisos parecidos; no quiero confundirte. " + ASK_APPLICATION_INTEREST
    if asks and not follow_up:
        return ASK_APPLICATION
    if follow_up:
        # A partial clue is useful. Never loop back to "send the link".
        if norm:
            return ASK_APPLICATION_INTEREST
        return ASK_APPLICATION
    return None


def worksite_reply(db: Session, lead, message: str, prior_prompt: str = "", *, notices=None) -> str | None:
    location_question = is_worksite_location(message)
    project_question = bool(_PROJECT.search(plain(message)))
    follow_up = prior_prompt in {ASK_WORKSITE, ASK_PROJECT}
    if not (follow_up or location_question or project_question):
        return None
    if follow_up and not (location_question or project_question) and "?" in message:
        return None
    value = plain(message)
    if (not value or private_data(message) or analyze(message).intent in {"human", "restricted"}
            or value in {"si", "no", "gracias", "hola", "buenas", "vale"}):
        return None
    notices = published_notices(db, lead.org_id, lead.page_id) if notices is None else notices
    matches = _matches_public_notice(message, notices)
    remaining = _TOPIC.sub(" ", _LOCATION.sub(" ", value)).split()
    generic = set(remaining) <= {"la", "el", "las", "los", "de", "del", "esa", "ese", "esta", "este",
                                 "ubicada", "ubicado", "ubicacion", "direccion", "y", "hola", "porfa",
                                 "por", "favor", "que", "q", "comuna", "donde", "dnde", "disculpa",
                                 "amigo", "amiga", "compadre", "estimado", "estimada"}
    if not matches and not follow_up and notices and generic and not _POST_LINK.search(message):
        # Allow a reference from the user's recent messages in this same thread.
        recent = db.scalars(select(FacebookChatMessage.body).where(
            FacebookChatMessage.lead_id == lead.id,
            FacebookChatMessage.org_id == lead.org_id,
            FacebookChatMessage.direction == "inbound",
            FacebookChatMessage.created_at >= (lead.last_inbound_at or utcnow()) - timedelta(hours=24),
        ).order_by(FacebookChatMessage.created_at.desc()).limit(8))
        for body in recent:
            matches = _matches_public_notice(body, notices)
            if matches:
                break
    if len({row.site_name for row in matches}) != 1:
        if follow_up:
            return "No ubiqué ese aviso. ¿Tienes el link de la publicación?"
        return ASK_PROJECT if project_question and not location_question else ASK_WORKSITE
    notice = matches[0]
    if not location_question and (project_question or prior_prompt == ASK_PROJECT):
        return f"La obra indicada es {notice.site_name}. Te dejo el aviso: https://www.facebook.com/{notice.post_id}"
    question = "Dónde queda la obra " + notice.site_name
    approved = exact_answer(retrieve(db, lead.org_id, question, "messenger"))
    if approved and not private_data(approved) and approved.count("?") <= 1:
        return approved
    return (f"No tengo la dirección confirmada de {notice.site_name}. "
            f"Te dejo el aviso: https://www.facebook.com/{notice.post_id}")
