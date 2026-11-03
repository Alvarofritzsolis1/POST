"""Regression: contract audit payloads must be JSON serializable in PostgreSQL."""
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.control_admin import contract_view


def test_contract_view_can_be_written_to_audit_json():
    record = SimpleNamespace(
        id="contract-1",
        association_id="association-1",
        worker_assignment_id=None,
        contract_type="fixed_term",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 11, 12),
        status="active",
        notes="QA",
        created_by="user-1",
        updated_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    payload = contract_view(record)
    encoded = json.dumps({"created": payload, "before": payload})
    decoded = json.loads(encoded)
    assert decoded["created"]["start_date"] == "2026-09-01"
    assert decoded["created"]["end_date"] == "2026-11-12"
    assert decoded["created"]["updated_at"].endswith("+00:00")


def test_indefinite_contract_without_end_date_serializes():
    record = SimpleNamespace(
        id="contract-2", association_id="association-2",
        worker_assignment_id=None, contract_type="indefinite",
        start_date=date(2026, 9, 1), end_date=None,
        status="active", notes="", created_by="user-1",
        updated_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    assert json.loads(json.dumps(contract_view(record)))["end_date"] is None
