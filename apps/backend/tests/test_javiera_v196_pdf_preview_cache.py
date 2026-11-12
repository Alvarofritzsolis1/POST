"""Performance and tenant isolation for the private Excel-first document preview."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app.javiera_pdf_preview_cache import PreviewPdfCache, pdf_preview_cache
from app import javiera_layout_api as excel


def test_cache_hit_eviction_and_ttl(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.javiera_pdf_preview_cache.time.monotonic", lambda: clock[0])
    cache = PreviewPdfCache(ttl=5, max_items=2, max_bytes=16)
    cache.put("one", b"12345678")
    assert cache.read("one") == b"12345678"
    cache.put("two", b"abcd")
    cache.put("three", b"four")
    assert cache.read("one") is None
    assert cache.read("two") == b"abcd"
    clock[0] += 6
    assert cache.read("two") is None
    assert cache.read("three") is None


def test_cache_never_exceeds_memory_budget():
    cache = PreviewPdfCache(ttl=60, max_items=100, max_bytes=13)
    cache.put("a", b"12345678")
    cache.put("b", b"12345678")
    assert cache.read("a") is None
    assert cache.read("b") == b"12345678"
    cache.clear()
    assert cache.read("b") is None


def test_excel_preview_reuses_render_only_for_identical_tenant_template_and_data(monkeypatch):
    pdf_preview_cache.clear()
    workbook = b"test-source-is-an-isolated-synthetic-excel"
    digest = hashlib.sha256(workbook).hexdigest()
    fake_path = SimpleNamespace(read_bytes=lambda: workbook)
    calls = []
    monkeypatch.setattr(excel, "private_workbook_path", lambda *_: fake_path)

    def fake_render(raw, code, data, *, changes, matrix, extra_matrices, preview):
        calls.append((code, data, preview))
        return (b"%PDF-1.7\n" + bytes([len(calls)]) * 96)

    monkeypatch.setattr(excel, "pdf_from_workbook", fake_render)
    item = SimpleNamespace(
        code="internal_rules_receipt", id="template-1", revision=1,
        workbook_sha256=digest, workbook_path="/private/synthetic.xlsx", overrides=[],
    )
    a = SimpleNamespace(org_id="tenant-A")
    b = SimpleNamespace(org_id="tenant-B")
    first = excel.make_pdf(None, a, item, {"worker": {"name": "Demo A"}}, preview=True)
    second = excel.make_pdf(None, a, item, {"worker": {"name": "Demo A"}}, preview=True)
    assert first == second
    assert len(calls) == 1
    other_person = excel.make_pdf(None, a, item, {"worker": {"name": "Demo B"}}, preview=True)
    assert other_person != first
    assert len(calls) == 2
    other_tenant = excel.make_pdf(None, b, item, {"worker": {"name": "Demo A"}}, preview=True)
    assert other_tenant != first
    assert len(calls) == 3
    item.revision = 2
    new_revision = excel.make_pdf(None, a, item, {"worker": {"name": "Demo A"}}, preview=True)
    assert new_revision != first
    assert len(calls) == 4
    item.overrides = [{"coordinate":"B2","text":"New approved header"}]
    new_override = excel.make_pdf(None, a, item, {"worker": {"name": "Demo A"}}, preview=True)
    assert new_override != new_revision
    assert len(calls) == 5
    pdf_preview_cache.clear()


def test_excel_preview_not_returned_if_private_workbook_hash_changes(monkeypatch):
    pdf_preview_cache.clear()
    state = {"bytes": b"synthetic"}
    fake_path = SimpleNamespace(read_bytes=lambda: state["bytes"])
    monkeypatch.setattr(excel, "private_workbook_path", lambda *_: fake_path)
    monkeypatch.setattr(excel, "pdf_from_workbook",
                        lambda *_, **__: b"%PDF-1.7\n")
    item = SimpleNamespace(
        code="internal_rules_receipt", id="template-security", revision=1,
        workbook_sha256=hashlib.sha256(state["bytes"]).hexdigest(),
        workbook_path="/private/synthetic.xlsx", overrides=[],
    )
    user = SimpleNamespace(org_id="tenant-A")
    assert excel.make_pdf(None,user,item,{},preview=True).startswith(b"%PDF")
    state["bytes"] = b"tampered-workbook"
    try:
        excel.make_pdf(None,user,item,{},preview=True)
    except Exception as error:
        assert getattr(error, "status_code", None) == 409
        assert "Excel privado cambió" in error.detail
    else:
        raise AssertionError("Cache must never hide a modified workbook")
    pdf_preview_cache.clear()
