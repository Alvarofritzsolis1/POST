"""Reglas documentales conservadoras. El texto extraído NO valida pagos oficialmente."""
from __future__ import annotations
import re
import unicodedata

PAID = "Pago acreditado documentalmente"
REVIEW = "Pendiente de revisión"
NOT_ACCREDITED = "Pago no acreditado"
UNREADABLE = "Documento ilegible"
WRONG = "Documento incorrecto"

MONTHS = dict(zip(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    range(1, 13)
))
MONTHS["setiembre"] = 9


def normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def valid_rut(candidate: str) -> bool:
    compact = re.sub(r"[^0-9kK]", "", candidate).upper()
    if len(compact) < 2 or len(compact) > 10 or not compact[:-1].isdigit():
        return False
    digits = list(map(int, compact[:-1]))[::-1]
    score = 11 - sum(n * (2 + i % 6) for i, n in enumerate(digits)) % 11
    return compact[-1] == ("0" if score == 11 else "K" if score == 10 else str(score))


def extract_ruts(value: str) -> list[str]:
    found = []
    regex = r"(?<![0-9])(?:\d{1,2}\.?\d{3}\.?\d{3}|\d{7,8})[-\s]?[0-9kK](?!\w)"
    for match in re.finditer(regex, value):
        raw = match.group()
        if valid_rut(raw):
            compact = re.sub(r"[^0-9kK]", "", raw).upper()
            formatted = str(int(compact[:-1])) + "-" + compact[-1]
            if formatted not in found:
                found.append(formatted)
    return found[:200]


def period_from_text(text: str) -> str | None:
    normalized = normalize(text)
    contexts = r"(?:periodo|mes)(?:\s+de)?(?:\s+(?:remuneraciones|cotizaciones|previsional|remuneracion))?"
    m = re.search(contexts + r"\s*[:\-]?\s*(0?[1-9]|1[0-2])\s*[\/\-]\s*(20\d{2})", normalized)
    if m:
        return f"{m[2]}-{int(m[1]):02}"
    m = re.search(contexts + r"\s*[:\-]?\s*([a-z]+)\s*(?:de\s+)?(20\d{2})", normalized)
    if m and m[1] in MONTHS:
        return f"{m[2]}-{MONTHS[m[1]]:02}"
    return None


def document_type(text: str) -> str:
    s = normalize(text)
    if re.search(r"\bf[-\s]?30[-\s]?1\b", s) or "certificado de cumplimiento de obligaciones laborales" in s:
        return "f30_1"
    if "cotizante independiente" in s or "trabajador independiente" in s:
        return "cotizaciones"
    if any(word in s for word in ("previred", "afp", "fonasa", "isapre", "cotizaciones previsionales", "planilla previsional", "comprobante de pago")):
        return "cotizaciones"
    return "desconocido"


NEGATIVE = re.compile(
    r"declaracion\s+y\s+no\s+pago|declarad[ao]\s+sin\s+pago|"
    r"pendiente\s+de\s+pago|pago\s+rechazado|pago\s+fallido|no\s+pagad[oa]|sin\s+pago"
    r"|\bno\s+pago\b"
)
RECEIPT = re.compile(r"comprobante\s+de\s+pago|recibo\s+de\s+pago|comprobante\s+transaccional")
SUCCESS = re.compile(
    r"(?:estado|resultado|situacion)\s*(?:del?\s+)?(?:pago)?\s*[:\-]?\s*pagad[oa]|"
    r"pago\s+(?:realizado|exitoso|efectuado|aprobado)"
)
TRANSACTION = re.compile(
    r"(?:folio|numero\s+(?:de\s+)?operacion|id\s+(?:de\s+)?transaccion|"
    r"codigo\s+(?:de\s+)?pago)\s*[:#\-]?\s*[a-z0-9][a-z0-9\-]{3,}"
)
FOLIO_LABEL = re.compile(r"^(?:folio|numero\s+(?:de\s+)?operacion|id\s+(?:de\s+)?transaccion|codigo\s+(?:de\s+)?pago)\b")
STATE_LABEL = re.compile(r"^(?:estado|resultado|situacion|pago\s+(?:realizado|exitoso|efectuado|aprobado))\b")


