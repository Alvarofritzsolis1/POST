"""IRL: extraer originales gráficos de la hoja Excel PRIVADA, sin OCR ni reescritura.

Origen: JavieraExcelLayout por organización. Solo se exportan los cinco bloques
de la hoja IRL; ninguna celda de identidad, contrato o trabajador de muestra.
Las imágenes se devuelven como data URI para un HTML A4 y el motor PDF nativo.
"""
from __future__ import annotations

import base64
import hashlib
import io
from pathlib import PurePosixPath
from posixpath import basename, dirname, join, normpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

from fastapi import HTTPException

from .javiera_excel import Q, cell_text, shared_strings, sheet_files

DRAW = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
STATIC_CELLS = (
    "A2", "B2", "B3", "C3", "D2", "A4", "A5", "A13", "A14",
    "A17", "A21", "A22", "A24", "A27", "A30", "A37", "A68",
    "A169", "A172",
)
PHOTO_TITLES = (
    "Antecedentes generales y otras consideraciones",
    "Normas generales de seguridad, puntos 1–3",
    "Normas generales de seguridad, puntos 4–6",
    "Normas generales de seguridad, puntos 7–9",
    "Normas generales de seguridad, puntos 10–13",
)
MAX_IMAGES = 12
MAX_IMAGE_BYTES = 1_000_000
MAX_TOTAL_IMAGE_BYTES = 5_000_000


def _part(origin: str, target: str) -> str:
    if not target or target.startswith(("http:", "https:", "//")):
        raise ValueError("Recurso externo no permitido en la plantilla IRL.")
    part = (target.lstrip("/") if target.startswith("/")
            else normpath(join(dirname(origin), target)))
    if (part == ".." or part.startswith("../") or
            not part.startswith("xl/") or "\\" in part):
        raise ValueError("Ruta OOXML fuera de xl/ no permitida.")
    return str(PurePosixPath(part))


def _relationships(zf: ZipFile, origin: str) -> dict[str, str]:
    path = join(dirname(origin), "_rels", basename(origin) + ".rels")
    if path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(path))
    found = {}
    for element in root.findall(PKG + "Relationship"):
        if element.get("TargetMode") == "External":
            continue
        ident = element.get("Id")
        if ident:
            found[ident] = _part(origin, element.get("Target", ""))
    return found


def _mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def extract_irl_original(raw: bytes) -> dict:
    """Leer dibujos y cláusulas fijas de IRL; se conservan exactamente los píxeles.

    No se admite fallback a nombres de archivo xl/media: se resuelven
    las relaciones hoja -> dibujo -> imagen para evitar mezclar otros documentos.
    """
    try:
        with ZipFile(io.BytesIO(raw)) as zf:
            files = sheet_files(zf)
            if "IRL" not in files:
                raise ValueError("El libro no contiene la hoja IRL original.")
            path = files["IRL"]
            root = ET.fromstring(zf.read(path))
            strings = shared_strings(zf)
            static = {
                cell.get("r"): cell_text(cell, strings).strip()
                for cell in root.iter(Q("c"))
                if cell.get("r") in STATIC_CELLS
            }
            rels = _relationships(zf, path)
            images = []
            total_bytes = 0
            for drawing in root.findall(MAIN + "drawing"):
                drawing_path = rels.get(drawing.get(REL + "id"))
                if not drawing_path:
                    raise ValueError("Hoja IRL con dibujo no vinculado.")
                draw = ET.fromstring(zf.read(drawing_path))
                draw_rels = _relationships(zf, drawing_path)
                for anchor in draw:
                    pic = anchor.find(DRAW + "pic")
                    if pic is None:
                        continue
                    blip = pic.find(".//" + A + "blip")
                    image_path = draw_rels.get(blip.get(REL + "embed")) if blip is not None else None
                    if not image_path:
                        raise ValueError("Imagen IRL sin referencia de archivo.")
                    data = zf.read(image_path)
                    media_type = _mime(data)
                    if media_type is None:
                        raise ValueError("Imagen IRL con formato distinto de PNG/JPEG.")
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ValueError("Una imagen IRL supera el límite seguro de 1 MB.")
                    total_bytes += len(data)
                    if total_bytes > MAX_TOTAL_IMAGE_BYTES or len(images) >= MAX_IMAGES:
                        raise ValueError("La hoja IRL contiene demasiadas imágenes.")
                    position = anchor.find(DRAW + "from")
                    row_node = position.find(DRAW + "row") if position is not None else None
                    col_node = position.find(DRAW + "col") if position is not None else None
                    row = int(row_node.text) + 1 if row_node is not None else None
                    column = int(col_node.text) + 1 if col_node is not None else None
                    images.append({
                        "anchor_row": row, "anchor_column": column,
                        "media_type": media_type,
                        "data_uri": ("data:" + media_type + ";base64," +
                                     base64.b64encode(data).decode("ascii")),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    })
            images.sort(key=lambda item: (item["anchor_row"] if item["anchor_row"] is not None
                                         else 10**9, item["anchor_column"] or 1))
            for i, item in enumerate(images):
                item["order"] = i + 1
                item["title"] = (PHOTO_TITLES[i] if i < len(PHOTO_TITLES)
                                 else "Bloque original " + str(i + 1))
            return {
                "source_sheet": "IRL",
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "source_version": static.get("D2", ""),
                "document_code": static.get("C3", ""),
                "static": static,
                "images": images,
                "image_count": len(images),
                "all_five_images_present": len(images) == 5,
                "automatic_image_extraction": True,
                "original_images_are_not_ocr_transcriptions": True,
            }
    except (OSError, BadZipFile, KeyError, ValueError, ET.ParseError) as exc:
        raise ValueError("No se pudo reconstruir íntegramente el material gráfico del IRL: " +
                         str(exc)) from None


def load_original_for_user(db, user, *, approved_only: bool = False) -> dict:
    """Recuperar la plantilla previamente importada; sin nuevos pasos por cargo."""
    # Importación diferida para evitar ciclos: layout_api también usa el motor Excel.
    from .javiera_layout_api import latest_layout, private_workbook_path

    layout = latest_layout(db, user.org_id, "irl", approved=approved_only)
    if layout is None:
        return {
            "available": False, "image_count": 0, "images": [], "static": {},
            "status": "not_imported_or_not_approved" if approved_only else "not_imported",
            "message": "Importa una vez el Excel original en Proyecto Javiera para recuperar las fotos.",
        }
    raw = private_workbook_path(user, layout.workbook_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != layout.workbook_sha256:
        raise HTTPException(409, "El Excel original cambió. Reimporta y revisa la plantilla.")
    try:
        result = extract_irl_original(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    result.update({
        "available": True, "status": layout.state,
        "layout_revision": layout.revision,
        "layout_id": layout.id,
        "private_source": True,
        "ready_for_final_document": layout.state == "approved" and
                                    result["all_five_images_present"],
    })
    return result
