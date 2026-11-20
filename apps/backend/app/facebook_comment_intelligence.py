"""Señales preliminares locales para comentarios de Facebook.

No perfila personas ni envía mensajes. Una etiqueta obtenida por reglas no
se presenta como resultado de un modelo externo; un operador puede corregirla.
"""
from __future__ import annotations

import re
import unicodedata

CATEGORIES = frozenset({
    "interested", "question", "positive", "negative", "spam", "ambiguous", "human_review"
})
REVIEW_STATES = frozenset({"new", "review", "handled", "dismissed"})

TRADE_WORDS = (
    "carpinter", "carpint", "gasfit", "gafit", "electric", "albanil", "maestro", "soldador",
    "pintor", "pintura", "tabiquer", "ceram", "enfierr", "jornal", "yeser",
    "techumbr", "impermeabili", "excavador", "operador", "obrero", "instalador",
    "jardin", "topograf", "sanitari", "terminacion", "hormigon", "alumin", "constructor", "maquinaria", "andam", "bodegu",
)
OFFER = re.compile(
    r"\b(soy|soi|somos|hago|hacemos|realizo|realizamos|trabajo|trabajamos|"
    r"ofrezco|ofrecemos|me dedico|nos dedicamos|tengo (?:una? )?cuadrilla|"
    r"tengo disponibilidad|tamos disponibles|ando buscando pega|busco pega|"
    r"busco trabajo|estoy disponible|estamos disponibles|necesito pega|"
    r"quiero postular|donde postulo|como postulo|me interesa|estoy interesado|estamos interesados)\b"
)
ASK = re.compile(r"[?¿]|\b(como|cuando|donde|cuanto|requisitos|informacion|disponible|hay cupos)\b")
NEG = re.compile(r"\b(estafa|enga[nñ]o|mentira|no pagan|no pagaron|reclamo|denuncia|pesimo|malo|abuso)\b")
POS = re.compile(r"\b(buen trabajo|excelente|felicitaciones|felicidades|buena iniciativa|genial|muy bueno)\b")
SPAM = re.compile(r"(https?://\S+.*){3,}|\b(apuesta|casino|bitcoin gratis|credito inmediato)\b")
SENSITIVE = re.compile(r"\b(amenaz|acoso|discriminacion|violencia|suicid|agresi[oó]n)\b")


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(c for c in value if not unicodedata.combining(c))


def classify_comment(text: str) -> tuple[str, int]:
    """Devuelve categoría y fuerza de señal heurística (NO probabilidad IA)."""
    value = normalize(text).strip()[:6000]
    if not value:
        return "ambiguous", 0
    if SENSITIVE.search(value):
        return "human_review", 90
    if SPAM.search(value):
        return "spam", 85
    if NEG.search(value):
        return "negative", 80
    if OFFER.search(value):
        if any(word in value for word in TRADE_WORDS):
            return "interested", 90
        if any(term in value for term in ("busco pega", "busco trabajo", "quiero postular", "donde postulo", "como postulo", "necesito pega")):
            return "interested", 77
        if "cuadrilla" in value or "disponib" in value or "interesa" in value:
            return "interested", 73
    if value in {"info", "informacion", "hola", "ola", "buenas", "interesado"}:
        return "ambiguous", 20
    if ASK.search(value):
        return "question", 65
    if POS.search(value):
        return "positive", 74
    if len(value.split()) <= 2:
        return "ambiguous", 20
    return "ambiguous", 30


def reply_template(body: str, category: str) -> str:
    """Borrador verificable sin datos de vacantes, pagos ni promesas."""
    if category == "interested":
        return "¡Hola! Gracias por escribir. ¿Trabajas por tu cuenta o con una cuadrilla?"
    if category == "question":
        return "¡Hola! Gracias por consultar. ¿Nos puedes contar qué información necesitas?"
    if category == "positive":
        return "¡Muchas gracias por tu comentario!"
    if category == "negative":
        return "Hola, lamentamos conocer esta situación. Revisaremos tu comentario con el equipo."
    if category == "human_review":
        return ""
    if category == "spam":
        return ""
    return "¡Hola! ¿Nos cuentas en qué podemos ayudarte?"


# Información profesional SOLO cuando aparece explícitamente en el comentario.
# El oficio del anuncio nunca se atribuye al comentarista.
DECLARED_TRADES = {
    "Carpintería": ("carpint", "muebl", "mueblist"),
    "Gasfitería": ("gasfit", "gafit", "sanitari"),
    "Electricidad": ("electric", "electrico", "electrica"),
    "Pintura": ("pintor", "pintura"),
    "Tabiquería": ("tabiquer", "volcometal"),
    "Cerámica": ("ceramic", "ceramista"),
    "Albañilería": ("albanil", "albaniler"),
    "Soldadura": ("soldador", "soldadur"),
    "Enfierradura": ("enfierr"),
    "Impermeabilización": ("impermeabil"),
    "Techumbre": ("techumbr", "techero"),
    "Jardinería": ("jardin", "paisaj"),
    "Hormigón": ("hormigon", "hormigonado"),
    "Topografía": ("topograf",),
    "Excavación": ("excavador", "excavacion", "excavadora"),
}
TEAM = re.compile(r"\b(?:somos|cuadrilla de|equipo de)\s*(\d{1,2})\b")


def declared_profile(text: str) -> dict:
    """Perfil declarativo de texto público, no validación de idoneidad."""
    normalized = normalize(text)[:6000]
    trades = [label for label, roots in DECLARED_TRADES.items()
              if any(root in normalized for root in roots)]
    match = TEAM.search(normalized)
    workers = int(match.group(1)) if match else None
    if workers is not None and not 1 <= workers <= 50:
        workers = None
    return {"trades": trades, "team_size_declared": workers}
