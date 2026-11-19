"""Intake assistance and plain-language construction site entry orientation.

An assistance flag describes a *request for help*, not intelligence, education or
legal eligibility. Required paperwork is never waived; document collection is
postponed until the person is ready and a secure channel is established.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

EntityType = Literal["unknown", "company", "individual"]


def _normal(text: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                    if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", value).split())


def assistance_signal(message: str, is_audio: bool = False) -> str | None:
    """Only explicit, observable questions or requests; don't infer education or ability."""
    if is_audio:
        return "Solicitó comunicación por audio; requiere atención humana para escucharlo"
    text = _normal(message)
    if re.search(r"\b(no necesito ayuda|ya entiendo|no tengo dudas)\b", text):
        return None
    confusion = [
        "no entiendo", "no comprendo", "no cacho", "me confundo",
        "no se como", "no se sacar", "no se que es", "no se que son",
        "no se hacerlo", "no puedo llenar", "no puedo completar",
        "no se escribir", "no se rellenar", "no puedo subir",
        "me cuesta entender", "me cuesta escribir", "no tengo idea",
        "no se que papel", "no se que documento",
    ]
    if any(term in text for term in confusion):
        return "La persona expresó dificultades con la explicación o el trámite"
    if any(term in text for term in [
        "que documentos", "que papeles", "cuales documentos", "cuales papeles",
        "que necesito para entrar", "como hago el f30", "como saco el f30",
        "necesito ayuda con documentos", "ayudame con los papeles",
        "como consigo los papeles", "como entro a obra", "que es mutualidad",
        "que es el f30", "que es la mutual",
    ]):
        return "Solicitó orientación sobre documentación o ingreso a obra"
    return None


def reply_for_support(reason: str, trade_known: bool = False) -> str:
    if "audio" in reason:
        return "Recibí tu audio. Se lo dejé al equipo para que lo revise. Puedes seguir escribiendo por aquí."
    if "documentación" in reason or "trámite" in reason:
        return ("Vamos de a poco con los papeles. "
                + ("¿Qué parte te dejó dudas?" if trade_known else "¿Para qué trabajo estás postulando?"))
    return "Te ayudo. ¿Qué parte te dejó dudas?"


def onboarding_guide(entity_type: EntityType = "unknown",
                     has_employees: bool | None = None, trade: str = "",
                     needs_support: bool = False) -> dict:
    """Explain the user's supplied intake list conditionally; never legal clearance."""
    if entity_type not in {"company", "individual", "unknown"}:
        raise ValueError("Tipo de contratista inválido")
    base: list[str] = []
    conditional: list[str] = []
    not_applicable: list[str] = []
    questions: list[str] = []
    if entity_type == "unknown":
        questions.append("¿Trabajas con una empresa o a tu propio nombre?")
    else:
        conditional.append("Inicio de actividades SII, según situación tributaria")
        if entity_type == "company":
            base.extend([
                "Constitución de la sociedad o estatuto actualizado",
                "Identidad del representante legal por un canal seguro",
            ])
        else:
            conditional.append("Identificación del titular por canal seguro")
            not_applicable.append("Constitución de sociedad: no corresponde sin sociedad")
    if has_employees is None:
        questions.append("¿Trabajas solo o tienes trabajadores contratados?")
    elif has_employees:
        base.extend([
            "F-30: certificado de antecedentes laborales/previsionales, revisar vigencia y resultado",
            "Contratos de trabajo de quienes ingresarán a obra",
        ])
        conditional.append("Certificado de afiliación a mutualidad o ISL, según corresponda")
    else:
        not_applicable.append("Contratos de trabajadores: no corresponde si no existen empleados")
        conditional.extend([
            "Revisar obligaciones laborales/previsionales que correspondan al caso; no exigir F-30 de empleador automáticamente",
            "Revisar cobertura para accidentes del trabajo como independiente",
        ])
    prevention = [
        "Ejemplo: participar en inducción de seguridad de la obra",
        "Ejemplo: usar casco, zapatos y otros elementos de protección según tarea",
        "Ejemplo: conocer los riesgos de las herramientas y del lugar de trabajo",
    ]
    term = _normal(trade)
    if "gasfit" in term or "sanitari" in term:
        prevention.append("Gasfitería: ejemplo de corte de cañerías, herramientas y riesgos específicos de instalaciones")
    elif "carpint" in term or "muebl" in term:
        prevention.append("Carpintería: ejemplo de herramientas eléctricas, cortes, polvo y protección ocular")
    elif "pintur" in term:
        prevention.append("Pintura: ejemplo de ventilación, sustancias utilizadas y protección al trabajar en altura")
    return {
        "phase": "help_first" if needs_support else "orientation",
        "next_question": (questions[0] if questions else None),
        "required_for_review": base,
        "conditional": conditional,
        "not_applicable": not_applicable,
        "prevention_examples": prevention,
        "notice": "Orientación preliminar. No reemplaza revisión documental ni autorización de ingreso.",
        "ask_for_files_now": False,
        "secure_channel_required": True,
        "human_followup": needs_support,
    }
