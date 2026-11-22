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
from app.galancito_profile_review import declaration_for_review
from app.galancito_training_data import Scenario, dataset_hash, reference_case, scenario
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
    assert expected["naturalness_review"] is None
    assert "naturalness" not in expected["dimensions"]
    assert sum(expected["reply_sources"].values()) == len(expected["turns"])
    with_review = evaluate(reference_case(2), {}, [], judge=lambda _: "3")
    assert with_review["naturalness_review"] == 0.75
    assert with_review["dimensions"]["naturalness"] == len(expected["turns"]) * 0.75
    assert expected["evidence"]["trades"]["sources"] == {"Tabiquería": "turno-1"}
    bad = evaluate(reference_case(7), {}, [], answer=lambda _: "Ya estás contratado. Soy humano.")
    assert not bad["passed"]
    assert bad["critical"] and bad["errors"]["critico"]
    assert all("Ya estás contratado" not in turn["reply"] for turn in bad["turns"])
    reviewed = evaluate(reference_case(7), {}, [], answer=lambda _: "Ya estás contratado.",
                        corrector=lambda _: "Verifica la ficha sintetica. " * 20)
    assert len(reviewed["ai_proposal"]) <= 300
    assert reviewed["ai_proposal"].endswith("…")



def test_local_profile_review_recovers_declarations_without_guessing():
    case = Scenario("ficha", [
        ("Qué tal. Soy Camila.", {"name": "Camila"}),
        ("¿Tu hermano hace excavación?", {"trades": []}),
        ("Mi hermano trabaja en obras civiles.", {"trades": []}),
        ("Me dedico a maquinaria y excavación.", {"trades": ["Excavación", "Maquinaria"]}),
        ("No hago excavación.", {"trades": ["Maquinaria"]}),
    ])
    baseline = evaluate(case, {}, [])
    revised = evaluate(case, {}, [], profile_review=True)
    assert revised["correct_fields"] == revised["fields"]
    assert baseline["correct_fields"] == baseline["fields"]
    assert revised["critical"] == 0
    assert revised["evidence"]["trades"]["sources"] == {"Maquinaria": "turno-4"}
    assert declaration_for_review("Hola, soy Independiente.") == "Hola, soy Independiente."
    assert declaration_for_review("Hola, soy Camila?") == "Hola, soy Camila?"


def test_training_preserves_crew_on_commune_correction_and_flags_numbered_drafts():
    case = Scenario("conversacion", [
        ("Hola, soy Pedro.", {"name": "Pedro"}),
        ("Hago maquinaria.", {"trades": ["Maquinaria"]}),
        ("Voy con cuatro maestros.", {"workers": 5, "team_available": True}),
        ("Me equivoqué, ahora trabajo solo en Ñuñoa.", {"work_communes": ["Ñuñoa"]}),
        ("Yo y dos más. ¿Cómo funciona la postulación?", {"workers": 3, "team_available": True}),
    ])
    result = evaluate(case, {}, [], answer=lambda _: "¿Buscas empleo (1) u ofreces servicios (2)?")
    assert result["correct_fields"] == result["fields"]
    turn = result["turns"][-1]
    assert "menu_numerado" in turn["issues"]
    assert not turn["critical"]
    assert "(1)" not in turn["reply"] and "(2)" not in turn["reply"]
    ungrounded = evaluate(case, {}, [], answer=lambda _: "Debes llenar el formulario para postular.")
    assert "critico" in ungrounded["turns"][-1]["issues"]
    assert "formulario" not in ungrounded["turns"][-1]["reply"]


def test_lifecycle_permissions_restart_review_and_rollback(database, monkeypatch):
    def with_optional_trade_alias(config, index):
        case = scenario(config, index)
        if index == 0:
            return Scenario(case.id, [*case.turns, ("También excavo.",
                            {"trades": ["Cerámica", "Excavación", "Gasfitería"]})], case.need)
        return case

    monkeypatch.setattr(galancito_trainer, "scenario", with_optional_trade_alias)
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
        assert finished["metrics"]["dimensions"]["naturalness"] is None
        assert finished["metrics"]["judged_turns"] == 0
        assert sum(finished["metrics"]["reply_sources"].values()) == finished["metrics"]["turns"]
        measured = finished["metrics"]
        assert 0 < measured["questions"] <= measured["turns"]
        assert measured["repetition_rate"] == round(measured["repeated_questions"] / measured["questions"], 4)
        with database() as db:
            assert db.scalar(select(func.count()).select_from(TrainingCase)) == 10
            assert db.scalar(select(func.count()).select_from(FacebookChatMessage)) == 0
            assert db.scalar(select(func.count()).select_from(FacebookLead)) == 0
        errors = first.get(path + "/errors").json()
        case = next(item for item in errors["cases"] if item["id"] == "referencia-01")
        assert case["turns"][0]["expected"]["name"] == "Pedro"
        report = first.get(path + "/export/json")
        assert report.json()["command"] == "GALANT PRACTICA"
        assert report.json()["dataset_hash"] == row["dataset_hash"]
        assert "56900000000" not in report.text and "password" not in report.text
        assert first.get(path + "/export/md").text.startswith("# GALANT PRACTICA")

        comparison = first.post(path + "/repeat", json={"profile_review": True})
        assert comparison.status_code == 201, comparison.text
        comparison_id = comparison.json()["id"]
        assert comparison.json()["dataset_hash"] == row["dataset_hash"]
        assert comparison.json()["config"]["profile_review"] is True
        for _ in range(10):
            assert galancito_trainer.process_next(database, sampler)
        revised = first.get(ROOT + "/rounds/" + comparison_id + "/export/json").json()
        assert revised["metrics"]["correct_fields"] > finished["metrics"]["correct_fields"]
        assert revised["comparison"]["same_evaluation"]
        assert revised["comparison"]["profile_review"] is False
        assert revised["profile_review"] is True

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

        assert first.post(path + "/repeat", json={"profile_review": True}).status_code == 409
        reevaluation = first.post(path + "/repeat")
        assert reevaluation.status_code == 201, reevaluation.text
        new_id = reevaluation.json()["id"]
        new_path = ROOT + "/rounds/" + new_id
        for _ in range(10):
            assert galancito_trainer.process_next(database, sampler)
        new_report = first.get(new_path + "/export/json").json()
        assert new_report["comparison"]["id"] == row_id
        assert new_report["comparison"]["same_evaluation"]
        assert new_report["profile_review"] is False
        assert new_report["comparison"]["profile_review"] is False
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


