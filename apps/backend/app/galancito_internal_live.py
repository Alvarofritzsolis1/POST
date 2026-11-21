"""Permission-scoped, read-only live facts for GALANT's internal assistant.

No arbitrary model-generated SQL, external HTTP, or private Messenger contents.
Callers receive deterministic answers from actual authorized rows, or an
explicit explanation of a missing capability.
"""
from collections import Counter
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


def _site_scope(db: Session, user: User, message: str, history: list[str]):
    sites = _authorized_sites(db, user)
    current = key(message)
    matching = [(id, name) for id, name in sites if key(name) in current]
    if matching:
        return matching, True
    # Context is confined to the latest user message with a named authorized site.
    if len(current) < 75 and any(term in current for term in (
            "y cuales", "y cuantos", "y las", "y los", "y que", "y como",
            "tambien", "y ahora", "los pendientes")):
        for prior in reversed(history[-4:]):
            found = [(id, name) for id, name in sites if key(name) in key(prior)]
            if found:
                return found, True
    return sites, False


def _counts(db, user: User, site_ids: list[str]):
    org = user.org_id
    states = dict(db.execute(
        select(NetworkRequirement.state, func.count(NetworkRequirement.id))
        .where(NetworkRequirement.org_id == org, NetworkRequirement.site_id.in_(site_ids))
        .group_by(NetworkRequirement.state)
    ).all())
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
        NetworkRequirement.state == "published", NetworkRequirement.deadline < today()
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
               NetworkCandidateFollowUp.follow_up_on <= today())
    ) or 0
    return {"needs": states, "active": active, "urgent": urgent, "overdue": overdue,
            "posts": posts, "followups_due": due}


def _summarize_counts(values):
    posts = ", ".join(f"{state}: {count}" for state, count in sorted(values["posts"].items()))
    return (f"Necesidades vigentes: {values['active']}; urgentes: {values['urgent']}; "
            f"con fecha límite vencida: {values['overdue']}; seguimientos programados hasta hoy: "
            f"{values['followups_due']}. Publicaciones por estado: {posts or 'sin registros'}.")


def internal_reply(db: Session, user: User, message: str, history: list[str] | None = None):
    """Return (text, intent) for a bounded, permission-aware internal question."""
    if user.role not in {"admin", "resident"}:
        return "Este perfil no tiene acceso al asistente interno.", "permission"
    normalized = key(message)
    if any(part in normalized for part in ("contrasena", "clave secreta", "token de acceso",
                                           "credenciales", "exporta datos privados", "rut de", "password")):
        return "No puedo entregar contraseñas, credenciales ni información personal por el chat.", "permission"
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
    if any(word in normalized for word in ("contratista", "cotizacion", "documento", "f30", "finiquito")):
        if user.role != "admin":
            return "La consulta documental y de contratistas requiere un perfil autorizado de administración.", "permission"
        if any(word in normalized for word in ("cotizacion", "documento", "f30", "finiquito")):
            data = dict(db.execute(select(MonthlyDocument.review_status, func.count(MonthlyDocument.id))
                .join(ContractorWorksite, MonthlyDocument.association_id == ContractorWorksite.id)
                .where(MonthlyDocument.org_id == user.org_id, ContractorWorksite.org_id == user.org_id,
                       ContractorWorksite.worksite_id.in_(ids))
                .group_by(MonthlyDocument.review_status)).all())
            return (f"Documentos mensuales registrados para {label}, agrupados por estado de revisión: "
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
