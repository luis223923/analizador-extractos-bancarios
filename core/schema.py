"""
Esquema estándar de columnas para todos los extractos bancarios.

Cualquier parser de banco debe producir un DataFrame con exactamente
estas columnas. Esto garantiza que todos los módulos (clasificador,
saldos, duplicados, exportador) funcionen con cualquier banco.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd

# Columnas canónicas del sistema — no modificar sin actualizar todos los módulos
STANDARD_COLUMNS = [
    "fecha",        # datetime  — fecha de la operación
    "descripcion",  # str       — texto libre del concepto
    "importe",      # float     — positivo=ingreso, negativo=gasto
    "saldo",        # float     — saldo tras la operación (puede ser NaN)
    "referencia",   # str       — número de referencia/operación (puede ser NaN)
    "banco",        # str       — nombre del banco origen
    "cuenta",       # str       — número de cuenta / IBAN parcial (puede ser NaN)
    "moneda",       # str       — código de moneda: BOB, USD, EUR, Sin definir
    "archivo",      # str       — nombre del archivo cargado
]

COLUMN_DTYPES = {
    "fecha": "datetime64[ns]",
    "descripcion": "object",
    "importe": "float64",
    "saldo": "float64",
    "referencia": "object",
    "banco": "object",
    "cuenta": "object",
    "moneda": "object",
    "archivo": "object",
}

# Opciones de moneda disponibles en la interfaz
MONEDAS = ["BOB", "USD", "EUR", "Sin definir"]

# Prefijo de símbolo para cada moneda
MONEDA_PREFIJO = {
    "BOB": "Bs",
    "USD": "USD",
    "EUR": "EUR",
    "Sin definir": "",
}


def empty_standard_df() -> pd.DataFrame:
    """Devuelve un DataFrame vacío con el esquema estándar."""
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def validate_standard_df(df: pd.DataFrame) -> list[str]:
    """Devuelve lista de errores de validación; lista vacía = OK."""
    errors = []
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"Columnas faltantes: {missing}")
    if not missing and not pd.api.types.is_datetime64_any_dtype(df["fecha"]):
        errors.append("La columna 'fecha' debe ser datetime.")
    if not missing and not pd.api.types.is_numeric_dtype(df["importe"]):
        errors.append("La columna 'importe' debe ser numérica.")
    return errors
