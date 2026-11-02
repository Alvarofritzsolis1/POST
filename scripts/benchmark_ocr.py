"""Mide OCR inicial y reinterpretación con un PDF sintético o uno autorizado.

No imprime texto, nombres ni identificadores extraídos. El archivo se copia a un
directorio temporal privado; el JSON OCR temporal se elimina al finalizar.
"""
from __future__ import annotations

import argparse
import json
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend"))
from app.ocr import effective_ocr_language  # noqa: E402
from app.pipeline import extraction_path, process_document  # noqa: E402


def synthetic_pdf(path: Path) -> None:
    with fitz.open() as source:
        page = source.new_page()
        for index, line in enumerate(("PREVIRED COMPROBANTE DE PAGO", "Periodo: 10/2026",
                                      "Folio: ABCD123456", "Estado: Pagado")):
            page.insert_text((45, 80 + 45 * index), line, fontsize=19)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB, alpha=False)
        image = pix.tobytes("png")
    with fitz.open() as pdf:
        pdf.new_page().insert_image(pdf[0].rect, stream=image)
        pdf.save(path)


def cpu_seconds() -> float:
    parent = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return parent.ru_utime + parent.ru_stime + children.ru_utime + children.ru_stime


def timed(path: Path, declared: str) -> tuple[dict, dict]:
    start_wall, start_cpu = time.perf_counter(), cpu_seconds()
    result = process_document(path, declared)
    metrics = {"wall_s": round(time.perf_counter() - start_wall, 4),
               "cpu_s_including_tesseract": round(cpu_seconds() - start_cpu, 4),
               "ocr_reused": result["extracted"]["ocr_reutilizado"]}
    return result, metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, help="PDF o imagen autorizada; se copia a un directorio temporal")
    parser.add_argument("--declared", choices=("auto", "cotizaciones", "f30_1"), default="auto")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="galant-benchmark-") as folder:
        temporary = Path(folder)
        temporary.chmod(0o700)
        source = temporary / ("sample" + args.file.suffix.lower() if args.file else "sample.pdf")
        if args.file:
            shutil.copyfile(args.file, source)
        else:
            synthetic_pdf(source)
        source.chmod(0o600)
        first, cold = timed(source, args.declared)
        second, warm = timed(source, args.declared)
        with extraction_path(source).open(encoding="utf-8") as stream:
            extraction = json.load(stream)
        print(json.dumps({
            "source": "authorized-file" if args.file else "synthetic-scan",
            "pages": len(extraction["pages"]),
            "ocr_language_used": effective_ocr_language(),
            "initial": cold, "reanalysis": warm,
            "detected_type": second["detected_type"],
            "payment_status": second["payment_status"],
            "period_detected": bool(second["extracted"]["periodo"]),
            "recognized_characters": sum(len(page["text"]) for page in extraction["pages"]),
            "recognized_tokens": sum(len(page["tokens"]) for page in extraction["pages"]),
            "peak_python_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
