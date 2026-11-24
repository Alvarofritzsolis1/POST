"""Local-first response selection; caller owns consent, provider budget and privacy."""
import re

from .galancito_flow import grounded_reply
from .galancito_triage import plain, private_data

UNKNOWN = re.compile(
    r"\b(?:no se (?:como responder|que responder|la respuesta)|no tengo (?:informacion|datos) "
    r"(?:suficiente|suficientes)|no puedo (?:responder|resolver|confirmar)|"
    r"no dispongo de (?:informacion|datos)|no tengo una respuesta|"
    r"deje tu consulta para que la revise el equipo|necesito mas informacion)\b"
)


def usable_answer(draft, context, validator=None):
    if not isinstance(draft, str) or not draft.strip() or private_data(draft):
        return None
    result = grounded_reply(draft, context)
    if not result or private_data(result) or (validator and not validator(result)):
        return None
    return result


def needs_external_help(answer):
    return not answer or bool(UNKNOWN.search(plain(answer)))


def select_response(local, external, context, *, allow_external=False,
                    local_fallback=None, validator=None):
    """At most one call to the external gateway (it enforces its own limits).

    A valid guided fallback wins over spending API tokens on simple wording.
    No private context is sent to either callback. Uncertainty is not a license
    to invent facts; retain honest local uncertainty when the gateway fails.
    """
    if private_data(context):
        return None, "private"
    try:
        answer = usable_answer(local(), context, validator)
    except (RuntimeError, ValueError, TimeoutError, OSError):
        answer = None
    if not needs_external_help(answer):
        return answer, "local_model"
    if local_fallback:
        return local_fallback, "guided_fallback"
    if allow_external and external:
        try:
            candidate = usable_answer(external(), context, validator)
        except (RuntimeError, ValueError, TimeoutError, OSError):
            candidate = None
        if not needs_external_help(candidate):
            return candidate, "external_fallback"
    return answer, "unresolved"
