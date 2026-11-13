"""Preserve OOXML namespace aliases used as values by Microsoft Excel.

ElementTree retains expanded element/attribute names, but drops declarations
referenced only by mc:Ignorable/Requires/QName values. Keep the source aliases
without changing the process-global namespace registry (requests can overlap).
"""
from __future__ import annotations
import io
from copy import copy
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr


def root_namespaces(raw: bytes) -> dict[str, str]:
    namespaces = {}
    for event, value in ET.iterparse(io.BytesIO(raw), events=("start-ns", "start")):
        if event == "start":
            break
        prefix, uri = value
        namespaces[prefix] = uri
    return namespaces


def preserve_namespaces(raw: bytes, source: bytes) -> bytes:
    """Restore source root aliases lost by XML serialization, byte-preserving otherwise."""
    original = root_namespaces(source)
    current = root_namespaces(raw)
    missing = [(prefix, uri) for prefix, uri in original.items() if prefix not in current]
    if not missing:
        return raw
    # An unprefixed original default namespace must not change a new root's meaning.
    root = ET.fromstring(raw)
    additions = []
    for prefix, uri in missing:
        if not prefix and not root.tag.startswith("{" + uri + "}"):
            continue
        name = "xmlns:" + prefix if prefix else "xmlns"
        additions.append(" " + name + "=" + quoteattr(uri))
    match = re.search(rb"<(?![?!])[^\s/>]+", raw)
    if not match:
        raise ValueError("XML sin elemento raíz")
    return raw[:match.end()] + "".join(additions).encode("utf-8") + raw[match.end():]


def compatible_package(raw: bytes, reference: bytes) -> bytes:
    """Repair exports of older stored revisions using their immutable original."""
    from zipfile import ZipFile, ZIP_DEFLATED
    with ZipFile(io.BytesIO(reference)) as original, ZipFile(io.BytesIO(raw)) as source:
        changes = {}
        names = set(original.namelist())
        for name in source.namelist():
            if name in names and name.endswith((".xml", ".rels")):
                content = source.read(name)
                repaired = preserve_namespaces(content, original.read(name))
                if repaired != content:
                    changes[name] = repaired
        if not changes:
            return raw
        out = io.BytesIO()
        with ZipFile(out, "w", ZIP_DEFLATED) as target:
            for item in source.infolist():
                target.writestr(copy(item), changes.get(item.filename, source.read(item.filename)))
        return out.getvalue()
