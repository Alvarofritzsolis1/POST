"""Permission-scoped, read-only live facts for GALANT's internal assistant.

No arbitrary model-generated SQL, external HTTP, or private Messenger contents.
Callers receive deterministic answers from actual authorized rows, or an
explicit explanation of a missing capability.
"""
import re
from datetime import date, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .galancito_training_models import TrainingRound
from .models import User
from .network_models import NetworkRequirement, NetworkFacebookPost, NetworkCandidateFollowUp
from .network_service import assigned_sites, key, today
from .ops_models import ContractorWorksite, MonthlyDocument, Worksite
from .version import SOURCE_COMMIT, VERSION


def _authorized_sites(db: Session, user: User):
    query = select(Worksite.id, Worksite.name).where(Worksite.org_id == user.org_id)
    if user.role == "resident":
        query = query.where(Worksite.id.in_(assigned_sites(db, user)))
    return list(db.execute(query.order_by(Worksite.name).limit(150)).all())


def _matching_sites(sites, normalized_text: str):
    matching = [(site_id, name) for site_id, name in sites if key(name) in normalized_text]
    if len(matching) <= 1:
        return matching
    # A longer nested name suppresses the shorter one unless both appear
    # explicitly. Apply the same rule to current and earlier questions.
    return [(site_id, name) for site_id, name in matching if not any(
        key(name) != key(other_name) and key(name) in key(other_name) and
        normalized_text.count(key(name)) <= normalized_text.count(key(other_name))
        for _, other_name in matching
    )]


def _site_scope(db: Session, user: User, message: str, history: list[str]):
    sites = _authorized_sites(db, user)
    current = key(message)
    matching = _matching_sites(sites, current)
    if matching:
        return matching, True
    # Context is confined to the latest user message with a named authorized site.
    if len(current) < 75 and any(term in current for term in (
            "y cuales", "y cuantos", "y cuantas", "y cuanto", "y las", "y los", "y que", "y como",
            "tambien", "y ahora", "los pendientes")):
        for prior in reversed(history[-4:]):
            found = _matching_sites(sites, key(prior))
            if found:
                return found, True
    return sites, False


MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def _requested_month(message: str):
    """Apply an explicit Chilean month/year; never silently filter a whole archive."""
    normalized = key(message)
    base = today()
    if "mes pasado" in normalized or "mes anterior" in normalized:
        previous = base.replace(day=1) - timedelta(days=1)
        return f"{previous.year:04}-{previous.month:02}"
    if "este mes" in normalized or "mes actual" in normalized:
        return f"{base.year:04}-{base.month:02}"
    found = next((index for index, name in enumerate(MONTHS, 1)
                  if re.search(r"\b" + name + r"\b", normalized)), None)
    if found is None:
        return None
    year = re.search(r"\b(20[0-9]{2})\b", normalized)
    return f"{int(year.group(1)) if year else base.year:04}-{found:02}"


def _counts(db, user: User, site_ids: list[str]):
    org = user.org_id
    active = db.scalar(select(func.count(NetworkRequirement.id)).where(
        NetworkRequirement.org_id == org, NetworkRequirement.site_id.in_(site_ids),
        NetworkRequirement.state == "published", NetworkRequirement.end_date >= today()
    )) or 0
    urgent = db.scalar(select(func.count(NetworkRequirement.id)).where(
        NetworkRequirement.org_id == org, NetworkRequirement.site_id.in_(site_ids),
        NetworkRequirement.state == "published", NetworkRequirement.end_date >= today(),
        NetworkRequirement.priority.in_(("high", "urgent"))
    )) or 0
    overdue = db.scalar(select(func.count(NetworkRequirement.id)).where(
        NetworkRequirement.org_id == org, NetworkRequirement.site_id.in_(site_ids),
        NetworkRequirement.state == "published",
        NetworkRequirement.end_date >= today(), NetworkRequirement.deadline < today()
    )) or 0
    posts = dict(db.execute(
        select(NetworkFacebookPost.state, func.count(NetworkFacebookPost.id))
        .join(NetworkRequirement, NetworkRequirement.id == NetworkFacebookPost.requirement_id)
        .where(NetworkFacebookPost.org_id == org,
               NetworkRequirement.org_id == org,
               NetworkRequirement.site_id.in_(site_ids))
        .group_by(NetworkFacebookPost.state)
    ).all())
    due = db.scalar(
        select(func.count(NetworkCandidateFollowUp.id))
        .join(NetworkRequirement, NetworkRequirement.id == NetworkCandidateFollowUp.requirement_id)
        .where(NetworkCandidateFollowUp.org_id == org, NetworkRequirement.org_id == org,
               NetworkRequirement.site_id.in_(site_ids),
               NetworkCandidateFollowUp.follow_up_on <= today(),
               NetworkCandidateFollowUp.stage != "discarded")
    ) or 0
    return {"active": active, "urgent": urgent, "overdue": overdue,
            "posts": posts, "followups_due": due}


