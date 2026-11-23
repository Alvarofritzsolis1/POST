"""Reproducible synthetic fixtures for professional intake. Never a LoRA input."""
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .facebook_crm_models import FacebookLead, FacebookLeadTrace, FacebookLeadTrade
from .galancito_contact_profile import contact_profile
from .galancito_intake import intake_question_fields, next_intake_reply, small_talk_reply
from .galancito_memory import (
    apply_messenger_message, capture_voluntary_contact, note_profile_sources, professional_message, profile_facts,
)
from .galancito_triage import plain, quick_reply
from .models import Base, Organization

SOURCE = "sintetico_generado"
EVENT = "synthetic_intake_completed"
WEIGHTS = {"profile": 45, "understanding": 25, "humanity": 20, "continuity": 10}
# Bump when extraction or the evaluation protocol changes, even with the same fixtures.
PROTOCOL = "20.9.32.1"
QWEN_CRITERION = "synthetic_reply"
ANCHOR = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Turn:
    message: str
    expected: dict = field(default_factory=dict)
    prior: str | None = None
    topic: tuple = ()
    states: dict = field(default_factory=dict)
    late: bool = False
    continuity: bool = False


def generate_scenarios():
    """Each case has independent, authored values, context and expected outcomes."""
    return {
        "giro-y-pega": (
            Turn("ola soi carpintreo, busco pega y también ofresco servicios.",
                 {"specialty": "Carpintería", "interest_type": "both", "entity_type": "unknown"}),
            Turn("Trabajo por mi cuenta, soy independiente.",
                 {"entity_type": "individual", "interest_type": "both"}, continuity=True),
        ),
        "cuadrilla-empresa": (
            Turn("Somos una empresa, hacemos enfierradura. Somos seis maestros.",
                 {"entity_type": "company", "specialty": "Enfierradura", "workers": 6,
                  "team_available": True, "has_employees": None, "employee_count": None}),
            Turn("Tenemos 3 trabajadores contratados.",
                 {"has_employees": True, "employee_count": 3, "workers": 6}, continuity=True),
        ),
        "equipo-sin-contratos": (
            Turn("Me dedico a la tabiquería. Puedo ir con dos ayudantes.",
                 {"specialty": "Tabiquería", "workers": 3, "has_employees": None}),
            Turn("No tengo trabajadores contratados.",
                 {"has_employees": False, "employee_count": 0, "workers": 3}, continuity=True),
        ),
        "movilidad-y-domicilio": (
            Turn("Trabajo en Ñuñoa, La Reina y Macul. Vivo en Santiago.",
                 {"work_communes": ["Ñuñoa", "La Reina", "Macul"]}),
            Turn("Corrijo: trabajo solo en La Reina.",
                 {"work_communes": ["La Reina"], "team_available": None},
                 states={"work_communes": "corregido"}, continuity=True),
        ),
        "fecha-retomada": (
            Turn("Estoy disponible mañana.", {"availability": "2026-11-24"}),
            Turn("Corrijo, puedo comenzar el 27/11/2026.", {"availability": "2026-11-27"},
                 states={"availability": "corregido"}, continuity=True),
            Turn("Puedo comenzar el 24/11/2026.", {"availability": "2026-11-27"}, late=True,
                 continuity=True),
        ),
        "fecha-indecisa": (
            Turn("Tal vez pueda partir mañana o el jueves.", {"availability": ""},
                 prior="¿Desde cuándo podrías comenzar?", states={"availability": "ambiguo"}),
            Turn("Ahora sí, puedo partir el 30/11/2026.", {"availability": "2026-11-30"},
                 states={"availability": "confirmado_por_declaracion"}, continuity=True),
        ),
        "oficio-reemplazado": (
            Turn("Soy eléctrico. También hago soldadura.",
                 {"specialty": "Electricidad", "trades": ["Electricidad", "Soldadura"]}),
            Turn("Corrijo: ya no hago electricidad, me dedico a la soldadura.",
                 {"specialty": "Soldadura", "trades": ["Soldadura"]}, continuity=True),
        ),
        "oficio-indeciso": (
            Turn("Pintor o carpintero", {"specialty": "", "trades": []},
                 prior="¿Qué trabajo realizas?", states={"specialty": "ambiguo"}),
        ),
        "nombre-voluntario": (
            Turn("Prefiero no decir", {"name_opt_out": True}, prior="¿Cómo prefieres que te llamemos?",
                 states={"display_name": "rechazado_por_usuario"}),
            Turn("Me llamo Inés.", {"display_name": "Inés", "name_opt_out": False}, continuity=True),
        ),
        "experiencia-corregida": (
            Turn("Llevo 8 años haciendo cerámica.", {"experience": "8 años"}),
            Turn("Corrijo, llevo 8 meses haciendo cerámica.", {"experience": "8 meses"},
                 states={"experience": "corregido"}, continuity=True),
        ),
        "dato-manual": (
            Turn("Corrijo, llevo 7 años.", {"experience": "2 años"}, continuity=True),
        ),
        "contacto-sintetico": (
            Turn("Mi correo es ficha@example.invalid. Soy jardinera.",
                 {"contact_email": "ficha@example.invalid", "specialty": "Jardinería",
                  "contact_state": "canal_voluntario"}),
            Turn("Corrijo, mi correo es jardin@example.invalid.",
                 {"contact_email": "jardin@example.invalid", "specialty": "Jardinería"},
                 states={"contact_email": "corregido"}, continuity=True),
        ),
        "contacto-rechazado": (
            Turn("Prefiero seguir por Messenger.", {"contact_state": "solo_messenger", "contact_phone": "",
                 "contact_email": ""}, prior="¿Prefieres dejar tu teléfono o tu correo?",
                 states={"contact_phone": "rechazado_por_usuario", "contact_email": "rechazado_por_usuario"}),
        ),
        "telefono-sintetico": (
            Turn("Mi celular es +56 9 0000 0000. Trabajo en Coronel.",
                 {"contact_phone": "+56900000000", "work_communes": ["Coronel"],
                  "contact_state": "canal_voluntario"}),
            Turn("Si necesitan coordinar, me pueden llamar.",
                 {"contact_phone": "+56900000000", "contact_email": ""}, continuity=True),
        ),
        "consulta-de-pago": (
            Turn("Busco pega de maestro pintor, cuanto pagan",
                 {"specialty": "Pintura", "contact_phone": ""}, topic=("pago",)),
        ),
        "consulta-de-cupos": (
            Turn("Hay pega de gasfiter?", {"specialty": "", "workers": None}, topic=("cupos", "obra")),
        ),
        "pregunta-y-declaracion": (
            Turn("Soy gasfiter. ¿Cuánto pagan?", {"specialty": "Gasfitería", "has_employees": None},
                 topic=("pago",)),
        ),
        "saludo-retomado": (
            Turn("Hola", {"specialty": "", "display_name": "Interesado de Facebook"}),
            Turn("Hola", {"specialty": ""}, continuity=True),
        ),
        "contratos-sin-capacidad": (
            Turn("Tengo 12 trabajadores contratados.",
                 {"has_employees": True, "employee_count": 12, "workers": None}),
        ),
        "fecha-inmediata-y-cambio-de-rol": (
            Turn("Busco pega de soldadora y puedo empezar hoy.",
                 {"interest_type": "employment", "specialty": "Soldadura", "availability": "2026-11-23"}),
            Turn("Al final ofrezco servicios por mi cuenta.",
                 {"interest_type": "service_offer", "entity_type": "individual", "availability": "2026-11-23"},
                 continuity=True),
        ),
        "pregunta-operativa-despues-del-oficio": (
            Turn("Soy maestro sanitario", {"specialty": "Gasfitería"}),
            Turn("tienen cupos", {"specialty": "Gasfitería"}, topic=("cupos", "obra"), continuity=True),
        ),
    }


