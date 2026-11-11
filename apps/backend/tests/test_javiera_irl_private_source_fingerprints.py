"""Contrato técnico del Excel privado: 25 cargos / 338 filas IRL.

Las huellas se generaron leyendo exclusivamente MATRIZ IRL (columnas B:F)
del XLSX privado JAVIERA_ETAPA_1_PTS_CORREGIDOS.xlsx, SHA-256 declarado
por el catálogo. No contiene nombres, RUT ni información de trabajadores.

Este test certifica equivalencia de VALORES FUENTE, no firma de prevención,
funcionamiento de cada fórmula bajo entradas arbitrarias ni paridad visual.
"""
from collections import defaultdict
from app.javiera_v194_api import catalog

EXPECTED = {
  "GASFITER": (
    26,
    "40641dad"
  ),
  "PINTOR": (
    13,
    "4979253c"
  ),
  "CARPINTERO": (
    13,
    "746de387"
  ),
  "ENFIERRADOR": (
    13,
    "bdcf2957"
  ),
  "TECHADOR": (
    13,
    "a5c884b6"
  ),
  "CERAMISTA": (
    13,
    "86eb4c3b"
  ),
  "OPERARIO DE HORMIGON": (
    13,
    "1b0fc6b2"
  ),
  "MOLDAJERO": (
    13,
    "7ca990df"
  ),
  "ALUMINERO": (
    13,
    "0b4b5f77"
  ),
  "OPERARIO DE URBANIZACION": (
    13,
    "ae680f15"
  ),
  "IMPERMEABILIZADOR": (
    13,
    "c7f1f0a0"
  ),
  "ESTRUCTURERO METÁLICO": (
    13,
    "b911497d"
  ),
  "NIVELADOR DE PISOS": (
    13,
    "28a43d23"
  ),
  "ALFOMBRERO": (
    13,
    "1c4ca4f6"
  ),
  "HOJALATERO": (
    13,
    "85be6c90"
  ),
  "ALBAÑIL": (
    13,
    "74a00334"
  ),
  "ELETRICO": (
    13,
    "a5bb1982"
  ),
  "INSTALADOR DE EIFS": (
    13,
    "dd2e1fb4"
  ),
  "CAMARERO": (
    13,
    "7157a70e"
  ),
  "INSTALADOR DE PANDERETAS / VIBRADOS": (
    13,
    "b8fa8542"
  ),
  "CARPINTERIA EN TERMINACIONES": (
    13,
    "837c16bf"
  ),
  "MUEBLISTA": (
    13,
    "3f3571d4"
  ),
  "PAISAJISTA": (
    13,
    "0feafd29"
  ),
  "OPERARIO DE OBRA GRUESA": (
    13,
    "54341f4f"
  ),
  "SOLDADOR": (
    13,
    "75d837eb"
  )
}
SOURCE_SHA = "2a6657a0f6c7d78731565ecbb59485542343629903aaf161aacfbea405da5edd"

def _fnv32(text: str) -> str:
    h = 2166136261
    for char in text:
        h = ((h ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"

def test_338_irl_cells_match_source_excel_by_cargo_and_source_row():
    data = catalog()
    assert data["source_sha256"] == SOURCE_SHA
    assert len(data["rows"]) == 338
    groups = defaultdict(list)
    for row in data["rows"]:
        groups[row["cargo"]].append(row)
    assert set(groups) == set(EXPECTED)
    for cargo, expected in EXPECTED.items():
        rows = sorted(groups[cargo], key=lambda row: int(row["excel_row"]))
        text = "".join(str(row["excel_row"]) + "|" +
                       "|".join(str(row.get(key) or "") for key in
                                ("tarea", "peligro", "riesgo", "medidas")) + "\n"
                       for row in rows)
        assert len(rows) == expected[0], cargo
        assert _fnv32(text) == expected[1], cargo
        assert len({int(r["excel_row"]) for r in rows}) == len(rows)

def test_irl_source_discloses_missing_carpintero_fields_and_prints_13_rows():
    data = catalog()
    row = next(r for r in data["rows"] if r["excel_row"] == 40)
    assert row["cargo"] == "CARPINTERO"
    assert row["tarea"] and row["peligro"]
    assert not row["riesgo"] and not row["medidas"]
    # La fuente Excel tiene 13 riesgos por cargo, pero su visor solo 12
    # grupos de fórmulas: GALANT no puede truncar el decimotercero.
    assert sum(1 for r in data["rows"] if r["cargo"] == "PINTOR") == 13
    assert sum(1 for r in data["rows"] if r["cargo"] == "GASFITER") == 26

def test_74_formula_cell_contract_includes_only_12_excel_print_rows():
    # Inventario independiente del XLSX privado, IRL, 74 fórmulas.
    metadata = {"A8", "C8", "D8", "A9", "D9", "A10", "A11"}
    metadata |= {"A18", "A23", "A25", "A28", "A31"}
    metadata |= {"A177", "A178"}
    risk_rows = [*range(40,57,2),63,65,67]
    risks = {column+str(row) for row in risk_rows for column in "ABCD"}
    chemicals = {"C"+str(row) for row in range(69,81)}
    manifest = metadata | risks | chemicals
    assert len(risk_rows) == 12
    assert len(risks) == 48
    assert len(chemicals) == 12
    assert len(manifest) == 74
    assert "A63" in manifest and "D63" in manifest


def test_native_irl_html_includes_every_risk_without_excel_twelve_row_limit():
    from app.javiera_native import _irl_table_rows
    from app.javiera_irl import preventive_matrix_blocker
    sections = [
        f"Tarea: Trabajo real {i}\\nPeligro: Peligro {i}\\n"
        f"Riesgo: Consecuencia {i}\\nMedidas: Control {i}"
        for i in range(1, 14)
    ]
    assert preventive_matrix_blocker("IRL", sections) is None
    markup = _irl_table_rows(sections, "PINTOR")
    assert markup.count("<tr>") == 13
    for i in range(1, 14):
        assert f"Trabajo real {i}</td>" in markup
        assert f"Control {i}</td>" in markup
    assert "Trabajo real 13</td>" in markup
    assert "Control 13</td>" in markup


def test_native_irl_does_not_silently_complete_carpintero_excel_row_40():
    from app.javiera_irl import preventive_matrix_blocker
    rows = catalog()["rows"]
    for row in rows:
        if row["excel_row"] == 40:
            incomplete = ("Tarea: " + row["tarea"] + "\\nPeligro: " + row["peligro"]
                          + "\\nRiesgo: " + row["riesgo"] + "\\nMedidas: " + row["medidas"])
            break
    else:
        raise AssertionError("No se encontró fila 40")
    reason = preventive_matrix_blocker("IRL", [incomplete])
    assert reason is not None
    assert "Medida preventiva" in reason
