"""No-paid-token curriculum import and 40-epoch offline topic training."""
import json

from sqlalchemy import select, func

from app.ai_models import AIUsage
from app.config import settings
from app.galancito_knowledge_models import Knowledge, KnowledgeVersion
from app.galancito_offline_training import train, features, predict
from test_ai_control_center import ai_env, signin


def test_curriculum_trains_small_local_model_for_40_epochs():
    model, report = train()
    assert report["epochs_completed"] == 40
    assert report["curated_cases"] == 72
    assert report["provider_tokens_used"] == 0
    assert report["api_requests"] == 0
    assert len(report["categories"]) == 7
    assert 0 <= report["holdout_accuracy"] <= 1
    assert 0 <= report["training_accuracy"] <= 1
    assert len(model["weights"]) == 7
    assert not features("x y")
    assert predict(model["weights"], "cómo registrar un contratista nuevo")[0]


def test_admin_activates_curated_knowledge_for_entire_org_without_provider_tokens(
    ai_env, monkeypatch, tmp_path
):
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path / "curriculum-private"))
    settings.cache_clear()
    try:
        client = ai_env["client"]
        headers = signin(client)
        endpoint = "/api/v1/network/galancito/knowledge-curriculum"
        result = client.post(endpoint, headers=headers)
        assert result.status_code == 201, result.text
        assert result.json()["created"] == 102
        assert result.json()["training_epochs"] == 40
        assert result.json()["external_api_calls"] == 0
        assert result.json()["holdout_accuracy"] is not None
        model_path = tmp_path / "curriculum-private" / "galancito-topic-model.json"
        model = json.loads(model_path.read_text())
        assert model["report"]["epochs_completed"] == 40

        repeated = client.post(endpoint, headers=headers)
        assert repeated.status_code == 201
        assert repeated.json()["created"] == 0
        assert repeated.json()["already_present"] == 102

        with ai_env["sessions"]() as db:
            rows = list(db.scalars(select(Knowledge).where(
                Knowledge.org_id == ai_env["org_id"])))
            assert len(rows) == 102
            assert all(r.status == "approved" and r.approved_by for r in rows)
            assert db.scalar(select(func.count(KnowledgeVersion.id))) == 102
            assert db.scalar(select(func.count(AIUsage.id))) == 0

        signin(client, "resident")
        resident = client.get("/api/v1/network/galancito/status")
        assert resident.status_code == 200
        no_install = client.post(
            endpoint, headers={"X-CSRF-Token": client.cookies["galant_post_csrf"]})
        assert no_install.status_code == 403
        signin(client, "outside")
        assert client.get("/api/v1/network/galancito/knowledge").json() == []
    finally:
        settings.cache_clear()


def test_second_round_privacy_and_progress(ai_env, monkeypatch, tmp_path):
    from app.galancito_learning_progress import curriculum
    from app.galancito_contractor_conversation import (
        employer_question, protect_outgoing, known_from_history, contractor_followup,
    )
    first, second = curriculum()
    assert len(first) == 72 and len(second) == 30
    assert employer_question("¿Para qué empresa es el trabajo?")
    assert "constructora ejemplo" not in protect_outgoing("El mandante es Constructora Ejemplo").lower()
    known = known_from_history(["tengo una empresa de pintura", "tengo 4 trabajadores"])
    reply = contractor_followup("somos de Coronel", known)
    assert "disponibilidad" in reply.lower()

    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path / "private"))
    settings.cache_clear()
    try:
        client = ai_env["client"]
        headers = signin(client)
        before = client.get("/api/v1/admin/ai/bootstrap").json()["galancito_progress"]
        assert before["knowledge"]["percent"] == 0
        assert before["round2"]["percent"] == 0
        assert before["conversation_tests"]["total"] >= 20
        assert before["privacy_tests"]["percent"] == 100
        r = client.post("/api/v1/network/galancito/knowledge-curriculum", headers=headers)
        assert r.status_code == 201, r.text
        assert r.json()["created"] == 102
        after = client.get("/api/v1/admin/ai/bootstrap").json()["galancito_progress"]
        assert after["knowledge"]["percent"] == 100
        assert after["round2"]["percent"] == 100
        assert after["conversation_tests"]["percent"] == 100
        assert after["external_api_calls"] == 0
        signin(client, "outside")
        assert client.get("/api/v1/admin/ai/bootstrap").json()["galancito_progress"]["knowledge"]["percent"] == 0
    finally:
        settings.cache_clear()
