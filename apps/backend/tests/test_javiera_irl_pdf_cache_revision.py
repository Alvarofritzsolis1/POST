"""The IRL draft and issue share one conversion for one dossier revision."""

import fitz

from app import javiera_workbook as workbook
from app import javiera_layout_api


def test_irl_preview_reuses_definitive_pdf_and_revision_changes_invalidate_cache(
    monkeypatch, tmp_path
):
    calls = []

    def convert(*args, **kwargs):
        calls.append(kwargs)
        with fitz.open() as document:
            page = document.new_page(width=612, height=792)
            page.insert_text((40, 60), "DEPARTAMENTO DE PREVENCION")
            pdf = document.tobytes()
        return pdf, {"pages": 1, "elapsed_ms": 9.0, "engine": "QA"}

    monkeypatch.setattr(workbook, "roles", lambda _: {"CARPINTERO": {"IRL": [1]}})
    monkeypatch.setattr(workbook, "resolve_workbook_role", lambda _, role, __: role)
    monkeypatch.setattr(workbook, "fill_workbook", lambda raw, *_: raw)
    monkeypatch.setattr(workbook, "irl_continuations", lambda raw, _: (raw, []))
    monkeypatch.setattr(workbook, "irl_print_sections", lambda raw, *_: (raw, []))
    monkeypatch.setattr(workbook, "convert_pdf", convert)
    monkeypatch.setattr(javiera_layout_api, "source_leaks", lambda *_: [])

    base = {"role": "CARPINTERO"}
    args = (b"private-qa-workbook", "irl", base, "org-1", tmp_path)
    definitive, first = workbook.cached_pdf(*args, False, dossier_id="dossier-1", template_revision=2)
    draft, preview = workbook.cached_pdf(*args, True, dossier_id="dossier-1", template_revision=2)
    repeated, reused = workbook.cached_pdf(*args, False, dossier_id="dossier-1", template_revision=2)
    again, draft_reused = workbook.cached_pdf(*args, True, dossier_id="dossier-1", template_revision=2)
    assert len(calls) == 1
    assert definitive == repeated and draft == again and definitive != draft
    assert first["cache_hit"] is False and reused["cache_hit"] is True
    assert preview["preview_source_sha256"] == first["sha256"]
    assert preview["cache_hit"] is False and draft_reused["cache_hit"] is True
    with fitz.open(stream=definitive, filetype="pdf") as issued:
        assert "BORRADOR" not in issued[0].get_text()
    with fitz.open(stream=draft, filetype="pdf") as marked:
        assert "BORRADOR" in marked[0].get_text()

    workbook.cached_pdf(*args, False, dossier_id="dossier-1", template_revision=3)
    workbook.cached_pdf(*args, False, dossier_id="dossier-2", template_revision=2)
    workbook.cached_pdf(args[0], "irl", {"role": "ALBAÑIL"}, args[3], args[4], False,
                        dossier_id="dossier-1", template_revision=2)
    assert len(calls) == 4
