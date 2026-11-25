"""Local, bounded retrieval: approved organization/channel-scoped evidence only."""
import json
from functools import lru_cache
from pathlib import Path
from sqlalchemy import select, or_, func, literal_column
from sqlalchemy.orm import Session
from .galancito_flow import retired_permission_prompt
from .galancito_knowledge_models import Knowledge
from .galancito_triage import plain

STOP = set("que como para una uno unos unas los las del con por soy tengo quiero necesito cual donde puede puedes desde esta esto hacer sobre galancito".split())


def search_value(title: str, content: str, phrases: list[str]) -> str:
    return plain(" ".join([title, *phrases, content]))


def retrieve(db: Session, org_id: str, message: str, channel: str) -> list[dict]:
    tokens = list(dict.fromkeys(w for w in plain(message).split() if len(w) > 2 and w not in STOP))[:8]
    if not tokens:
        return []
    query = select(Knowledge).where(
        Knowledge.org_id == org_id, Knowledge.status == "approved",
        Knowledge.scope.in_([channel, "both"]),
    )
    # Parameterized DB search; no external service or embedding model on the VPS.
    if db.bind.dialect.name == "postgresql":
        vector = func.to_tsvector(literal_column("'simple'"), Knowledge.search_text)
        tsquery = func.to_tsquery(literal_column("'simple'"), " | ".join(tokens))
        query = query.where(vector.op("@@")(tsquery)).order_by(func.ts_rank(vector, tsquery).desc())
    else:
        query = query.where(or_(*(Knowledge.search_text.contains(t) for t in tokens)))
    rows = list(db.scalars(query.order_by(Knowledge.updated_at.desc(), Knowledge.id).limit(24)))
    ranked = []
    normalized = plain(message)
    for row in rows:
        if channel == "messenger" and retired_permission_prompt(row.content):
            continue
        exact = normalized in [plain(p) for p in row.phrases]
        score = sum(1 for t in tokens if t in row.search_text.split()) + (20 if exact else 0)
        if not score:
            continue
        # Rank small chunks; never send a complete uploaded document to the model.
        chunks = [row.content[i:i + 700] for i in range(0, len(row.content), 600)]
        chunk = (row.content if exact and len(row.content) <= 650 else
                 max(chunks or [""], key=lambda c: sum(t in plain(c).split() for t in tokens)))
        ranked.append((score, {"id": row.id, "version": row.version, "title": row.title,
                              "kind": row.kind, "content": chunk, "exact": exact}))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in ranked[:3]]


@lru_cache(maxsize=1)
def _conversation_examples():
    """Release-reviewed examples, not tenant data or verified job availability."""
    rows = json.loads(Path(__file__).with_name("galancito_examples.json").read_text(encoding="utf-8"))
    return tuple(row for row in rows if row.get("kind") == "example" and row.get("scope") == "messenger"
                 and row.get("title", "").startswith("Conversación natural — "))


def conversation_example(message: str, prior: str = "") -> str:
    """Small optional coaching context. Never use it as a direct answer."""
    value = plain(message)
    if not value:
        return ""
    candidates = []
    for row in _conversation_examples():
        for phrase in row["phrases"]:
            normalized = plain(phrase)
            # Single-word responses require the preceding question to disambiguate.
            if normalized == value and (len(value.split()) > 1 or ("solo" == value and "trabajas solo" in plain(prior))):
                candidates.append(row["content"])
    return candidates[0][:400] if candidates else ""


def exact_answer(evidence: list[dict]) -> str | None:
    item = next((e for e in evidence if e["exact"] and len(e["content"]) <= 650
                 and e["kind"] in {"faq", "correction"}), None)
    if not item:
        return None
    return item["content"][:650]


def evidence_context(evidence: list[dict]) -> str:
    # Serialized as untrusted reference material; never concatenated to system instructions.
    return json.dumps([{"reference": e["id"] + ":v" + str(e["version"]),
                        "kind": e["kind"], "text": e["content"][:400]}
                       for e in evidence], ensure_ascii=False)


def public_sources(evidence: list[dict]) -> list[dict]:
    return [{k: item[k] for k in ("id", "version", "title")} for item in evidence]