def _evidence_close(text: str, period: str | None) -> bool:
    """Exige que folio, estado, comprobante y período estén cerca en texto lineal."""
    if not period:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    receipts = [i for i, line in enumerate(lines) if RECEIPT.search(line)]
    states = [i for i, line in enumerate(lines) if STATE_LABEL.match(line) and SUCCESS.search(line)]
    folios = [i for i, line in enumerate(lines) if FOLIO_LABEL.match(line) and TRANSACTION.search(line)]
    periods = [i for i, line in enumerate(lines)
               if period_from_text(line + " " + (lines[i + 1] if i + 1 < len(lines) else "")) == period]
    return any(abs(f - s) <= 2 and any(abs(f - r) <= 12 for r in receipts)
               and any(abs(f - p) <= 12 for p in periods)
               for f in folios for s in states)


def assess_page(text: str, page: int, confidence: float | None) -> dict:
    t = normalize(text)
    period = period_from_text(t)
    negative = bool(NEGATIVE.search(t))
    receipt = bool(RECEIPT.search(t))
    status = bool(SUCCESS.search(t))
    operation = bool(TRANSACTION.search(t))
    # Sin parser de filas, cualquier indicio de varios registros exige revisión.
    ambiguous_rows = (bool(re.search(r"\btrabajador(?:es|a|as)?\b|\bnomina\b", t))
                      or len(extract_ruts(text)) > 1
                      or len(list(TRANSACTION.finditer(t))) > 1
                      or len(list(SUCCESS.finditer(t))) > 1)
    nearby = not ambiguous_rows and _evidence_close(t, period)
    enough = bool(receipt and status and operation and period and nearby
                  and not ambiguous_rows and not negative)
    if confidence is not None and confidence < 75:
        enough = False  # números y estados de escaneos dudosos se revisan
    return {
        "page": page, "period": period, "negative": negative,
        "receipt": receipt, "paid_state": status, "transaction": operation,
        "ambiguous_rows": ambiguous_rows, "evidence_close": nearby,
        "evidence_sufficient": enough,
        "reasons": ([] if enough else [
            name for name, ok in (("comprobante", receipt), ("estado de pago", status),
                                  ("folio de operación", operation), ("período", bool(period)),
                                  ("evidencia cercana", nearby),
                                  ("filas sin asociación verificada", not ambiguous_rows),
                                  ("lectura confiable", confidence is None or confidence >= 75))
            if not ok
        ])
    }


def assess_document(pages: list[dict], declared_type: str = "auto") -> dict:
    texts = [p.get("text", "") for p in pages]
    full = "\n".join(texts)
    kind = document_type(full)
    period = next((period_from_text(t) for t in texts if period_from_text(t)), None)
    rows = [assess_page(p.get("text", ""), p["page"], p.get("confidence")) for p in pages]
    notes: list[str] = []
    if len(full.strip()) < 25:
        state = UNREADABLE
        notes.append("No se recuperó texto suficiente")
    elif declared_type != "auto" and declared_type != kind:
        state = WRONG
        notes.append("El documento no corresponde al módulo solicitado")
    elif kind == "desconocido":
        state = WRONG
        notes.append("Formato documental no reconocido")
    elif kind == "f30_1":
        state = REVIEW
        notes.append("F30-1 no prueba por sí mismo una transacción previsional")
    elif any(row["negative"] for row in rows):
        state = REVIEW
        notes.append("Hay una declaración sin pago, un rechazo o una contradicción: verificar")
    elif any(row["evidence_sufficient"] for row in rows):
        state = PAID
        notes.append("Evidencia de pago observada en el archivo; NO verificación externa")
    else:
        state = REVIEW
        notes.append("Sin evidencia documental suficiente; no equivale a impago")
    if any(not p.get("text", "").strip() for p in pages):
        notes.append("Existen páginas sin texto recuperado")
        if state == PAID:
            state = REVIEW
    ruts = extract_ruts(full)
    return {
        "detected_type": kind, "payment_status": state, "page_count": len(pages),
        "extracted": {"periodo": period, "ruts_validos": ruts, "verificacion_externa": False,
                      "controles_por_pagina": rows},
        "warnings": notes,
        "evidence": [{"pagina": p["page"], "motor": p["method"],
                      "confianza_ocr": p.get("confidence"),
                      "extracto": p.get("text", "")[:600],
                      "palabras": p.get("tokens", [])[:150],
                      "control_pago": rows[i]} for i, p in enumerate(pages)]
    }
