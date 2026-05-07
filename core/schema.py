"""
Esquema estándar de columnas para todos los extractos bancarios.

Los parsers producen las CORE_COLUMNS. Las columnas extendidas son
añadidas por app.py a partir de los metadatos ingresados por el usuario.
"""

import pandas as pd

# Columnas producidas por los parsers (requeridas por validate_standard_df)
_CORE_COLUMNS = [
    "fecha",        # datetime  — fecha de la operación
    "descripcion",  # str       — concepto del movimiento
    "importe",      # float     — positivo=ingreso, negativo=gasto
    "saldo",        # float     — saldo tras la operación (puede ser NaN)
    "referencia",   # str       — número de referencia / folio
    "banco",        # str       — nombre del banco (asignado por el parser)
    "cuenta",       # str       — número de cuenta detectado en el archivo
    "archivo",      # str       — nombre del archivo cargado
]

# Columnas extendidas añadidas por app.py con los metadatos del usuario
_EXTENDED_COLUMNS = [
    "empresa",      # str       — empresa propietaria de la cuenta
    "nombre_corto", # str       — alias corto de la cuenta (ej. "BNB Cte BOB")
    "moneda",       # str       — código de moneda: BOB, USD, EUR, Sin definir
    "tipo_cuenta",  # str       — Corriente, Ahorro, Vista, Plazo Fijo, Otra
    "debito",       # float     — valor absoluto del egreso (>= 0)
    "credito",      # float     — valor absoluto del ingreso (>= 0)
    "hoja_origen",  # str       — hoja del Excel de origen
    "fila_origen",  # str       — fila aproximada en el archivo de origen
    "observaciones",# str       — notas libres
]

# Esquema completo del sistema
STANDARD_COLUMNS = _CORE_COLUMNS + _EXTENDED_COLUMNS

COLUMN_DTYPES = {
    "fecha":        "datetime64[ns]",
    "descripcion":  "object",
    "importe":      "float64",
    "saldo":        "float64",
    "referencia":   "object",
    "banco":        "object",
    "cuenta":       "object",
    "archivo":      "object",
    "empresa":      "object",
    "nombre_corto": "object",
    "moneda":       "object",
    "tipo_cuenta":  "object",
    "debito":       "float64",
    "credito":      "float64",
    "hoja_origen":  "object",
    "fila_origen":  "object",
    "observaciones":"object",
}

# Opciones de moneda disponibles
MONEDAS = ["BOB", "USD", "EUR", "Sin definir"]

# Tipos de cuenta disponibles
TIPOS_CUENTA = [
    "Cuenta corriente",
    "Caja de ahorro",
    "Cuenta recaudadora",
    "Cuenta operativa",
    "Cuenta inversión",
    "Cuenta custodia",
    "Otra",
    "Sin definir",
]

# Empresas registradas en el sistema
EMPRESAS = [
    "NSPF",
    "NSVS",
    "GNI",
    "Otra",
    "Sin definir",
]

# Bancos sugeridos (referencia — no limita el ingreso manual)
BANCOS = [
    "BNB",
    "BCP",
    "Banco Mercantil Santa Cruz",
    "Banco Ganadero",
    "Banco Bisa",
    "Banco Unión",
    "Banco Económico",
    "Banco FIE",
    "BancoSol",
    "Otro",
    "Sin definir",
]

# Prefijo de símbolo para cada moneda
MONEDA_PREFIJO = {
    "BOB": "Bs",
    "USD": "USD",
    "EUR": "EUR",
    "Sin definir": "",
}


def fmt_amount(value, moneda: str) -> str:
    """
    Formatea un número con el prefijo de moneda correcto.
    Ej: fmt_amount(1500, 'BOB') → 'Bs 1,500.00'
        fmt_amount(-800, 'USD') → '-USD 800.00'
        fmt_amount(999, 'Sin definir') → '999.00'
    """
    try:
        v = float(value)
        prefix = MONEDA_PREFIJO.get(moneda, "")
        formatted = f"{abs(v):,.2f}"
        result = f"{prefix} {formatted}".strip() if prefix else formatted
        return f"-{result}" if v < 0 else result
    except (ValueError, TypeError):
        return ""


def empty_standard_df() -> pd.DataFrame:
    """Devuelve un DataFrame vacío con el esquema estándar completo."""
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def validate_standard_df(df: pd.DataFrame) -> list[str]:
    """
    Valida que el DataFrame tenga las columnas core requeridas.
    Las columnas extendidas son opcionales (las añade app.py).
    """
    errors = []
    missing = [c for c in _CORE_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"Columnas faltantes: {missing}")
    if not missing and not pd.api.types.is_datetime64_any_dtype(df["fecha"]):
        errors.append("La columna 'fecha' debe ser datetime.")
    if not missing and not pd.api.types.is_numeric_dtype(df["importe"]):
        errors.append("La columna 'importe' debe ser numérica.")
    return errors
