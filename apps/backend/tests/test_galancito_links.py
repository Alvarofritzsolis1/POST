"""Acceptance checks: Chilean multi-trade declarations, links, RBAC and trace.

All messages and requirements are synthetic. No external Meta requests.
"""
from app.galancito_links import extract_declared_trades, suggest_requirements
from test_facebook_crm import enable_messaging, incoming
from test_network import network, request_body


def test_multi_trade_extraction_and_negation():
    found = extract_declared_trades(
        "Wena, soy carpintero, igual le pego a la gasfitería y hago cerámica"
    )
    assert set(found) == {"Carpintería", "Gasfitería", "Cerámica"}
    assert extract_declared_trades("¿Buscan carpinteros y gasfíteres?") == []
    assert extract_declared_trades("¿Soy carpintero si aprendí de mi papá?") == []
    assert extract_declared_trades("Soy carpintero, tienen pega?") == ["Carpintería"]
    assert extract_declared_trades("No soy carpintero, hago gasfitería") == ["Gasfitería"]
    assert extract_declared_trades("carpintero", "¿Qué oficio realizas?") == ["Carpintería"]
    assert extract_declared_trades("carpintero") == []


def test_messenger_trades_need_link_and_history(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    msg = "Soy carpintero, gasfíter y también hago cerámica"
    assert incoming(n, text=msg, mid="multi-trade-901").status_code == 200
    # Messenger replay must be idempotent.
    assert incoming(n, text=msg, mid="multi-trade-901").status_code == 200
    leads = n["admin"].get("/api/v1/network/facebook/center").json()["leads"]
    lead_id = leads[0]["id"]
    detailed = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id)
    assert detailed.status_code == 200
    assert set(detailed.json()["lead"]["trades"]) == {
        "Carpintería", "Gasfitería", "Cerámica"
    }

    body = request_body(n)
    body["specialty"] = "Gasfitería"
    body["title"] = "Instalaciones sanitarias de prueba"
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201, created.text
    requirement_id = created.json()["id"]
    listing = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento")
    assert listing.status_code == 200
    row = listing.json()["rows"][0]
    assert set(row["trades"]) == {"Carpintería", "Gasfitería", "Cerámica"}
    match = next(item for item in row["matches"] if item["id"] == requirement_id)
    assert match["coincidence_percent"] == 100
    assert match["coverage_percent"] < 100  # Unknown is not a rejection.
    assert match["review_required"] is True
    assert not match["linked"]

    path = "/facebook/leads/" + lead_id + "/needs/" + requirement_id
    assert n["send"](n["a"], path + "/link").status_code == 403
    linked = n["send"](n["admin"], path + "/link")
    assert linked.status_code == 200, linked.text
    assert linked.json()["changed"] is True
    assert n["send"](n["admin"], path + "/link").json()["changed"] is False
    after = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()
    assert after["rows"][0]["links"][0]["id"] == requirement_id
    assert after["unlinked"] == 0
    audit = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id + "/trace")
    assert audit.status_code == 200
    events = [item["event"] for item in audit.json()]
    assert "trade_added" in events
    assert "need_linked" in events
    assert n["a"].get("/api/v1/network/facebook/leads/" + lead_id + "/trace").status_code == 403

    removed = n["send"](n["admin"], path + "/unlink")
    assert removed.status_code == 200
    assert removed.json()["changed"] is True
    assert n["send"](n["admin"], path + "/unlink").json()["changed"] is False
    assert n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()["unlinked"] == 1
    audit2 = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id + "/trace").json()
    assert "need_unlinked" in [item["event"] for item in audit2]


def test_missing_trade_does_not_produce_automatic_candidate_score(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="Hola, busco pega", mid="multi-trade-902").status_code == 200
    body = request_body(n)
    assert n["send"](n["a"], "/requirements", body).status_code == 201
    row = n["admin"].get("/api/v1/network/facebook/galancito/seguimiento").json()["rows"][0]
    assert row["matches"] == []
    assert row["profile_state"] == "Oficio por conocer"
    assert row["links"] == []
