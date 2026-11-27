"""Evidence-based repair cases; all names, contacts and conversations are synthetic."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.facebook_crm_models import FacebookLead, FacebookChatMessage
from app.galancito_contact_profile import contact_profile
from app.galancito_intake import apply_intake, intake_question_fields
from app.galancito_memory import remember_declared_context
from app.models import utcnow
from test_facebook_crm import enable_messaging
from test_galancito_curriculum_20 import blank_lead
from test_network import network
from test_ai_control_center import ai_env, signin
from app.facebook_refresh_policy import refresh_retry_allowed


@pytest.mark.parametrize("trade", ["pintores y yeseros", "carpinteros", "electricistas", "albañiles", "soldadores"])
def test_explicit_crew_count_with_occupational_unit(trade):
    lead = blank_lead()
    apply_intake(lead, "Tengo una cuadrilla de 6 " + trade)
    assert lead.workers == 6 and lead.team_available is True
    assert lead.has_employees is None


@pytest.mark.parametrize("text", ["No tengo una cuadrilla de 6 pintores", "Tengo un equipo de 6 máquinas", "Conozco 6 pintores"])
def test_equipment_negation_and_other_people_do_not_become_crew(text):
    lead = blank_lead()
    apply_intake(lead, text)
    assert lead.workers is None


def remember(lead, message, prior="", *, at=None, remote_id="synthetic-evidence"):
    remember_declared_context(lead, message, prior, remote_id=remote_id, at=at or utcnow())
    return lead.profile_sources.get("_declared_context", {})


def test_approximate_crew_keeps_qualification_and_unit():
    lead = blank_lead()
    message = "Tengo una cuadrilla de más de 10 pintores"
    apply_intake(lead, message)
    context = remember(lead, message)
    assert lead.workers is None
    assert context["crew_size"]["value"] == "mas de 10 pintores"
    assert "Personas que pueden acudir" not in contact_profile(lead)["missing"]


@pytest.mark.parametrize("text,channel", [("Me sirve más el guasap", "whatsapp"),
    ("Soy yesero y me sirve más el guasap", "whatsapp"), ("Prefiero el correo", "email"),
    ("Mejor por Messenger", "messenger")])
def test_voluntary_channel_preference_does_not_need_a_model(text, channel):
    context = remember(blank_lead(), text)
    assert context["preferred_contact"]["value"] == channel
    assert context["preferred_contact"]["message_id"] == "synthetic-evidence"


@pytest.mark.parametrize("text", ["La página tiene WhatsApp", "Mi amigo prefiere WhatsApp",
    "No quiero WhatsApp", "¿Tienen WhatsApp?", "Si tuviera WhatsApp, te escribiría",
    "Prefiero WhatsApp o Messenger"])
def test_channel_preference_does_not_infer_from_questions_or_other_people(text):
    assert "preferred_contact" not in remember(blank_lead(), text)


def test_channel_replay_respects_manual_and_newer_evidence():
    now = utcnow()
    lead = blank_lead()
    remember(lead, "Prefiero WhatsApp", at=now)
    remember(lead, "Prefiero correo", at=now - timedelta(days=1))
    assert lead.profile_sources["_declared_context"]["preferred_contact"]["value"] == "whatsapp"
    lead.profile_sources["_declared_context"]["preferred_contact"]["source"] = "manual"
    remember(lead, "Prefiero correo", at=now + timedelta(days=1))
    assert lead.profile_sources["_declared_context"]["preferred_contact"]["value"] == "whatsapp"


@pytest.mark.parametrize("prior", ["¿Ha trabajado para Galilea antes?", "Necesito una información adicional, ¿a trabajado para Galilea antes?"])
def test_galilea_role_answer_keeps_master_and_contractor_distinct(prior):
    assert "worked_at_galilea" in intake_question_fields(prior)
    lead = blank_lead()
    context = remember(lead, "Como subcontrato no pero sí como maestro en San Pedro", prior)
    assert context["worked_at_galilea"]["value"] is True
    assert "subcontrato no" in context["galilea_experience_detail"]["value"]
    assert "maestro" in contact_profile(lead)["summary"]
    assert not lead.work_area  # Experience location does not declare work coverage.


def test_negative_role_alone_does_not_deny_all_experience():
    context = remember(blank_lead(), "Como contratista no", "¿Has trabajado en Galilea?")
    assert "worked_at_galilea" not in context
    assert context["galilea_experience_detail"]["value"] == "Como contratista no"


def test_role_confirmation_cannot_override_explicit_target_denial():
    context = remember(blank_lead(), "Como maestro sí, pero no en Galilea", "¿Has trabajado antes en Galilea?")
    assert context["worked_at_galilea"]["value"] is False
    assert "no en Galilea" in context["galilea_experience_detail"]["value"]


def test_role_confirmation_in_another_company_does_not_confirm_galilea():
    context = remember(blank_lead(), "Como maestro sí, pero en otra empresa", "¿Has trabajado antes en Galilea?")
    assert "worked_at_galilea" not in context


@pytest.mark.parametrize("error,allowed", [
    ("HTTP 400", False), ("HTTP 404", False), ("HTTP 410", False),
    ("HTTP 400 · código Meta 100", False), ("HTTP 400 · código Meta 230", False),
    ("HTTP 400 · código Meta 4", True), ("HTTP 400 · código Meta 613", True),
    ("HTTP 400 · código Meta 2", True), ("HTTP 429", True), ("HTTP 503", True),
])
def test_refresh_does_not_repeat_invalid_requests_but_recovers_transient_errors(error, allowed):
    now = utcnow()
    assert refresh_retry_allowed("failed", error, now - timedelta(days=1), now) is allowed


def test_export_discloses_partial_training_and_local_policy(ai_env, monkeypatch):
    from app.galancito_training_models import TrainingRound
    from app.models import User
    monkeypatch.setenv("FACEBOOK_LOCAL_PROCESSING_AUTHORIZED", "false")
    settings.cache_clear()
    client = ai_env["client"]
    signin(client)
    with ai_env["sessions"].begin() as db:
        creator = db.scalar(select(User.id).where(User.org_id == ai_env["org_id"]))
        db.add(TrainingRound(org_id=ai_env["org_id"], created_by=creator,
                             state="stopped", target=100, completed=7,
                             config={"profile": "postulantes"}, dataset_hash="synthetic",
                             prompt_version="synthetic", system_version="synthetic",
                             aliases={}, knowledge=[], metrics={"passed": 7, "failed": 0}))
    report = client.get("/api/v1/admin/ai/red-obras/feedback-export").json()
    metrics = report["datasets"]["training_rounds"][0]["metrics"]
    assert metrics["score"] == 100 and metrics["score_is_partial"] is True
    assert metrics["evaluated_cases"] == 7 and metrics["target_cases"] == 100
    assert metrics["score_basis"] == "synthetic_case_pass_rate"
    ready = client.get("/api/v1/admin/ai/bootstrap").json()["messenger_ready"]
    assert ready["local_processing_authorized"] is False


@pytest.mark.parametrize("answer,expected", [("s", "true"), ("n", "false")])
def test_local_setup_requires_operator_authorization_and_preserves_private_settings(tmp_path, monkeypatch, answer, expected):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "scripts/setup-galancito-local.py"
    spec = importlib.util.spec_from_file_location("patch_local_setup", path)
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    env_path = tmp_path / ".env.preview"
    env_path.write_text("APP_SECRET=synthetic-preserved\nFACEBOOK_PAGE_TOKEN=synthetic-preserved-token\n")
    env_path.chmod(0o600)
    monkeypatch.setattr(setup, "ENV", env_path)
    monkeypatch.setattr(setup, "preflight", lambda: None)
    monkeypatch.setattr(setup, "command", lambda *args, **kwargs: "Modelo local probado")
    answers = iter(["s", "s", answer, "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    setup.install()
    values = setup.env_values(env_path)
    assert values["FACEBOOK_LOCAL_PROCESSING_AUTHORIZED"] == expected
    assert values["FACEBOOK_AI_ENABLED"] == "true"
    assert values["FACEBOOK_PAGE_TOKEN"] == "synthetic-preserved-token"
    assert values["APP_SECRET"] == "synthetic-preserved"


def test_repair_preview_recovers_crew_and_channel_without_modifying_manual_fields(network, monkeypatch):
    org_id = enable_messaging(network, monkeypatch)
    with network["Session"].begin() as db:
        lead = FacebookLead(org_id=org_id, page_id=settings().facebook_page_id,
                            psid="patch-crew-synthetic", experience="12 años",
                            profile_sources={"experience": {"source": "manual"}})
        db.add(lead)
        db.flush()
        ident = lead.id
        db.add(FacebookChatMessage(org_id=org_id, lead_id=ident, page_id=lead.page_id,
                                  direction="inbound", state="received", remote_id="patch-crew-message",
                                  body="Tengo una cuadrilla de 6 pintores y yeseros. Me sirve más el guasap"))
    url = f"/facebook/leads/{ident}/refresh-profile"
    result = network["send"](network["admin"], url + "?dry_run=true", {})
    assert result.status_code == 200, result.text
    assert result.json()["changes"]["workers"]["after"] == 6
    assert result.json()["evidence"]["workers"] == "patch-crew-message"
    with network["Session"]() as db:
        assert db.get(FacebookLead, ident).workers is None
    applied = network["send"](network["admin"], url, {})
    assert applied.status_code == 200, applied.text
    with network["Session"]() as db:
        lead = db.get(FacebookLead, ident)
        assert lead.workers == 6 and lead.experience == "12 años"
        assert lead.profile_sources["_declared_context"]["preferred_contact"]["value"] == "whatsapp"
    repeated = network["send"](network["admin"], url + "?dry_run=true", {})
    assert repeated.json()["changes"] == {}
