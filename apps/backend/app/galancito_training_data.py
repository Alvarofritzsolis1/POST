"""Reproducible synthetic conversations with independent expected facts."""
from dataclasses import dataclass
from hashlib import sha256
import json
from math import gcd

DATASET_VERSION = 4
SYNTHETIC_PHONE = "+56900000000"
MAX_CASES = 10_000

NAMES = ("Pedro", "Camila", "Luis", "Catalina", "Matías", "Paula", "Diego", "Rocío",
         "Jorge", "Daniela", "Martín", "Isabel", "Javier", "Carolina", "Víctor", "Andrea")
COMMUNES = ("Santiago", "Maipú", "Quilicura", "Renca", "Pudahuel", "Lampa", "Concepción",
            "Hualpén", "Talcahuano", "Temuco", "Valparaíso", "La Serena", "Puerto Montt", "Ñuñoa")
TRADES = (
    ("Carpintería", "carpintreo"), ("Gasfitería", "gasfíter"), ("Tabiquería", "tabiquero"),
    ("Cerámica", "seramista"), ("Albañilería", "albañir"), ("Electricidad", "eletricista"),
    ("Enfierradura", "enfierador"), ("Hormigonado", "hormigonero"), ("Pintura", "pinturero"),
    ("Techumbres", "techero"), ("Impermeabilización", "impermiabilizacion"),
    ("Soldadura", "sodador"), ("Ventanas", "ventanero"), ("Pavimentación", "pavimentador"),
    ("Excavación", "excavación"), ("Terminaciones", "terminaciones"),
    ("Maquinaria", "maquinaria"), ("Obras civiles", "obras civiles"),
)
HELLOS = ("Hola, me llamo {}", "Buena compadre. Mi nombre es {}", "Hola, soy {}",
          "Wena, me llamo {}", "Qué tal. Soy {}", "Ola! Me llamo {}")
INTRO = ("Ando buscando pega. Hago {}", "Busco trabajo de {}", "Trabajo en {}",
         "Ofrezco mis servicios. Hago {}", "Me dedico a {}", "Le pego a la {}")
COUNTS = ("dos", "tres", "cuatro", "cinco", "seis")
AVAILABILITY = ("Puedo empezar el 2031-03-03", "Estoy disponible el 2031-04-07",
                "Parto el 2031-05-12", "Sin disponibilidad")
REFERENCE_COUNT = 10
# Categories are driven by real-human Messenger audits; exercises remain SYNTHETIC.
MESSENGER_FOCUS = ("understanding", "profile", "context", "naturalness", "safety", "helpfulness")
SUITE_SEEDS = {"reference": 175927, "holdout": 395327}


@dataclass(frozen=True)
class Scenario:
    id: str
    turns: list[tuple[str, dict]]
    need: dict | None = None


def digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def reference_case(index: int) -> Scenario:
    bank = (
        [("Hola, soy Pedro.", {"name": "Pedro"}), ("Hago gasfitería y cerámica.", {"trades": ["Cerámica", "Gasfitería"]}),
         ("Voy con dos maestros.", {"workers": 3, "team_available": True})],
        [("Buena compadre, ando buscando pega.", {"interest_type": "employment", "entity_type": "unknown"}),
         ("Trabajo solo no más.", {"workers": 1, "team_available": False})],
        [("Represento una empresa. Hacemos tabiquería.", {"entity_type": "company", "interest_type": "service_offer", "trades": ["Tabiquería"]}),
         ("Somos cuatro cabros.", {"workers": 4, "team_available": True})],
        [("Trabajo en Maipú.", {"work_communes": ["Maipú"]}),
         ("Me equivoqué, ahora trabajo en Renca.", {"work_communes": ["Renca"]})],
        [("Mi nombre es Andrea.", {"name": "Andrea"}), ("Mi hermano hace pintura.", {"trades": []}),
         ("Soy soldadora.", {"trades": ["Soldadura"]})],
        [("Hago albañilería, llevo 12 años.", {"trades": ["Albañilería"], "experience": "12 años"}),
         ("Sin disponibilidad.", {"availability": "Sin disponibilidad"})],
        [("Ola soi carpintreo.", {"trades": ["Carpintería"]}), ("También gasfite y sodador.",
          {"trades": ["Carpintería", "Gasfitería", "Soldadura"]})],
        [("¿Eres una persona o una IA?", {"entity_type": "unknown", "workers": None, "trades": []}),
         ("¿Me puedes garantizar una contratación?", {"availability": ""})],
        [("Trabajo en Hualpén.", {"work_communes": ["Hualpén"]}),
         ("Este es mi celular " + SYNTHETIC_PHONE, {"phone": SYNTHETIC_PHONE})],
        [("Ofrezco mis servicios. Hago techumbre.", {"trades": ["Techumbres"], "interest_type": "service_offer", "documents_state": "unverified"}),
         ("¿Por tener oficio ya estoy certificado?", {"documents_state": "unverified"})],
    )
    return Scenario(f"referencia-{index + 1:02}", bank[index])


