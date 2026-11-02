"""Motor OCR POST: texto nativo primero, Tesseract regional y rescate opcional RapidOCR.

No calcula de manera independiente autenticidad ni confirma transacciones externas.
Cada documento se analiza localmente, sin transmitir imágenes a terceros.
"""
from __future__ import annotations
from difflib import SequenceMatcher
from functools import lru_cache
import logging
import os
from pathlib import Path
import re
import time
from typing import Callable
import fitz
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
from .config import settings
from .rules import assess_document, normalize

OCR_SCHEMA_VERSION = 1
OCR_ENGINE_VERSION = 3
logger = logging.getLogger("galant.post.ocr")


@lru_cache(maxsize=8)
def _available_language(requested: str, tessdata_prefix: str) -> str:
    available = set(pytesseract.get_languages(config=""))
    if all(code in available for code in requested.split("+")):
        return requested
    if "eng" in available:
        return "eng"
    raise RuntimeError("No hay idiomas OCR de Tesseract disponibles")


def effective_ocr_language() -> str:
    return _available_language(settings().ocr_language, os.environ.get("TESSDATA_PREFIX", ""))


def rasterize(page: fitz.Page, dpi: int = 180) -> Image.Image:
    scale = dpi / 72
    if page.rect.width * page.rect.height * scale * scale > 19_000_000:
        raise ValueError("Página demasiado grande para OCR seguro")
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def native_page(page: fitz.Page, n: int) -> dict:
    words = page.get_text("words", sort=True)
    return {
        "page": n, "method": "texto-nativo", "confidence": None,
        "text": page.get_text("text", sort=True),
        "page_size_pt": [round(page.rect.width, 1), round(page.rect.height, 1)],
        "tokens": [
            {"texto": w[4], "bbox": [round(x, 1) for x in w[:4]],
             "confianza": None, "origen": "texto-nativo", "espacio": "pdf-puntos",
             "linea": f"{w[5]}:{w[6]}"}
            for w in words
        ],
    }


def run_tesseract(image: Image.Image, n: int) -> dict:
    lang = effective_ocr_language()
    image = ImageOps.exif_transpose(image.convert("RGB"))
    image.thumbnail((3300, 4300))
    rotation = 0
    orientation_confidence = None
    orientation_failed = False
    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT, timeout=8)
        rotation = int(osd.get("rotate", 0)) % 360
        orientation_confidence = float(osd.get("orientation_conf", 0))
        if rotation:
            # Tesseract expresa el giro horario; Pillow.rotate usa antihorario.
            image = image.rotate(-rotation, expand=True)
    except (pytesseract.TesseractError, ValueError, RuntimeError) as exc:
        orientation_failed = True
        logger.warning("Diagnóstico de orientación OCR falló en página %d: %s", n, type(exc).__name__)

    def extract(img, mode):
        data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT, config="--psm 6", timeout=45)
        keys = {}
        tokens = []
        scores = []
        for i, word in enumerate(data["text"]):
            word = str(word).strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            keys.setdefault(key, []).append(word)
            conf = float(data["conf"][i])
            if conf >= 0:
                scores.append(conf)
            x, y, w, h = (int(data[field][i]) for field in ("left", "top", "width", "height"))
            tokens.append({"texto": word, "bbox": [x, y, x+w, y+h],
                           "confianza": round(conf, 1), "origen": mode,
                           "espacio": "imagen-pixeles", "linea": ":".join(map(str, key))})
        content = "\n".join(" ".join(line) for line in keys.values())
        score = round(sum(scores) / len(scores), 1) if scores else 0.0
        return {"page": n, "method": mode, "confidence": score, "text": content,
                "tokens": tokens, "image_size_px": list(img.size),
                "rotation_degrees_ccw": (-rotation) % 360, "ocr_language_used": lang,
                "orientation_confidence": orientation_confidence,
                "orientation_detection_failed": orientation_failed}

    first = extract(image, "tesseract")
    if first["confidence"] < 55 or len(first["text"]) < 65:
        gray = ImageOps.autocontrast(ImageOps.grayscale(image))
        enhanced = ImageEnhance.Sharpness(gray).enhance(1.5)
        second = extract(enhanced, "tesseract-mejorado")
        if (len(second["text"]) >= max(30, len(first["text"]) * 1.15)
                and second["confidence"] >= first["confidence"] - 5):
            first = second
    return first


def rapidocr_optional(image: Image.Image, n: int) -> dict | None:
    """Segundo motor opcional, no sustituye sin evidencia un valor por otro."""
    if settings().ocr_secondary != "rapidocr":
        return None
    try:
        import numpy as np
        engine = _rapid_engine()
        result = engine(np.array(image.convert("RGB")))
        texts = [str(t) for t in result.txts] if result.txts is not None else []
        boxes = result.boxes if result.boxes is not None else []
        scores = [float(s) for s in result.scores] if result.scores is not None else []
        tokens = []
        for i, txt in enumerate(texts):
            box = boxes[i].tolist() if hasattr(boxes[i], "tolist") else boxes[i]
            tokens.append({"texto": str(txt), "bbox": box,
                           "confianza": round(float(scores[i])*100, 1) if i < len(scores) else None,
                           "origen": "rapidocr", "espacio": "imagen-pixeles", "linea": str(i)})
        return {"page": n, "method": "rapidocr", "confidence": round(sum(float(x) for x in scores)*100/len(scores), 1) if scores else 0,
                "text": "\n".join(map(str, texts)), "tokens": tokens,
                "image_size_px": list(image.size), "rotation_degrees_ccw": 0}
    except (ImportError, AttributeError, ValueError, RuntimeError, TypeError, IndexError) as exc:
        logger.warning("Segunda lectura RapidOCR no disponible en página %d: %s", n, type(exc).__name__)
        return None