def _summarize_counts(values):
    posts = ", ".join(f"{state}: {count}" for state, count in sorted(values["posts"].items()))
    return (f"Necesidades vigentes: {values['active']}; urgentes: {values['urgent']}; "
            f"con fecha límite vencida: {values['overdue']}; seguimientos programados hasta hoy: "
            f"{values['followups_due']}. Publicaciones por estado: {posts or 'sin registros'}.")



def _candidate_reply(db: Session, user: User, question: str, site_ids: list[str]):
    """Reuse the existing permission-checked candidate-matching service."""
    from .network_candidates import requirement_candidates

    requirements = list(db.scalars(
        select(NetworkRequirement).where(
            NetworkRequirement.org_id == user.org_id,
            NetworkRequirement.site_id.in_(site_ids),
            NetworkRequirement.state == "published",
        ).order_by(NetworkRequirement.created_at.desc()).limit(80)
    ))
    if not requirements:
        return "No hay necesidades publicadas para consultar candidatos en estas obras.", "candidates"
    query = key(question)
    matching = [row for row in requirements if key(row.title) in query]
    if len(matching) != 1:
        matching = [row for row in requirements if key(row.specialty) in query]
    if len(matching) != 1 and len(requirements) == 1:
        matching = requirements
    if len(matching) != 1:
        labels = "; ".join(row.title[:75] for row in requirements[:4])
        return (f"Indica la necesidad para comparar candidatos. "
                f"Necesidades disponibles en tus obras: {labels}. "
                "Abre la necesidad para revisar las fichas completas."), "candidates"
    need = matching[0]
    details = requirement_candidates(need.id, limit=4, user=user, db=db)
    total = details["candidate_total"]
    if not total:
        return (f"Para '{need.title}' no hay candidatos compatibles registrados en el panel. "
                "No se infiere interés a partir de comentarios públicos."), "candidates"
    rows = []
    for candidate in details["candidates"][:4]:
        fit = candidate.get("fit") or {}
        score = fit.get("compatibility")
        match = (f"compatibilidad estimada {score}%" if score is not None else
                 "compatibilidad sin verificar")
        trades = ", ".join(candidate.get("trades") or [])[:80] or "oficio por confirmar"
        stage = (candidate.get("tracking") or {}).get("stage", "sin seguimiento")
        rows.append(f"{candidate['name'][:80]} · {trades} · {match} · estado: {stage}")
    cutoff = (" Se muestran solo cuatro candidatos; revisa el panel para ver el resto."
              if total > 4 else "")
    return (f"Necesidad: {need.title}. Candidatos que aparecen en el motor de coincidencias: "
            f"{total}. " + "; ".join(rows) + "." + cutoff +
            " Estas coincidencias son sugerencias, no adjudicaciones; confirma experiencia y disponibilidad."), "candidates"


# Navigation labels verified against App.tsx and Network.tsx navigation tables.
# Informational only: the assistant cannot navigate or modify the current page.
_INTERNAL_NAV = (
    (("facebook", "publicaciones", "publicacion", "anuncios"), "Red de Obras > Facebook"),
    (("necesidades", "necesidad"), "Red de Obras > Necesidades"),
    (("coincidencias", "seguimiento", "postulantes", "candidatos"), "Red de Obras > Seguimiento"),
    (("contratistas", "contratista"), "Contratistas"),
    (("trabajadores", "trabajador"), "Trabajadores"),
    (("asistencia",), "Control de asistencia"),
    (("documentacion", "documental", "documentos", "f30"), "Control documental"),
    (("cotizaciones", "cotizacion", "pagos"), "Cotizaciones y pagos"),
    (("evaluacion administrativa", "evaluaciones"), "Evaluación administrativa"),
    (("importacion", "importar"), "Importación masiva"),
    (("informes", "reporte", "reportes"), "Informes"),
    (("ine",), "INE · Contratistas activos"),
    (("javiera",), "Proyecto JAVIERA"),
    (("configuracion", "usuarios y permisos"), "Configuración"),
    (("red de obras",), "Red de Obras"),
)


