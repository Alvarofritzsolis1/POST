"""Literal vocabulary anchors for the contextual model's attribution decision."""
from difflib import get_close_matches
import re

from .galancito_communes import commune_mentions
from .galancito_intake import role_mentions
from .galancito_links import trade_mentions
from .galancito_triage import declaration_text, plain

QUANTITY = (r"\d{1,4}|un[oa]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|"
            r"once|doce|trece|catorce|quince|dieci\w+|veint\w+|treinta|cuarenta|cincuenta|"
            r"sesenta|setenta|ochenta|noventa|cien|ciento|varios|varias")
QUALIFIER = r"mas de|menos de|como|alrededor de|cerca de|unas?|aprox\w*|entre|hasta|sobre"
QUALIFIED_CREW = re.compile(r"\b(?:" + QUALIFIER + r")\b")
QUANTITY_PATTERN = re.compile(r"\b(?:" + QUANTITY + r")\b")
CREW_UNIT = r"maestros?|personas?|trabajadores?|ayudantes?|cabros?|compas?|integrantes?"
CREW_SPAN = re.compile(r"\b(?:(?:" + QUALIFIER + r") )?(?:" + QUANTITY + r")"
                       r"(?: (?:a|y) (?:" + QUANTITY + r"))?(?: " + CREW_UNIT + r")?\b")
PARTIES = re.compile(r"\b(?:mi|un|una|el|la) (?:vecin[oa]|amig[oa]|herman[oa]|prim[oa]|colega|jefe|"
                     r"conocid[oa]|cunad[oa]|companero|companera)\b")
REPORTED = re.compile(r"\b(?:(?:segun|en) (?:el aviso|la publicacion)|"
                      r"(?:el aviso|la publicacion|la pagina|el sitio|la empresa) "
                      r"(?:pide|busca|dice|ofrece|tiene|publica))\b")
SELF = re.compile(r"\b(?:yo|por mi parte|en mi caso|por mi lado)\b")
BREAK = re.compile(r"[,.;!\n]+|\b(?:pero|mientras que)\b", re.I)
NEGATED = re.compile(r"^(?:(?:yo|ya) )*no (?:soy|somos|hago|hacemos|tengo|tenemos|"
                     r"ofrezco|ofrecemos|trabajo|trabajamos|vivo|vivimos|busco|buscamos)\b")
ORIGIN_PREFIX = re.compile(r"(?:^|\b)(?:de|vivo en|vivimos en|radico en|resido en|residimos en|"
                           r"somos de|soy de|vengo de|desde) $")
TRADE_DETAILS = re.compile(r" (?:en|de) (\w+(?: y \w+)?)\b")
OWN_WORK = re.compile(r"\b(?:hago|hacemos|me dedico a|nos dedicamos a|me especializo en|"
                      r"trabaj(?:o|amos) (?:de|en|\w+(?:ando|iendo))) "
                      r"(?P<trade>\w+(?: (?!en\b|para\b|desde\b|pero\b|porque\b|cuando\b)\w+){0,5})")
WORK_MODE = re.compile(r"^(?:a trato|por mi cuenta|por las mias|por mi propia cuenta|sol[oa])\b")
EXTRA_TRADES = (("Yeso", ("yeso", "yesero", "yesera", "yesería")),
                ("Andamios", ("andamio", "andamios", "andamiero")))
CHANNEL_NAMES = {"wsp": "whatsapp", "wa": "whatsapp"}


def declaration_segments(text):
    """Keep the speaker's clause when it follows a clear reference to somebody else."""
    for clause in BREAK.split(declaration_text(text)):
        normalized = plain(clause)
        if other := (PARTIES.search(normalized) or REPORTED.search(normalized)):
            own = SELF.search(normalized, other.end())
            normalized = normalized[own.end():].strip() if own else ""
        if normalized and not NEGATED.search(normalized):
            yield normalized


def _quantity_mentions(value):
    for match in CREW_SPAN.finditer(value):
        text = match[0]
        prefix = value[:match.start()]
        if (re.search(r"\b(?:" + CREW_UNIT + r")$", text)
                or re.search(r"\b(?:somos|vamos|van|andamos|cuadrilla de|equipo de|voy con) $", prefix)):
            yield match.start(), "crew", text, text


def channel_preference(value):
    return bool(re.fullmatch(r"[a-z]+", value) or re.search(
        r"\b(?:por|prefiero|mandame|manda|escribeme|escribanme|contactame|mi|"
        r"me (?:acomoda|sirve|conviene|queda (?:mas )?comod[oa]))\b", value))


def _channel_mentions(value):
    words = list(re.finditer(r"\b[a-z]+\b", value))
    for word in words:
        candidate = word[0]
        names = ([CHANNEL_NAMES[candidate]] if candidate in CHANNEL_NAMES else
                 get_close_matches(candidate, ("whatsapp", "messenger"), n=1, cutoff=.75))
        if names:
            yield word.start(), "channel", names[0], candidate


def evidence_options(fragments):
    """Give Qwen references it may accept. The lexicon never writes the profile."""
    options = []
    seen = set()
    for index, fragment in enumerate(fragments):
        for value in declaration_segments(fragment.text):
            cities = list(commune_mentions(value))
            mentions = [(match.start(), "role", role, match[0]) for match, role in role_mentions(value)]
            for match, _ in cities:
                prefix = value[:match.start()]
                field = "origin" if ORIGIN_PREFIX.search(prefix) else "area"
                mentions.append((match.start(), field, match[0], match[0]))
            catalog = list(trade_mentions(value, extra=EXTRA_TRADES))
            for match in catalog:
                detail = TRADE_DETAILS.match(value, match.end())
                end = match.end()
                if detail and not list(commune_mentions(detail[1])) and not list(
                        trade_mentions(detail[1], extra=EXTRA_TRADES)):
                    end = detail.end()
                span = value[match.start():end]
                mentions.append((match.start(), "trade", span, span))
            if not catalog and (work := OWN_WORK.search(value)):
                trade = work["trade"]
                # An idiom about contracting is not an occupation.
                if not WORK_MODE.search(trade) and not list(commune_mentions(trade)):
                    mentions.append((work.start("trade"), "trade", trade, trade))
            mentions.extend(_quantity_mentions(value))
            if channel_preference(value):
                mentions.extend(_channel_mentions(value))
            for _, field, normalized, evidence in sorted(mentions):
                key = field, normalized
                if key not in seen:
                    seen.add(key)
                    options.append((index, field, normalized, evidence))
    return options[:18]
