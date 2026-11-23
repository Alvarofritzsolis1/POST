"""No GPU required: durable metric journal and truthful progress semantics."""
import json
from pathlib import Path
import runpy
import sys
from uuid import uuid4
import pytest

SCRIPTS=Path(__file__).resolve().parents[3]/"scripts"
sys.path.insert(0,str(SCRIPTS))
from galancito_lora_progress import ProgressReporter


def test_real_metric_journal_is_append_only_and_resumable(tmp_path):
    run=str(uuid4())
    reporter=ProgressReporter(tmp_path,run_id=run,org_id=None,dataset_sha256="a"*64)
    row=reporter.emit("metric",step=2,total_steps=10,epoch=0.25,loss=1.32,
                      gpu_memory_mb=8430,private_message="NEVER EXPORTED")
    assert row["sequence"]==1
    assert "private_message" not in row
    assert "train_samples_per_second" not in row
    assert row["loss"]==1.32
    assert row["weights_trained"] is False
    reporter.close()
    restored=ProgressReporter(tmp_path,run_id=run,org_id=None,dataset_sha256="a"*64)
    final=restored.emit("finished",step=10,total_steps=10,
                         holdout_loss_before=2.3,holdout_loss_after=1.4,
                         weights_trained=True,candidate_accepted=False)
    restored.close()
    assert final["sequence"]==2
    history=[json.loads(x) for x in (tmp_path/"training-metrics.jsonl").read_text().splitlines()]
    assert len(history)==2
    assert all("private_message" not in item for item in history)
    with pytest.raises(ValueError,match="incompatible"):
        ProgressReporter(tmp_path,run_id=str(uuid4()),org_id=None,dataset_sha256="a"*64)


def test_remote_telemetry_requires_https_scoped_credentials(tmp_path):
    with pytest.raises(ValueError,match="requiere"):
        ProgressReporter(tmp_path,run_id=str(uuid4()),org_id=str(uuid4()),
                         dataset_sha256="a"*64,telemetry_url="http://localhost:8080/telemetry")
    with pytest.raises(ValueError,match="HTTPS"):
        ProgressReporter(tmp_path,run_id=str(uuid4()),org_id=str(uuid4()),
                         dataset_sha256="a"*64,telemetry_url="http://example.com/api/v1/admin/ai/max-power/finetune/telemetry",
                         telemetry_token="f"*64)
    with pytest.raises(ValueError,match="Endpoint"):
        ProgressReporter(tmp_path,run_id=str(uuid4()),org_id=str(uuid4()),
                         dataset_sha256="a"*64,telemetry_url="https://example.com/other",
                         telemetry_token="f"*64)


def test_neuronal_script_remains_off_by_default_and_requires_signed_approval():
    namespace=runpy.run_path(str(SCRIPTS/"train_galancito_lora.py"),run_name="galant_test")
    assert callable(namespace["main"])
    source=(SCRIPTS/"train_galancito_lora.py").read_text()
    assert "if not args.execute:" in source
    assert "verified_training_manifest" in source
    assert "torch.cuda.is_available()" in source
    assert "trainer.train(resume_from_checkpoint=" in source
    assert "reporter.emit(" in source
