"""Motor determinista JAVIERA: nunca confunde un PDF con firma o entrega.

El cliente muestra estimaciones inmediatas; el servidor decide si puede emitir.
Las reglas configurables son declarativas (sin eval ni ejecución de código).
"""
from __future__ import annotations
import re
import unicodedata

DOCUMENTS = [
    ("labor_contract", "Zona Subcontratos", "Contrato de trabajo", "laboral",
     ["employer.name", "employer.rut", "worker.name", "worker.rut", "site.name",
      "contract.start", "contract.salary", "contract.hours"]),
    ("transfer_addendum", "Zona Subcontratos", "Anexo de traslado", "traslado",
     ["employer.name", "worker.name", "worker.rut", "site.name", "contract.transfer_date"]),
    ("sworn_declaration", "Zona Subcontratos", "Declaración jurada", "declaracion",
     ["employer.name", "worker.name", "worker.rut", "contract.declaration_reason"]),
    ("extension_addendum", "Zona Subcontratos", "Anexo extensión de contrato", "prorroga",
     ["employer.name", "worker.name", "worker.rut", "contract.end", "contract.new_end"]),
    ("internal_rules_receipt", "Prevención de Riesgos", "Recepción de Reglamento Interno", "reglamento",
     ["employer.name", "worker.name", "worker.rut", "contract.regulation_version", "event.date"]),
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


def normalize_cargo(value: str | None) -> str:
    text = unicodedata.normalize("NFD", (value or "").strip().upper())
    return re.sub(r"\s+", " ", "".join(c for c in text if unicodedata.category(c) != "Mn"))


def validate_requirements(data: dict, required: list[str]) -> tuple[list[str], list[str]]:
    missing = [key for key in required if field(data, key) in (None, "", [], {})]
    errors = []
    for key in ("worker.rut", "employer.rut"):
        if key not in missing and key in required and not rut_valid(field(data, key)):
            errors.append(key + ": RUT inválido")
    contract = data.get("contract") or {}
    if contract.get("start") and contract.get("end") and contract["end"] < contract["start"]:
        errors.append("contract.end: término anterior al ingreso")
    if contract.get("end") and contract.get("new_end") and contract["new_end"] <= contract["end"]:
        errors.append("contract.new_end: extensión debe ser posterior al término actual")
    if contract.get("salary") and (not str(contract["salary"]).replace(".", "").isdigit() or
                                   float(str(contract["salary"]).replace(".", "")) <= 0):
        errors.append("contract.salary: monto inválido")
    if contract.get("hours"):
        try:
            if not 0 < float(contract["hours"]) <= 45:
                errors.append("contract.hours: jornada inválida")
        except (TypeError, ValueError):
            errors.append("contract.hours: jornada inválida")
    return missing, errors


def eligibility(data: dict, templates: dict, matrix_approved: set[str] | None = None,
                existing: set[str] | None = None) -> list[dict]:
    """La falta de aprobación impide la emisión aunque todos los datos estén."""
    matrix_approved = matrix_approved or set()
    existing = existing or set()
    event = data.get("event_type") or "ingreso"
    kind = data.get("employment_type") or ""
    has_context = bool(field(data, "employer.name") or field(data, "worker.name") or field(data, "site.name"))
    results = []
    for code, area, title, mode, defaults in DOCUMENTS:
        template = templates.get(code)
        settings = template or {}
        required = settings.get("fields") or defaults
        missing, errors = validate_requirements(data, required)
        reason = ""
        applies = "aplica"
        if not has_context:
            applies, reason = "por_determinar", "Selecciona empresa, obra o trabajador"
        elif mode == "laboral" and kind == "independiente":
            applies, reason = "no_aplica", "No consta vínculo laboral dependiente"
        elif mode == "laboral" and kind != "dependiente":
            applies, reason = "por_determinar", "Confirma el vínculo laboral"
        elif mode in {"traslado", "prorroga", "declaracion", "reglamento", "entrega_epp",
                      "recepcion_pts", "induccion"} and event != mode and event != "ingreso":
            applies, reason = "no_aplica", "Este documento no corresponde al evento seleccionado"
        elif mode in {"traslado", "prorroga", "declaracion"} and event != mode:
            applies, reason = "no_aplica", "Se emite solo al registrar el evento correspondiente"
        elif mode in {"reglamento", "entrega_epp", "recepcion_pts", "induccion"} and event == "ingreso":
            # La emisión de un acuse exige un evento real o evidencia, nunca solo completar el formulario.
            applies, reason = "por_determinar", "Confirma que el evento y la entrega ocurrieron"
        if code in existing and applies != "no_aplica":
            status = "EXISTENTE_POR_VERIFICAR"
            reason = "Hay un PDF histórico; verifica vigencia, firma y contexto"
        elif applies == "no_aplica":
            status = "NO_APLICA"
        elif applies == "por_determinar":
            status = "POR_DETERMINAR"
        elif missing or errors:
            status = "FALTAN_DATOS"
        elif code in ("pts", "irl") and normalize_cargo(field(data, "role")) not in matrix_approved:
            status, reason = "PENDIENTE_REVISION", "Matriz preventiva no aprobada para este cargo"
        elif not template or not template.get("published_version"):
            status, reason = "PENDIENTE_REVISION", "Plantilla no aprobada"
        else:
            status = "LISTO_PARA_EMITIR"
        results.append(dict(code=code, area=settings.get("area", area), title=settings.get("title", title),
            applicability=applies, status=status, reason=reason, missing_fields=missing,
            blocking_errors=errors, completion_percent=round(
                100 * (len(required) - len(missing)) / max(1, len(required))),
            can_preview=applies == "aplica" and not missing and not errors,
            can_issue=status == "LISTO_PARA_EMITIR",
            template_version=settings.get("published_version", 0),
            has_history=code in existing))
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