def _navigation_answer(message: str, role: str):
    normalized = key(message)
    if not any(phrase in normalized for phrase in (
        "donde", "como encuentro", "en que modulo", "como ingreso",
        "como abro", "como llego", "ir a ", "abrir ", "ubicacion de",
    )):
        return None
    for terms, destination in _INTERNAL_NAV:
        if not any(term in normalized for term in terms):
            continue
        # The resident UI only contains Red de Obras and its own workspace.
        if role == "resident" and not destination.startswith("Red de Obras"):
            return ("Ese apartado no está disponible en la navegación de residente. "
                    "Consulta con administración si necesitas acceso a otra función."), "navigation"
        return (f"Encuentras ese apartado en: {destination}. "
                "Selecciona la sección desde la navegación de GALANT; "
                "no he abierto ni modificado ninguna pantalla."), "navigation"
    return ("No encuentro una ruta verificada para esa función. "
            "Revisa el menú de GALANT o indica el nombre del módulo."), "navigation"


def internal_reply(db: Session, user: User, message: str, history: list[str] | None = None):
    """Return (text, intent) for a bounded, permission-aware internal question."""
    if user.role not in {"admin", "resident"}:
        return "Este perfil no tiene acceso al asistente interno.", "permission"
    normalized = key(message)
    if user.role == "resident":
        permitted = {site_id for site_id, _ in _authorized_sites(db, user)}
        org_sites = list(db.execute(select(Worksite.id, Worksite.name).where(
            Worksite.org_id == user.org_id)).all())
        specified_sites = _matching_sites(org_sites, normalized)
        if any(site_id not in permitted for site_id, _ in specified_sites):
            return "No tienes permiso para consultar la obra solicitada.", "permission"
    if any(part in normalized for part in ("contrasena", "clave secreta", "token de acceso",
                                           "credenciales", "exporta datos privados", "rut de", "password")):
        return "No puedo entregar contraseñas, credenciales ni información personal por el chat.", "permission"
    navigation = _navigation_answer(message, user.role)
    if navigation is not None:
        return navigation
    if any(word in normalized for word in ("version", "desplegada", "commit", "revision")):
        version = f"Versión del backend: {VERSION}."
        revision = f" Commit de compilación: {SOURCE_COMMIT}." if SOURCE_COMMIT != "unbuilt" else (
            " El proceso no contiene identificador de compilación verificable.")
        return version + revision + " Estos datos corresponden al servidor que respondió, no a GitHub.", "version"
    if any(word in normalized for word in ("internet", "buscar en la web", "investigar online", "google")):
        return ("El chat interno aún no tiene un proveedor de búsqueda web configurado y verificado. "
                "No puedo afirmar que haya consultado internet."), "external_unavailable"
    if any(word in normalized for word in ("memoria", "cpu", "ram", "rendimiento", "saturado", "lento", "vps")):
        if user.role != "admin":
            return "Las métricas internas del servidor requieren permisos de administración.", "permission"
        from .galancito_training import ResourceSampler
        try:
            snapshot = ResourceSampler().sample()
        except (OSError, ValueError, KeyError):
            return "No se pudieron obtener métricas confiables del servidor.", "metrics_unavailable"
        available = snapshot.get("available_ram_mb")
        cpu = snapshot.get("host_cpu_percent")
        return (f"Medición actual del entorno del proceso: RAM disponible "
                f"{available if available is not None else 'sin medición'} MB; "
                f"CPU servidor {str(cpu) + '%' if cpu is not None else 'sin medición'}. "
                "No confirma por sí sola la causa de una lentitud; revisa también la latencia del modelo."), "metrics"
    if any(word in normalized for word in ("practica bot", "entrenamiento", "rondas", "laboratorio")):
        if user.role != "admin":
            return "El laboratorio de Práctica Bot es de uso administrativo.", "permission"
        rows = list(db.scalars(select(TrainingRound).where(TrainingRound.org_id == user.org_id)
                               .order_by(TrainingRound.created_at.desc()).limit(3)))
        if not rows:
            return "Práctica Bot no tiene rondas registradas en esta organización.", "training"
        parts = [f"{row.config.get('profile', 'postulantes')}: {row.state} "
                 f"({row.completed}/{row.target} casos)" for row in rows]
        return "Últimas rondas registradas: " + "; ".join(parts) + ".", "training"

    # Scope each query to authorized sites; do not use company-wide counts for residents.
    sites, named = _site_scope(db, user, message, history or [])
    if not sites:
        return "No hay obras consultables con tus permisos actuales.", "no_sites"
    ids = [site_id for site_id, _ in sites]
    label = (", ".join(site_name for _, site_name in sites[:3])
             + (" y otras" if len(sites) > 3 else "")) if named else "las obras autorizadas"
    if any(word in normalized for word in ("postulant", "candidat", "ficha", "mejor opcion", "mas compatible")):
        return _candidate_reply(db, user, message, ids)
    if any(word in normalized for word in ("contratista", "cotizac", "documento", "documentacion", "liquidac", "f30", "finiquito")):
        if user.role != "admin":
            return "La consulta documental y de contratistas requiere un perfil autorizado de administración.", "permission"
        if any(word in normalized for word in ("cotizac", "documento", "documentacion", "liquidac", "f30", "finiquito")):
            period = _requested_month(message)
            query = (select(MonthlyDocument.review_status, func.count(MonthlyDocument.id))
                .join(ContractorWorksite, MonthlyDocument.association_id == ContractorWorksite.id)
                .where(MonthlyDocument.org_id == user.org_id, ContractorWorksite.org_id == user.org_id,
                       ContractorWorksite.worksite_id.in_(ids)))
            if period:
                query = query.where(MonthlyDocument.period == period)
            data = dict(db.execute(query.group_by(MonthlyDocument.review_status)).all())
            period_label = f"período {period}" if period else "todos los períodos"
            return (f"Documentos mensuales registrados para {label} ({period_label}), por estado de revisión: "
                    + (", ".join(f"{status}: {count}" for status, count in sorted(data.items()))
                       or "sin documentos registrados") +
                    ". No equivale a certificar cumplimiento ni a determinar documentos faltantes sin una matriz de exigencias."), "documents"
        active = db.scalar(select(func.count(ContractorWorksite.id)).where(
            ContractorWorksite.org_id == user.org_id,
            ContractorWorksite.worksite_id.in_(ids),
            ContractorWorksite.contract_status == "active")) or 0
        return (f"Contratistas con asociación activa en {label}: {active}. "
                "Es un recuento de asociaciones a obras, no de empresas únicas."), "contractors"
    values = _counts(db, user, ids)
    if any(word in normalized for word in ("postulant", "candidat", "interesado", "seguimiento", "ficha")):
        return (f"Seguimientos con fecha hasta hoy para {label}: {values['followups_due']}. "
                "Esta cifra no incluye automáticamente a todos los interesados sin ficha; "
                "para revisar candidatos concretos usa el panel de la necesidad."), "followups"
    if any(word in normalized for word in ("publicacion", "facebook", "comentario", "anuncio")):
        posts = values["posts"]
        listed = ", ".join(f"{state}: {count}" for state, count in sorted(posts.items()))
        return (f"Publicaciones asociadas a {label}, por estado registrado: {listed or 'sin registros'}. "
                "Estos estados no representan alcance, visitas ni comentarios de Meta si no existen métricas de API."), "publications"
    if any(word in normalized for word in ("informe", "reporte", "resumen", "como vamos", "estado", "pendiente",
                                           "necesidad", "urgente", "atrasado", "obra")):
        prefix = f"Resumen verificable de {label} (consulta {today()}): "
        return prefix + _summarize_counts(values) + " Fuente: registros internos autorizados de Red de Obras.", "overview"
    return ("Puedo consultar la versión de GALANT, un resumen de necesidades, publicaciones, "
            "seguimientos y, según tus permisos, contratistas y documentos. "
            "Para informes profundos o internet necesitaré herramientas adicionales verificadas."), "help"