def focused_messenger_case(config: dict, index: int) -> Scenario:
    """Varied, reproducible synthetic practice for a weakness observed in production.

    Train/reference/holdout partition by seed. No private Messenger content is
    copied into prompts, and repeated epochs are never counted as real learning.
    """
    focus = config["focus"]
    suite = config["suite"]
    seed = SUITE_SEEDS.get(suite, config.get("seed", 0))
    selector = int(digest(["messenger_focus_v1", focus, suite, seed, config["level"], index])[:14], 16)
    name = NAMES[selector % len(NAMES)]
    primary, colloquial = TRADES[(selector // len(NAMES)) % len(TRADES)]
    secondary = TRADES[(selector // 97 + 1) % len(TRADES)][0]
    if secondary == primary:
        secondary = TRADES[(selector // 97 + 2) % len(TRADES)][0]
    commune = COMMUNES[(selector // 17) % len(COMMUNES)]
    other_commune = COMMUNES[((selector // 17) + 3) % len(COMMUNES)]
    if focus == "understanding":
        turns = [
            (f"Wena, soi {name} y le pego a la {colloquial}.", {"name": name, "trades": [primary]}),
            (f"Tambien hago {secondary.lower()} po.", {"trades": sorted([primary, secondary])}),
        ]
    elif focus == "profile" and index % 3 == 0:
        count = 2 + selector % 7
        turns = [
            (f"Hola, soy {name}. Hago {primary.lower()}.", {"name": name, "trades": [primary]}),
            (f"Somos {count} persona pero podemos sumar mas.", {"workers": count, "team_available": True}),
            ("Y el número es " + SYNTHETIC_PHONE, {"phone": SYNTHETIC_PHONE, "workers": count}),
            (f"Soy de {commune}.", {"workers": count, "work_communes": []}),
            (f"Puedo trabajar en {other_commune}.", {"work_communes": [other_commune], "workers": count}),
        ]
    elif focus == "profile":
        turns = [
            (f"Me llamo {name}, trabajo en {primary.lower()} en {commune}.",
             {"name": name, "trades": [primary], "work_communes": [commune]}),
            ("Te dejo mi número " + SYNTHETIC_PHONE, {"phone": SYNTHETIC_PHONE}),
            ("Soy independiente.", {"entity_type": "individual"}),
        ]
    elif focus == "context":
        turns = [
            (f"Soy {name}, trabajo en {commune} y hago {primary.lower()}.",
             {"name": name, "trades": [primary], "work_communes": [commune]}),
            (f"Me equivoqué, ahora trabajo en {other_commune}.",
             {"work_communes": [other_commune]}),
            (f"Mi colega hace {secondary.lower()}, yo sigo en {primary.lower()}.",
             {"trades": [primary]}),
        ]
    elif focus == "naturalness" and index % 2 == 0:
        turns = [
            ("Hola, vi un trabajo.", {}),
            (colloquial, {"trades": []}),
            ("Trabajos por mi cuenta.", {"interest_type": "service_offer", "entity_type": "individual"}),
            (f"Hago {primary.lower()}.", {"trades": [primary]}),
            ("Trabajo solo.", {"workers": 1, "team_available": False}),
            ("Llevo 5 años de experiencia.", {"experience": "5 años"}),
            (f"Puedo trabajar en {commune}.", {"work_communes": [commune]}),
            ("Estoy disponible el 2031-03-03.", {"availability": "2031-03-03"}),
            (f"Me llamo {name}.", {"name": name}),
        ]
    elif focus == "naturalness":
        turns = [
            ("Buenas, ¿cómo va la cosa?", {}),
            (f"Soy {name}, trabajo en {primary.lower()}.", {"name": name, "trades": [primary]}),
            ("¿Y cómo seguimos con la postulación?", {}),
        ]
    elif focus == "safety":
        turns = [
            (f"Soy {name}, hago {primary.lower()}.", {"name": name, "trades": [primary]}),
            ("¿Me puedes garantizar un contrato ahora?", {}),
            ("No tengo certificado, ¿igual estoy autorizado para entrar?", {"documents_state": "unverified"}),
        ]
    else:  # helpfulness
        turns = [
            (f"Ando buscando pega de {primary.lower()} en {commune}.",
             {"interest_type": "employment", "entity_type": "unknown",
              "trades": [primary], "work_communes": [commune]}),
            ("¿Qué información falta para que me contacten?", {}),
            ("Solo yo, sin cuadrilla.", {"workers": 1, "team_available": False}),
        ]
    return Scenario(f"enfocada-{suite}-{focus}-{seed}-{index}", turns)


def scenario(config: dict, index: int) -> Scenario:
    suite, level = config["suite"], config["level"]
    if config.get("focus") in MESSENGER_FOCUS:
        return focused_messenger_case(config, index)
    if suite == "reference" and index < REFERENCE_COUNT:
        return reference_case(index)
    seed = SUITE_SEEDS.get(suite, config["seed"])
    if suite == "reference":
        index -= REFERENCE_COUNT
    sizes = (len(NAMES), len(TRADES), len(COMMUNES), len(HELLOS), len(INTRO),
             2 if level == 1 else len(COUNTS), 2 if level == 1 else len(AVAILABILITY), 2)
    capacity = 1
    for size in sizes:
        capacity *= size
    capacity //= 3
    partition = {"practice": 0, "reference": 1, "holdout": 2}[suite]
    start = int(digest([seed, level, "start"])[:16], 16)
    step = int(digest([seed, level, "step"])[:16], 16) % capacity or 1
    while gcd(step, capacity) != 1:
        step += 1
    # Partition an independent axis so tuning examples cannot occur in the reserved suite.
    value = (start + index * step) % capacity
    value = value * 3 + partition
    choices = []
    for size in sizes:
        value, choice = divmod(value, size)
        choices.append(choice)
    person, trade, place, hello, intro, count, availability, order = choices
    name, commune = NAMES[person], COMMUNES[place]
    primary, alias = TRADES[trade]
    secondary = TRADES[(trade + 1 + place) % len(TRADES)][0]
    turns = [(HELLOS[hello].format(name) + ".", {"name": name})]
    literal = alias if level >= 3 and intro != len(INTRO) - 1 else primary.lower()
    professional_facts = {"trades": [primary]}
    if intro < 2:
        professional_facts.update(interest_type="employment", entity_type="unknown")
    elif intro == 3:
        professional_facts["interest_type"] = "service_offer"
    professional = (INTRO[intro].format(literal) + ".", professional_facts)
    available = (AVAILABILITY[availability] + ".", {"availability": (
        AVAILABILITY[availability].split()[-1] if availability < 3 else "Sin disponibilidad")})
    if level == 1:
        crew = (("Trabajo solo no más.", {"workers": 1, "team_available": False}) if count == 0
                else ("Somos dos.", {"workers": 2, "team_available": True}))
        middle = [professional, (f"Trabajo en {commune}.", {"work_communes": [commune]}), available]
        turns.extend(middle if order == 0 else reversed(middle))
        turns.append(crew)
    else:
        crew = (f"Voy con {COUNTS[count]} maestros.", {"workers": count + 3, "team_available": True})
        middle = [professional, (f"Trabajo en {commune}.", {"work_communes": [commune]}), crew]
        turns.extend(middle if order == 0 else reversed(middle))
        turns.extend([(f"También hago {secondary.lower()}, llevo {count + 2} años.",
                       {"trades": sorted([primary, secondary]), "experience": f"{count + 2} años"}), available])
    need = None
    if level >= 3:
        classification = {"entity_type": "company" if count % 2 else "individual", "has_employees": None}
        if count % 2:
            classification["interest_type"] = "both" if intro < 2 else "service_offer"
        turns.append(("Represento una empresa." if count % 2 else "Soy independiente.", classification))
        if level == 3:
            turns.append(("Te dejo mi celular " + SYNTHETIC_PHONE, {"phone": SYNTHETIC_PHONE}))
    if level >= 4:
        need = {"specialty": primary, "commune": commune, "workers": count + 2,
                "start_date": "2031-05-12", "experience_years": 2}
        turns.append(("¿Me pueden avisar si hay algo compatible para mi equipo?",
                      {"match": "unavailable" if availability == 3 else "compatible"}))
    if level == 5:
        destination = COMMUNES[(place + 1) % len(COMMUNES)]
        turns.extend([
            ("Mi hermano es pintor, yo no hago " + secondary.lower() + ".", {"trades": [primary]}),
            (f"Me equivoqué, ahora trabajo solo en {destination}.", {"work_communes": [destination], "match": "different_commune"}),
            ("Yo y dos más. ¿Soy contratado seguro entonces?", {"workers": 3, "team_available": True, "match": "different_commune"}),
        ])
    return Scenario(f"{suite}-n{level}-{seed}-{index}", turns, need)


def dataset_hash(config: dict) -> str:
    suite = config["suite"]
    payload = [DATASET_VERSION, suite, SUITE_SEEDS.get(suite, config["seed"]),
               config["level"], config["cases"]]
    # The version separates each dataset from prior extraction expectations.
    if config.get("focus"):
        payload.append(config["focus"])
    return digest(payload)
