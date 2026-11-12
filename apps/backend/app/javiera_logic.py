"""Motor determinista JAVIERA: nunca confunde un PDF con firma o entrega.

El cliente muestra estimaciones inmediatas; el servidor decide si puede emitir.
Las reglas configurables son declarativas (sin eval ni ejecución de código).
"""
from __future__ import annotations
import re
import unicodedata
from datetime import date

DOCUMENTS = [
    ("labor_contract", "Zona Subcontratos", "Contrato de trabajo", "laboral",
     ["employer.name", "employer.rut", "worker.name", "worker.rut", "site.name",
      "contract.start", "contract.salary", "contract.hours"]),
    ("transfer_addendum", "Zona Subcontratos", "Anexo de traslado", "traslado",
     ["employer.name", "worker.name", "worker.rut", "site.name", "contract.transfer_date"]),
    ("sworn_declaration", "Zona Subcontratos", "Declaración jurada", "declaracion",
     ["employer.name", "employer.rut", "extra.representative_name",
      "extra.representative_rut", "contract.declaration_reason", "event.date"]),
    ("extension_addendum", "Zona Subcontratos", "Anexo extensión de contrato", "prorroga",
     ["employer.name", "worker.name", "worker.rut", "contract.end", "contract.new_end"]),
    ("internal_rules_receipt", "Prevención de Riesgos", "Recepción de Reglamento Interno", "reglamento",
     ["employer.name", "worker.name", "worker.rut", "event.date"]),
    ("ppe_delivery", "Prevención de Riesgos", "Entrega de EPP", "entrega_epp",
     ["worker.name", "worker.rut", "role", "event.date", "event.epp_items"]),
    ("irl", "Prevención de Riesgos", "IRL de acuerdo con el cargo", "preventivo",
     ["worker.name", "worker.rut", "role", "site.name"]),
    ("pts", "Prevención de Riesgos", "PTS", "preventivo",
     ["worker.name", "worker.rut", "role", "site.name"]),
    ("pts_receipt", "Prevención de Riesgos", "Recepción de PTS", "recepcion_pts",
     ["worker.name", "worker.rut", "role", "event.date", "event.pts_version"]),
    ("induction", "Prevención de Riesgos", "Inducción de Prevención para contratistas", "induccion",
     ["employer.name", "worker.name", "worker.rut", "site.name", "event.date"]),
]
# Requisitos específicos derivados de las referencias reales del XLSX.
# Las plantillas Excel se publican solo si las variables necesarias existen.
LAYOUT_REQUIRED = {
    "labor_contract": [
        "extra.representative_name", "extra.representative_rut",
        "extra.employer_address", "extra.employer_commune",
        "extra.employer_city", "extra.worker_nationality",
        "extra.worker_birthdate", "extra.worker_marital_status",
        "extra.worker_address", "extra.worker_commune",
        "extra.payment_frequency", "extra.bank_account",
        "extra.afp", "extra.health_provider", "event.date",
        "contract.end",
    ],
    "transfer_addendum": [
        "event.date", "extra.employer_city", "extra.site_address",
        "role",
    ],
    "extension_addendum": [
        "extra.representative_name", "extra.representative_rut",
        "event.date", "contract.start", "contract.end", "contract.new_end",
    ],
    "sworn_declaration": [
        "extra.representative_name", "extra.representative_rut",
        "extra.representative_nationality",
        "extra.employer_address", "extra.employer_city",
        "extra.specialty", "extra.site_address",
        "extra.principal_company", "extra.declaration_period",
        "event.date",
    ],
    "internal_rules_receipt": ["extra.employer_city", "event.date"],
    "ppe_delivery": ["event.date", "event.epp_items"],
    "irl": ["event.date", "role"],
    "pts": ["event.date", "extra.representative_name", "extra.representative_rut"],
    "pts_receipt": ["event.date", "extra.representative_name", "extra.representative_rut"],
    "induction": [
        "extra.representative_name", "extra.representative_rut",
        "extra.employer_phone", "extra.employer_address",
        "extra.specialty", "extra.site_address", "event.date", "role",
        "extra.principal_company",
    ],
}

DOCUMENT_BY_CODE = {row[0]: row for row in DOCUMENTS}
ROLES = {"laboral", "traslado", "prorroga", "declaracion", "reglamento",
         "entrega_epp", "preventivo", "recepcion_pts", "induccion"}
EVENTS = {"ingreso", "reingreso", "actualizacion", "traslado", "prorroga",
          "cambio_cargo", "cambio_obra", "declaracion", "entrega_epp",
          "reglamento", "recepcion_pts", "induccion"}
SAFE_FIELD = re.compile(r"^(employer|worker|site|contract|event|extra)\.[a-z][a-z0-9_]{0,50}$|^role$")


