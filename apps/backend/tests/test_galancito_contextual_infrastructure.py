"""Queue and storage tests. Semantic quality is evaluated with real Ollama."""
from datetime import timedelta

from sqlalchemy import func, select

import pytest

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_contextual import (
    Declaration, Fragment, Turn, apply_declarations, request_attribution, supported_declarations, validated_reply,
    verified_followup,
)
from app.galancito_evidence import evidence_options
from app.models import utcnow
from test_facebook_crm import enable_messaging, incoming, network, no_real_meta_sender_actions


def configure(network, monkeypatch):
    org_id = enable_messaging(network, monkeypatch)
    for name, value in {
        "FACEBOOK_AI_ENABLED": "true", "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true", "GALANCITO_CONTEXTUAL_MESSENGER_ENABLED": "true",
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

def test_parroting_the_current_question_is_rejected():
    message = "¿A cuánto pagan el metro de pintura?"
    fragment = Fragment("test-question", utcnow(), message)
    decision = Turn(i="question", q="other", r=message, d=[])
    assert validated_reply(decision, {}, [], message, (fragment,)) is None

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
    assert wants_human("¿Habrá una persona que me pueda ayudar?")
    assert not wants_human("¿Habrá una persona que trabaje en la obra?")


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
