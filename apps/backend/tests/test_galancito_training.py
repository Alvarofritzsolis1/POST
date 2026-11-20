"""Acceptance checks for Galancito Evolution in SQLite or a real QA PostgreSQL."""
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app import galancito_trainer
from app.config import settings
from app.db import Base, get_db
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_training import eligible_at
from app.galancito_training_data import dataset_hash, reference_case, scenario
from app.galancito_training_eval import evaluate
from app.galancito_training_models import TrainingCase, TrainingRound
from app.main import app
from app.migrations.galancito_training import upgrade
from app.models import AuditEvent, Organization, User, utcnow
from app.security import hash_password

ROOT = "/api/v1/admin/ai/training"
PASSWORD = "Synthetic-Training-test-password"
RESOURCES = {
    "available_ram_mb": 7000, "worker_ram_mb": 80, "worker_ram_limit_mb": 384,
    "host_cpu_percent": 10, "disk_free_mb": 20000, "worker_cores": 2,
}
PG = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=pytest.mark.skipif(not PG, reason="Requiere PostgreSQL"))])
def database(request, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET", "isolated-galancito-training-test-only-" * 2)
    settings.cache_clear()
    admin_engine = None
    if request.param == "postgresql":
        schema = "galancito_train_qa_" + uuid4().hex
        admin_engine = create_engine(PG)
        with admin_engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(PG, connect_args={"options": "-csearch_path=" + schema})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'qa.sqlite'}")

    existing = [t for t in Base.metadata.sorted_tables if not t.name.startswith("galancito_training_")]
    Base.metadata.create_all(engine, tables=existing)
    with engine.begin() as conn:
        upgrade(conn)
        upgrade(conn)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        orgs = [Organization(name="Laboratorio A"), Organization(name="Laboratorio B")]
        db.add_all(orgs)
        db.flush()
        for name, role, org in (("admin-a", "admin", orgs[0]), ("admin-b", "admin", orgs[1]),
                                ("reader-a", "administrative", orgs[0])):
            db.add(User(org_id=org.id, email=name + "@example.test", role=role,
                        password_hash=hash_password(PASSWORD)))

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        yield sessions
    finally:
        app.dependency_overrides.pop(get_db, None)
        settings.cache_clear()
        engine.dispose()
        if admin_engine:
            with admin_engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin_engine.dispose()


def client_for(name):
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"email": name + "@example.test", "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies["galant_post_csrf"]
    return client


def request_round(client, **changes):
    response = client.post(ROOT + "/rounds", json={
        "model": "guided", "cases": 10, "concurrency": 1, **changes,
    })
    assert response.status_code == 201, response.text
    return response.json()


def latest(client, row_id):
    return next(row for row in client.get(ROOT).json()["rounds"] if row["id"] == row_id)


def test_scenarios_distinct_and_night_opening_in_chile():
    count = 2000
    config = {"level": 3, "suite": "practice", "seed": 155, "cases": count}
    cases = [scenario(config, index) for index in range(count)]
    sets = {tuple(message for message, _ in case.turns) for case in cases}
    assert len(sets) == count
    holdout = {tuple(message for message, _ in scenario({**config, "suite": "holdout"}, i).turns)
               for i in range(count)}
    assert sets.isdisjoint(holdout)
    assert cases == [scenario(config, index) for index in range(count)]
    assert dataset_hash(config) != dataset_hash({**config, "suite": "holdout"})
    assert dataset_hash(config) == dataset_hash(config.copy())
    config = {"night": True, "night_start": 23, "night_end": 7}
    daytime = datetime(2026, 11, 20, 18, tzinfo=timezone.utc)
    assert eligible_at(config, daytime) == datetime(2026, 11, 21, 2, tzinfo=timezone.utc)
    inside = datetime(2026, 6, 4, 3, tzinfo=timezone.utc)
    assert eligible_at(config, inside) == inside


def test_verifiable_profile_and_critical_draft():
    expected = evaluate(reference_case(2), {}, [])
    assert expected["fields"] > 0
    assert expected["correct_fields"] == expected["fields"]
    assert expected["evidence"]["trades"]["sources"] == {"Tabiquería": "turno-1"}
    bad = evaluate(reference_case(7), {}, [], answer=lambda _: "Ya estás contratado. Soy humano.")
    assert not bad["passed"]
    assert bad["critical"] and bad["errors"]["critico"]
    assert all("Ya estás contratado" not in turn["reply"] for turn in bad["turns"])
    reviewed = evaluate(reference_case(0), {}, [], corrector=lambda _: "Verifica la ficha sintetica. " * 20)
    assert len(reviewed["ai_proposal"]) <= 300
    assert reviewed["ai_proposal"].endswith("…")