def field(data: dict, key: str):
    if key == "role":
        return data.get("role")
    node = data
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def rut_valid(value: str | None) -> bool:
    if not value:
        return False
    normalized = re.sub(r"[.\-\s]", "", str(value)).upper()
    if not re.fullmatch(r"\d{7,8}[\dK]", normalized):
        return False
    digits, dv = normalized[:-1], normalized[-1]
    total = sum(int(ch) * (2 + idx % 6) for idx, ch in enumerate(reversed(digits)))
    check = 11 - (total % 11)
    return ("0" if check == 11 else "K" if check == 10 else str(check)) == dv


CARGO_ALIASES = {
    "PINTURA":"PINTOR", "PINTURAS":"PINTOR", "MAESTRO PINTOR":"PINTOR",
    "CARPINTERIA":"CARPINTERO", "CARPINTERIA OBRA GRUESA":"CARPINTERO",
    "GASFITERIA":"GASFITER", "GASFINTERIA":"GASFITER",
    "TECHUMBRE":"TECHADOR", "TECHUMBRES":"TECHADOR",
    "ALUMINIO":"ALUMINERO", "ALUMINERIA":"ALUMINERO",
    "CERAMICA":"CERAMISTA", "CERAMICAS":"CERAMISTA",
    "IMPERMEABILIZACION":"IMPERMEABILIZADOR",
    "ENFIERRADURA":"ENFIERRADOR", "ENFIERRADO":"ENFIERRADOR",
    "MOLDAJE":"MOLDAJERO", "MOLDAJES":"MOLDAJERO",
    "HORMIGONADO":"OPERARIO DE HORMIGON", "HORMIGON":"OPERARIO DE HORMIGON",
    "URBANIZACION":"OPERARIO DE URBANIZACION",
    "ESTRUCTURAS METALICAS":"ESTRUCTURERO METALICO",
}


def normalize_cargo(value: str | None) -> str:
    text = unicodedata.normalize("NFD", (value or "").strip().upper())
    raw = re.sub(r"\s+", " ", "".join(c for c in text if unicodedata.category(c) != "Mn"))
    return CARGO_ALIASES.get(raw, raw)


def ordinary_weekly_hours_limit(effective_date: str | None) -> int:
    """Jornada ordinaria general de Chile, según transición Ley 21.561.

    Se usa la fecha del evento documentado (no la fecha actual del servidor).
    Regímenes especiales y excepciones quedan sujetos a revisión laboral.
    """
    try:
        when = date.fromisoformat(str(effective_date or date.today().isoformat())[:10])
    except (ValueError, TypeError):
        when = date.today()
    if when >= date(2028, 4, 26):
        return 40
    if when >= date(2026, 4, 26):
        return 42
    if when >= date(2024, 4, 26):
        return 44
    return 45


