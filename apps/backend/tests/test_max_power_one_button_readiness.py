"""One-button readiness must not depend on Messenger production model flags."""
from app import max_power_worker as worker
from app import max_power_messenger as messenger
from app.config import Settings
from app.galancito_model_config import QWEN_2B


def test_max_power_isolated_2b_is_independent_of_production_settings(monkeypatch):
    production = Settings(galancito_local_ai_enabled=False,
                          galancito_local_model="qwen3:1.7b")
    monkeypatch.setattr(messenger, "settings", lambda: production)
    lab = messenger.isolated_qwen_config()
    assert lab.galancito_local_model == QWEN_2B
    assert production.galancito_local_ai_enabled is False
    assert production.galancito_local_model == QWEN_2B


def test_one_button_prepares_model_and_protects_messenger_resources(monkeypatch):
    monkeypatch.setattr(worker, "MAX_POWER_ISOLATED", True)
    calls = []
    class FakeTrainingModel:
        def __init__(self, reason=None):
            self.reason = reason
        def waiting_reason(self, disk, model):
            calls.append((disk, model))
            return self.reason
    good = {"available_ram_mb": 9400, "disk_free_mb": 80000}
    assert worker.isolated_qwen_ready(good, FakeTrainingModel()) is True
    assert calls == [(80000, QWEN_2B)]
    assert worker.isolated_qwen_ready(good, FakeTrainingModel("Descarga pendiente")) is False
    assert worker.isolated_qwen_ready({"available_ram_mb": 3000, "disk_free_mb": 80000},
                                      FakeTrainingModel()) is False
    assert len(calls) == 2
    monkeypatch.setattr(worker, "MAX_POWER_ISOLATED", False)
    assert worker.isolated_qwen_ready(good, FakeTrainingModel()) is False


def test_no_fabricated_consent_or_production_promotions_in_one_button_lab():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    cpu = (repo / "scripts" / "train_galancito_cpu_lora.py").read_text(encoding="utf-8")
    assert "synthetic_development_adapter_not_for_production" in cpu
    assert '"production_promoted":False' in cpu
    assert "GALANT_SYNTHETIC_DEV_TRAINING" in cpu
    assert "verified_optimizer_update(" in cpu


def test_training_state_requires_fresh_real_optimizer_evidence(tmp_path):
    import sys
    import json
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts))
    import max_power_cpu_manager as cpu
    run = tmp_path / "run"
    run.mkdir()
    journal = run / "training-metrics.jsonl"
    old = {"kind": "metric", "data_kind": "curated_synthetic", "step": 2}
    journal.write_text(json.dumps(old) + "\n", encoding="utf-8")
    offset = journal.stat().st_size
    assert cpu.newly_recorded_optimizer_step(run, offset) is False
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "start", "data_kind": "curated_synthetic", "step": 0}) + "\n")
        f.write(json.dumps({"kind": "metric", "data_kind": "human_reviewed_real", "step": 3}) + "\n")
    assert cpu.newly_recorded_optimizer_step(run, offset) is False
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "metric", "data_kind": "curated_synthetic", "step": 3}) + "\n")
    assert cpu.newly_recorded_optimizer_step(run, offset) is True
    journal.unlink()
    journal.symlink_to(tmp_path / "external")
    assert cpu.newly_recorded_optimizer_step(run, offset) is False
