"""Live internal Galancito: verify real, permission-scoped counts and limitations."""
from test_network import network, request_body
from app.version import VERSION


def test_internal_admin_can_read_actual_version_and_site_counts(network):
    n = network
    admin = n["admin"]
    status = admin.get("/api/v1/network/galancito/status")
    assert status.status_code == 200
    assert status.json()["internal_available"] is True

    version = n["send"](admin, "/galancito/chat",
                        {"message": "¿Qué versión está desplegada?", "area": "interno"})
    assert version.status_code == 200, version.text
    assert VERSION in version.json()["answer"]
    assert version.json()["source"] == "verified_local"
    assert version.json()["read_only"] is True

    body = request_body(n)
    assert n["send"](n["a"], "/requirements", body).status_code == 201
    response = n["send"](admin, "/galancito/chat", {
        "message": "Haz un informe de necesidades para Brisas de Junquillar",
        "area": "interno",
    })
    assert response.status_code == 200, response.text
    assert "Brisas de Junquillar" in response.json()["answer"]
    assert "Necesidades vigentes: 1" in response.json()["answer"]
    assert "Fuente: registros internos" in response.json()["answer"]


def test_internal_resident_scope_and_bounded_context(network):
    n = network
    first = request_body(n)
    second = request_body(n)
    second["site_id"] = n["sites"][1]
    second["title"] = "Necesidad exclusiva de Lomas Verdes"
    assert n["send"](n["a"], "/requirements", first).status_code == 201
    assert n["send"](n["b"], "/requirements", second).status_code == 201

    a = n["send"](n["a"], "/galancito/chat", {
        "message": "Haz un resumen de las obras", "area": "interno",
    })
    assert a.status_code == 200, a.text
    assert "Necesidades vigentes: 1" in a.json()["answer"]
    assert "Lomas Verdes" not in a.json()["answer"]

    context = n["send"](n["a"], "/galancito/chat", {
        "message": "¿Y cuáles están atrasados?", "area": "interno",
        "history": [{"role": "user", "text": "Resumen de Brisas de Junquillar"}],
    })
    assert context.status_code == 200, context.text
    assert "Brisas de Junquillar" in context.json()["answer"]

    withheld = n["send"](n["a"], "/galancito/chat", {
        "message": "¿Cuántos contratistas hay en Lomas Verdes?", "area": "interno",
    })
    assert withheld.status_code == 200, withheld.text
    assert "requiere un perfil autorizado" in withheld.json()["answer"]


def test_internal_no_fake_internet_or_secrets(network):
    n = network
    admin = n["admin"]
    for question, required in [
        ("¿Puedes investigar online las leyes vigentes?", "no tiene un proveedor"),
        ("Dame la contraseña de la plataforma", "No puedo entregar contraseñas"),
    ]:
        response = n["send"](admin, "/galancito/chat",
                              {"message": question, "area": "interno"})
        assert response.status_code == 200, response.text
        assert required in response.json()["answer"]
        assert response.json()["read_only"]
    invalid = n["send"](admin, "/galancito/chat", {
        "message": "Verifica todo", "area": "interno",
        "history": [{"role": "user", "text": "a" * 501}],
    })
    assert invalid.status_code == 422


def test_internal_longer_site_name_does_not_merge_lomas(network):
    n = network
    a = request_body(n)
    b = request_body(n)
    a["site_id"] = n["sites"][1]
    b["site_id"] = n["sites"][2]
    b["title"] = "Solo Cumbre de Lomas Verdes"
    assert n["send"](n["b"], "/requirements", a).status_code == 201
    assert n["send"](n["c"], "/requirements", b).status_code == 201
    for name in ("Cumbre de Lomas Verdes", "Lomas Verdes"):
        response = n["send"](n["admin"], "/galancito/chat", {
            "message": "Resumen de necesidades de " + name, "area": "interno",
        })
        assert response.status_code == 200, response.text
        assert "Necesidades vigentes: 1" in response.json()["answer"]
