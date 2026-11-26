"""Queue and storage tests. Semantic quality is evaluated with real Ollama."""
from datetime import timedelta

from sqlalchemy import func, select

import pytest

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_contextual import (
    Declaration, Fragment, Turn, apply_declarations, reconcile_declarations, request_attribution,
    supported_declarations, validated_reply,
    verified_followup,
)
from app.galancito_evidence import evidence_options
from app.models import utcnow
from test_facebook_crm import enable_messaging, incoming, network, no_real_meta_sender_actions


def configure(network, monkeypatch):
    org_id = enable_messaging(network, monkeypatch)
    monkeypatch.delenv("GALANCITO_CONTEXTUAL_MESSENGER_ENABLED", raising=False)
    for name, value in {
        "FACEBOOK_AI_ENABLED": "true", "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
    }.items():
        monkeypatch.setenv(name, value)
    settings.cache_clear()
    with network["Session"].begin() as db:
        db.add(FacebookLead(org_id=org_id, page_id=settings().facebook_page_id, psid="123456789012345",
                            ai_consent=True, ai_consent_provider="ollama", ai_consent_state="accepted"))
    return network["Session"]


def test_burst_replay_and_worker_restart(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "Instalo aislación acústica", mid="test-acoustic").status_code == 200
    assert incoming(network, "Nos movemos por Cabrero", mid="test-location").status_code == 200
    assert incoming(network, "Nos movemos por Cabrero", mid="test-location").status_code == 200
    assert not process_chat_next(sessions)
    with sessions.begin() as db:
        rows = list(db.scalars(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending")))
        assert len(rows) == 1
        assert db.scalar(select(func.count()).select_from(FacebookChatMessage).where(
            FacebookChatMessage.direction == "inbound")) == 2
        rows[0].state = "drafting"
        rows[0].updated_at = utcnow() - timedelta(seconds=160)

    observed = []
    def unavailable(context, fragments, **kwargs):
        observed.extend((item.message_id, item.text) for item in fragments)
        raise RuntimeError("Ollama is unavailable")
    monkeypatch.setattr("app.galancito_contextual.request_attribution", lambda *args: [])
    monkeypatch.setattr("app.galancito_contextual.request_turn", unavailable)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *args: "test-meta-sent")
    assert process_chat_next(sessions)
    assert observed == [("test-acoustic", "Instalo aislación acústica"),
                        ("test-location", "Nos movemos por Cabrero")]
    assert not process_chat_next(sessions)


def test_new_inbound_invalidates_draft_before_meta(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "Hacemos sellos cortafuego", mid="test-first").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.updated_at = utcnow() - timedelta(seconds=2)

    def interrupted(*args, **kwargs):
        assert incoming(network, "¿Dónde queda la obra?", mid="test-newer").status_code == 200
        raise RuntimeError("Ollama is unavailable")
    def unexpected(*args):
        raise AssertionError("The superseded outbound must not reach Meta")
    monkeypatch.setattr("app.galancito_contextual.request_attribution", interrupted)
    monkeypatch.setattr("app.galancito_contextual.request_turn", interrupted)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    assert process_chat_next(sessions)
    with sessions() as db:
        states = set(db.scalars(select(FacebookChatMessage.state).where(
            FacebookChatMessage.direction == "outbound")))
        assert "cancelled" in states
        assert "sent" not in states


def test_evidence_bounds_manual_fields_and_idempotence(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    at = utcnow()
    fragments = (Fragment("test-origin", at, "Somos de Chillán, somos cerca de 15 en la cuadrilla"),)
    raw = Turn(i="intake", q="none", r="Gracias por contarme.", d=[
        {"f": "origin", "v": "Penco", "e": "Somos de Chillán"},
        {"f": "origin", "v": "Chillán", "e": "Somos de Chillán"},
        {"f": "crew", "v": "cerca de 15 en la cuadrilla", "e": "somos cerca de 15 en la cuadrilla"},
    ])
    declarations = supported_declarations(raw.d, fragments)
    assert [declaration[1] for declaration in declarations] == ["Chillán", "cerca de 15 en la cuadrilla"]
    with sessions.begin() as db:
        lead = db.scalar(select(FacebookLead).with_for_update())
        lead.profile_sources = {"_declared_context": {"declared_origin": {
            "value": "Lota", "source": "manual", "at": at.isoformat(),
        }}}
        assert apply_declarations(db, lead, declarations) == 1
        assert apply_declarations(db, lead, declarations) == 0
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert lead.workers is None and lead.employee_count is None
        assert lead.profile_sources["_declared_context"]["declared_origin"]["value"] == "Lota"
        saved = lead.profile_sources["_declared_context"]["crew_size"]
        assert saved["message_id"] == "test-origin"
        assert saved["value"] == "cerca de 15 en la cuadrilla"

def test_questions_and_partial_counts_cannot_supply_profile_values():
    at = utcnow()
    fragments = (
        Fragment("test-price", at, "¿A cuánto pagan la pintura?"),
        Fragment("test-crew", at, "Somos más de 10 maestros"),
        Fragment("test-town", at, "Me puedo mover a Bulnes"),
    )
    draft = Turn(i="question", q="none", r="Lo confirma el equipo.", d=[
        {"f": "trade", "v": "pintura", "e": "pintura"},
        {"f": "crew", "v": "10 maestros", "e": "10 maestros"},
        {"f": "crew", "v": "Bulnes", "e": "Bulnes"},
        {"f": "crew", "v": "más de 10 maestros", "e": "más de 10 maestros"},
    ])
    assert [(field, value) for field, value, _ in supported_declarations(draft.d, fragments)] == [
        ("crew", "más de 10 maestros"),
    ]


def test_evidence_must_support_the_field_and_the_speaker():
    at = utcnow()
    mixed = Fragment("mixed", at, "Mi vecino trabaja en Lota y vivo en Tomé. "
                     "Yo trabajo en Penco y Talcahuano y mi compañero trabaja en Coronel.")
    numbers = Fragment("numbers", at, "Si me prestan un furgón, podría llevar a 7 maestros. Tengo 30 años de edad.")
    proposals = [Declaration(f=field, v=value, e=value) for field, value in (
        ("area", "Lota"), ("area", "Tomé"), ("origin", "Tomé"), ("area", "Penco"), ("area", "Talcahuano"),
        ("area", "Coronel"), ("name", "Penco"), ("crew", "7 maestros"), ("experience", "30 años"),
    )]
    proposals += [Declaration(f="team", v="yes", e="30 años"),
                  Declaration(f="entity", v="company", e="trabajo en Penco")]
    assert reconcile_declarations(supported_declarations(proposals, (mixed, numbers))) == [
        ("origin", "Tomé", mixed), ("area", "Penco, Talcahuano", mixed),
    ]


def test_conflicting_interpretations_of_one_message_stay_pending():
    fragment = Fragment("choices", utcnow(), "Soy de Talca pero también soy de Chillán")
    assert reconcile_declarations([
        ("origin", "Talca", fragment), ("origin", "Chillán", fragment),
        ("trade", "soldadura", fragment), ("trade", "Soldadura", fragment),
    ]) == [("trade", "soldadura", fragment)]


def test_justified_roles_keep_their_normalized_enum_values():
    fragment = Fragment("role", utcnow(), "Soy contratista de pintura")
    proposed = [Declaration(f="role", v=role, e="contratista") for role in ("service_offer", "employment")]
    assert supported_declarations(proposed, (fragment,)) == [("role", "service_offer", fragment)]


def test_work_by_the_job_needs_a_service_declaration_to_support_contractor_role():
    at = utcnow()
    proposed = [Declaration(f="role", v="service_offer", e="trabajo a trato")]
    unclear = Fragment("rate", at, "Trabajo a trato")
    employee = Fragment("employee", at, "Trabajo a trato para mi patrón y hago mantenciones de edificios")
    service = Fragment("service", at, "Trabajo a trato y hago mantenciones de edificios")
    assert supported_declarations(proposed, (unclear,)) == []
    assert supported_declarations(proposed, (employee,)) == []
    assert supported_declarations(proposed, (service,)) == [("role", "service_offer", service)]


@pytest.mark.parametrize(("message", "communes", "origin"), [
    ("Atendemos en Los Ángeles", ["Los Ángeles"], None),
    ("Nos podemos mover a Hualpén y Chiguayante", ["Hualpén", "Chiguayante"], None),
    ("Vivo en Lota, la pega la puedo hacer en Coronel", ["Coronel"], "Lota"),
    ("Soy de Cañete. Las obras que tomo son en Arauco", ["Arauco"], "Cañete"),
])
def test_explicit_work_coverage_is_saved_before_model_runs(network, monkeypatch, message, communes, origin):
    sessions = configure(network, monkeypatch)
    assert incoming(network, message, mid="coverage").status_code == 200
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert lead.work_communes == communes
        assert lead.profile_sources["work_communes"]["message_id"] == "coverage"
        declared = lead.profile_sources.get("_declared_context", {}).get("declared_origin", {})
        assert declared.get("value") == origin

    fragment = Fragment("coverage", utcnow(), message)
    locations = [value for _, field, value, _ in evidence_options((fragment,)) if field == "area"]
    assert len(locations) == len(communes)


def test_intake_question_does_not_answer_a_new_request():
    fragment = Fragment("question", utcnow(), "Trabajo en pintura. ¿Puedo participar si soy independiente?")
    draft = Turn(i="intake", q="area", r="Perfecto, gracias. ¿En qué comuna puedes trabajar?", d=[])
    assert validated_reply(draft, {}, [], fragment.text, (fragment,)) is None

@pytest.mark.parametrize("reply", [
    "Seguro que ya dominas el trabajo en alta mar. ¿En qué comuna puedes trabajar?",
    "¿En qué lugar te gustaría probar tus manos?",
])
def test_intake_rejects_speculation_and_questions_that_do_not_match_the_chosen_field(reply):
    fragment = Fragment("work", utcnow(), "Llevo 8 años de soldador")
    draft = Turn(i="intake", q="area", r=reply, d=[])
    assert validated_reply(draft, {}, [], fragment.text, (fragment,)) is None


def test_parroting_the_current_question_is_rejected():
    message = "¿A cuánto pagan el metro de pintura?"
    fragment = Fragment("test-question", utcnow(), message)
    decision = Turn(i="question", q="other", r=message, d=[])
    assert validated_reply(decision, {}, [], message, (fragment,)) is None


def test_parroting_an_earlier_short_question_in_the_burst_is_rejected():
    fragments = (
        Fragment("test-opening", utcnow(), "¿Qué hago ahora?"),
        Fragment("test-latest", utcnow(), "Necesito una persona real"),
    )
    draft = Turn(i="question", q="other", r="¿Qué hago ahora?", d=[])
    assert validated_reply(draft, {}, [], "", fragments) is None


@pytest.mark.parametrize("reply", [
    "¿En qué comuna puedes trabajar?",
    "¿Me puedes dar más detalles?",
    "Ya avisé al equipo para que revise tu caso.",
])
def test_rejects_repeated_generic_and_unconfirmed_replies(reply):
    fragment = Fragment("follow-up", utcnow(), "No caché a qué te refieres.")
    draft = Turn(i="clarification", q="other" if "?" in reply else "none", r=reply, d=[])
    assert validated_reply(draft, {}, [], fragment.text, (fragment,),
                           prior="¿En qué comuna puedes trabajar?") is None


def test_tries_a_contextual_clarification_before_handing_off(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "No cacho bien lo de los papeles", mid="documents-doubt").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.updated_at = utcnow() - timedelta(seconds=2)

    revisions = []

    def draft(context, fragments, *, revision, **kwargs):
        assert [part.text for part in fragments] == ["No cacho bien lo de los papeles"]
        revisions.append(revision)
        if not revision:
            raise ValueError("Esquema de turno inválido")
        return Turn(i="clarification", q="other", d=[],
                    r="No tengo ese dato. ¿Qué documento menciona el aviso?")

    sent = []
    monkeypatch.setattr("app.galancito_contextual.request_turn", draft)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *args: sent.append(args[2]) or "meta-doubt")
    assert process_chat_next(sessions)
    assert len(revisions) == 2 and not revisions[0] and revisions[1]
    assert sent == ["No tengo ese dato. ¿Qué documento menciona el aviso?"]
    with sessions() as db:
        assert db.scalar(select(FacebookLead)).needs_support is False


def test_a_revised_draft_preserves_the_intent_of_a_professional_declaration(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "Hago pintura en Lebu", mid="paint-intake").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.updated_at = utcnow() - timedelta(seconds=2)

    drafts = iter((Turn(i="intake", q="availability", d=[], r="Hago pintura en Lebu"),
                   Turn(i="clarification", q="other", d=[], r="¿Qué duda tienes sobre pintura?")))
    monkeypatch.setattr("app.galancito_contextual.request_attribution", lambda *args: [
        Declaration(f="trade", v="Pintura", e="pintura", message_index=0),
    ])
    monkeypatch.setattr("app.galancito_contextual.request_turn", lambda *args, **kwargs: next(drafts))
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *args: sent.append(args[2]) or "meta-intake")
    assert process_chat_next(sessions)
    assert sent == ["¿Desde cuándo podrías comenzar?"]


