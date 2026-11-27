"""Literal vocabulary anchors for the contextual model's attribution decision."""
from difflib import get_close_matches
import re

from .galancito_communes import commune_mentions
from .galancito_intake import CREW_PERSON_UNIT, WORK_AREA_CUE, role_mentions
from .galancito_links import trade_mentions
from .galancito_triage import declaration_text, plain

QUANTITY = (r"\d{1,4}|un[oa]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|"
            r"once|doce|trece|catorce|quince|dieci\w+|veint\w+|treinta|cuarenta|cincuenta|"
            r"sesenta|setenta|ochenta|noventa|cien|ciento|varios|varias")
QUALIFIER = r"mas de|menos de|como|alrededor de|cerca de|unas?|aprox\w*|entre|hasta|sobre"
QUALIFIED_CREW = re.compile(r"\b(?:" + QUALIFIER + r")\b")
CREW_UNIT = "(?:" + CREW_PERSON_UNIT + ")"
CREW_SPAN = re.compile(r"\b(?:(?:" + QUALIFIER + r") )?(?:" + QUANTITY + r")"
                       r"(?: (?:a|y) (?:" + QUANTITY + r"))?(?: " + CREW_UNIT + r")?\b")
PARTY = (r"(?:mi|un|una|el|la) (?:vecin[oa]|amig[oa]|herman[oa]|prim[oa]|colega|jefe|"
         r"conocid[oa]|cu[nñ]ad[oa]|compa[nñ]er[oa])")
PARTIES = re.compile(r"\b" + PARTY + r"\b")
REPORTED = re.compile(r"\b(?:(?:segun|en) (?:el aviso|la publicacion)|"
                      r"(?:el aviso|la publicacion|la pagina|el sitio|la empresa) "
                      r"(?:pide|busca|dice|ofrece|tiene|publica)|"
                      r"(?:vi|lei|dicen|dijeron) que (?:piden|buscan|necesitan|ofrecen))\b")
SENTENCES = re.compile(r"[.!;\n]+")
CLAUSES = re.compile(r",+|\b(?:pero|mientras que)\b|\by\s+(?=(?:yo|soy|trabajo|vivo|resido|hago|ofrezco|"
                     r"me dedico|me muevo|no s[eé]|por mi parte|en mi caso|por mi lado|el aviso|la publicaci[oó]n|"
                     + PARTY + r")\b)", re.I)
UNCERTAIN = re.compile(r"\b(?:tal vez|quizas?|puede que|capaz que|a lo mejor|no se si|podria(?:mos)?|"
                       r"si (?:me|nos|se|hay|consigo|conseguimos)|en caso de que)\b")
NEGATED = re.compile(r"^(?:(?:yo|ya) )*no (?:soy|somos|hago|hacemos|tengo|tenemos|"
                     r"ofrezco|ofrecemos|trabajo|trabajamos|vivo|vivimos|busco|buscamos)\b")
ORIGIN_PREFIX = re.compile(r"\b(?:vivo en|vivimos en|radico en|resido en|residimos en|donde vivo es|"
                           r"somos de|soy de|vengo de)\b")
ORIGIN_TRADE = re.compile(r"\b(?:contratista|soy|somos)\b.*\bde $")
TRADE_DETAILS = re.compile(r" (?:en|de) (\w+(?: y \w+)?)\b")
OWN_WORK = re.compile(r"\b(?:hago|hacemos|me dedico a|nos dedicamos a|me especializo en|"
                      r"trabaj(?:o|amos) (?:de|en|\w+(?:ando|iendo))) "
                      r"(?P<trade>\w+(?: (?!en\b|para\b|desde\b|pero\b|porque\b|cuando\b)\w+){0,5})")
WORK_MODE = re.compile(r"^(?:a trato|por mi cuenta|por las mias|por mi propia cuenta|sol[oa])\b")
EXTRA_TRADES = (("Yeso", ("yeso", "yesero", "yesera", "yesería")),
                ("Andamios", ("andamio", "andamios", "andamiero")))
CHANNEL_NAMES = {"wsp": "whatsapp", "wa": "whatsapp", "guasap": "whatsapp",
                 "wasap": "whatsapp", "watsap": "whatsapp", "guasa": "whatsapp",
                 "correo": "email", "email": "email", "mail": "email", "correo electronico": "email"}