# Distinct situations, fixed before evaluation. The reserved set is never used
# by the signed real-data training pipeline or by the development summary.
RESERVED = frozenset({
    "giro-y-pega", "equipo-sin-contratos", "movilidad-y-domicilio", "fecha-retomada",
    "oficio-indeciso", "nombre-voluntario", "dato-manual",
    "pregunta-y-declaracion", "contratos-sin-capacidad", "telefono-sintetico",
    "fecha-inmediata-y-cambio-de-rol", "pregunta-operativa-despues-del-oficio",
})


def dataset_digest(scenarios):
    payload = {"source": SOURCE, "anchor": ANCHOR.isoformat(), "reserved": sorted(RESERVED),
               "cases": {key: [asdict(turn) for turn in turns] for key, turns in scenarios.items()}}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def practice_id(scenarios):
    return str(uuid5(NAMESPACE_URL, PROTOCOL + ":" + dataset_digest(scenarios)))


def reply_cases(scenarios):
    """Each replay targets one concrete question, with its own expected subject."""
    return {case_id: (index, turn) for case_id, turns in scenarios.items()
            for index, turn in enumerate(turns) if turn.topic}


def reply_reference(scenarios, case_id):
    index, turn = reply_cases(scenarios)[case_id]
    previous = scenarios[case_id][:index]
    statements = "\n".join(item.message for item in previous)
    known = {key for item in previous for key, value in item.expected.items()
             if value not in (None, "", "unknown", [])}
    context = ("Declaraciones anteriores:\n" + statements + "\n" if statements else "")
    return context + "Consulta de la persona: " + turn.message, turn, known


