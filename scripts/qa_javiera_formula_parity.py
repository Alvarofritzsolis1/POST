#!/usr/bin/env python3
"""Auditoría sin modificar los Excel: compara las 423 fórmulas y cachés OOXML.

No hace upload de planillas, nombres, RUT, fórmulas ni datos personales.
Esta auditoría verifica conservación y cachés, NO sustituye la paridad funcional
de todos los cálculos para entradas nuevas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def workbook_formula_snapshot(path: str | Path) -> dict:
    with ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        paths = {}
        for rel in rels.findall(PR + "Relationship"):
            target = rel.get("Target", "")
            if target.startswith("/"):
                paths[rel.get("Id", "")] = target.lstrip("/")
            else:
                paths[rel.get("Id", "")] = "xl/" + target.lstrip("/")
        entries = {}
        sheets = []
        for sheet in workbook.findall("./" + M + "sheets/" + M + "sheet"):
            name = sheet.get("name", "")
            target = paths.get(sheet.get(R + "id", ""))
            if not target:
                raise ValueError("Hoja sin ruta OOXML: " + name)
            root = ET.fromstring(zf.read(target))
            sheets.append(name)
            for c in root.iter(M + "c"):
                f = c.find(M + "f")
                if f is None:
                    continue
                cached = c.find(M + "v")
                key = name + "!" + c.get("r", "")
                formula = f.text or ""
                attrs = tuple(sorted(f.attrib.items()))
                entries[key] = {
                    "signature": [formula, list(attrs)],
                    "cached": [c.get("t", ""), cached.text if cached is not None else None],
                    "shared": f.get("t") == "shared",
                    "cached_error": c.get("t") == "e",
                }
        canonical = json.dumps(
            {key: entry["signature"] for key, entry in sorted(entries.items())},
            ensure_ascii=False, separators=(",", ":"),
        )
        return {
            "sheet_names": sheets,
            "formula_count": len(entries),
            "shared_formula_count": sum(v["shared"] for v in entries.values()),
            "cached_nonempty": sum(v["cached"][1] not in (None, "") for v in entries.values()),
            "cached_errors": sum(v["cached_error"] for v in entries.values()),
            "formula_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "entries": entries,
        }


def compare_workbooks(original: str | Path, candidate: str | Path,
                      *, min_formulas: int = 423) -> dict:
    old = workbook_formula_snapshot(original)
    new = workbook_formula_snapshot(candidate)
    keys = set(old["entries"]) | set(new["entries"])
    changed = sorted(key for key in keys
                     if old["entries"].get(key, {}).get("signature") !=
                        new["entries"].get(key, {}).get("signature"))
    cached_changed = sorted(key for key in keys if
                            old["entries"].get(key, {}).get("cached") !=
                            new["entries"].get(key, {}).get("cached"))
    same_sheets = old["sheet_names"] == new["sheet_names"]
    passed = (old["formula_count"] >= min_formulas and
              old["formula_count"] == new["formula_count"] and
              same_sheets and not changed and not cached_changed and
              new["cached_errors"] == 0)
    counts = Counter(key.rsplit("!", 1)[0] for key in old["entries"])
    return {
        "passed": passed,
        "original": {
            key: old[key] for key in ("formula_count", "shared_formula_count",
                                     "cached_nonempty", "cached_errors", "formula_sha256")
        },
        "candidate": {
            key: new[key] for key in ("formula_count", "shared_formula_count",
                                     "cached_nonempty", "cached_errors", "formula_sha256")
        },
        "original_sheets": len(old["sheet_names"]),
        "candidate_sheets": len(new["sheet_names"]),
        "sheet_structure_identical": same_sheets,
        "formulas_by_sheet": dict(counts),
        "changed_formula_cell_count": len(changed),
        "changed_cached_cell_count": len(cached_changed),
        "changed_formula_cell_refs": changed[:150],
        "changed_cached_cell_refs": cached_changed[:150],
        "scope": "Conservación exacta de fórmulas OOXML y resultados almacenados.",
        "limitation": (
            "NO demuestra equivalencia de cálculos ante cambios de datos; "
            "se necesitan escenarios evaluados en Excel y en el backend. "
            "Las fórmulas compartidas se comparan con sus referencias OOXML."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--min-formulas", type=int, default=423)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = compare_workbooks(args.original, args.candidate,
                               min_formulas=args.min_formulas)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
