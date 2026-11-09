"""Migración determinista de las 23 fórmulas 'NUMEROS A LETRAS' del Excel.

Es una traducción de la salida de la hoja 'NUMEROS A LETRAS'!S4:
el contrato original usa 'Datos Contrato'!C32 y el texto generado en C33.
Se preserva por ahora la redacción del Excel, incluso en casos donde la
gramática podría perfeccionarse. Cualquier revisión editorial será separada.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


INVALID_AMOUNT = "REVISAR MONTO: ingrese pesos enteros de 0 a 999.999.999"
_UNDER_30 = {
    1:"uno",2:"dos",3:"tres",4:"cuatro",5:"cinco",6:"seis",
    7:"siete",8:"ocho",9:"nueve",10:"diez",11:"once",12:"doce",
    13:"trece",14:"catorce",15:"quince",16:"dieciséis",
    17:"diecisiete",18:"dieciocho",19:"diecinueve",20:"veinte",
    21:"veintiuno",22:"veintidós",23:"veintitrés",24:"veinticuatro",
    25:"veinticinco",26:"veintiséis",27:"veintisiete",28:"veintiocho",
    29:"veintinueve",
}
_TENS = {
    3:"treinta",4:"cuarenta",5:"cincuenta",6:"sesenta",
    7:"setenta",8:"ochenta",9:"noventa",
}
_HUNDREDS = {
    1:"ciento",2:"doscientos",3:"trescientos",4:"cuatrocientos",
    5:"quinientos",6:"seiscientos",7:"setecientos",8:"ochocientos",
    9:"novecientos",
}


def _group(value: int) -> str:
    if not 0 <= value <= 999:
        raise ValueError("El bloque numérico debe contener tres cifras.")
    if value == 0:
        return ""
    hundreds, rest = divmod(value, 100)
    head = "cien" if value == 100 else _HUNDREDS.get(hundreds, "")
    if rest == 0:
        tail = ""
    elif rest < 30:
        tail = _UNDER_30[rest]
    else:
        tens, units = divmod(rest, 10)
        tail = _TENS[tens] + ((" y " + _UNDER_30[units]) if units else "")
    return (head + " " + tail).strip()


def _apocope(text: str) -> str:
    # Es exactamente la regla aplicada a Q3/Q4 del Excel.
    if text.endswith("veintiuno"):
        return text[:-9] + "veintiún"
    if text.endswith("uno"):
        return text[:-3] + "un"
    return text


def pesos_a_letras_excel(value) -> str:
    """Salida equivalente a S4 para 0..999.999.999 pesos enteros."""
    if isinstance(value, bool):
        return INVALID_AMOUNT
    # El formulario web envía strings: aceptar solamente dígitos sin
    # puntuación para no confundir 550.000 (separador de miles) con 550 CLP.
    if isinstance(value, str) and not value.strip().isdecimal():
        return INVALID_AMOUNT
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return INVALID_AMOUNT
    if not number.is_finite() or number < 0 or number >= 1_000_000_000:
        return INVALID_AMOUNT
    if number != number.to_integral_value():
        return INVALID_AMOUNT
    amount = int(number)
    if amount == 0:
        return "Cero pesos."
    millions, remainder = divmod(amount, 1_000_000)
    thousands, units = divmod(remainder, 1000)
    pieces = []
    if millions:
        pieces.append("un millón" if millions == 1 else
                      _apocope(_group(millions)) + " millones")
    if thousands:
        pieces.append("mil" if thousands == 1 else
                      _apocope(_group(thousands)) + " mil")
    if units:
        pieces.append(_group(units))
    text = " ".join(pieces)
    return text[:1].upper() + text[1:] + (" peso." if amount == 1 else " pesos.")
