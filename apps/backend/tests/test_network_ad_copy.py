"""Focused safety tests for editable social advertisement summaries."""
from types import SimpleNamespace

from app.network_ad_copy import (
    candidate_grounded, detail_question, draft_summary, editorial_diagnostics,
    fallback_summary, summary_safe,
)
from app.network_facebook import public_message


def test_copy_preserves_facts_and_refuses_unconfirmed_details():
    source = "Realizar pintura de exteriores de edificios y terminaciones."
    assert fallback_summary(source).startswith("Pintura")
    assert candidate_grounded("Pintura de exteriores de edificios y terminaciones.", source)
    assert not candidate_grounded("Pintura de exteriores con contrato garantizado.", source)
    assert not candidate_grounded("Pintura de exteriores con sueldo de 800000.", source)
    assert not summary_safe("Trabajos en Brisas de Junquillar.", source,
                            site_name="Brisas de Junquillar")
    assert not summary_safe("Contactar a alguien@example.com", source)


def test_ai_falls_back_without_model_and_does_not_fabricate(monkeypatch):
    from app import network_ad_copy
    source = "Instalación de canalizaciones eléctricas en edificios."
    monkeypatch.setattr(network_ad_copy, "infer", lambda *args, **kwargs: None)
    answer, source_name = draft_summary(None, org_id="org", description=source,
                                        specialty="Electricidad")
    assert source_name == "automatico"
    assert answer == "Instalación de canalizaciones eléctricas en edificios."


def test_ai_uses_grounded_valid_summary(monkeypatch):
    from app import network_ad_copy
    source = "Realizar pintura de exteriores de edificios y terminaciones."
    monkeypatch.setattr(network_ad_copy, "infer", lambda *args, **kwargs:
                        "Pintura de exteriores de edificios y terminaciones.")
    answer, mode = draft_summary(None, org_id="org", description=source,
                                 specialty="Pintura")
    assert mode == "ia"
    assert answer == "Pintura de exteriores de edificios y terminaciones."


def test_public_message_omits_internal_site_and_pending_date():
    req = SimpleNamespace(
        specialty="Carpintería", public_summary="Montaje de muebles y puertas.",
        public_location="San Pedro de la Paz, Biobío",
        workers=3, start_date_pending=True, start_date=__import__("datetime").date(2026, 11, 23),
        title="Brisas de Junquillar", description="Planos privados"
    )
    message = public_message(None, req)
    assert message.startswith("Buscamos empresas contratistas de carpintería.")
    assert "Montaje de muebles y puertas." in message
    assert "San Pedro de la Paz" in message
    assert "Brisas de Junquillar" not in message
    assert "23/11/2026" not in message
    assert "Inicio estimado" not in message


def test_sparse_painting_is_readable_but_not_fabricated():
    text = "PINTURA EN EXTERIOR"
    assert fallback_summary(text) == "Trabajos de pintura en exteriores."
    assert detail_question(text, "Pintura").startswith("¿Qué superficies")
    details = editorial_diagnostics(text, "Pintura")
    assert details["needs_detail"] is True
    assert "muros" in details["detail_question"]
    assert "fachadas" in details["detail_question"]


def test_real_specificity_skips_extra_question():
    text = "Pintura de fachadas y rejas exteriores."
    assert editorial_diagnostics(text, "Pintura") == {
        "needs_detail": False, "detail_question": ""
    }
    assert fallback_summary(text) == text
    assert candidate_grounded("Pintura de fachadas y rejas exteriores.", text)


def test_ai_copy_is_discarded_when_fabricated_or_near_verbatim(monkeypatch):
    from app import network_ad_copy
    monkeypatch.setattr(
        network_ad_copy, "infer", lambda *args, **kwargs:
        "Pintura de fachadas y rejas, sueldo garantizado y beneficios."
    )
    source = "Pintura de fachadas y rejas."
    suggestion, mode = draft_summary(None, org_id="org",
                                     description=source, specialty="Pintura")
    assert suggestion == source
    assert mode == "automatico"

    monkeypatch.setattr(
        network_ad_copy, "infer", lambda *args, **kwargs: source
    )
    suggestion, mode = draft_summary(None, org_id="org",
                                     description=source, specialty="Pintura")
    assert suggestion == source
    assert mode == "automatico"


def test_ai_can_rewrite_only_grounded_facts(monkeypatch):
    from app import network_ad_copy
    source = "PINTURA EXTERIOR: FACHADAS, REJAS"
    monkeypatch.setattr(
        network_ad_copy, "infer",
        lambda *args, **kwargs: "Pintura exterior de fachadas y rejas."
    )
    proposed, label = draft_summary(None, org_id="org",
                                    description=source, specialty="Pintura")
    assert proposed == "Pintura exterior de fachadas y rejas."
    assert label == "ia"


def test_ai_cannot_invent_a_different_trade_or_work_location():
    source = "Pintura de fachadas."
    assert not candidate_grounded("Electricidad de fachadas.", source)
    assert not candidate_grounded("Pintura exterior de fachadas.", source)
    assert candidate_grounded("Pintura de fachadas.", source)
