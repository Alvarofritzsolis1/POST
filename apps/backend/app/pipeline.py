"""Caché privado de reconocimiento; las reglas pueden ejecutarse de nuevo sin OCR."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable

from .config import settings
from .ocr import OCR_ENGINE_VERSION, OCR_SCHEMA_VERSION, effective_ocr_language, extract_document, interpret_extraction


def extraction_path(source: str | Path) -> Path:
    path = Path(source)
    return path.with_name(path.name + ".ocr.json")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_cache(data: object, digest: str) -> bool:
    if not isinstance(data, dict):
        return False
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        return False
    for number, page in enumerate(pages, 1):
        if not isinstance(page, dict) or type(page.get("page")) is not int or page["page"] != number:
            return False
        if not isinstance(page.get("text"), str) or not isinstance(page.get("method"), str):
            return False
        confidence = page.get("confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)):
            return False
        tokens = page.get("tokens")
        if not isinstance(tokens, list) or any(not isinstance(token, dict)
                                               or not isinstance(token.get("texto"), str)
                                               or not isinstance(token.get("bbox"), list)
                                               for token in tokens):
            return False
    return (isinstance(data, dict)
            and data.get("schema_version") == OCR_SCHEMA_VERSION
            and data.get("engine_version") == OCR_ENGINE_VERSION
            and data.get("source_sha256") == digest
            and data.get("ocr_language") == settings().ocr_language
            and data.get("ocr_language_used") == effective_ocr_language()
            and data.get("ocr_secondary") == settings().ocr_secondary
            and isinstance(data.get("ocr_seconds"), (int, float)))


def _save_atomic(path: Path, extraction: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(extraction, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def process_document(source: str | Path, declared: str = "auto",
                     expected_sha256: str | None = None,
                     progress: Callable[[int, int], None] | None = None) -> dict:
    started = time.perf_counter()
    source = Path(source)
    digest = file_sha256(source)
    verified_at = time.perf_counter()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("El archivo original cambió después de la carga")
    cache_path = extraction_path(source)
    extraction = None
    try:
        with cache_path.open("r", encoding="utf-8") as stream:
            candidate = json.load(stream)
        if _valid_cache(candidate, digest):
            extraction = candidate
    except (OSError, ValueError, TypeError):
        pass
    cache_checked_at = time.perf_counter()
    reused = extraction is not None
    if extraction is None:
        extraction = extract_document(source, progress=progress)
        extraction["source_sha256"] = digest
        _save_atomic(cache_path, extraction)
    elif progress:
        progress(len(extraction["pages"]), len(extraction["pages"]))
    recognized_at = time.perf_counter()
    outcome = interpret_extraction(extraction, declared)
    interpreted_at = time.perf_counter()
    outcome["extracted"].update({
        "ocr_reutilizado": reused,
        "tiempo_ocr_s": 0.0 if reused else extraction["ocr_seconds"],
        "tiempo_procesamiento_s": round(interpreted_at - started, 4),
        "tiempos_etapas_s": {
            "verificacion_archivo": round(verified_at - started, 4),
            "lectura_cache": round(cache_checked_at - verified_at, 4),
            "extraccion_y_guardado": round(recognized_at - cache_checked_at, 4),
            "interpretacion": round(interpreted_at - recognized_at, 4),
        },
    })
    return outcome
