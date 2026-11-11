"""IRL: cinco bloques editables, fuente privada y gate de aprobación.

La API usa una fuente simulada para que CI no pueda publicar imágenes, datos
personales ni Excel privados en el repositorio. La aprobación profesional
requiere la firma real de un usuario designado en el flujo de revisiones.
"""
from types import SimpleNamespace

from app import javiera_v195_api as visual
from app.javiera_irl_render_context import original_context
from test_control_api import env, login

ROOT = "/api/v1/javiera/v195"
SOURCE = "a" * 64
HASHES = [hex(i)[2:] * 64 for i in range(1, 6)]


def fake_source(*args, **kwargs):
    return {
        "available": True, "source_sha256": SOURCE,
        "images": [{"sha256": HASHES[i], "title": str(i+1),
                    "data_uri": "data:image/png;base64,AA==",
                    "anchor_row": [87,101,120,135,153][i]} for i in range(5)],
        "static": {"A4": "IRL"}, "document_code": "DPR-IRL-03",
    }


def valid_payload():
    return {
        "source_sha256": SOURCE,
        "image_hashes": HASHES,
        "reason": "Primera revisión editorial del IRL, cotejo manual obligatorio.",
        "blocks": [{"id": i, "text": f"Norma {i}: contenido sintético para revisar." +
                    " Texto técnico de prueba sin valor legal.",
                    "reviewed": False} for i in range(1,6)],
    }


def test_editor_draft_requires_same_private_source_and_never_auto_approves(env, monkeypatch):
    monkeypatch.setattr(visual, "_authorized_original", fake_source)
    client, _ = env
    headers = login(client, "a@example.cl")
    before = client.get(ROOT + "/irl-blocks", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["approved_revision"] is None

    bad = valid_payload()
    bad["image_hashes"][0] = "f" * 64
    rejected = client.post(ROOT + "/irl-blocks", json=bad, headers=headers)
    assert rejected.status_code == 409

    content = valid_payload()
    result = client.post(ROOT + "/irl-blocks", json=content, headers=headers)
    assert result.status_code == 200, result.text
    revision_id = result.json()["id"]
    assert result.json()["state"] == "draft"
    current = client.get(ROOT + "/irl-blocks", headers=headers)
    assert current.status_code == 200
    assert current.json()["latest"]["revision"] == 1
    assert current.json()["latest"]["source_matches"] is True
    assert current.json()["approved_revision"] is None
    assert current.json()["latest"]["preventive_verdict"] == "pending"
    assert current.json()["latest"]["preventive_authorization_valid"] is False
    assert current.json()["latest"]["can_publish"] is False
    assert current.json()["latest"]["author_is_current_user"] is True

    # No hay aprobación profesional; aunque el autor pulse publicar, se rechaza.
    publish = client.post(ROOT + "/irl-blocks/" + revision_id + "/publish", headers=headers)
    assert publish.status_code in (403,409,422)
    assert client.get(ROOT + "/irl-blocks", headers=headers).json()["approved_revision"] is None


def test_source_graphics_stay_printed_without_signed_editorial_override():
    original = fake_source()
    output = original_context({"PERFILES": ["Cargo de prueba"]}, original)
    assert output["original_images"].count("<img") == 5
    assert "data:image/png;base64" in output["original_images"]


def test_safe_html_replaces_exactly_five_images_only_when_override_is_approved():
    original = fake_source()
    original["approved_editable_blocks"] = [
        {"title": f"Bloque {i}", "text": f"Título {i} <script>alert(1)</script>\n☐ Ítem {i}"}
        for i in range(1,6)
    ]
    output = original_context({}, original)
    markup = output["original_images"]
    assert markup.count('class="irl-ed-block"') == 5
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "<img" not in markup
    assert "☐ Ítem 5" in markup


def test_publish_cannot_use_stale_signed_revision(env, monkeypatch):
    monkeypatch.setattr(visual, "_authorized_original", fake_source)
    client, _ = env
    headers = login(client, "a@example.cl")
    first = client.post(ROOT + "/irl-blocks", json=valid_payload(), headers=headers)
    assert first.status_code == 200, first.text
    second = client.post(ROOT + "/irl-blocks", json=valid_payload(), headers=headers)
    assert second.status_code == 200
    old_id = first.json()["id"]
    # Se bloquea revisión anterior antes incluso de revisar la firma.
    attempt = client.post(ROOT + "/irl-blocks/" + old_id + "/publish", headers=headers)
    assert attempt.status_code == 409


def test_completely_reviewed_blocks_still_require_independent_preventive_signoff(env, monkeypatch):
    monkeypatch.setattr(visual, "_authorized_original", fake_source)
    client, _ = env
    headers = login(client, "a@example.cl")
    payload = valid_payload()
    for block in payload["blocks"]:
        block["reviewed"] = True
    result = client.post(ROOT + "/irl-blocks", json=payload, headers=headers)
    assert result.status_code == 200, result.text
    current = client.get(ROOT + "/irl-blocks", headers=headers).json()
    assert current["latest"]["can_publish"] is False
    assert current["latest"]["preventive_verdict"] == "pending"
    attempt = client.post(ROOT + "/irl-blocks/" + result.json()["id"] + "/publish", headers=headers)
    assert attempt.status_code == 409, attempt.text
    assert "acta preventiva" in attempt.json()["detail"]