def test_model_cannot_answer_as_a_contractor():
    fragment = Fragment("test-introduction", utcnow(), "Soy contratista, hago pintura")
    decision = Turn(i="intake", q="none", r="Hola. Soy un contratista especializado en pintura.", d=[])
    assert validated_reply(decision, {}, [], fragment.text, (fragment,)) is None

def test_evidence_options_preserve_literals_and_exclude_other_speakers():
    at = utcnow()
    fragments = (
        Fragment("first", at, "¿Cuánto pagan los eléctricos? Un vecino trae 25 maestros."),
        Fragment("own", at, "Soy de Constitución, hacemos carpintería en madera y metal, somos alrededor de ocho."),
        Fragment("correction", at, "Ya no hago gasfitería."),
        Fragment("reference", at, "En el aviso buscan pintores para Castro."),
    )
    options = evidence_options(fragments)
    assert options == [
        (1, "origin", "constitucion", "constitucion"),
        (1, "trade", "carpinteria en madera y metal", "carpinteria en madera y metal"),
        (1, "crew", "alrededor de ocho", "alrededor de ocho"),
    ]
    provenance = [
        Declaration(f="crew", v="25 maestros", e="25 maestros"),
        Declaration(f="origin", v="constitucion", e="constitucion", message_index=0),
        Declaration(f="origin", v="constitucion", e="constitucion", message_index=1),
    ]
    assert supported_declarations(provenance, fragments) == [("origin", "constitucion", fragments[1])]