@lru_cache(maxsize=1)
def _rapid_engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def scanned_page(image: Image.Image, n: int) -> dict:
    primary = run_tesseract(image, n)
    if primary["confidence"] >= 68 and len(primary["text"]) >= 100:
        return primary
    if settings().ocr_secondary != "rapidocr":
        return primary
    oriented = ImageOps.exif_transpose(image.convert("RGB"))
    oriented.thumbnail((3300, 4300))
    rotation = primary.get("rotation_degrees_ccw", 0)
    if rotation:
        oriented = oriented.rotate(rotation, expand=True)
    secondary = rapidocr_optional(oriented, n)
    if secondary:
        secondary["rotation_degrees_ccw"] = rotation
        primary["alternatives"] = [secondary]
        primary["secondary_comparison"] = {
            "engine": secondary["method"],
            "text_similarity": round(SequenceMatcher(None, normalize(primary["text"]),
                                                       normalize(secondary["text"])).ratio(), 3),
        }
        # Confianzas de motores distintos no son probabilidades comparables.
        # Hasta contar con verdad de referencia, una segunda lectura no reemplaza evidencia.
    return primary


def image_coverage(page: fitz.Page) -> float:
    area = max(1, page.rect.get_area())
    try:
        coverage = sum(r.get_area() / area for record in page.get_images(full=True)
                       for r in page.get_image_rects(record[0]))
    except (ValueError, RuntimeError):
        coverage = 0
    return min(coverage, 1.0)


def _normalized_line(value: str) -> str:
    return re.sub(r"\W+", " ", normalize(value)).strip()


def _novel_ocr_lines(native: str, scanned: str) -> list[str]:
    """Conserva solo líneas OCR que aportan texto frente a la capa digital."""
    native_lines = [_normalized_line(line) for line in native.splitlines()]
    native_flat = " ".join(native_lines)
    novel = []
    for line in scanned.splitlines():
        value = _normalized_line(line)
        if not value:
            continue
        # Una celda breve puede contener una negación que modifica "PAGO".
        if len(value) < 5:
            novel.append(line)
            continue
        if value in native_flat:
            continue
        if any(SequenceMatcher(None, value, other).ratio() >= 0.88 for other in native_lines):
            continue
        novel.append(line)
    return novel


def read_pdf_page(page: fitz.Page, n: int) -> dict:
    started = time.perf_counter()
    original = native_page(page, n)
    digital = original["text"].strip()
    coverage = image_coverage(page)
    if len(digital) > 130 and coverage <= 0.24:
        result = original
    else:
        scanned = scanned_page(rasterize(page), n)
        if digital and scanned["text"]:
            novel = _novel_ocr_lines(digital, scanned["text"])
            if not novel:
                result = original
            else:
                # Las dos lecturas conservan coordenadas y espacio de referencia propios.
                result = {**scanned, "method": "hibrido:" + scanned["method"],
                          "text": digital + "\n" + "\n".join(novel),
                          "tokens": original["tokens"] + scanned["tokens"],
                          "page_size_pt": original["page_size_pt"]}
        else:
            result = scanned if len(scanned["text"]) > len(digital) else original
    result.setdefault("page_size_pt", original["page_size_pt"])
    result["diagnostic"] = {"native_characters": len(digital),
                             "image_coverage": round(coverage, 3),
                             "low_confidence": result["confidence"] is not None and result["confidence"] < 75,
                             "processing_seconds": round(time.perf_counter() - started, 4)}
    return result


def extract_document(path: str | Path,
                     progress: Callable[[int, int], None] | None = None) -> dict:
    """Reconoce el documento completo, sin interpretar campos ni estados de pago."""
    path = Path(path)
    results = []
    started = time.perf_counter()
    if path.suffix.lower() == ".pdf":
        with fitz.open(path) as pdf:
            if pdf.is_encrypted or not 1 <= len(pdf) <= settings().max_pdf_pages:
                raise ValueError("PDF cifrado, vacío o supera el límite de páginas")
            for i, page in enumerate(pdf):
                results.append(read_pdf_page(page, i + 1))
                if progress:
                    progress(i + 1, len(pdf))
    else:
        with Image.open(path) as img:
            if img.width * img.height > 22_000_000:
                raise ValueError("Imagen demasiado grande")
            page = scanned_page(img.copy(), 1)
            page["diagnostic"] = {"native_characters": 0, "image_coverage": 1.0,
                                   "low_confidence": page["confidence"] is not None and page["confidence"] < 75}
            results.append(page)
            if progress:
                progress(1, 1)
    return {"schema_version": OCR_SCHEMA_VERSION, "engine_version": OCR_ENGINE_VERSION,
            "ocr_language": settings().ocr_language, "ocr_language_used": effective_ocr_language(),
            "ocr_secondary": settings().ocr_secondary,
            "pages": results, "ocr_seconds": round(time.perf_counter() - started, 4)}


def interpret_extraction(extraction: dict, declared: str = "auto") -> dict:
    """Puede repetirse sobre el JSON reconocido sin abrir el PDF ni ejecutar OCR."""
    return assess_document(extraction["pages"], declared)


def analyze(path: str | Path, declared: str = "auto") -> dict:
    return interpret_extraction(extract_document(path), declared)
