"""Private Messenger sender run by the existing Facebook worker.

The API/webhook never receives the Page token. A completed/uncertain send is not retried
automatically; an ambiguous network outcome must be checked in Meta first.
"""
from datetime import timedelta, timezone
import json
import re
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from sqlalchemy import and_, or_, select

from .config import settings
from .db import SessionLocal
from .facebook_availability_reply import availability_reply
from .facebook_worksite_reply import application_reply, worksite_reply
from .facebook_ai import (LOCAL_REPLY_INSTRUCTIONS, REPLY_INSTRUCTIONS, generate_text,
                          messenger_contact_ai_source, local_first_messenger, messenger_external_fallback_enabled)
from .galancito_hybrid import select_response
from .ai_gateway import AIServiceError, orchestrated_text
from .galancito_flow import wants_human, safe_ai_reply, consented_for, grounded_reply, is_permission_prompt, external_permission_prompt
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide, FacebookLeadTrade
from .models import utcnow
from .network_service import key
from .galancito_triage import plain, analyze, quick_reply, private_data, application_ai_candidate, application_role, application_role_question
from .galancito_phone import confirmed_phone_reply
from . import galancito_contextual as contextual
from .facebook_lead_insights import trace_unique_requirement
from .network_service import today
from .galancito_semantic import PROTOCOL, decode_local_reply, remember_confirmation, has_semantic_opportunity, CORRECTION
from .galancito_intake import semantic_reasoning_needed, contact_followup_reply, contact_pending_questions, model_contact_question, compose_contact_followup, CONTACT_RECEIVED_CONTEXT, acceptable_intake_draft, intake_question_fields, clarification_reply, identity_reply, model_intake_candidate, next_intake_reply, small_talk_reply, natural_messenger_reply, needs_deeper_response
from .galancito_memory import aware, note_profile_sources, prior_delivered_prompt, profile_facts, reply_focus, messenger_context
from .galancito_knowledge import retrieve, exact_answer
from .galancito_runtime import infer, record_run
from .galancito_local import generate_local_text, last_timings, MAX_CONTEXT_CHARS
from .galancito_escalation import flag_for_human
from .ai_defect_learning import approved_coaching

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("La API de Meta redirigió el envío")

_opener = build_opener(NoRedirect)


