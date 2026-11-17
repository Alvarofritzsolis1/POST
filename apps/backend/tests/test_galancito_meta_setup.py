"""Pruebas aisladas del asistente Meta; no tocan credenciales ni APIs reales."""
import importlib.util
import os
import re
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "setup-galancito-messenger.py"
spec = importlib.util.spec_from_file_location("galancito_setup_cli", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_env_edit_is_atomic_private_and_preserves_settings(tmp_path):
    path = tmp_path / ".env.preview"
    path.write_text("# Comentario previo\nAPP_SECRET=real\nPOSTGRES_PASSWORD=secret\n"
                    "FACEBOOK_AI_ENABLED=false\nFACEBOOK_AI_ENABLED=false\n")
    path.chmod(0o600)
    backup = setup.write_env_atomically(path, {
        "FACEBOOK_AI_ENABLED": "true",
        "FACEBOOK_WEBHOOK_VERIFY_TOKEN": "random-test-only-do-not-use",
    })
    final = path.read_text()
    assert final.count("FACEBOOK_AI_ENABLED=") == 1
    assert "FACEBOOK_AI_ENABLED=true" in final
    assert "APP_SECRET=real" in final
    assert "POSTGRES_PASSWORD=secret" in final
    assert "# Comentario previo" in final
    assert backup.read_text().count("FACEBOOK_AI_ENABLED=false") == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    other_backup = setup.write_env_atomically(path, {"FACEBOOK_MESSAGING_ENABLED": "true"})
    assert other_backup != backup
    assert setup.env_values(path)["FACEBOOK_MESSAGING_ENABLED"] == "true"


def test_env_rejects_injection_and_symlink(tmp_path):
    path = tmp_path / ".env.preview"
    path.write_text("APP_SECRET=only-local\n")
    with pytest.raises(setup.SetupError):
        setup.write_env_atomically(path, {"FACEBOOK_PAGE_ID": "12345\nINJECTED=yes"})
    link = tmp_path / ".env.preview.link"
    link.symlink_to(path)
    with pytest.raises(setup.SetupError):
        setup.write_env_atomically(link, {"FACEBOOK_PAGE_ID": "12345"})


def test_meta_graph_uses_header_token_not_url(monkeypatch):
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"success":true}'

    def fake_open(req, timeout):
        calls.append(req)
        return Response()

    monkeypatch.setattr(setup.opener, "open", fake_open)
    assert setup.graph("POST", "/1234567890/subscribed_apps",
                       "secret-page-token", {"subscribed_fields": "messages"}) == {"success": True}
    assert len(calls) == 1
    req = calls[0]
    assert "secret-page-token" not in req.full_url
    assert req.get_header("Authorization") == "Bearer secret-page-token"
    assert parse_qs(req.data.decode()) == {"subscribed_fields": ["messages"]}
    with pytest.raises(setup.SetupError):
        setup.graph("POST", "/1234567890/feed", "secret-page-token", {})
    assert setup.graph("GET", "/me", "secret-page-token", {"fields": "id,name"}) == {"success": True}
    with pytest.raises(setup.SetupError):
        setup.graph("POST", "/me", "secret-page-token", {})



def test_local_webhook_verification_matches_meta_protocol(monkeypatch):
    captured = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b"galancito-abcdef1234567890"

    def fake_open(req, timeout):
        captured.append(req.full_url)
        return Response()

    monkeypatch.setattr(setup.opener, "open", fake_open)
    monkeypatch.setattr(setup.secrets, "token_hex", lambda n: "abcdef1234567890")
    setup.test_webhook("https://galant.dpdns.org/api/v1/network/facebook/webhook", "private-test-token")
    data = parse_qs(urlparse(captured[0]).query)
    assert data == {"hub.mode": ["subscribe"],
                    "hub.verify_token": ["private-test-token"],
                    "hub.challenge": ["galancito-abcdef1234567890"]}


def test_script_cannot_print_meta_secrets_by_error_message(monkeypatch):
    from urllib.error import HTTPError

    def fake_open(req, timeout):
        raise HTTPError(req.full_url, 403, "Not authorized token=secret", {}, None)
    monkeypatch.setattr(setup.opener, "open", fake_open)
    with pytest.raises(setup.SetupError) as exc:
        setup.graph("POST", "/1234567890/subscriptions",
                    "1234567890|test-app-secret", {"object": "page"})
    assert "test-app-secret" not in str(exc.value)
    assert "token=" not in str(exc.value)