def test_attribution_outputs_cannot_reference_facts_outside_this_request(monkeypatch):
    fragments = (Fragment("own", utcnow(), "Vivo en Maullín."),)
    options = evidence_options(fragments)
    monkeypatch.setattr("app.galancito_contextual.generate_local_text", lambda *args, **kw: '{"aceptar":["999"]}')
    with pytest.raises(ValueError, match="Selección de evidencia inválida"):
        request_attribution(fragments, options)

def test_verified_followup_only_renders_a_pending_question_for_an_intake_turn():
    declaration = Fragment("own", utcnow(), "Hago tabiquería y cuento con mi equipo.")
    question = Fragment("query", utcnow(), "¿Hay obras en Penco?")
    decision = Turn(i="intake", q="area", r="¿En qué comuna quieres comprar pintura?", d=[])
    assert verified_followup(decision, {}, (declaration,)) == "¿En qué comuna puedes trabajar?"
    assert verified_followup(decision, {"work_communes": ["Penco"]}, (declaration,)) is None
    assert verified_followup(decision, {"field_states": {"work_communes": "rechazado_por_usuario"}},
                             (declaration,)) is None
    assert verified_followup(decision, {}, (declaration, question)) is None


def test_evidence_preserves_out_of_catalog_trade_and_ignores_business_contact():
    fragments = (
        Fragment("trade", utcnow(), "Trabajo reparando quemadores industriales en terreno."),
        Fragment("reference", utcnow(), "La página dice que tienen WhatsApp. ¿Cuál es?"),
        Fragment("preference", utcnow(), "Me acomoda más el wasap."),
    )
    assert evidence_options(fragments) == [
        (0, "trade", "quemadores industriales", "quemadores industriales"),
        (2, "channel", "whatsapp", "wasap"),
    ]
    phonetic = Fragment("phonetic", utcnow(), "Me sirve el guasap.")
    assert evidence_options((phonetic,)) == [(0, "channel", "whatsapp", "guasap")]


