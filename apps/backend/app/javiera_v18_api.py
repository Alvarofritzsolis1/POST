"""GALANT 18: on-demand printable-page preflight for every approved/draft XLSX layout.

No mutations, no operational worker changes, no publication or approval.
Always uses a synthetic dossier when checking PDF consistency.
"""
from __future__ import annotations

import hashlib
from fastapi import APIRouter, Depends, HTTPException
import fitz
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_excel import DOC_SHEETS, DOCUMENT_PRINT_AREAS, layout_summary
from .javiera_layout_api import layout_for, layout_preview, private_workbook_path
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v18", tags=["Javiera 18 · Excel/PDF quality"])

@router.get("/print-profiles")
def profiles(user: User = Depends(administrator)):
    """A profile exists for all ten templates; actual approval is separate."""
    return {"count": len(DOCUMENT_PRINT_AREAS), "profiles": [
        {"code": code, "sheet": DOC_SHEETS[code], "range": bounds,
         "size": "A4", "orientation": "portrait",
         "fit_width_pages": 1, "fit_height_pages": 0}
        for code, bounds in DOCUMENT_PRINT_AREAS.items()
    ], "source": "private approved Excel", "auto_approves": False}


@router.post("/layouts/{layout_id}/check")
def check_layout(layout_id: str, user: User = Depends(administrator),
                 db: Session = Depends(get_db)):
    """Return grounded PDF and formula checks without modifying or approving."""
    layout = layout_for(db, user, layout_id)
    source = private_workbook_path(user, layout.workbook_path).read_bytes()
    if hashlib.sha256(source).hexdigest() != layout.workbook_sha256:
        raise HTTPException(409, "El Excel privado cambió: vuelve a importar y revisa la versión")
    entries = layout_summary(source)
    entry = next((x for x in entries if x["code"] == layout.code), None)
    if not entry or not entry.get("found"):
        raise HTTPException(422, "No se encontró la hoja de origen del documento")
    # Same PDF engine and synthetic input as the real preview endpoint.
    response = layout_preview(layout_id=layout.id, dossier_id="", user=user, db=db)
    with fitz.open(stream=response.body, filetype="pdf") as pdf:
        pages = pdf.page_count
        misplaced = []
        text_length = 0
        for number, page in enumerate(pdf, 1):
            text = page.get_text()
            text_length += len(text.strip())
            for block in page.get_text("blocks"):
                if len(block) < 5 or not isinstance(block[4], str) or not block[4].strip():
                    continue
                if (block[0] < -0.5 or block[1] < -0.5 or
                        block[2] > page.rect.width + 0.5 or
                        block[3] > page.rect.height + 0.5):
                    misplaced.append({
                        "page": number, "side": "out_of_bounds",
                        "bbox": [round(float(x), 1) for x in block[:4]],
                    })
    ok = pages >= 1 and text_length > 20 and not misplaced
    return {
        "layout_id": layout.id, "code": layout.code,
        "sheet": DOC_SHEETS[layout.code], "revision": layout.revision,
        "state": layout.state, "source_sha256": layout.workbook_sha256,
        "pages": pages, "pdf_preview": "synthetic",
        "formula_count": entry["formulas"], "merged_ranges": entry["merged"],
        "configured_print_area": DOCUMENT_PRINT_AREAS[layout.code],
        "text_length": text_length, "out_of_bounds": misplaced,
        "passed": ok, "requires_human_approval": layout.state != "approved",
        "message": ("Vista previa PDF sintética sin texto fuera de página."
                    if ok else
                    "Vista previa con problemas de impresión o sin contenido legible."),
    }
