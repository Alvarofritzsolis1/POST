"""Regression tests: internal Galancito training cannot claim production data."""
from app.galancito_internal_training import (
    INTERNAL_CATEGORIES, INTERNAL_WEIGHTS, InternalCase, evaluate_internal,
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


def test_internal_dataset_hash_includes_cycle_plan():
    assert internal_dataset_hash(config(cycles=1)) != internal_dataset_hash(config(cycles=40))
    configs = config(cases=4, cycles=2)
    examples = [internal_case(configs, pos) for pos in range(8)]
    assert len({example.id for example in examples}) == 8
    assert examples[0].id.startswith("interno-reference-c01")
    assert examples[4].id.startswith("interno-reference-c02")
    assert all(evaluate_internal(item)["passed"] for item in examples)


def _count_case(number: int) -> InternalCase:
    import json
    return InternalCase(
        id="synthetic-count-unit", category="contratistas",
        question="¿Cuántos contratistas hay en Obra Demo 57?",
        context=json.dumps({"status": "ok", "tool": "contractors",
                            "data": {"contratistas_activos": str(number)}}),
        required=(str(number),), baseline=f"Hay {number} contratistas activos.",
        status="ok", tool="contractors",
    )


def test_count_word_equivalence_requires_correct_quantity_and_noun():
    one = _count_case(1)
    assert evaluate_internal(one, answer=lambda _: "Hay un contratista activo.")["passed"]
    assert not evaluate_internal(one, answer=lambda _: "Hay una persona registrada.")["passed"]
    assert evaluate_internal(one, answer=lambda _: "Hay 1 contratista activo.")["passed"]
    twelve = _count_case(12)
    assert evaluate_internal(twelve, answer=lambda _: "Hay doce contratistas activos.")["passed"]
    assert not evaluate_internal(one, answer=lambda _: "Hay doce contratistas activos.")["passed"]
    assert not evaluate_internal(one, answer=lambda _: "Hay un ejemplo y ningún contratista.")["passed"]
    assert not evaluate_internal(one, answer=lambda _: "Hay un contratista y 999 adicionales.")["passed"]


def test_internal_disclaimer_does_not_get_credit_for_usefulness():
    case = _count_case(1)
    report = evaluate_internal(case, answer=lambda _: (
        "No tengo acceso a GALANT real y no puedo revisar esta obra simulada."
    ))
    assert not report["passed"]
    assert report["turns"][0]["checks"]["usefulness"] is False
    assert report["turns"][0]["inference_ms"] >= 0
    assert report["evidence"]["evaluation"] == "partial_deterministic_rules"


def test_internal_category_focus_is_isolated_from_reference_bank():
    focused = config(cases=4, cycles=3, focus_categories=["seguimiento", "contratistas"])
    cases = [internal_case(focused, index) for index in range(12)]
    assert {case.category for case in cases} == {"seguimiento", "contratistas"}
    assert internal_dataset_hash(focused) != internal_dataset_hash(config(cases=4, cycles=3))
    assert len({case.id for case in cases}) == 12
    assert all(evaluate_internal(case)["passed"] for case in cases)


def test_internal_focus_validation_and_threads_are_bounded():
    import pytest
    from pydantic import ValidationError
    from app.galancito_training_api import RoundInput
    from app.galancito_trainer import practice_threads

    assert RoundInput(profile="interno", focus_categories=["seguimiento"]).focus_categories == ["seguimiento"]
    for invalid in (
        {"profile": "interno", "focus_categories": ["unknown"]},
        {"profile": "interno", "focus_categories": ["seguimiento", "seguimiento"]},
        {"profile": "postulantes", "focus_categories": ["seguimiento"]},
        {"profile": "interno", "suite": "live", "focus_categories": ["seguimiento"]},
    ):
        with pytest.raises(ValidationError):
            RoundInput(**invalid)
    assert practice_threads({"worker_cores": 1}) == 1
    assert practice_threads({"worker_cores": 2}) == 2
    assert practice_threads({"worker_cores": 1.5}) == 2
    assert practice_threads({"worker_cores": 0.5}) == 1
    assert practice_threads({"worker_cores": 2.4}) == 3
    assert practice_threads({"worker_cores": 8}) == 4
    assert practice_threads({"worker_cores": None}) == 1


def test_synthetic_coaching_is_applied_only_to_practice_not_real_learning():
    from app.galancito_internal_training import (
        INTERNAL_PROMPT, propose_synthetic_coaching, synthetic_practice_prompt,
    )
    selected = propose_synthetic_coaching({"contexto": 2, "exactitud": 4, "herramienta": 3})
    assert selected == ["exactitud", "herramienta", "contexto"]
    coached = synthetic_practice_prompt("practice", selected)
    assert "Correcciones de ciclos sintéticos previos" in coached
    assert "Fundamenta cifras" in coached
    assert synthetic_practice_prompt("reference", selected) == INTERNAL_PROMPT
    assert synthetic_practice_prompt("holdout", selected) == INTERNAL_PROMPT
    assert synthetic_practice_prompt("live", selected) == INTERNAL_PROMPT
    assert propose_synthetic_coaching({"inventado": 99}, []) == []


def test_clean_synthetic_practice_can_end_early_but_not_holdout():
    from app.galancito_internal_training import clean_synthetic_streak
    clean = {
        "1": {"passed": 4, "failed": 0},
        "2": {"passed": 4, "failed": 0},
        "3": {"passed": 4, "failed": 0},
    }
    assert not clean_synthetic_streak(clean, 2, 3)
    assert clean_synthetic_streak(clean, 3, 3)
    assert not clean_synthetic_streak(clean, 3, 0)
    assert not clean_synthetic_streak({**clean, "2": {"passed": 3, "failed": 1}}, 3, 3)
    from app.galancito_training_api import RoundInput
    from pydantic import ValidationError
    import pytest
    assert RoundInput(profile="interno", suite="practice").stop_after_clean_cycles == 3
    with pytest.raises(ValidationError):
        RoundInput(profile="interno", stop_after_clean_cycles=1)


def test_real_latency_percentiles_use_samples_not_estimates():
    from app.galancito_training import inference_percentile_ms, summarize
    assert inference_percentile_ms([90, 20, 10, 50, 30], 0.5) == 30
    assert inference_percentile_ms([90, 20, 10, 50, 30], 0.95) == 90
    assert inference_percentile_ms([], 0.95) is None
    summary = summarize({"turns": 5, "passed": 2, "failed": 3,
                         "inference_samples_ms": [90, 20, 10, 50, 30]}, "interno")
    assert summary["inference_p50_ms"] == 30
    assert summary["inference_p95_ms"] == 90
    assert summary["inference_samples"] == 5