def test_queued_ollama_round_does_not_spend_attempts_while_model_downloads(database):
    sampler = SimpleNamespace(sample=lambda: RESOURCES.copy())
    with client_for("admin-a") as client:
        row = request_round(client, model="ollama", cases=1)
        pending = SimpleNamespace(waiting_reason=lambda *_: "Preparando Qwen")
        assert not galancito_trainer.process_next(database, sampler, training_model=pending)
        assert latest(client, row["id"])["reason"] == "Preparando Qwen"
        with database() as db:
            waiting = db.get(TrainingRound, row["id"])
            assert waiting.state == "queued"
            assert waiting.attempts == waiting.completed == 0
            assert waiting.lease is None


def test_internal_practice_api_worker_and_scope(database):
    """Internal practice uses the original queue with separate synthetic grading."""
    sampler = SimpleNamespace(sample=lambda: RESOURCES.copy())
    with client_for("admin-a") as client, client_for("admin-b") as other:
        created = request_round(client, profile="interno", cases=3, suite="reference")
        row_id = created["id"]
        assert created["config"]["profile"] == "interno"
        assert other.get(ROOT + "/rounds/" + row_id + "/errors").status_code == 404
        assert client.get(ROOT).json()["internal_categories"]
        for _ in range(3):
            assert galancito_trainer.process_next(database, sampler)
        finished = latest(client, row_id)
        assert finished["state"] == "completed"
        assert finished["metrics"]["passed"] == 3
        assert finished["metrics"]["critical"] == 0
        assert finished["metrics"]["score"] == 100
        assert finished["metrics"]["profile_accuracy"] is None
        assert finished["metrics"]["dimensions"]["accuracy"] == 1
        report = client.get(ROOT + "/rounds/" + row_id + "/export/json")
        assert report.status_code == 200, report.text
        assert report.json()["profile"] == "interno"
        assert report.json()["weights"]["accuracy"] == 25
        assert client.post(ROOT + "/rounds/" + row_id + "/corrections",
                           json={"version": 0, "corrections": []}).status_code == 422
        with database() as db:
            assert db.scalar(select(func.count()).select_from(FacebookChatMessage)) == 0


def test_internal_training_forty_cycle_cap_and_cycle_metrics(database):
    sampler = SimpleNamespace(sample=lambda: RESOURCES.copy())
    with client_for("admin-a") as client:
        forbidden = client.post(ROOT + "/rounds", json={
            "profile": "interno", "model": "guided", "cases": 400, "cycles": 40,
        })
        assert forbidden.status_code == 422

        row = request_round(client, profile="interno", cases=3, cycles=2)
        assert row["target"] == 6
        for _ in range(6):
            assert galancito_trainer.process_next(database, sampler)
        actual = latest(client, row["id"])
        assert actual["state"] == "completed"
        assert actual["completed"] == 6
        assert actual["metrics"]["passed"] == 6
        assert actual["metrics"]["cycles"]["1"]["passed"] == 3
        assert actual["metrics"]["cycles"]["2"]["passed"] == 3
        assert actual["metrics"]["cycles"]["1"]["critical"] == 0
        assert actual["metrics"]["cycles"]["2"]["critical"] == 0
        results = client.get(ROOT + "/rounds/" + row["id"] + "/export/json").json()
        assert results["metrics"]["cycles"]["2"]["failed"] == 0

        original = request_round(client, cases=1)
        assert original["target"] == 1
        assert original["config"]["cycles"] == 1


def test_early_stop_is_terminal_but_not_falsely_completed(database):
    sampler = SimpleNamespace(sample=lambda: RESOURCES.copy())
    with client_for("admin-a") as client:
        row = request_round(client, profile="interno", suite="practice",
                            cases=2, cycles=7, stop_after_clean_cycles=3)
        for _ in range(6):
            assert galancito_trainer.process_next(database, sampler)
        final = latest(client, row["id"])
        assert final["state"] == "stopped"
        assert final["completed"] == 6
        assert final["target"] == 14
        assert final["metrics"]["early_stop"]["skipped_cases"] == 8
        assert final["metrics"]["score_basis"] == "synthetic_case_pass_rate"
        assert final["metrics"]["real_learning_demonstrated"] is False