def personal_statements(text):
    """Preserve the speaker's own statements and explicit corrections."""
    for sentence in SENTENCES.split(declaration_text(text)):
        stripped = sentence.strip()
        if re.match(r"si\s+(?!(?:claro|po|obvio|dale|bueno)\b)\w", stripped, re.I) and "," in stripped:
            continue  # A leading condition also governs the clause after the comma.
        for clause in CLAUSES.split(stripped):
            normalized = plain(clause)
            if normalized and not (PARTIES.search(normalized) or REPORTED.search(normalized)
                                   or UNCERTAIN.search(normalized)):
                yield clause.strip()


def declaration_segments(text):
    for clause in personal_statements(text):
        normalized = plain(clause)
        if (normalized and not NEGATED.search(normalized)
                and not (normalized.startswith("no ") and any(
                    match.start() == 0 for match in trade_mentions(normalized[3:], extra=EXTRA_TRADES)))):
            yield normalized


def location_mentions(value):
    """Attribute each commune using its own preceding cue."""
    cues = [(match.start(), "origin") for match in ORIGIN_PREFIX.finditer(value)]
    cues.extend((match.start(), "area") for match in WORK_AREA_CUE.finditer(value))
    cues.sort()
    for match, commune in commune_mentions(value):
        field = next((role for start, role in reversed(cues) if start < match.start()), None)
        if field is None and ORIGIN_TRADE.search(value[:match.start()]):
            field = "origin"
        yield match, commune, field


def crew_mentions(value):
    for match in CREW_SPAN.finditer(value):
        text = match[0]
        prefix = value[:match.start()]
        # Contacts with tradespeople are not an owned or available crew.
        if re.search(r"\b(?:conozco|conocemos|conoci|conocimos|tengo conocidos|tengo amigos|conocemos a)\s*$", prefix):
            continue
        if re.match(r" (?:contratad[oa]s?|con contrato)\b", value[match.end():]):
            continue
        if (re.search(r"\b(?:" + CREW_UNIT + r")$", text)
                or re.search(r"\b(?:somos|vamos|van|andamos|(?:cuadrilla|equipo) (?:es )?de|voy con) $", prefix)):
            yield match.start(), "crew", text, text


def channel_preference(value):
    if re.search(r"\b(?:no|nunca|sin|ejemplo|reservado|hipotetico)\b", value):
        return False
    return bool(re.fullmatch(r"[a-z]+(?: electronico)?", value) or re.search(
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


def explicit_channel_mentions(text):
    """Recover only unambiguous volunteered channel labels, not conversational intent."""
    value = plain(text)
    if ("?" in text or "¿" in text or PARTIES.search(value) or REPORTED.search(value)
            or re.search(r"\b(?:no|nunca|sin|si|quizas|tal vez|ejemplo|reservado|otro|otra)\b", value)):
        return []
    # A short channel label is common after a voluntarily shared phone number.
    mentions = list(_channel_mentions(value))
    if len({item[2] for item in mentions}) != 1:
        return []
    for _, _, channel, evidence in mentions:
        if (value in CHANNEL_NAMES or value in {"whatsapp", "messenger"}
                or re.search(r"\b(?:prefiero|me acomoda(?: mas)?|me sirve(?: mas)?|me conviene|"
                             r"escribeme|escribanme|contactame|contactenme|mandame|mandenme|"
                             r"mejor) (?:el |la |por |al |a |via )?"
                             + re.escape(evidence) + r"\b", value)):
            return [(channel, evidence)]
    return []


def evidence_options(fragments):
    """Give Qwen references it may accept. The lexicon never writes the profile."""
    options = []
    seen = set()
    for index, fragment in enumerate(fragments):
        for value in declaration_segments(fragment.text):
            mentions = [(match.start(), "role", role, match[0]) for match, role in role_mentions(value)]
            for match, _, field in location_mentions(value):
                if field is None:
                    continue
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
            mentions.extend(crew_mentions(value))
            if channel_preference(value):
                mentions.extend(_channel_mentions(value))
            for _, field, normalized, evidence in sorted(mentions):
                key = field, normalized
                if key not in seen:
                    seen.add(key)
                    options.append((index, field, normalized, evidence))
    return options[:18]