def test_lifecycle_permissions_restart_review_and_rollback(database):
    sampler = SimpleNamespace(sample=lambda: RESOURCES.copy())
    with client_for("admin-a") as first, client_for("admin-b") as other, client_for("reader-a") as reader:
        assert reader.get(ROOT).status_code == 403
        assert reader.post(ROOT + "/rounds", json={}).status_code == 403
        row = request_round(first)
        row_id = row["id"]
        path = ROOT + "/rounds/" + row_id
        assert first.post(ROOT + "/rounds", json={"model": "guided"}).status_code == 409
        assert other.get(path + "/errors").status_code == 404
        assert other.post(path + "/control/stop").status_code == 404
        assert other.get(path + "/export/json").status_code == 404
        assert other.get(ROOT).json()["rounds"] == []
        assert first.post(path + "/control/pause").json()["state"] == "paused"
        assert not galancito_trainer.process_next(database, sampler)
        assert latest(first, row_id)["completed"] == 0
        assert first.post(path + "/control/resume").json()["state"] == "queued"
        # Closing browser then losing a worker after claiming the next case.
        assert galancito_trainer.process_next(database, sampler)
        with galancito_trainer.worker_lock(database):
            pending, _ = galancito_trainer.claim(database, sampler.sample())
        assert pending.completed == 1
        if database.kw["bind"].dialect.name != "postgresql":
            with database.begin() as db:
                db.get(TrainingRound, row_id).lease_until = utcnow() - timedelta(seconds=1)
        for _ in range(9):
            assert galancito_trainer.process_next(database, sampler)
        finished = latest(first, row_id)
        assert finished["state"] == "completed" and finished["completed"] == 10
        assert finished["metrics"]["profile_accuracy"] is not None
        assert finished["metrics"]["failed"] > 0 and finished["metrics"]["passed"] > 0
        assert finished["metrics"]["input_tokens"] == 0
        with database() as db:
            assert db.scalar(select(func.count()).select_from(TrainingCase)) == 10
            assert db.scalar(select(func.count()).select_from(FacebookChatMessage)) == 0
            assert db.scalar(select(func.count()).select_from(FacebookLead)) == 0
        errors = first.get(path + "/errors").json()
        case = next(item for item in errors["cases"] if item["id"] == "referencia-01")
        assert case["turns"][0]["expected"]["name"] == "Pedro"
        report = first.get(path + "/export/json")
        assert report.json()["command"] == "GALANCITO PRACTICA"
        assert report.json()["dataset_hash"] == row["dataset_hash"]
        assert "56900000000" not in report.text and "password" not in report.text
        assert first.get(path + "/export/md").text.startswith("# GALANCITO PRACTICA")

        corrections = {
            "version": 0, "corrections": [{"case_id": case["id"], "turn": 1,
                "reply": "Hola, Pedro. ¿Qué oficio tienes?", "instruction": "Saluda a la persona por su nombre declarado."}],
        }
        result = first.post(path + "/corrections", json=corrections)
        assert result.status_code == 201, result.text
        assert result.json()["version"] == 1
        assert first.post(path + "/corrections", json=corrections).status_code == 409
        datasets = [first.get(ROOT + "/knowledge/dataset/" + split).text
                    for split in ("train", "validation", "test")]
        assert sum(item.count("Pedro.") for item in datasets) == 2
        assert all(first.get(k).json() == [] for k in ("/api/v1/network/galancito/knowledge",))

        reevaluation = first.post(path + "/repeat")
        assert reevaluation.status_code == 201, reevaluation.text
        new_id = reevaluation.json()["id"]
        new_path = ROOT + "/rounds/" + new_id
        for _ in range(10):
            assert galancito_trainer.process_next(database, sampler)
        new_report = first.get(new_path + "/export/json").json()
        assert new_report["comparison"]["id"] == row_id
        assert new_report["approved_corrections"] == 1
        assert new_report["dataset_hash"] == row["dataset_hash"]
        assert first.post(ROOT + "/knowledge/rollback", json={"version": 1, "restore_version": 0}).json()["version"] == 2
        assert first.get(ROOT).json()["knowledge"]["corrections"] == []
        assert other.get(ROOT).json()["knowledge"]["version"] == 0
        with database() as db:
            assert db.scalar(select(func.count()).select_from(AuditEvent)
                             .where(AuditEvent.action == "ai.training.rollback")) == 1


def test_resource_pressure_messenger_priority_and_budget(database, monkeypatch):
    sampler = SimpleNamespace(sample=lambda: RESOURCES.copy())
    with client_for("admin-a") as client:
        queued = request_round(client, model="ollama", judge="ollama", cases=2, token_budget=1)
        path = ROOT + "/rounds/" + queued["id"]
        with database.begin() as db:
            row = db.get(TrainingRound, queued["id"])
            lead = FacebookLead(org_id=row.org_id, page_id="synthetic", psid="synthetic")
            db.add(lead)
            db.flush()
            db.add(FacebookChatMessage(org_id=row.org_id, lead_id=lead.id, page_id="synthetic",
                                       direction="outbound", state="pending", body="NO LEER"))
        assert not galancito_trainer.process_next(database, sampler)
        assert latest(client, queued["id"])["reason"] == "Messenger tiene prioridad"
        with database.begin() as db:
            db.scalar(select(FacebookChatMessage)).state = "sent"
            db.get(TrainingRound, queued["id"]).next_at = utcnow()
        under_pressure = SimpleNamespace(sample=lambda: {**RESOURCES, "available_ram_mb": 1900})
        assert not galancito_trainer.process_next(database, under_pressure)
        assert "reserva de RAM" in latest(client, queued["id"])["reason"]
        with database.begin() as db:
            db.get(TrainingRound, queued["id"]).next_at = utcnow()
        monkeypatch.setattr(galancito_trainer, "generate_training_text",
                            lambda *_: pytest.fail("El presupuesto no autoriza ninguna llamada"))
        assert galancito_trainer.process_next(database, sampler)
        result = latest(client, queued["id"])
        assert result["state"] == "completed" and result["completed"] == 0
        assert "presupuesto de tokens" in result["reason"]
        assert client.post(path + "/control/stop").status_code == 409