def graph_send(page_id: str, psid: str, message: str, token: str) -> str:
    if not (re.fullmatch(r"[0-9]{5,30}", page_id) and
            re.fullmatch(r"[0-9]{5,90}", psid)):
        raise ValueError("Identificador de Meta no válido")
    payload = json.dumps({
        "recipient": {"id": psid},
        "messaging_type": "RESPONSE",
        "message": {"text": message[:1800]},
    }).encode("utf-8")
    request = Request(
        "https://graph.facebook.com/v27.0/" + page_id + "/messages",
        data=payload, method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with _opener.open(request, timeout=15) as response:
        obj = json.loads(response.read(16384).decode("utf-8"))
    mid = obj.get("message_id")
    if not isinstance(mid, str) or not mid:
        raise RuntimeError("Meta no confirmó un identificador de mensaje")
    return mid[:180]


def graph_sender_action(page_id: str, psid: str, action: str, token: str) -> None:
    """Show real Messenger read/typing indicators when the sender begins work.

    These Meta actions are best-effort and never replace a confirmed message.
    No token or page-scoped user identifier is logged.
    """
    if (action not in {"mark_seen", "typing_on", "typing_off"} or
            not re.fullmatch(r"[0-9]{5,30}", page_id) or
            not re.fullmatch(r"[0-9]{5,90}", psid)):
        raise ValueError("Acción o identificador de Meta no válido")
    payload = json.dumps({
        "recipient": {"id": psid},
        "sender_action": action,
    }).encode("utf-8")
    request = Request(
        "https://graph.facebook.com/v27.0/" + page_id + "/messages",
        data=payload, method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with _opener.open(request, timeout=1.0) as response:
        response.read(2048)


def meta_messenger_error(exc: HTTPError) -> str:
    """Conservar solo códigos estructurados; jamás el texto libre o credenciales de Meta.

    La respuesta puede contener URLs, PSID, tokens y parámetros privados.
    El código, subcódigo y fbtrace_id seguro bastan para diagnóstico.
    """
    code, subcode, trace = None, None, None
    try:
        response = json.loads(exc.read(8192).decode("utf-8"))
        details = response.get("error") if isinstance(response, dict) else None
        if isinstance(details, dict):
            raw_code = details.get("code")
            raw_subcode = details.get("error_subcode")
            if type(raw_code) is int and 0 < raw_code < 1000000:
                code = raw_code
            if type(raw_subcode) is int and 0 < raw_subcode < 10000000:
                subcode = raw_subcode
            raw_trace = details.get("fbtrace_id")
            if isinstance(raw_trace, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", raw_trace):
                trace = raw_trace
    except (OSError, UnicodeError, ValueError, TypeError):
        pass
    status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else 0
    markers = [f"HTTP {status}"]
    if code is not None:
        markers.append(f"código Meta {code}")
    if subcode is not None:
        markers.append(f"subcódigo {subcode}")
    if trace:
        markers.append("referencia " + trace)
    if code in {190, 102}:
        hint = "Token rechazado. Renueva el token de página en el VPS y reinicia facebook-publisher."
    elif code in {10, 200, 230, 283}:
        hint = ("Permiso de Messenger denegado. Revisa pages_messaging, el acceso MESSAGING "
                "a la página, los roles de prueba y App Review de Meta.")
    elif code in {551, 613}:
        hint = ("Meta no permite entregar este mensaje. Revisa la disponibilidad del destinatario "
                "y las restricciones de mensajería de la página.")
    elif status == 401:
        hint = ("Meta rechazó la autorización de envío. Comprueba pages_messaging, "
                "rol MESSAGING del token, destinatario y estado de la aplicación.")
    else:
        hint = ("Meta rechazó el envío. Comprueba los permisos de Messenger, "
                "la suscripción de página y la ventana de respuesta.")
    return "Meta rechazó el mensaje (" + " · ".join(markers) + "). " + hint


def messenger_profile_name(psid: str, token: str) -> str | None:
    """Obtener el nombre permitido por el perfil PSID, sin exponer token o URL.

    Meta puede denegar datos del perfil incluso con pages_messaging. En ese caso
    el administrador puede confirmar el nombre declarado en el chat.
    """
    if not re.fullmatch(r"[0-9]{5,90}", psid):
        return None
    request = Request(
        "https://graph.facebook.com/v27.0/" + psid +
        "?fields=id%2Cname%2Cfirst_name%2Clast_name",
        headers={"Authorization": "Bearer " + token}, method="GET",
    )
    with _opener.open(request, timeout=5) as response:
        payload = json.loads(response.read(8192).decode("utf-8"))
    if not isinstance(payload, dict) or str(payload.get("id")) != psid:
        return None
    first, last = payload.get("first_name"), payload.get("last_name")
    full = payload.get("name")
    value = (full if isinstance(full, str) else
             (str(first or "") + " " + str(last or "")).strip())
    value = " ".join(value.split())[:155]
    if len(value) < 2 or not all(char.isprintable() for char in value):
        return None
    return value


# Cada instancia del worker intenta un perfil por contacto, no en cada sondeo.
# No hay credenciales ni nombres privados en logs o el frontend hasta que
# el servicio de Meta responde y se valida el ID de página.
_profile_attempted: set[str] = set()
_profile_auth_denied = False


def process_profile_next(session_factory=SessionLocal) -> bool:
    """Mejor esfuerzo, aislado de la cola de mensajes y sin migrar tablas."""
    global _profile_auth_denied
    cfg = settings()
    if _profile_auth_denied or not (cfg.facebook_messaging_enabled and
            cfg.facebook_page_token and cfg.facebook_page_id and cfg.facebook_org_id):
        return False
    with session_factory() as db:
        candidates = list(db.scalars(select(FacebookLead).where(
            FacebookLead.org_id == cfg.facebook_org_id,
            FacebookLead.page_id == cfg.facebook_page_id,
            FacebookLead.display_name == "Interesado de Facebook",
            FacebookLead.name_opt_out.is_(False),
            FacebookLead.last_inbound_at.is_not(None),
        ).order_by(FacebookLead.last_inbound_at.desc()).limit(300)))
        lead = next((x for x in candidates if x.id not in _profile_attempted), None)
        if lead is None:
            return False
        lead_id, psid = lead.id, lead.psid
    _profile_attempted.add(lead_id)
    try:
        name = messenger_profile_name(psid, cfg.facebook_page_token)
    except HTTPError as exc:
        if exc.code in (401, 403):
            _profile_auth_denied = True
        return True
    except (URLError, TimeoutError, OSError, ValueError, TypeError):
        return True
    if name:
        with session_factory.begin() as db:
            lead = db.get(FacebookLead, lead_id, with_for_update=True)
            if (lead and lead.org_id == cfg.facebook_org_id and
                    lead.page_id == cfg.facebook_page_id and
                    lead.display_name == "Interesado de Facebook" and not lead.name_opt_out):
                lead.display_name = name
                note_profile_sources(lead, ["display_name"], source="meta", at=utcnow())
                lead.updated_at = utcnow()
    return True


def _within_24h(lead: FacebookLead) -> bool:
    incoming = lead.last_inbound_at
    if incoming and incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    return bool(incoming and incoming >= utcnow() - timedelta(hours=24))


def process_chat_next(session_factory=SessionLocal, *, simulation_config=None, notices=None) -> bool:
    started = perf_counter()
    simulated = simulation_config is not None
    if simulated and session_factory is SessionLocal:
        raise ValueError("La simulación requiere almacenamiento aislado")
    cfg = simulation_config if simulated else settings()
    if not (cfg.facebook_messaging_enabled and cfg.facebook_page_token and
            cfg.facebook_page_id and cfg.facebook_org_id):
        return False
    now = utcnow()
    with session_factory.begin() as db:
        pickable = FacebookChatMessage.state.in_(["pending", "ai_pending"])
        if contextual.enabled(cfg) and not simulated:
            pickable = or_(
                and_(FacebookChatMessage.state == "pending", FacebookChatMessage.operator_id.is_not(None)),
                and_(FacebookChatMessage.state.in_(["pending", "ai_pending"]), or_(
                    FacebookChatMessage.updated_at <= now - timedelta(milliseconds=700),
                    FacebookChatMessage.created_at <= now - timedelta(seconds=3),
                )),
                and_(FacebookChatMessage.state == "drafting", FacebookChatMessage.ai_generated.is_(True),
                     FacebookChatMessage.updated_at < now - timedelta(seconds=150)),
            )
        job = db.scalar(select(FacebookChatMessage).where(
            FacebookChatMessage.org_id == cfg.facebook_org_id,
            FacebookChatMessage.page_id == cfg.facebook_page_id,
            FacebookChatMessage.direction == "outbound",
            pickable,
        ).order_by(FacebookChatMessage.created_at, FacebookChatMessage.id)
          .with_for_update(skip_locked=True))
        if job is None:
            return False
        if job.state == "drafting":
            job.state = "ai_pending"  # Draft leases can recover, sends with unknown outcomes cannot.
        lead = db.get(FacebookLead, job.lead_id)
        if (lead is None or lead.org_id != cfg.facebook_org_id or
                lead.page_id != cfg.facebook_page_id):
            job.state, job.error = "failed", "Contacto no disponible"
            return True
        if not _within_24h(lead):
            job.state, job.error = "failed", "Fuera de la ventana estándar de 24 horas"
            return True
        if job.state == "pending" and job.operator_id is None and external_permission_prompt(job.body):
            if lead.ai_paused or lead.needs_support:
                job.state, job.error = "cancelled", "Solicitud externa retirada"
                return True
            flag_for_human(db, lead, "Consulta pendiente tras retirar solicitud externa")
            job.body = "Dejé tu consulta para que la revise una persona del equipo."
        permission_request = job.state == "pending" and job.operator_id is None and "autorizas" in job.body.casefold()
        ai_source = (messenger_contact_ai_source(db, lead, cfg)
                     if job.state == "ai_pending" or permission_request else "disabled")
        if permission_request and (ai_source == "disabled" or lead.ai_consent_provider != ai_source or
                lead.ai_consent_state not in {"requested", "requested_team"} or
                not is_permission_prompt(lead, job.body)):
            job.state, job.error = "cancelled", "Solicitud de consentimiento superada"
            return True
        if job.state == "ai_pending" and lead.needs_support:
            job.state, job.error = "cancelled", "El contacto pidió apoyo: revisión humana prioritaria"
            return True
        if job.state == "ai_pending" and (lead.ai_paused or lead.ai_consent_state == "declined"):
            job.state, job.error = "cancelled", "Galancito pausado para este contacto"
            return True
        if job.state == "ai_pending" and not consented_for(lead, ai_source):
            job.state, job.error = "cancelled", "El contacto no autorizó ese proveedor"
            return True
        job_id, lead_id, org_id, psid, state, body = job.id, lead.id, lead.org_id, lead.psid, job.state, job.body
        automated_reply = job.operator_id is None
        # Only the one fixed handoff acknowledgement can be delivered after
        # handoff has atomically paused all other automatic replies.
        handoff_ack = (state == "pending" and (
            body.startswith("Ya avisé al equipo para que te atienda una persona.")
            or body.startswith("Entendido, no usaré IA con tus mensajes.")
            or body.startswith("Entendido. No usaré IA con tus mensajes.")
            or body.startswith("Dejé tu consulta para que la revise una persona del equipo.")
            or body.startswith("Aún no puedo confirmar ese dato. Dejé tu consulta para que la revise el equipo.")
            or body.startswith("Ahora no puedo resolver esa consulta por aquí. La dejé para que la revise el equipo.")))
        inbound_at = lead.last_inbound_at
        outbound_queue_ms = max(0, round((utcnow() - aware(job.created_at)).total_seconds() * 1000))
        fast, intent, fast_source, model_needed, context = None, "unknown", "local", False, ""
        semantic_proposal = None
        structured_fragments = ()
        declarations = []
        decision = None
        requested_handoff = False
        trace = {"trace_version": 1, "context_turns": 0, "known_fields": 0,
                 "knowledge_count": 0, "model_requested": False, "context_truncated": False}
        if state == "ai_pending":
            turns = list(db.scalars(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.state.in_(["received", "sent"]),
            ).order_by(FacebookChatMessage.updated_at.desc(), FacebookChatMessage.id.desc()).limit(60)))
            focus = reply_focus(turns)
            latest = focus.body if focus else ""
            facts = profile_facts(lead, changed=bool(focus and lead.profile_sources and
                any(origin.get("message_id") == focus.remote_id for origin in lead.profile_sources.values())))
            prior_question = (prior_delivered_prompt(db, lead, at=focus.created_at)
                              if focus else "")
            phone_ack = confirmed_phone_reply(lead, latest, prior_question)
            contact_turn = bool(phone_ack)
            help_answer = clarification_reply(latest, prior_question)
            location = None if help_answer else worksite_reply(db, lead, latest, prior_question, notices=notices)
            follow_up = availability_reply(db, lead, latest, prior_question, focus.created_at) if focus and not help_answer else None
            apply = None if help_answer or location or follow_up else application_reply(db, lead, latest, prior_question, notices=notices)
            intake = help_answer or location or follow_up or apply or small_talk_reply(latest, prior_question) or next_intake_reply(latest, facts, prior_question)
            intent = "worksite_location" if location else "apply" if apply else analyze(latest).intent
            fast = intake or quick_reply(latest, known=facts)
            evidence = []
            application_model = bool(apply and local_first_messenger(cfg) and
                                     application_ai_candidate(latest, prior_question))
            rewrite_intake = (not (location or follow_up) and (not apply or application_model) and
                              model_intake_candidate(latest, facts, prior_question, intake))
            if (not intake or rewrite_intake) and not private_data(latest) and intent not in {"human", "restricted"}:
                evidence = retrieve(db, lead.org_id, latest, "messenger")
                if not evidence and len(plain(latest).split()) <= 3 and prior_question and not private_data(prior_question):
                    evidence = retrieve(db, lead.org_id, latest + " " + prior_question, "messenger")
                if not rewrite_intake and (learned := exact_answer(evidence)):
                    fast = learned
                    if not local_first_messenger(cfg) or not needs_deeper_response(latest):
                        fast_source = "knowledge"
            model_needed = (bool(latest) and not (location or follow_up) and (not apply or application_model) and not private_data(latest) and not identity_reply(latest)
                            and intent not in {"human", "restricted"} and fast_source != "knowledge"
                            and (not fast or needs_deeper_response(latest) or rewrite_intake))
            if contact_turn:
                fast = contact_followup_reply(phone_ack, facts, prior_question)
                model_needed = bool(local_first_messenger(cfg) and contact_pending_questions(facts, prior_question))
                rewrite_intake = False
                intent = "contact_followup"
                latest = (CONTACT_RECEIVED_CONTEXT + " Campos aplicables: " +
                          ", ".join(contact_pending_questions(facts, prior_question)))  # No phone digits.
            semantic_reasoning = bool(model_needed and local_first_messenger(cfg) and not contact_turn and (
                (application_role_question(prior_question) and application_role(latest, prior_question) is None)
                or semantic_reasoning_needed(latest, prior_question, facts)))
            semantic_protocol = bool(semantic_reasoning and ai_source == "ollama" and
                (has_semantic_opportunity(facts) or CORRECTION.search(plain(latest))))
            if (contextual.authorized(cfg, lead) and not (location or follow_up or (apply and not application_model))
                    and not identity_reply(focus.body if focus else "")):
                structured_fragments = contextual.current_fragments(turns)
                if structured_fragments:
                    model_needed = True
                    semantic_protocol = False
                    semantic_reasoning = False
                    evidence = evidence or retrieve(db, lead.org_id, structured_fragments[-1].text, "messenger")
            trace["semantic_reasoning_requested"] = semantic_reasoning
            trace["contextual_turn"] = bool(structured_fragments)
            trace["fragment_count"] = len(structured_fragments)
            model_options = {"thinking": True} if semantic_reasoning else {}
            trace["contact_followup"] = contact_turn
            trace["model_requested"] = bool(model_needed)
            trace["knowledge_count"] = len(evidence)
            if model_needed:
                facts["trades"] = list(db.scalars(select(FacebookLeadTrade.trade).where(
                    FacebookLeadTrade.lead_id == lead.id, FacebookLeadTrade.active.is_(True))))
                guides = db.scalars(select(FacebookTradeGuide).where(
                    FacebookTradeGuide.org_id == lead.org_id, FacebookTradeGuide.approved.is_(True)))
                terms = {key(t) for t in [lead.specialty, *facts["trades"]] if t}
                guide = next((g for g in guides if terms.intersection(
                    {key(g.trade), *(key(a) for a in (g.aliases or []))})), None)
                if structured_fragments:
                    context, count = contextual.memory_text(facts, turns, structured_fragments, prior_question, evidence, guide)
                else:
                    context, count = messenger_context(latest, facts, prior_question, turns, evidence, guide,
                        limit=MAX_CONTEXT_CHARS - (len(PROTOCOL) + 1 if semantic_protocol else 0))
                if semantic_protocol:
                    context = PROTOCOL + "\n" + context
                trace["context_turns"] = count
                trace["known_fields"] = sum(bool(value) for key, value in facts.items()
                                            if key not in {"field_states", "turn_changed", "manual_fields"})
        db_ms = (perf_counter() - started) * 1000
        # A separate persisted drafting state lets the UI show real stages.
        # Do not claim to be sending before the AI has generated its reply.
        job.state, job.updated_at = ("drafting" if automated_reply else "sending"), utcnow()
        claimed_at = job.updated_at

    uncertain = False
    result_id, problem = None, None
    outcome_at = None
    source, timings, failed_ai = fast_source, {}, False
    typing_started = False
    graph_calls = 0
    try:
        if state == "ai_pending" and model_needed and not simulated:
            # The worker is actively handling this contact now. Do not claim
            # "seen" when a webhook merely stores a message or the bot is paused.
            try:
                graph_calls += 1
                graph_sender_action(cfg.facebook_page_id, psid, "mark_seen", cfg.facebook_page_token)
                graph_calls += 1
                graph_sender_action(cfg.facebook_page_id, psid, "typing_on", cfg.facebook_page_token)
                typing_started = True
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError):
                # Indicators are cosmetic; never block the actual reply.
                pass
        if structured_fragments:
            grounding = context + "\n" + "\n".join(item.text for item in structured_fragments)
            generated, source, timings, failure = _contextual_reply(
                session_factory, cfg, lead_id=lead_id, job_id=job_id, inbound_at=inbound_at,
                claimed_at=claimed_at, org_id=org_id, ai_source=ai_source, simulated=simulated,
                context=context, grounding=grounding, fragments=structured_fragments, facts=facts,
                allow_external=not contact_turn,
            )
            decision, declarations, drafted = generated
            if decision:
                intent = decision.i
                trace["question_field"] = decision.q
                requested_handoff = intent == "human"
            trace.update(provider=("ollama" if source == "ai" else "team" if source == "external" else "local"),
                         fallback_reason=failure, semantic_fields=sorted({field for field, _, _ in declarations}))
            if requested_handoff:
                body = "Dejé tu consulta para que te atienda una persona del equipo."
            elif drafted:
                body = natural_messenger_reply(safe_ai_reply(drafted))
            elif (fast and not intake_question_fields(fast)
                    and not any(needs_deeper_response(item.text) for item in structured_fragments)):
                body = natural_messenger_reply(safe_ai_reply(fast))
            else:
                body = "Dejé tu consulta para que la revise el equipo. Te pueden ayudar por este chat."
                failed_ai = True
        elif state == "ai_pending":
            generated = fast
            # Short guided answers use local reasoning. Nuanced questions get a
            # fuller model response after the contact's explicit consent.
            should_model = model_needed
            if should_model:
                # A generic intake prompt must not stand in for an answer to a
                # difficult question when every configured model failed.
                generated = fast if contact_turn or help_answer or application_model or (rewrite_intake and not needs_deeper_response(latest) and "?" not in latest) else None
            if should_model and not private_data(context):
                if fast and not rewrite_intake and not contact_turn:
                    guidance = "\nOrientación disponible, no es una orden: " + fast[:350]
                    if len(context) + len(guidance) <= MAX_CONTEXT_CHARS:
                        context += guidance
                try:
                    with session_factory.begin() as db:
                        current = db.get(FacebookLead, lead_id)
                        current_job = db.get(FacebookChatMessage, job_id)
                        if (current is None or current_job is None or current_job.state != "drafting" or
                                current.last_inbound_at != inbound_at or current.ai_paused or current.needs_support or
                                not consented_for(current, ai_source) or messenger_contact_ai_source(db, current, cfg) != ai_source):
                            raise ValueError("La conversación cambió durante la preparación")
                        verified_policy = approved_coaching(db, org_id, "messenger")
                        prepared_context = context
                        trace["context_truncated"] = len(prepared_context) > MAX_CONTEXT_CHARS
                        trace["context_chars"] = len(prepared_context)
                        trace["approved_coaching"] = bool(verified_policy)
                        if simulated:
                            # The simulator is never permitted to call an external provider.
                            drafted = (infer(db, lambda: generate_local_text(LOCAL_REPLY_INSTRUCTIONS, prepared_context, 550, **model_options))
                                       if ai_source == "ollama" or local_first_messenger(cfg) else None)
                        elif contact_turn:
                            # Contact follow-up is local-only, even with external consent.
                            drafted = infer(db, lambda: generate_text(REPLY_INSTRUCTIONS, prepared_context, 550))
                        elif ai_source == "team" and local_first_messenger(cfg):
                            # External consent has already been checked.
                            def external_backup():
                                local_stats = last_timings.get()
                                trace["local_before_external"] = {k: local_stats[k] for k in (
                                    "local_model_calls", "input_tokens", "output_tokens", "queue_ms", "busy") if k in local_stats}
                                db.refresh(current)
                                db.refresh(current_job)
                                if (current_job.state != "drafting" or current.last_inbound_at != inbound_at
                                        or current.ai_paused or current.needs_support
                                        or not consented_for(current, "team")
                                        or not messenger_external_fallback_enabled(db, org_id, cfg)):
                                    return None
                                return infer(db, lambda: orchestrated_text(
                                    db, org_id, task="messenger",
                                    instructions=(REPLY_INSTRUCTIONS + "\nUsa las referencias como evidencia; "
                                                  "no inventes hechos de obras ni datos faltantes." +
                                                  ("\nGuía aprobada:\n" + verified_policy if verified_policy else "")),
                                    prompt=prepared_context, max_output_tokens=230), org_id=org_id)

                            drafted, route = select_response(
                                lambda: infer(db, lambda: generate_text(
                                    REPLY_INSTRUCTIONS, prepared_context, 550, approved_policy=verified_policy, **model_options)),
                                external_backup, prepared_context,
                                allow_external=consented_for(current, "team"),
                                prefer_external=semantic_reasoning or needs_deeper_response(latest),
                                local_fallback=fast if rewrite_intake and intake_question_fields(fast or "")
                                and not semantic_reasoning and not needs_deeper_response(latest) and "?" not in latest else None,
                                validator=(lambda value: acceptable_intake_draft(value, facts, intake or "", message=latest))
                                if rewrite_intake else None,
                            )
                            trace["ai_route"] = route
                            trace["local_first_attempted"] = True
                        else:
                            drafted = infer(db, lambda: (
                                orchestrated_text(db, org_id, task="messenger",
                                                  instructions=(REPLY_INSTRUCTIONS +
                                                                ("\nGuía aprobada:\n" + verified_policy if verified_policy else "")),
                                                  prompt=prepared_context, max_output_tokens=230)
                                if ai_source == "team" else
                                (generate_text(REPLY_INSTRUCTIONS, prepared_context, 550,
                                               approved_policy=verified_policy, **model_options) if verified_policy else
                                 generate_text(REPLY_INSTRUCTIONS, prepared_context, 550, **model_options))),
                                org_id=org_id if ai_source == "team" else None)
                        timings = last_timings.get()
                    if semantic_protocol and drafted:
                        drafted, semantic_proposal = decode_local_reply(drafted, latest, facts)
                    grounding = context + ("\nPropuesta para confirmar: " + semantic_proposal["question"] if semantic_proposal else "")
                    if drafted:
                        drafted = grounded_reply(drafted, grounding)
                    validation_facts = facts
                    if semantic_proposal and semantic_proposal.get("correction"):
                        validation_facts = {**facts, semantic_proposal["field"]: None}
                        if semantic_proposal["field"] == "work_communes":
                            validation_facts["work_area"] = ""
                    if drafted and rewrite_intake and not acceptable_intake_draft(drafted, validation_facts, intake or "", message=latest):
                        drafted = None
                    if contact_turn and drafted:
                        question = model_contact_question(drafted, facts, prior_question)
                        drafted = compose_contact_followup(question) if question else None
                    if drafted:
                        generated, source = drafted, ("fallback" if trace.get("ai_route") == "guided_fallback" else "ai")
                    else:
                        semantic_proposal = None
                        source = "fallback"
                except (RuntimeError, ValueError):
                    source = "fallback"
                    timings = last_timings.get()
            if generated:
                body = natural_messenger_reply(safe_ai_reply(generated))
            elif not model_needed:
                # Never treat an empty permission-acceptance turn as a model
                # outage or tell a greeting-only contact that humans were paged.
                body = "Te leo. Cuéntame qué necesitas y seguimos por aquí."
                source = "local_recovery"
            else:
                # A genuine unresolved question must be visible for human
                # review; do not invent a job, wage or hiring decision.
                body = ("Aún no puedo confirmar ese dato. "
                        "Dejé tu consulta para que la revise el equipo.")
                failed_ai = True
        if automated_reply and external_permission_prompt(body):
            body = "Aún no puedo confirmar ese dato. Dejé tu consulta para que la revise el equipo."
            failed_ai, source = True, "fallback"
        # Re-check after slow inference: a human may have taken over or the
        # contact may have revoked permission/sent a newer question meanwhile.
        with session_factory.begin() as db:
            current = db.get(FacebookLead, lead_id, with_for_update=True)
            current_job = db.get(FacebookChatMessage, job_id, with_for_update=True)
            if (current is None or not _within_24h(current) or
                    current_job is None or current_job.state != (
                        "drafting" if automated_reply else "sending") or
                    (automated_reply and aware(current_job.updated_at) != aware(claimed_at)) or
                    (automated_reply and ((current.ai_paused and not handoff_ack)
                                          or current.last_inbound_at != inbound_at)) or
                    (state == "ai_pending" and (current.needs_support or not consented_for(current, ai_source)
                     or messenger_contact_ai_source(db, current, cfg) != ai_source))):
                if current_job and current_job.state == "drafting" and aware(current_job.updated_at) == aware(claimed_at):
                    current_job.state, current_job.error = "cancelled", "La conversación cambió antes del envío"
                if automated_reply:
                    record_run(db, org_id=org_id, channel="messenger", source="cancelled",
                               intent=intent, started=started, db_ms=db_ms,
                               timings={**timings, "graph_calls": graph_calls + int(typing_started),
                                        "cancelled": True})
                return True
            if structured_fragments:
                trace["semantic_updates"] = contextual.apply_declarations(db, current, declarations)
                if trace["semantic_updates"]:
                    trace_unique_requirement(db, current, today=today(), remote_id=structured_fragments[-1].message_id)
                if failed_ai and decision and declarations:
                    followup = contextual.verified_followup(decision, profile_facts(current), structured_fragments)
                    if followup:
                        body, failed_ai = followup, False
                        trace["guided_followup"] = decision.q
                if requested_handoff or failed_ai:
                    flag_for_human(db, current, "Solicitó atención humana" if requested_handoff else
                                  "Galancito no obtuvo una respuesta confirmada; revisión pendiente")
            if automated_reply:
                current_job.state, current_job.updated_at = "sending", utcnow()
        if simulated:
            result_id = "simulated-" + uuid4().hex
        else:
            graph_calls += 1
            result_id = graph_send(cfg.facebook_page_id, psid, body, cfg.facebook_page_token)
    except HTTPError as exc:
        problem = meta_messenger_error(exc)
    except (URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
        problem = "No se confirmó el envío (" + type(exc).__name__ + "). Verifica Messenger."
        uncertain = isinstance(exc, (URLError, TimeoutError, OSError))
    finally:
        outcome_at = utcnow()
        if typing_started:
            try:
                graph_calls += 1
                graph_sender_action(cfg.facebook_page_id, psid, "typing_off", cfg.facebook_page_token)
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError):
                pass
    with session_factory.begin() as db:
        contact = db.get(FacebookLead, lead_id, with_for_update=True)
        row = db.get(FacebookChatMessage, job_id, with_for_update=True)
        if row is None:
            return True
        row.body = body[:1800]
        row.remote_id = result_id
        row.state = "sent" if result_id else ("uncertain" if uncertain else "failed")
        row.error, row.updated_at = problem, utcnow()
        if result_id and automated_reply and semantic_proposal and source == "ai":
            if contact is not None and contact.last_inbound_at == inbound_at and not contact.ai_paused:
                remember_confirmation(contact, semantic_proposal, body, result_id)
        if result_id and automated_reply and intake_question_fields(body) & {"contact_phone", "contact_email"}:
            if contact is not None and not contact.phone_requested_at:
                contact.phone_requested_at = utcnow()
        if automated_reply:
            record_run(db, org_id=org_id, channel="messenger", source=source,
                       intent=intent, started=started, db_ms=db_ms,
                       timings={**timings, **trace, "graph_calls": graph_calls, "outbound_queue_ms": outbound_queue_ms,
                                "conversation_ms": max(0, round((outcome_at - aware(inbound_at)).total_seconds() * 1000)),
                                "delivery_error": not bool(result_id), "model_error": failed_ai,
                                "outbound_message_id": row.id})
        if failed_ai and not structured_fragments:
            if contact:
                flag_for_human(db, contact,
                               "Galancito no obtuvo una respuesta confirmada; revisión pendiente")
        if automated_reply and not result_id:
            if contact:
                flag_for_human(db, contact,
                               "No se confirmó la entrega en Messenger; revisar antes de reintentar")
    return True


def _contextual_reply(session_factory, cfg, *, lead_id, job_id, inbound_at, claimed_at, org_id,
                      ai_source, simulated, context, grounding, fragments, facts, allow_external):
    """Use the same inference and validation for real and simulated Messenger."""
    decision, declarations, timings = None, [], {}
    failure = "invalid_reply"
    def is_current(db):
        lead = db.get(FacebookLead, lead_id, populate_existing=True)
        job = db.get(FacebookChatMessage, job_id, populate_existing=True)
        return (lead and job and job.state == "drafting" and aware(job.updated_at) == aware(claimed_at)
                and lead.last_inbound_at == inbound_at and not (lead.ai_paused or lead.needs_support)
                and contextual.authorized(cfg, lead) and messenger_contact_ai_source(db, lead, cfg) == ai_source)

    if private_data(grounding):
        return (decision, declarations, None), "fallback", timings, "private_context"

    hints = contextual.evidence_options(fragments)
    for attempt in range(2):
        selecting = bool(hints and attempt == 0)
        revision = ("El primer borrador no pasó la validación. El campo que intentó preguntar fue " +
                    decision.q + ". Responde la consulta o pregunta por otro dato pertinente."
                    if attempt and decision else "")
        with session_factory.begin() as db:
            if not is_current(db):
                return (None, [], None), "fallback", timings, "superseded"
            policy = approved_coaching(db, org_id, "messenger")
            try:
                if selecting:
                    selected = infer(db, lambda: contextual.request_attribution(fragments, hints))
                    candidate = None
                else:
                    candidate = infer(db, lambda: contextual.request_turn(
                        context, fragments, revision=revision, policy=policy, accepted=declarations))
            except (RuntimeError, ValueError) as exc:
                failure = type(exc).__name__
                candidate, selected = None, []
            step = last_timings.get()
            totals = {metric: timings.get(metric, 0) + step.get(metric, 0)
                      for metric in ("local_model_calls", "input_tokens", "output_tokens")}
            timings = {**timings, **step, **totals}
        if selecting:
            if failure == "RuntimeError":
                break
            declarations = contextual.supported_declarations(selected, fragments)
            continue
        if candidate is None:
            break
        proposed = contextual.supported_declarations(candidate.d, fragments)
        declarations = list(dict.fromkeys([*declarations, *proposed]))
        if not revision:
            decision = candidate
        answer = contextual.validated_reply(candidate, facts, declarations, grounding, fragments)
        if candidate.i == "human":
            if any(wants_human(part.text) for part in fragments):
                return (candidate, declarations, answer), "ai", timings, None
            decision = None
            continue
        if answer:
            return (candidate, declarations, answer), "ai", timings, None

    if allow_external and not simulated and ai_source == "team":
        with session_factory.begin() as db:
            if is_current(db) and messenger_external_fallback_enabled(db, org_id, cfg):
                try:
                    answer = infer(db, lambda: orchestrated_text(
                        db, org_id, task="messenger", instructions=REPLY_INSTRUCTIONS,
                        prompt=grounding, max_output_tokens=160), org_id=org_id)
                except (AIServiceError, RuntimeError, ValueError):
                    answer = None
                timings["external_model_calls"] = last_timings.get().get("external_model_calls", 0)
                if answer and acceptable_intake_draft(answer, facts) and (answer := grounded_reply(answer, grounding)):
                    return (decision, declarations, answer), "external", timings, failure
    return (decision, declarations, None), "fallback", timings, failure
