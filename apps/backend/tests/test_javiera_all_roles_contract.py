"""Contrato matricial de 25 cargos: IRL y PTS sin asociación cruzada.

Todos los nombres/valores son sintéticos; no sustituye la revisión preventiva
de la matriz privada de cada empresa. Este test ejecuta el MISMO motor OOXML
que produce los documentos.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app.javiera_workbook import (
    IRL_PRINT_RISK_ROWS,
    _IRL_SUMMARY_ALIASES,
    _irl_role_key,
    fill_workbook,
    irl_continuations,
    matrix_records,
)
from test_javiera_workbook import master
from test_javiera_irl_rut_regression import formula_at


ROLES = [
    "GASFITER", "PINTOR", "CARPINTERO", "ENFIERRADOR", "TECHADOR",
    "CERAMISTA", "OPERARIO DE HORMIGON", "MOLDAJERO", "ALUMINERO",
    "OPERARIO DE URBANIZACION", "IMPERMEABILIZADOR", "ESTRUCTURERO METÁLICO",
    "NIVELADOR DE PISOS", "ALFOMBRERO", "HOJALATERO", "ALBAÑIL",
    "ELETRICO", "INSTALADOR DE EIFS", "CAMARERO",
    "INSTALADOR DE PANDERETAS / VIBRADOS", "CARPINTERIA EN TERMINACIONES",
    "MUEBLISTA", "PAISAJISTA", "OPERARIO DE OBRA GRUESA", "SOLDADOR",
]


@pytest.fixture(scope="module")
def all_roles_master():
    book = load_workbook(io.BytesIO(master()))
    risks = book["MATRIZ IRL"]
    pts = book["MATRIZ PTS"]
    optimized = book["Matriz IRL Optimizada"]
    for sheet in (risks, pts, optimized):
        if sheet.max_row > 1:
            sheet.delete_rows(2, sheet.max_row - 1)
    irl = book["IRL"]
    for target_row in IRL_PRINT_RISK_ROWS:
        for destination, source in zip("ABCD", "CDEF"):
            irl[f"{destination}{target_row}"] = (
                "=IF('MATRIZ IRL'!B2='Datos Contrato'!C29,"
                "'MATRIZ IRL'!" + source + "2,\"\")"
            )
    irl["A23"] = ("=VLOOKUP('Datos Contrato'!C29,"
                  "'Matriz IRL Optimizada'!A1:E100,2,FALSE)")
    for coord, index in (("A25", 3), ("A28", 4), ("A31", 5)):
        irl[coord] = ("=VLOOKUP('Datos Contrato'!C29,"
                      "'Matriz IRL Optimizada'!A1:E100," +
                      str(index) + ",FALSE)")
    irl.print_area = "A1:D80"
    for role_index, role in enumerate(ROLES):
        summary_role = _IRL_SUMMARY_ALIASES.get(_irl_role_key(role), role)
        optimized.append([summary_role, *[
            f"CONDICION QA {role_index} {j}" for j in range(1, 5)
        ]])
        pts.append([
            role, "PROCEDIMIENTO", "TITULO",
            *[f"PTS QA {role_index} {j}" for j in range(17)]
        ])
        for risk in range(13):
            risks.append([
                100 * role_index + risk + 1, role,
                *[f"IRL QA {role_index} RIESGO {risk} CAMPO {column}"
                  for column in "CDEF"],
            ])
    # Simula el duplicado verdadero: la misma tarea preventiva de GASFITER
    # no puede generar una segunda firma o una actividad artificial.
    risks.append([9999, "GASFITER", *[
        "IRL QA 0 RIESGO 3 CAMPO " + column for column in "CDEF"
    ]])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


@pytest.mark.parametrize("role", ROLES)
def test_all_25_roles_keep_exact_irl_risks_and_17_pts_fields(all_roles_master, role):
    raw = all_roles_master
    risks = matrix_records(raw, role, "IRL")
    procedures = matrix_records(raw, role, "PTS")
    assert len(risks) == 13, (role, len(risks))
    assert len(procedures) == 1, (role, len(procedures))
    assert all(r["values"].get(c) for r in risks for c in "CDEF")
    assert all(procedures[0]["values"].get(c) for c in "DEFGHIJKLMNOPQRST")

    workbook = fill_workbook(raw, {"role": role}, "irl")
    paginated, names = irl_continuations(workbook, role)
    assert names == ["IRL continuación 1"], role
    assert formula_at(paginated, "IRL", "A23").startswith(
        "'Matriz IRL Optimizada'!$B$"
    )
    assert formula_at(paginated, names[0], "A31").startswith(
        "'Matriz IRL Optimizada'!$E$"
    )
    for index, risk in enumerate(risks):
        target_sheet = "IRL" if index < 12 else names[(index // 12) - 1]
        target_row = IRL_PRINT_RISK_ROWS[index % 12]
        for target_col, source_col in zip("ABCD", "CDEF"):
            formula = formula_at(paginated, target_sheet, target_col + str(target_row))
            assert formula is not None, (role, index, target_col)
            assert (
                "'MATRIZ IRL'!$" + source_col + "$" + str(risk["row"])
            ) in formula, (role, index, target_col, formula)


def test_25_roles_are_unique_and_no_unlisted_role_is_created(all_roles_master):
    assert len(ROLES) == len(set(ROLES)) == 25
    assert len({
        role for role in ROLES if matrix_records(all_roles_master, role, "PTS")
    }) == 25
    with pytest.raises(Exception, match="No existe información"):
        matrix_records(all_roles_master, "CARGO NO VERIFICADO", "IRL")



def test_no_hidden_risk_deletion_for_roles_other_than_gasfiter():
    """Nunca asumir que una actividad repetida debe desaparecer."""
    book = load_workbook(io.BytesIO(master()))
    risks = book["MATRIZ IRL"]
    repeated = [1, "PINTOR", "ACTIVIDAD REPETIDA", "PELIGRO", "RIESGO", "CONTROL"]
    risks.append(repeated)
    risks.append(repeated)
    result = io.BytesIO()
    book.save(result)
    records = matrix_records(result.getvalue(), "PINTOR", "IRL")
    assert len(records) == 2
    assert records[0]["row"] != records[1]["row"]
