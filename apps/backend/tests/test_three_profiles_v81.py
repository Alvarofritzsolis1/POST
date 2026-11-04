"""Contract tests for the only three GALANT POST v8.1 roles."""
import pytest
from pydantic import ValidationError
from app.network_schemas import AccountEdit, AccountInput

@pytest.mark.parametrize("role", ["admin", "administrative", "resident"])
def test_role_can_be_created(role):
    sites = [] if role == "admin" else ["site-qa"]
    data = AccountInput(name="Persona de prueba", email="prueba@example.test",
                        role=role, site_ids=sites)
    assert data.role == role

@pytest.mark.parametrize("legacy", ["analyst", "supervisor", "viewer", "reviewer"])
def test_legacy_role_cannot_be_created(legacy):
    with pytest.raises(ValidationError):
        AccountInput(name="Persona de prueba", email="prueba@example.test",
                     role=legacy, site_ids=["site-qa"])

@pytest.mark.parametrize("role", ["administrative", "resident"])
def test_worksite_assignment_is_required(role):
    with pytest.raises(ValidationError):
        AccountInput(name="Persona de prueba", email="prueba@example.test",
                     role=role, site_ids=[])
    with pytest.raises(ValidationError):
        AccountEdit(name="Persona de prueba", role=role, enabled=True, site_ids=[])

def test_only_three_roles_can_be_selected_in_account_edit():
    for role in ("admin", "administrative", "resident"):
        AccountEdit(name="Persona de prueba", role=role, enabled=True,
                    site_ids=["site-qa"] if role != "admin" else [])
    for role in ("analyst", "supervisor", "viewer", "reviewer"):
        with pytest.raises(ValidationError):
            AccountEdit(name="Persona de prueba", role=role, enabled=True,
                        site_ids=["site-qa"])
