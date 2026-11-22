"""Real-data learning tests: SQL provenance, privacy, scoring, and no fake pass."""

import json
from sqlalchemy import select

from test_network import network, request_body
from app.models import User
from app.galancito_real_learning import collect_live_cases, evaluate_live, live_hash


def test_real_cases_are_derived_from_actual_authorized_sql_and_hide_names(network):
    fixture = network
    with fixture["Session"].begin() as db:
        user = db.scalar(select(User).where(User.email == "admin@network.example.cl"))
        cases = collect_live_cases(db, user)
    assert len(cases) == 24
    assert all(c["source"] == "db_aggregate" for c in cases)
    assert all(c["evidence_hash"] and c["recorded_at"] for c in cases)
    assert cases[0]["expected"] == 2  # Two actual contractor associations per site.
    raw = json.dumps(cases, ensure_ascii=False)
    assert "Brisas de Junquillar" not in raw
    assert "Carpintería A" not in raw
    assert "76123456" not in raw
    assert "admin@network" not in raw
    assert "Obra autorizada 1" in raw

    with fixture["Session"].begin() as db:
        user = db.scalar(select(User).where(User.email == "admin@network.example.cl"))
        first_hash = live_hash({"level": 1, "cases": 4, "cycles": 3, "live_cases": cases})
        again = collect_live_cases(db, user)
        assert again[0]["expected"] == cases[0]["expected"]
        assert first_hash != live_hash({"level": 1, "cases": 4, "cycles": 3, "live_cases": [
            {**cases[0], "expected": 991}
        ]})


def test_real_evaluator_uses_actual_observations_and_fails_incorrect_answer(network):
    fixture = network
    with fixture["Session"].begin() as db:
        admin = db.scalar(select(User).where(User.email == "admin@network.example.cl"))
        case = collect_live_cases(db, admin)[0]

    captured = []
    def correct(context, instructions):
        captured.append(json.loads(context))
        return f"Resultado: {case['expected']}\nExplicación: Son asociaciones activas de contratistas registradas en la obra."

    passed = evaluate_live(case, answer=correct)
    assert passed["passed"]
    assert passed["evidence"]["source"] == "db_aggregate"
    assert passed["evidence"]["verified"] is True
    assert passed["reply_sources"] == {"model": 1}
    assert captured[0]["evidencia"]["agregados_reales"]["contratistas_asociados_activos"] == case["expected"]
    assert "required" not in captured[0] and "expected" not in captured[0]

    failed = evaluate_live(case, answer=lambda *_: "Resultado: 999\nExplicación: Conteo de registros en esta obra.")
    assert not failed["passed"]
    assert failed["errors"].get("accuracy") == 1
    assert failed["turns"][0]["differences"]["resultado"] == 999


def test_real_evaluator_rejects_unstructured_and_unsafe_invented_actions(network):
    fixture = network
    with fixture["Session"].begin() as db:
        admin = db.scalar(select(User).where(User.email == "admin@network.example.cl"))
        case = collect_live_cases(db, admin)[1]

    missing = evaluate_live(case, answer=lambda *_: "Todo está correcto y mejorando un 100%.")
    assert not missing["passed"]
    assert missing["errors"].get("accuracy") == 1

    unsafe = evaluate_live(case, answer=lambda *_: (
        f"Resultado: {case['expected']}\nExplicación: Ya modifiqué registros de esta obra."
    ))
    assert not unsafe["passed"]
    assert unsafe["critical"] == 1


def test_live_endpoint_disallows_rule_only_improvement(network):
    admin = network["admin"]
    csrf = {"X-CSRF-Token": admin.cookies.get("galant_post_csrf", "")}
    response = admin.post("/api/v1/admin/ai/training/rounds", headers=csrf,
                          json={"profile": "interno", "suite": "live",
                                "cases": 4, "cycles": 3, "model": "guided"})
    assert response.status_code == 422, response.text
    response = admin.post("/api/v1/admin/ai/training/rounds", headers=csrf,
                          json={"profile": "postulantes", "suite": "live", "cases": 4,
                                "cycles": 3, "model": "ollama"})
    assert response.status_code == 422, response.text


def test_paired_holdout_reports_statistical_evidence_without_inventing_learning():
    from app.galancito_real_learning import paired_holdout_metrics
    small = paired_holdout_metrics([False, True, True, True],
                                   [True, True, True, True])
    assert small["gain_cases"] == 1
    assert small["regressions"] == 0
    assert small["paired_cases"] == 4
    assert small["one_sided_p_value"] == 0.5  # One win does not prove learning.

    strong = paired_holdout_metrics([False] * 6 + [True] * 2,
                                    [True] * 8)
    assert strong["gain_cases"] == 6
    assert strong["paired_cases"] == 8
    assert strong["one_sided_p_value"] == 0.015625
    weak = paired_holdout_metrics([True] * 8, [True] * 8)
    assert weak["one_sided_p_value"] == 1.0
    regressed = paired_holdout_metrics([False, True, False],
                                       [True, False, False])
    assert regressed["gain_cases"] == 1 and regressed["regressions"] == 1
    assert regressed["one_sided_p_value"] == 0.75