def test_payment_guidance_does_not_treat_a_declaration_as_a_question():
    from app.galancito_triage import payment_guidance

    assert payment_guidance("A todo esto, ¿se paga por avance?")
    assert payment_guidance("¿A cuánto están pagando el metro de pintura en la obra?")
    assert not payment_guidance("Me pagan por avance. ¿Dónde queda la obra?")
    assert not payment_guidance("Me pagan por avance.")
    assert not payment_guidance("¿Cuánto cuestan las herramientas?")


def test_explicit_human_requests_survive_contextual_routing():
    from app.galancito_flow import wants_human

    assert wants_human("Quiero hablar con un humano")
    assert wants_human("Necesito una persona real")
    assert wants_human("Necesito hablar con una persona del equipo")
    assert wants_human("¿Habrá una persona que me pueda ayudar?")
    assert not wants_human("¿Habrá una persona que trabaje en la obra?")
    assert not wants_human("Necesito una persona para pintar la obra")


def test_unconfirmed_payment_does_not_pause_later_messages(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "A todo esto, ¿se paga por avance?", mid="test-payment").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.updated_at = utcnow() - timedelta(seconds=2)

    sent = []

    def unavailable(*args, **kwargs):
        raise RuntimeError("Ollama is unavailable")

    def send(_page, _psid, body, _token):
        sent.append(body)
        return "payment-reply"

    monkeypatch.setattr("app.galancito_contextual.request_turn", unavailable)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", send)
    assert process_chat_next(sessions)
    assert len(sent) == 1 and "forma de pago" in sent[0]
    assert incoming(network, "Puedo trabajar en Lebu.", mid="test-next-location").status_code == 200
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert not lead.ai_paused and not lead.needs_support
        assert db.scalar(select(func.count()).select_from(FacebookChatMessage).where(
            FacebookChatMessage.state == "ai_pending")) == 1


