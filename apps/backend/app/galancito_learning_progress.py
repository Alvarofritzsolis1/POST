"""Measured, read-only progress for Galancito; no external API or token use.

The percentages are *not* a measure of intelligence or model fine-tuning.
They are installed-curriculum coverage and deterministic conversation test passes.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .galancito_knowledge_models import Knowledge
from .galancito_triage import analyze, quick_reply
from .galancito_contractor_conversation import (
    employer_question, employer_response, protect_outgoing,
    sanitized_titles, known_from_history, contractor_followup,
    private_company_names, contains_confidential_name,
)

MODULE = Path(__file__).parent


@lru_cache(maxsize=1)
def curriculum() -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    first = json.loads((MODULE / "galancito_curriculum_2026.json").read_text(encoding="utf-8"))
    second = json.loads((MODULE / "galancito_curriculum_round2.json").read_text(encoding="utf-8"))
    return tuple(first), tuple(second)


def _pct(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


def _tests() -> list[tuple[str, str, bool]]:
    """Named checks on actual response rules; static, anonymous test inputs."""
    tests = []
    def check(topic: str, label: str, passed: bool):
        tests.append((topic, label, bool(passed)))

    check("Confidencialidad", "No confirmar nombre solicitado",
          employer_question("Esto es para Constructora Ejemplo"))
    check("Confidencialidad", "Consulta por contratante",
          employer_question("¿Para qué empresa es el trabajo?"))
    check("Confidencialidad", "Quién contrata",
          employer_question("¿Quién contrata?"))
    check("Confidencialidad", "Empresa mandante",
          employer_question("Quién es el mandante"))
    check("Confidencialidad", "Nunca divulgar nombre",
          "constructora ejemplo" not in protect_outgoing("La oferta es para Constructora Ejemplo").casefold())
    check("Confidencialidad", "Ocultar nombre del título",
          "constructora ejemplo" not in str(sanitized_titles(["Proyecto Constructora Ejemplo en obra"])).casefold())
    check("Confidencialidad", "No bloquear cualquier consulta",
          not employer_question("Soy maestro pintor"))
    check("Confidencialidad", "Respuesta sin identidad",
          "constructora ejemplo" not in employer_response().casefold())
    private_list = private_company_names()
    check("Confidencialidad", "Nombres privados configurados en VPS",
          bool(private_list) and contains_confidential_name(
              "Consulta sobre " + private_list[0])
          and not contains_confidential_name("Trabajo de pintura"))

    check("Atención a contratistas", "Trabajador no es empresa",
          analyze("busco pega de carpintero").intent == "job_seeker")
    check("Atención a contratistas", "Preguntar ubicación laboral",
          "comuna" in (quick_reply("busco pega de carpintero") or "").casefold())
    check("Atención a contratistas", "Empresa declarada",
          analyze("tengo una empresa de pintura").entity_type == "company")
    check("Atención a contratistas", "Cantidad declarada",
          analyze("tengo 4 trabajadores disponibles").workers == 4)
    check("Atención a contratistas", "Ortografía informal",
          analyze("ola soy gasfite").specialty == "Gasfitería")
    check("Atención a contratistas", "No asumir empresa",
          analyze("soy carpintero").entity_type == "unknown")
    check("Atención a contratistas", "Sin prometer contratación",
          "contratado" not in (quick_reply("quiero postular a una obra") or "").casefold())

    known = known_from_history(["Tengo una empresa de pintura con 4 trabajadores disponibles"])
    check("Seguimiento contextual", "Conservar oficio previo", known.get("specialty") == "Pintura")
    check("Seguimiento contextual", "Conservar cantidad previa", known.get("workers") == 4)
    check("Seguimiento contextual", "Conservar empresa declarada", known.get("entity_type") == "company")
    check("Seguimiento contextual", "Preguntar lo que falta",
          "disponibilidad" in (contractor_followup("somos de Coronel", known) or "").casefold())
    check("Seguimiento contextual", "No volver a preguntar la comuna",
          "¿En qué comuna" not in (contractor_followup("somos de Coronel", known) or ""))
    check("Seguimiento contextual", "No recordar un RUT",
          not known_from_history(["Mi RUT es 12.345.678-5"]))
    check("Seguimiento contextual", "Aceptar aclaración",
          "aclaración" in (contractor_followup("No somos carpinteros", known) or "").casefold())

    check("Requisitos y límites", "Preguntar antes de pedir documentos",
          "¿" in (quick_reply("qué documentos necesito") or ""))
    check("Requisitos y límites", "Publicar solo con revisión",
          "revis" in (quick_reply("quiero publicar una necesidad") or "").casefold())
    check("Requisitos y límites", "Ofrecer atención humana",
          "administración" in (quick_reply("quiero hablar con administración") or "").casefold())
    return tests


def learning_progress(db: Session, org_id: str) -> dict:
    first, second = curriculum()
    entries = first + second
    # Only exact, approved curriculum titles count as installed competencies.
    approved = set(db.scalars(select(Knowledge.title).where(
        Knowledge.org_id == org_id,
        Knowledge.status == "approved",
        Knowledge.scope.in_(["red_obras", "both"]),
    )))
    installed = sum(item["title"] in approved for item in entries)
    second_installed = sum(item["title"] in approved for item in second)
    grouped = defaultdict(lambda: {"available": 0, "approved": 0})
    for item in entries:
        row = grouped[item["category"]]
        row["available"] += 1
        row["approved"] += int(item["title"] in approved)
    topics = [{"name": name,
               "percent": _pct(v["approved"], v["available"]),
               "approved": v["approved"], "total": v["available"]}
              for name, v in sorted(grouped.items())]
    checks = _tests()
    suites = defaultdict(lambda: {"passed": 0, "total": 0, "failed": []})
    for group, name, passed in checks:
        suite = suites[group]
        suite["total"] += 1
        suite["passed"] += int(passed)
        if not passed:
            suite["failed"].append(name)
    tests = [{"name": group, "percent": _pct(v["passed"], v["total"]),
              "passed": v["passed"], "total": v["total"]}
             for group, v in sorted(suites.items())]
    privacy = suites["Confidencialidad"]
    gaps = []
    if not private_company_names():
        gaps.append("Configurar en el VPS las empresas cuyos nombres no pueden divulgarse")
    if second_installed < len(second):
        gaps.append("Activar la segunda ronda de conversaciones con contratistas")
    if installed < len(entries):
        gaps.append("Activar y revisar las guías que aún no están disponibles")
    for group, suite in suites.items():
        if suite["failed"]:
            gaps.append("Mejorar " + group.lower() + ": " + ", ".join(suite["failed"][:2]))
    # Honest capability boundaries even with all fixtures passing.
    gaps.extend([
        "Comprobar conversaciones reales anonimizadas de más de cuatro intervenciones",
        "Confirmar vacantes, identidad de mandantes y habilitaciones solo con personal autorizado",
    ])
    return {
        "knowledge": {"percent": _pct(installed, len(entries)), "approved": installed,
                      "total": len(entries)},
        "round2": {"percent": _pct(second_installed, len(second)),
                   "approved": second_installed, "total": len(second)},
        "conversation_tests": {"percent": _pct(sum(v["passed"] for v in suites.values()), len(checks)),
                               "passed": sum(v["passed"] for v in suites.values()), "total": len(checks)},
        "privacy_tests": {"percent": _pct(privacy["passed"], privacy["total"]),
                          "passed": privacy["passed"], "total": privacy["total"]},
        "topics": topics, "suites": tests, "missing": gaps[:5],
        "method": "static_local_checks_and_approved_curriculum",
        "note": "Porcentajes de pruebas locales y guías aprobadas, no nivel de inteligencia ni rendimiento de Gemini.",
        "external_api_calls": 0,
    }