def _measure(scenarios, case_ids, engine):
    profile = Counter()
    successful = Counter()
    understanding = []
    continuity = []
    style = []
    unsupported_fields = 0
    privacy_failures = 0
    failed = []
    evaluated_turns = 0
    from .max_power_messenger import objective_checks

    for case_id in sorted(case_ids):
        previous_answer = ""
        prior_facts = {}
        with Session(engine) as session, session.begin():
            org = Organization(name=SOURCE)
            session.add(org)
            session.flush()
            lead = FacebookLead(org_id=org.id, page_id=SOURCE, psid=case_id)
            session.add(lead)
            session.flush()
            if case_id == "dato-manual":
                lead.experience = "2 años"
                note_profile_sources(lead, ["experience"], source="manual", at=ANCHOR)
            lead_id = lead.id
        for index, turn in enumerate(scenarios[case_id], start=1):
            prior = previous_answer if turn.prior is None else turn.prior
            at = ANCHOR + timedelta(seconds=-1 if turn.late else index)
            message_id = f"{SOURCE}-{case_id}-{index}"
            with Session(engine) as session, session.begin():
                lead = session.get(FacebookLead, lead_id)
                if not turn.late:
                    capture_voluntary_contact(session, lead, turn.message, prior, at=at, remote_id=message_id)
                body = professional_message(turn.message)
                changed = apply_messenger_message(session, lead, body, prior, remote_id=message_id,
                                                  at=at, historical=turn.late)
            with Session(engine) as session:
                lead = session.get(FacebookLead, lead_id)
                facts = profile_facts(lead, changed=changed)
                facts["trades"] = sorted(session.scalars(select(FacebookLeadTrade.trade).where(
                    FacebookLeadTrade.org_id == lead.org_id, FacebookLeadTrade.lead_id == lead.id,
                    FacebookLeadTrade.active.is_(True))))
                public = contact_profile(lead)
                actual = {**facts, **{key: getattr(lead, key) for key in ("contact_phone", "contact_email")},
                          "contact_state": public.get("contact_state", "solo_messenger")}
                expected_known = {key for key, value in {**prior_facts, **turn.expected}.items()
                                  if value not in (None, "", "unknown", [], "Interesado de Facebook")}
                answer = "" if turn.late else (
                    small_talk_reply(body, prior) or next_intake_reply(body, facts, prior)
                    or quick_reply(body, known=facts) or "")
                wrong = []
                for field_name, expected in turn.expected.items():
                    profile[field_name] += 1
                    if actual.get(field_name) == expected:
                        successful[field_name] += 1
                    else:
                        wrong.append(field_name)
                        if expected in (None, "", "unknown", []) and actual.get(field_name) not in (None, "", "unknown", []):
                            unsupported_fields += 1
                for field_name, expected in turn.states.items():
                    key = field_name + "_estado"
                    profile[key] += 1
                    source = (lead.profile_sources or {}).get(field_name, {})
                    if (public.get("field_states", {}).get(field_name) == expected
                            and source.get("message_id") == message_id and source.get("at")):
                        successful[key] += 1
                    else:
                        wrong.append(key)
                if not turn.late:
                    evaluated_turns += 1
                    history = [{"role": "outbound", "text": previous_answer}] if previous_answer else []
                    checks = objective_checks({"question": body, "history": history}, answer,
                                              known_fields=expected_known)
                    privacy_failures += int(not checks["safe"])
                    style.append(not (checks["repeated_intro"] or checks["numbered_menu"] or
                                      (previous_answer and plain(previous_answer) == plain(answer))))
                repeated = bool(intake_question_fields(answer) & expected_known)
                if turn.topic:
                    understood = all(word in plain(answer) for word in turn.topic) and not intake_question_fields(answer)
                    understanding.append(understood)
                    if not understood:
                        wrong.append("consulta")
                if turn.continuity:
                    continuity.append(not wrong and not repeated)
                if repeated:
                    wrong.append("pregunta_repetida")
                if wrong:
                    failed.append({"case": case_id, "turn": index, "checks": wrong})
                prior_facts.update(turn.expected)
                if not turn.late:
                    previous_answer = answer

    def count(values):
        return {"passed": sum(values), "samples": len(values)}

    return {
        "cases": len(case_ids), "response_turns": evaluated_turns, "fields": {
            key: {"passed": successful[key], "samples": profile[key]} for key in sorted(profile)
        },
        "dimensions": {"profile": {"passed": sum(successful.values()), "samples": sum(profile.values())},
                       "understanding": count(understanding), "continuity": count(continuity),
                       "humanity": {"passed": None, "samples": 0}},
        "style_signals": count(style),
        "safety": {"unsupported_values": unsupported_fields, "privacy_or_promise_failures": privacy_failures,
                   "gate_passed": not (unsupported_fields or privacy_failures)},
        "failed_checks": failed,
    }


def run_practice(scenarios=None):
    scenarios = generate_scenarios() if scenarios is None else scenarios
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine, tables=[Organization.__table__, FacebookLead.__table__,
                                                FacebookLeadTrade.__table__, FacebookLeadTrace.__table__])
        return {
            "source": SOURCE, "protocol": PROTOCOL, "dataset_sha256": dataset_digest(scenarios),
            "engine": "reglas_messenger_y_sqlite_aislado", "weights_changed": False,
            "production_verified": False, "target_weights": WEIGHTS,
            "development": _measure(scenarios, set(scenarios) - RESERVED, engine),
            "holdout": _measure(scenarios, set(scenarios) & RESERVED, engine),
        }
    finally:
        engine.dispose()