@pytest.mark.parametrize("message, expected", [
    ("Guasap", "whatsapp"), ("Watsap", "whatsapp"),
    ("Me acomoda más el guasap.", "whatsapp"),
    ("Prefiero correo electrónico.", "email"), ("Escríbanme por mail.", "email"),
    ("Prefiero Messenger.", "messenger"), ("No uso correo.", None),
    ("Mi primo prefiere WhatsApp.", None), ("¿Tienen WhatsApp?", None),
    ("Si prefiero correo, ¿se puede?", None), ("[correo reservado]", None),
    ("Prefiero correo o WhatsApp.", None),
])
def test_explicit_channel_survives_model_omission(message, expected):
    from app.galancito_contextual import explicit_channel_declarations
    fragment = Fragment("channel-test", utcnow(), message)
    result = explicit_channel_declarations((fragment,))
    assert result == ([("channel", expected, fragment)] if expected else [])


def test_channel_evidence_cannot_be_relabelled():
    fragment = Fragment("channel-test", utcnow(), "Prefiero correo.")
    raw = Declaration(f="channel", v="whatsapp", e="correo")
    assert supported_declarations([raw], (fragment,)) == []
    raw = Declaration(f="channel", v="email", e="correo")
    assert supported_declarations([raw], (fragment,)) == [("channel", "email", fragment)]


def test_contextual_memory_uses_advert_and_galilea_as_distinct_chat_evidence():
    from app.galancito_contextual import memory_text

    fragments = (Fragment("synthetic-ad", utcnow(), "les hablo por el aviso de contratista de pintura"),)
    profile = {"declared_context": {"notice_trade": "Pintura", "worked_at_galilea": False}}
    context, _ = memory_text(profile, (), fragments, "", (), None)

    assert '"worked_at_galilea": false' in context
    assert "aviso consultado" in context and "oficio propio" in context
    assert "Ejemplo de práctica" in context
    assert "Respeta la respuesta" in context