def validate_requirements(data: dict, required: list[str]) -> tuple[list[str], list[str]]:
    missing = [key for key in required if field(data, key) in (None, "", [], {})]
    errors = []
    for key in ("worker.rut", "employer.rut", "extra.representative_rut"):
        if key not in missing and key in required and not rut_valid(field(data, key)):
            errors.append(key + ": RUT inválido")
    for key in ("event.date", "contract.start", "contract.end", "contract.new_end",
                "extra.worker_birthdate"):
        if key not in required:
            continue
        value = field(data, key)
        if value in (None, ""):
            continue
        try:
            date.fromisoformat(str(value)[:10])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
                raise ValueError
        except (ValueError, TypeError):
            errors.append(key + ": fecha inválida (AAAA-MM-DD)")
    period = field(data, "extra.declaration_period")
    if "extra.declaration_period" in required and period and (not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", str(period))):
        errors.append("extra.declaration_period: usa AAAA-MM")
    contract = data.get("contract") or {}
    if "contract.end" in required and contract.get("start") and contract.get("end") and contract["end"] < contract["start"]:
        errors.append("contract.end: término anterior al ingreso")
    if "contract.new_end" in required and contract.get("end") and contract.get("new_end") and contract["new_end"] <= contract["end"]:
        errors.append("contract.new_end: extensión debe ser posterior al término actual")
    if "contract.salary" in required and contract.get("salary") and (not str(contract["salary"]).replace(".", "").isdigit() or
                                   float(str(contract["salary"]).replace(".", "")) <= 0):
        errors.append("contract.salary: monto inválido")
    if "contract.hours" in required and contract.get("hours"):
        try:
            documented_date = (data.get("event") or {}).get("date") or contract.get("start")
            limit = ordinary_weekly_hours_limit(documented_date)
            if not 0 < float(contract["hours"]) <= limit:
                errors.append(
                    f"contract.hours: supera {limit} horas semanales del régimen ordinario general "
                    f"aplicable a la fecha del documento; revisar posibles excepciones con responsable laboral")
        except (TypeError, ValueError):
            errors.append("contract.hours: jornada inválida")
    return missing, errors


def eligibility(data: dict, templates: dict, matrix_approved: set[str] | None = None,
                existing: set[str] | None = None, historical: set[str] | None = None) -> list[dict]:
    """La falta de aprobación impide la emisión aunque todos los datos estén."""
    matrix_approved = matrix_approved or set()
    existing = existing or set()
    historical = historical or set()
    event = data.get("event_type") or "ingreso"
    kind = data.get("employment_type") or ""
    has_context = bool(field(data, "employer.name") or field(data, "worker.name") or field(data, "site.name"))
    results = []
    for code, area, title, mode, defaults in DOCUMENTS:
        template = templates.get(code)
        settings = template or {}
        required = settings.get("fields") or defaults
        custom_rule = settings.get("rule") or {}
        missing, errors = validate_requirements(data, required)
        reason = ""
        applies = "aplica"
        if not has_context:
            applies, reason = "por_determinar", "Selecciona empresa, obra o trabajador"
        elif code == "sworn_declaration" and field(data, "worker.name"):
            applies, reason = "no_aplica", "Esta declaración es de la empresa sin trabajadores; no corresponde a un expediente individual con trabajador asignado"
        elif mode == "laboral" and kind == "independiente":
            applies, reason = "no_aplica", "No consta vínculo laboral dependiente"
        elif mode == "laboral" and kind != "dependiente":
            applies, reason = "por_determinar", "Confirma el vínculo laboral"
        elif mode in {"traslado", "prorroga", "declaracion", "reglamento", "entrega_epp",
                      "recepcion_pts", "induccion"} and event != mode and event != "ingreso":
            applies, reason = "no_aplica", "Este documento no corresponde al evento seleccionado"
        elif mode in {"traslado", "prorroga", "declaracion"} and event != mode:
            applies, reason = "no_aplica", "Se emite solo al registrar el evento correspondiente"
        # Preparar el PDF no implica firma física, entrega ni capacitación realizada.
        # La recepción se acreditará después en el papel firmado.
        allowed_events = custom_rule.get("events")
        allowed_links = custom_rule.get("employment_types")
        if applies == "aplica" and isinstance(allowed_events, list) and allowed_events and event not in allowed_events:
            applies, reason = "no_aplica", "La regla publicada no habilita este evento"
        if applies == "aplica" and isinstance(allowed_links, list) and allowed_links and kind not in allowed_links:
            applies, reason = "no_aplica", "La regla publicada no habilita este tipo de vínculo"
        if code in existing and applies != "no_aplica":
            status = "EMITIDO"
            reason = "PDF emitido para esta revisión; no se sobrescribirá" 
        elif code in historical and applies != "no_aplica":
            status = "EXISTENTE_POR_VERIFICAR"
            reason = "Documento histórico pendiente de verificación de vigencia y contexto"
        elif applies == "no_aplica":
            status = "NO_APLICA"
        elif applies == "por_determinar":
            status = "POR_DETERMINAR"
        elif missing or errors:
            status = "FALTAN_DATOS"
        elif code in ("pts", "irl", "pts_receipt") and (
                ("IRL:" if code == "irl" else "PTS:") + normalize_cargo(field(data, "role"))) not in matrix_approved:
            status, reason = "PENDIENTE_REVISION", "Matriz preventiva específica no aprobada para este cargo"
        elif not template or not template.get("published_version"):
            status, reason = "PENDIENTE_REVISION", "Plantilla no aprobada"
        else:
            status = "LISTO_PARA_EMITIR"
        results.append(dict(code=code, area=settings.get("area", area), title=settings.get("title", title),
            applicability=applies, status=status, reason=reason, missing_fields=missing,
            blocking_errors=errors, completion_percent=round(
                100 * (len(required) - len(missing)) / max(1, len(required))),
            can_preview=applies == "aplica" and not missing and not errors and bool(settings.get("has_body")),
            can_issue=status == "LISTO_PARA_EMITIR",
            template_version=settings.get("published_version", 0),
            has_history=code in existing or code in historical))
    return results


def render_tokens(body: str, data: dict) -> str:
    def replace(match):
        key = match.group(1)
        if not SAFE_FIELD.fullmatch(key):
            raise ValueError("Variable no permitida: " + key)
        value = field(data, key)
        if value in (None, "", [], {}):
            raise ValueError("Campo requerido sin valor: " + key)
        return str(value)
    return re.sub(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", replace, body)


def check_template_fields(fields: list[str], body: str):
    if len(fields) > 70 or len(set(fields)) != len(fields):
        raise ValueError("Cantidad o duplicidad de campos inválida")
    if any(not SAFE_FIELD.fullmatch(f) for f in fields):
        raise ValueError("Campo fuera del catálogo permitido")
    tokens = re.findall(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", body)
    if any(not SAFE_FIELD.fullmatch(f) for f in tokens):
        raise ValueError("Token de plantilla inválido")
    if not set(tokens).issubset(set(fields)):
        raise ValueError("Cada variable del texto debe ser un campo requerido")
