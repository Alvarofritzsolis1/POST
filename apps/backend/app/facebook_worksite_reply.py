"""Local answers to Messenger questions about the location of a worksite."""
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .facebook_crm_models import FacebookChatMessage
from .galancito_knowledge import exact_answer, retrieve
from .galancito_triage import (
    ASK_APPLICATION, ASK_APPLICATION_LINK, analyze, asks_about_application, is_pure_greeting,
    plain, private_data, referring_to_application,
)
from .network_models import NetworkFacebookPost, NetworkRequirement
from .models import utcnow
from .network_service import today
from .ops_models import Worksite

ASK_WORKSITE = "¿Cuál obra viste? Mándame el nombre o el link del aviso."

_LOCATION = re.compile(
    r"\b(?:(?:donde|dnde) (?:q(?:u?e)d[ao]|esta|se ubica|se encuentra|ubico|es)|"
    r"en (?:que|q) (?:comuna|sector|ciudad)|cual es la (?:direccion|ubicacion)|"
    r"(?:pasas|mandas|envias|dices) la (?:direccion|ubicacion))\b"
)
_TOPIC = re.compile(r"\b(?:obra|obras|aviso|faena|proyecto|pega|trabajo|puesto|convocatoria)\b")
_BARE = re.compile(r"(?:(?:y|hola|ola|buenas|disculpa) )*"
                   r"(?:(?:donde|dnde) (?:(?:q(?:u?e)d[ao]|esta|es)(?: ubicad[ao])?)|"
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


def application_reply(db: Session, lead, message: str, prior_prompt: str = "", *, notices=None) -> str | None:
    follow_up = referring_to_application(prior_prompt)
    value = plain(message)
    asks = asks_about_application(message)
    if not (asks or follow_up) or private_data(message) or is_pure_greeting(message):
        return None
    if follow_up and (value == "no" or value.startswith(("no tengo el link", "no lo tengo", "no tengo el enlace"))):
        return "Está bien. Si encuentras el aviso, por acá podemos ver cómo postular."
    if not value or value in {"si", "no", "gracias", "vale"}:
        return None
    intent = analyze(message).intent
    if intent in {"human", "restricted"} or (not asks and ("?" in message or intent in {"documents", "requirements", "about", "publish"})):
        return None
    notices = published_notices(db, lead.org_id, lead.page_id) if notices is None else notices
    matches = _matches_public_notice(message, notices)
    if len(matches) == 1:
        notice = matches[0]
        return (f"Este es el aviso de {notice.title}: https://www.facebook.com/{notice.post_id}. "
                "Revisa ahí cómo reciben las postulaciones.")[:550]
    if asks and not follow_up:
        return ASK_APPLICATION
    if _POST_LINK.search(message):
        return "Con ese enlace no pude ubicar el aviso aquí. Si la publicación indica cómo postular, sigue ese paso."
    if prior_prompt == ASK_APPLICATION_LINK:
        return "Todavía no ubico la publicación. Si trae instrucciones para postular, sigue lo que indique el aviso."
    return ASK_APPLICATION_LINK


def worksite_reply(db: Session, lead, message: str, prior_prompt: str = "", *, notices=None) -> str | None:
    follow_up = prior_prompt == ASK_WORKSITE
    if not (follow_up or is_worksite_location(message)):
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
                                 "por", "favor", "que", "q", "comuna", "donde", "dnde", "disculpa"}
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
        return ASK_WORKSITE
    notice = matches[0]
    question = "Dónde queda la obra " + notice.site_name
    approved = exact_answer(retrieve(db, lead.org_id, question, "messenger"))
    if approved and not private_data(approved) and approved.count("?") <= 1:
        return approved
    return (f"No tengo la dirección confirmada de {notice.site_name}. "
            f"Te dejo el aviso: https://www.facebook.com/{notice.post_id}")
