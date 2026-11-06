"""GALANT JAVIERA 16.5: segregación de áreas y equivalencias explícitas de cargos."""
import pytest

from app.javiera_logic import (
    DOCUMENTS, CARGO_ALIASES, eligibility, normalize_cargo,
    validate_requirements
)


@pytest.mark.parametrize("raw,expected",[
    ("PINTOR","PINTOR"),("Pintura","PINTOR"),("pinturas","PINTOR"),
    ("Maestro pintor","PINTOR"),("CARPINTERÍA","CARPINTERO"),
    ("Carpintero","CARPINTERO"),("gasfitería","GASFITER"),
    ("cerámica","CERAMISTA"),("impermeabilización","IMPERMEABILIZADOR"),
    ("hormigonado","OPERARIO DE HORMIGON"),
])
def test_matriz_comparte_cargo_canonico_con_labor_empresa(raw,expected):
    assert normalize_cargo(raw)==expected


def test_no_identifica_automaticamente_un_cargo_no_equivalente():
    # No usar semejanza estadística para asignar matrices preventivas.
    assert normalize_cargo("SOLDADOR")=="SOLDADOR"
    assert normalize_cargo("OPERADOR MAQUINARIA")=="OPERADOR MAQUINARIA"


def test_prevencion_no_depende_de_contrato_incompleto_o_erroneo():
    data={
      "employer":{"name":"Empresa sintética"},
      "worker":{"name":"Trabajador sintético","rut":"11.111.111-1"},
      "site":{"name":"Brisas de Junquillar"},
      "role":"PINTOR","employment_type":"",
      "event_type":"ingreso",
      "event":{"date":"2026-11-06"},
      "contract":{"salary":"no-numérico","hours":"99","end":"2025-11-06","start":"2026-11-06"},
    }
    # Los campos contractuales no forman parte de la IRL, PTS o EPP.
    missing, errors=validate_requirements(data,
        ["employer.name","worker.name","worker.rut","site.name","role","event.date"])
    assert missing==[]
    assert errors==[]
    # Cuando se prepara un contrato sí deben comprobarse.
    _,contract_errors=validate_requirements(data,
        ["contract.salary","contract.hours","contract.start","contract.end"])
    assert contract_errors


def test_prevencion_no_requiere_confirmacion_de_vinculo_laboral():
    data={
        "employer":{"name":"Empresa sintética","rut":"11.111.111-1"},
        "worker":{"name":"Trabajador sintético","rut":"11.111.111-1"},
        "site":{"name":"Obra sintética"},"role":"PINTURA",
        "employment_type":"","event_type":"ingreso",
        "event":{"date":"2026-11-06"},"contract":{},
    }
    templates={"pts":{"published_version":1,"has_body":True}}
    out={x["code"]:x for x in eligibility(data,templates,{"PTS:PINTOR"})}
    assert out["pts"]["status"]=="LISTO_PARA_EMITIR"
    assert out["labor_contract"]["status"]=="POR_DETERMINAR"


def test_areas_del_excel_son_dos_y_documentos_diez():
    assert len(DOCUMENTS)==10
    assert sum(x[1]=="Zona Subcontratos" for x in DOCUMENTS)==4
    assert sum(x[1]=="Prevención de Riesgos" for x in DOCUMENTS)==6


def test_reglamento_interno_no_solicita_datos_contractuales():
    reg=next(x for x in DOCUMENTS if x[0]=="internal_rules_receipt")
    assert not any(x in reg[4] for x in
        ["contract.start","contract.end","contract.salary","contract.hours"])
    assert "extra.regulation_version" in reg[4]


def test_aliases_solo_equivalencias_declaradas():
    assert len(CARGO_ALIASES)==len(set(CARGO_ALIASES))
    assert CARGO_ALIASES["PINTURA"]=="PINTOR"
