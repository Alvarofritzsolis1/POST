"""Regression: per-requirement candidate search, access control and durable follow-up."""
from datetime import date
from app.facebook_crm_models import FacebookLead, FacebookLeadTrade
from app.network_models import NetworkCandidateFollowUp
from app.ops_models import Worksite
from test_network import network, request_body


def _lead(n, **overrides):
    with n["Session"].begin() as db:
        org_id = db.get(Worksite, n["sites"][0]).org_id
        props = {
            "org_id": org_id, "page_id": "test-page", "psid": "profile-1001",
            "display_name": "María Prueba", "specialty": "Carpintería",
            "specialty_source": "message", "workers": 4,
            "availability": str(date.today().replace(year=2099)),
            "interest_type": "service_offer", "work_area": "Coronel",
        }
        props.update(overrides)
        lead = FacebookLead(**props)
        db.add(lead)
        db.flush()
        db.add(FacebookLeadTrade(org_id=org_id, lead_id=lead.id,
                                 trade="Carpintería", source="message"))
        return lead.id


def test_scoped_candidate_workspace_and_follow_up(network):
    n = network
    requirement = n["send"](n["a"], "/requirements", request_body(n)).json()
    lead_id = _lead(n, availability=requirement["start_date"])
    path = "/requirements/" + requirement["id"] + "/candidates"
    read = n["send"](n["a"], path, method="GET")
    assert read.status_code == 200, read.text
    row = next(row for row in read.json()["candidates"] if row["id"] == lead_id)
    assert row["fit"]["compatibility"] == 100
    assert row["fit"]["data_coverage"] == 100
    assert row["tracking"]["stage"] == "suggested"
    assert read.json()["summary"]["interested"] == 0
    assert n["send"](n["b"], path, method="GET").status_code == 403

    save_path = path + "/" + lead_id + "/follow-up"
    saved = n["send"](n["a"], save_path, {
        "stage": "interested", "note": "Interés confirmado por revisión humana",
        "follow_up_on": requirement["start_date"], "version": 0,
    }, method="PUT")
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert n["send"](n["a"], save_path, {
        "stage": "selected", "note": "", "version": 0,
    }, method="PUT").status_code == 409
    assert n["send"](n["b"], save_path, {
        "stage": "selected", "note": "", "version": 1,
    }, method="PUT").status_code == 403
    reread = n["send"](n["a"], path, method="GET").json()
    assert reread["summary"]["interested"] == 1
    assert reread["candidates"][0]["tracking"]["note"].startswith("Interés")
    with n["Session"]() as db:
        stored = db.query(NetworkCandidateFollowUp).filter_by(
            requirement_id=requirement["id"], lead_id=lead_id
        ).one()
        assert stored.stage == "interested"


def test_worksite_specialty_conflict_is_advisory_only(network):
    n = network
    req_body = request_body(n)
    req_body["specialty"] = "Electricidad"
    req_body["title"] = "Se necesita gasfiter"
    requirement = n["send"](n["a"], "/requirements", req_body).json()
    result = n["send"](n["a"],
                       "/requirements/" + requirement["id"] + "/candidates",
                       method="GET")
    assert result.status_code == 200, result.text
    assert result.json()["classification_warning"]
    original = n["send"](n["a"],
                         "/requirements/" + requirement["id"],
                         method="GET").json()
    assert original["specialty"] == "Electricidad"


def test_original_network_migration_cannot_create_new_candidate_table():
    """0.7 must not try to create the candidate foreign key before Facebook CRM."""
    from app.migrations.v0_7_0 import LEGACY_NETWORK_TABLES

    assert "network_requirements" in LEGACY_NETWORK_TABLES
    assert "network_candidate_followups" not in LEGACY_NETWORK_TABLES
    assert "network_facebook_posts" not in LEGACY_NETWORK_TABLES
