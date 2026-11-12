"""Post-deploy checks with synthetic bytes only; no production records are written."""
import argparse
import base64
import io
import json
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.request import urlopen

import fitz
from openpyxl import Workbook, load_workbook
from sqlalchemy import inspect

from . import cli  # Register the complete, additive schema.
from .config import settings
from .db import SessionLocal, engine
from .javiera_workbook import warm_convert
from .migrations.v20_0_0 import MIGRATION_ID
from .platform_models import SchemaVersion
from .version import SOURCE_COMMIT, VERSION


def verify(expected_commit: str):
    if SOURCE_COMMIT != expected_commit:
        raise RuntimeError("El contenedor no corresponde al commit solicitado")
    if len(settings().app_secret) < 48:
        raise RuntimeError("La clave de sesión no cumple la longitud requerida")
    tables = set(inspect(engine).get_table_names())
    expected_tables = {
        "javiera_workbooks", "javiera_workbook_heads", "javiera_workbook_validations",
        "javiera_resets", "javiera_archives",
    }
    if not expected_tables <= tables:
        raise RuntimeError("Faltan tablas del espacio Excel")
    with SessionLocal() as db:
        if not db.get(SchemaVersion, MIGRATION_ID):
            raise RuntimeError("No consta la migración verificada de GALANT 20")
    private = Path(settings().document_dir)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=private) as stream:
        stream.write(b"galant-private-storage-check")
        stream.seek(0)
        if stream.read() != b"galant-private-storage-check":
            raise RuntimeError("El almacenamiento privado no permite lectura y escritura")
    for path in ("/api/v1/javiera/workbook", "/api/v1/javiera/dossiers"):
        try:
            with urlopen("http://127.0.0.1:8000" + path, timeout=5):
                raise RuntimeError("Una ruta privada permite acceso anónimo")
        except HTTPError as error:
            if error.code != 401:
                raise RuntimeError("Respuesta inesperada de autenticación") from None
    book = Workbook()
    inputs = book.active
    inputs.title = "Inputs"
    inputs["A1"] = 7
    inputs["A2"] = "PRIVATE_INPUT_MUST_NOT_BE_EXPORTED"
    output = book.create_sheet("Deployment")
    output["A1"] = "GALANT QA"
    output.column_dimensions["A"].width = 45
    output["A2"] = "='Inputs'!A1*2"
    output.print_area = "A1:B3"
    raw = io.BytesIO()
    book.save(raw)
    result = warm_convert(raw.getvalue(), ["Deployment"])
    calculated = load_workbook(io.BytesIO(base64.b64decode(result["calculated"], validate=True)), data_only=True)
    if calculated["Deployment"]["A2"].value != 14:
        raise RuntimeError("Calc no ha recalculado las referencias entre hojas")
    pdf = base64.b64decode(result["pdf"], validate=True)
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
        if len(document) != 1 or "GALANT QA" not in text or "14" not in text:
            raise RuntimeError("El PDF sintético no coincide con el Excel recalculado")
        if "PRIVATE_INPUT_MUST_NOT_BE_EXPORTED" in text:
            raise RuntimeError("Calc exportó una hoja no seleccionada")
    return {"version": VERSION, "commit": SOURCE_COMMIT, "migration": MIGRATION_ID,
            "private_storage": "ok", "anonymous_access": "blocked",
            "calc_recalculation": "ok", "selected_sheet_pdf": "ok",
            "calc_engine_ms": result.get("engine_ms")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.expected_commit), ensure_ascii=False))
