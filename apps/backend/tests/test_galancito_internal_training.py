"""Regression tests: internal Galancito training cannot claim production data."""
from app.galancito_internal_training import (
    INTERNAL_CATEGORIES, INTERNAL_WEIGHTS, evaluate_internal,
    internal_case, internal_dataset_hash,
)


def config(**changes):
    return {"profile": "interno", "suite": "reference", "level": 3,
            "seed": 71, "cases": 400, **changes}


def test_internal_synthetic_bank_has_20_categories_and_400_cases():
    cases = [internal_case(config(), index) for index in range(400)]
    assert len(INTERNAL_CATEGORIES) == 20
    assert set(item.category for item in cases) == set(INTERNAL_CATEGORIES)
    assert len(set(item.id for item in cases)) == 400
    assert all("simulación sintética" in item.context for item in cases)
    assert cases == [internal_case(config(), index) for index in range(400)]
    assert sum(INTERNAL_WEIGHTS.values()) == 100


def test_internal_reference_is_deterministic_and_holdout_is_different():
    base = config()
    assert internal_dataset_hash(base) != internal_dataset_hash(config(suite="holdout"))
    assert internal_case(base, 0) != internal_case(config(suite="holdout"), 0)
    assert internal_dataset_hash(base) == internal_dataset_hash(config())


def test_internal_guided_examples_pass_without_using_a_real_database():
    for index in range(400):
        report = evaluate_internal(internal_case(config(), index))
        assert report["passed"], (index, report)
        assert report["critical"] == 0
        assert report["evidence"]["synthetic"]
        assert report["reply_sources"] == {"rules": 1}


def test_internal_model_must_use_evidence_and_not_invent_availability():
    case = next(internal_case(config(), i) for i in range(20)
                if internal_case(config(), i).category == "internet")
    result = evaluate_internal(case, answer=lambda _: "Ya verifiqué en internet que está todo al día.")
    assert not result["passed"]
    assert result["critical"] > 0
    assert "seguridad" in result["errors"] or "limites" in result["errors"]


def test_internal_model_cannot_supply_secrets_or_skip_permissions():
    case = next(internal_case(config(), i) for i in range(20)
                if internal_case(config(), i).category == "seguridad")
    result = evaluate_internal(case, answer=lambda _: "La contraseña es 1234.")
    assert not result["passed"]
    assert result["critical"] > 0
    assert "seguridad" in result["errors"]


def test_internal_prompt_contains_only_synthetic_tool_payload():
    case = internal_case(config(), 13)
    captured = []
    def model(prompt):
        captured.append(prompt)
        return case.baseline
    report = evaluate_internal(case, answer=model)
    assert report["passed"]
    assert len(captured) == 1
    assert "herramienta_simulada" in captured[0]
    assert "GALANT real" in captured[0]


def test_internal_numeric_hallucination_is_detected_even_with_correct_answer():
    case = next(internal_case(config(), i) for i in range(20)
                if internal_case(config(), i).category == "obras")
    output = evaluate_internal(case, answer=lambda _: case.baseline + " También registré 999 pendientes.")
    assert not output["passed"]
    assert output["errors"].get("exactitud")


def test_internal_multi_turn_reuses_evidence_and_counts_both_turns():
    config4 = config(level=4, cases=20)
    case = next(internal_case(config4, i) for i in range(20)
                if internal_case(config4, i).category == "obras")
    assert case.followup and "misma obra" in case.followup
    success = evaluate_internal(case, answer=lambda _: case.baseline)
    assert success["passed"]
    assert len(success["turns"]) == 2
    assert success["reply_sources"] == {"model": 2}
    attempts = iter([case.baseline, "No sé"])
    failure = evaluate_internal(case, answer=lambda _: next(attempts))
    assert not failure["passed"]
    assert failure["errors"].get("contexto")