def test_invalid_model_draft_can_continue_after_the_work_commune_was_saved(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    with sessions.begin() as db:
        lead = db.scalar(select(FacebookLead))
        lead.interest_type, lead.specialty = "service_offer", "Yeso"

    replies = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: replies.append(args[2]) or "synthetic-continuity")
    monkeypatch.setattr("app.facebook_chat_worker._contextual_reply", lambda *args, **kwargs: (
        (Turn(i="intake", q="none", r="Perfecto.", d=[]), [], None), "fallback", {}, "invalid_reply",
    ))
    assert incoming(network, "Puedo trabajar en Hualqui", mid="saved-commune").status_code == 200
    with sessions.begin() as db:
        assert db.scalar(select(FacebookLead)).work_communes == ["Hualqui"]
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.updated_at = utcnow() - timedelta(seconds=3)

    assert process_chat_next(sessions)
    assert replies == ["¿Trabajas solo o puedes venir con otras personas?"]
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert not lead.needs_support and not lead.ai_paused

def test_legacy_scripted_trade_question_cannot_reach_meta(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    assert incoming(network, "Construcción obras civiles", mid="civil-works").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        job.state, job.body, job.ai_generated = "pending", "¿Qué trabajo realizas?", False
    monkeypatch.setattr("app.facebook_chat_worker._contextual_reply", lambda *args, **kwargs: (
        (None, [], None), "fallback", {}, "invalid_reply",
    ))
    def unexpected(*args):
        pytest.fail("A scripted question cannot be sent to Meta")
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    assert process_chat_next(sessions)
    with sessions() as db:
        assert not db.scalar(select(FacebookLead)).needs_support


def test_multiline_trade_list_is_saved_without_waiting_for_model(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    from app.facebook_crm_models import FacebookLeadTrade
    message = "Movimiento de tierra\nAlbañilería\nCarpintería\nTerminación\nPintura\nEifs\nHormigón vacio Y pulido"
    assert incoming(network, message, mid="seven-trades").status_code == 200
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        trades = set(db.scalars(select(FacebookLeadTrade.trade).where(FacebookLeadTrade.lead_id == lead.id, FacebookLeadTrade.active.is_(True))))
        assert trades == {"Movimiento de tierra", "Albañilería", "Carpintería", "Terminaciones", "Pintura", "EIFS", "Hormigón vaciado y pulido"}
        assert not lead.ai_paused


def test_paint_plaster_putty_and_eifs_across_messages_are_additive(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    from app.facebook_crm_models import FacebookLeadTrade
    from app.galancito_links import trade_declarations
    first = "Pintura completa yeso pasta muro pintura"
    assert trade_declarations(first, "¿Usted qué trabajo realiza?") == {"Pintura": True, "Yeso": True, "Pasta muro": True}
    assert trade_declarations("Y eif", allow_bare=True) == {"EIFS": True}
    assert trade_declarations("¿Y eif?", allow_bare=True) == {}
    assert trade_declarations("Mi hermano hace EIFS", allow_bare=True) == {}
    assert incoming(network, first, mid="paint-plaster-putty").status_code == 200
    assert incoming(network, "Y eif", mid="add-eifs").status_code == 200
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        trades = set(db.scalars(select(FacebookLeadTrade.trade).where(FacebookLeadTrade.lead_id == lead.id, FacebookLeadTrade.active.is_(True))))
        assert trades == {"Pintura", "Yeso", "Pasta muro", "EIFS"}
        assert not lead.ai_paused

    # Even if both Qwen drafting attempts are rejected, the verified additive
    # trade is acknowledged without pausing Messenger or inventing an oficio.
    delivered = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: delivered.append(args[2]) or "synthetic-trade-ack")
    monkeypatch.setattr("app.facebook_chat_worker.graph_sender_action", lambda *args: None)
    monkeypatch.setattr("app.facebook_chat_worker._contextual_reply", lambda *args, **kwargs: (
        (Turn(i="intake", q="none", r="Perfecto.", d=[]), [], None),
        "fallback", {}, "invalid_reply",
    ))
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        assert job is not None
        job.updated_at = utcnow() - timedelta(seconds=3)
    assert process_chat_next(sessions)
    assert delivered == ["Perfecto, también anoté EIFS entre tus trabajos."]
    with sessions() as db:
        from app.galancito_knowledge_models import AssistantRun
        assert not db.scalar(select(FacebookLead)).needs_support
        run = db.scalar(select(AssistantRun).order_by(AssistantRun.created_at.desc()).limit(1))
        assert run is not None and run.source == "local_recovery"
        assert run.timings.get("model_error") is True
        assert run.timings.get("verified_guidance") == "saved_trade_confirmation"


def test_joined_experience_units_and_natural_operator_question(network, monkeypatch):
    from app.galancito_intake import intake_question_fields
    from app.galancito_memory import apply_messenger_message

    sessions = configure(network, monkeypatch)
    prompt = "Excelente hace cuanto trabajas como contratista?"
    assert "experience" in intake_question_fields(prompt)
    assert "interest_type" not in intake_question_fields(prompt)
    assert "specialty" in intake_question_fields("¿Usted qué trabajo realiza?")
    assert "specialty" in intake_question_fields("¿Qué labores realiza?")
    with sessions.begin() as db:
        lead = db.scalar(select(FacebookLead))
        lead.ai_paused = True
        lead.needs_support = True
        assert apply_messenger_message(db, lead, "2años", prompt, remote_id="joined-experience",
                                       at=utcnow())
        assert lead.experience == "2 años"
        apply_messenger_message(db, lead, "Formalmente", prompt, remote_id="formal-experience",
                                at=utcnow())
        assert lead.experience == "2 años"
        assert lead.ai_paused

    fragment = Fragment("joined-months", utcnow(), "6meses")
    declaration = Declaration(f="experience", v="6 meses", e="6 meses")
    assert supported_declarations([declaration], (fragment,), prior=prompt)
    assert not supported_declarations([declaration], (fragment,), prior="¿Dónde vives?")

def test_known_tradespeople_are_not_a_confirmed_crew():
    from app.galancito_evidence import crew_mentions
    from app.galancito_triage import plain
    from app.galancito_contextual import supported_declarations

    fragment = Fragment("synthetic-acquaintances", utcnow(), "Conozco varios maestros")
    assert list(crew_mentions(plain(fragment.text))) == []
    assert supported_declarations(
        [Declaration(f="crew", v="varios maestros", e="varios maestros")],
        (fragment,),
    ) == []
    assert supported_declarations(
        [Declaration(f="team", v="yes", e="varios maestros")],
        (fragment,),
    ) == []


def test_compound_payment_question_is_answered_without_guessing_terms(network, monkeypatch):
    sessions = configure(network, monkeypatch)
    message = ("¿La pega es a trato o por día? "
               "Quiero cachar si vale la pena antes de hablar con los maestros.")
    replies = []
    called = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: replies.append(args[2]) or "synthetic-payment-terms")
    monkeypatch.setattr("app.galancito_contextual.request_attribution", lambda *args: [])
    def draft(*args, **kwargs):
        called.append(True)
        return Turn(i="question", q="none",
                    r="Primero hay que confirmar las condiciones de esa obra.", d=[])
    monkeypatch.setattr("app.galancito_contextual.request_turn", draft)
    assert incoming(network, message, mid="payment-context").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "ai_pending"))
        assert job is not None
        job.updated_at = utcnow() - timedelta(seconds=3)
    assert process_chat_next(sessions)
    assert called and len(replies) == 1
    assert "no tengo confirmada" in replies[0].lower()
    assert "modalidad de pago" in replies[0].lower()
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert lead.needs_support is False and lead.ai_paused is False

