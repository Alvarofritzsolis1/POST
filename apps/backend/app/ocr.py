"""Motor OCR POST: texto nativo primero, Tesseract regional y rescate opcional RapidOCR.

No calcula de manera independiente autenticidad ni confirma transacciones externas.
Cada documento se analiza localmente, sin transmitir imágenes a terceros.
"""
from __future__ import annotations
from pathlib import Path
import fitz
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
from .config import settings
from .rules import assess_document


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
        "tokens": [
            {"texto": w[4], "bbox": [round(x, 1) for x in w[:4]], "confianza": None}
            for w in words[:150]
        ],
    }


def run_tesseract(image: Image.Image, n: int) -> dict:
    lang = settings().ocr_language
    image = ImageOps.exif_transpose(image.convert("RGB"))
    image.thumbnail((3300, 4300))
    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT, timeout=8)
        rotation = int(osd.get("rotate", 0)) % 360
        if rotation:
            image = image.rotate(rotation, expand=True)
    except (pytesseract.TesseractError, ValueError, RuntimeError):
        pass

    def extract(img, mode):
        try:
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT, config="--psm 6", timeout=45)
        except pytesseract.TesseractError:
            data = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.DICT, config="--psm 6", timeout=45)
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
            if len(tokens) < 150:
                x, y, w, h = (int(data[field][i]) for field in ("left", "top", "width", "height"))
                tokens.append({"texto": word, "bbox": [x, y, x+w, y+h], "confianza": round(conf, 1)})
        content = "\n".join(" ".join(line) for line in keys.values())
        score = round(sum(scores) / len(scores), 1) if scores else 0.0
        return {"page": n, "method": mode, "confidence": score, "text": content, "tokens": tokens}

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
        from rapidocr import RapidOCR
        engine = RapidOCR()
        result = engine(np.array(image.convert("RGB")))
        texts = [str(t) for t in result.txts] if result.txts is not None else []
        boxes = result.boxes if result.boxes is not None else []
        scores = [float(s) for s in result.scores] if result.scores is not None else []
        tokens = []
        for i, txt in enumerate(texts[:150]):
            box = boxes[i].tolist() if hasattr(boxes[i], "tolist") else boxes[i]
            tokens.append({"texto": str(txt), "bbox": box, "confianza": round(float(scores[i])*100, 1) if i < len(scores) else None})
        return {"page": n, "method": "rapidocr", "confidence": round(sum(float(x) for x in scores)*100/len(scores), 1) if scores else 0,
                "text": "\n".join(map(str, texts)), "tokens": tokens}
    except (ImportError, AttributeError, ValueError, RuntimeError, TypeError, IndexError):
        return None


def scanned_page(image: Image.Image, n: int) -> dict:
    primary = run_tesseract(image, n)
    if primary["confidence"] >= 68 and len(primary["text"]) >= 100:
        return primary
    secondary = rapidocr_optional(image, n)
    if secondary and len(secondary["text"]) > len(primary["text"]) * 1.2 and secondary["confidence"] >= primary["confidence"]:
        return secondary
    return primary


def looks_rasterized(page: fitz.Page) -> bool:
    area = max(1, page.rect.get_area())
    try:
        coverage = sum(r.get_area() / area for record in page.get_images(full=True)
                       for r in page.get_image_rects(record[0]))
    except (ValueError, RuntimeError):
        coverage = 0
    return coverage > 0.24


def read_pdf_page(page: fitz.Page, n: int) -> dict:
    original = native_page(page, n)
    digital = original["text"].strip()
    if len(digital) > 130 and not looks_rasterized(page):
        return original
    image = rasterize(page)
    scanned = scanned_page(image, n)
    if digital and scanned["text"]:
        if len(scanned["text"]) < 30 and len(digital) > 80:
            return original
        scanned["method"] = "hibrido:" + scanned["method"]
        scanned["text"] = digital + "\n" + scanned["text"]
        return scanned
    return scanned if len(scanned["text"]) > len(digital) else original


def analyze(path: str | Path, declared: str = "auto") -> dict:
    path = Path(path)
    results = []
    if path.suffix.lower() == ".pdf":
        with fitz.open(path) as pdf:
            if pdf.is_encrypted or not 1 <= len(pdf) <= settings().max_pdf_pages:
                raise ValueError("PDF cifrado, vacío o supera el límite de páginas")
            for i, page in enumerate(pdf):
                results.append(read_pdf_page(page, i + 1))
    else:
        with Image.open(path) as img:
            if img.width * img.height > 22_000_000:
                raise ValueError("Imagen demasiado grande")
            results.append(scanned_page(img.copy(), 1))
    return assess_document(results, declared)
