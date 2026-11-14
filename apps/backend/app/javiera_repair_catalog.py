"""Reparaciones documentales verificadas con Excel privado del usuario.

La fuente de los textos es GALANT_JAVIERA_IRL_PTS_MATRICES_COMPLETADAS_REVISION.xlsx
SHA-256 81efa702676d0f8e6cee2ab99e1a7ae84c59970efb90c8263298558688993708.
Se crea únicamente un borrador nuevo: nunca se modifica ni publica el original.
"""
from __future__ import annotations

import io
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .javiera_excel import LayoutError, Q, cell_text, sheet_files, shared_strings

CARPENTER_CONSEQUENCE = (
    "Contacto eléctrico directo o indirecto, electrocución, quemaduras, "
    "tropiezos por extensiones atravesadas y lesiones derivadas del uso de EPP deteriorado."
)
CARPENTER_CONTROL = (
    "Revisar antes de cada uso cables, clavijas, aislación, protecciones y EPP; "
    "retirar inmediatamente elementos defectuosos y señalizar su condición. "
    "Mantener extensiones fuera de rutas de tránsito o protegidas con pasacables "
    "apropiados y libres de humedad. Verificar protección diferencial y puesta a "
    "tierra según instalación. Prohibir empalmes improvisados y reparaciones por "
    "personal no autorizado. Almacenar el EPP limpio, seco y según fabricante y "
    "reemplazarlo si presenta daño o pérdida de capacidad protectora."
)
IMPERMEABILIZADOR_CONDITIONS = (
    "Cubiertas, losas, terrazas, muros enterrados y fundaciones donde se preparan "
    "superficies y se aplican sistemas de impermeabilización especificados para la obra; "
    "verificar accesos y protecciones colectivas antes de intervenir.",
    "Exposición a vapores de imprimantes y solventes, contacto dérmico con sustancias, "
    "polvo de preparación de superficies y, si el sistema lo requiere, calor y riesgo "
    "de incendio por equipos de aplicación térmica; posible caída a distinto nivel.",
    "Mantener accesos despejados y proteger bordes; segregar inflamables y fuentes de "
    "ignición. Garantizar ventilación y revisar HDS de los productos reales; almacenar "
    "y disponer envases y residuos conforme a sus instrucciones. No realizar aplicación "
    "térmica sin permiso y medios de extinción disponibles cuando corresponda.",
    "Rodillos, brochas, espátulas, equipos de aplicación de impermeabilizante y "
    "herramientas de preparación de superficie. Sopletes u otros equipos térmicos "
    "exclusivamente si el sistema especificado lo requiere y existe autorización, "
    "inspección y capacitación.",
)


def proposed_repairs(raw: bytes) -> tuple[dict[str, list[dict]], list[str]]:
    """Fill only exact blank cells that match user-provided correction sources."""
    with ZipFile(io.BytesIO(raw)) as archive:
        sheets = sheet_files(archive)
        strings = shared_strings(archive)
        if not {"MATRIZ IRL", "Matriz IRL Optimizada"}.issubset(sheets):
            raise LayoutError("El maestro no contiene las matrices preventivas esperadas")
        def values(sheet: str) -> dict[str, str]:
            root = ET.fromstring(archive.read(sheets[sheet]))
            return {cell.get("r", ""): cell_text(cell, strings).strip()
                    for cell in root.findall(".//" + Q("c"))}
        risks = values("MATRIZ IRL")
        summary = values("Matriz IRL Optimizada")
    changes: dict[str, list[dict]] = {}
    details: list[str] = []
    if (risks.get("B40") == "CARPINTERO"
        and "Inspección" in risks.get("C40", "")
        and "extensiones eléctricas" in risks.get("C40", "")
        and "Cables eléctricos" in risks.get("D40", "")):
        for coordinate, suggestion in (
            ("E40", CARPENTER_CONSEQUENCE), ("F40", CARPENTER_CONTROL)
        ):
            if not risks.get(coordinate):
                changes.setdefault("MATRIZ IRL", []).append({
                    "cell": coordinate, "value": suggestion
                })
                details.append("MATRIZ IRL!" + coordinate)
    existing = [(ref, value) for ref, value in summary.items()
                if re.fullmatch(r"A[1-9]\d*", ref)
                and value == "IMPERMEABILIZADOR"]
    membrane = [(ref, value) for ref, value in summary.items()
                if re.fullmatch(r"A[1-9]\d*", ref)
                and value == "MEMBRANA ASFALTICA"]
    if len(existing) > 1:
        raise LayoutError("El maestro contiene perfiles duplicados de IMPERMEABILIZADOR")
    if (not existing and len(membrane) == 1
        and risks.get("B145") == "IMPERMEABILIZADOR"
        and "MEMBRANA ASFALTICA" in risks.get("C145", "")):
        occupied_rows = [int(match.group(1)) for ref in summary
                         if (match := re.fullmatch(r"A([1-9]\d*)", ref))
                         and summary[ref]]
        next_row = max(occupied_rows, default=1) + 1
        if (next_row > 1000 or
                any(summary.get(f"{col}{next_row}") for col in "ABCDE")):
            raise LayoutError("No hay una fila segura donde agregar el perfil preventivo")
        for col, content in zip(
            "ABCDE", ("IMPERMEABILIZADOR", *IMPERMEABILIZADOR_CONDITIONS)
        ):
            changes.setdefault("Matriz IRL Optimizada", []).append({
                "cell": f"{col}{next_row}", "value": content
            })
            details.append("Matriz IRL Optimizada!" + col + str(next_row))
    return changes, details