def test_cuento_con_equipo_burst_does_not_force_human(network, monkeypatch):
    """The production-style presentation cannot be lost to a drafting outage."""
    from app.galancito_links import trade_terms
    from app.galancito_contextual import field_supported
    assert set(trade_terms("pintura yeso eifs textura completo")) == {
        "Pintura", "Yeso", "EIFS", "Textura",
    }
    assert field_supported(
        "team", "yes", "cuento con equipo de trabajo en ambas partidas", "", (),
    )

    sessions = configure(network, monkeypatch)
    for i, line in enumerate((
        "Hola", "Buenas trades",
        "Le. Ablo por trabajo de pintura yeso eifs textura completo",
        "Cuento con equipo de trabajo en ambas partidas",
    ), start=1):
        assert incoming(network, line, mid=f"contractor-burst-{i}").status_code == 200
    with sessions.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state == "ai_pending",
        ))
        assert job is not None
        job.updated_at = utcnow() - timedelta(seconds=3)
        lead = db.scalar(select(FacebookLead))
        assert lead.team_available is True
        assert lead.workers is None
        assert not lead.needs_support

    delivered = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda *args: delivered.append(args[2]) or "contractor-team-ack")
    monkeypatch.setattr("app.facebook_chat_worker.graph_sender_action", lambda *args: None)
    monkeypatch.setattr("app.facebook_chat_worker._contextual_reply", lambda *args, **kwargs: (
        (Turn(i="intake", q="none", r="Gracias.", d=[]), [], None),
        "fallback", {}, "invalid_reply",
    ))
    assert process_chat_next(sessions)
    assert len(delivered) == 1
    assert "equipo de trabajo" in delivered[0].lower()
    assert "comuna" in delivered[0].lower()
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert not lead.needs_support and not lead.ai_paused
        assert lead.team_available is True and lead.workers is None


def test_non_model_professional_presentation_does_not_auto_handoff(network, monkeypatch):
    """An unconsented message must not invoke Qwen or turn into a human takeover."""
    sessions = configure(network, monkeypatch)
    with sessions.begin() as db:
        lead = db.scalar(select(FacebookLead))
        lead.ai_consent = False
        lead.ai_consent_state = "not_requested"
        lead.ai_consent_provider = "disabled"
    monkeypatch.setattr(
        "app.facebook_chat_worker.graph_send",
        lambda *args: "synthetic-intake-no-consent",
    )
    assert incoming(network, "Cuento con equipo de trabajo en ambas partidas",
                    mid="team-no-consent").status_code == 200
    with sessions() as db:
        lead = db.scalar(select(FacebookLead))
        assert lead.team_available is True and lead.workers is None
        assert lead.needs_support is False
        assert lead.ai_paused is False

def test_team_declaration_after_an_advert_question_keeps_the_speaker_attribution(network, monkeypatch):
    from app.galancito_memory import apply_messenger_message
    sessions = configure(network, monkeypatch)
    with sessions.begin() as db:
        lead = db.scalar(select(FacebookLead))
        assert apply_messenger_message(
            db, lead, "Cuento con equipo de trabajo en ambas partidas",
            "Claro, te ayudo. ¿De qué trabajo era el aviso?",
            remote_id="speaker-team-followup", at=utcnow(),
        )
        assert lead.team_available is True
        assert lead.workers is None
        assert (lead.profile_sources or {}).get("team_available", {}).get("message_id") == "speaker-team-followup"

def test_busy_qwen_queue_preserves_authorized_conversation(network, monkeypatch):
    """A third contact must not be transferred to a person when two jobs wait."""
    sessions = configure(network, monkeypatch)
    with sessions.begin() as db:
        main = db.scalar(select(FacebookLead))
        for i in (1, 2):
            other = FacebookLead(
                org_id=main.org_id, page_id=main.page_id, psid=f"synthetic-backlog-{i}",
                ai_consent=True, ai_consent_provider="ollama", ai_consent_state="accepted",
            )
            db.add(other)
            db.flush()
            db.add(FacebookChatMessage(
                org_id=main.org_id, lead_id=other.id, page_id=main.page_id,
                direction="outbound", state="ai_pending", body="", ai_generated=True,
            ))
    assert incoming(network, "Cuento con equipo de trabajo en ambas partidas",
                    mid="busy-queue-contact").status_code == 200
    with sessions() as db:
        main = db.scalar(select(FacebookLead).where(
            FacebookLead.psid == "123456789012345",
        ))
        assert main.team_available is True and main.workers is None
        assert not main.needs_support and not main.ai_paused
        jobs = list(db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.state == "ai_pending",
            FacebookChatMessage.direction == "outbound",
        )))
        assert len(jobs) == 3
        assert any(job.lead_id == main.id for job in jobs)

