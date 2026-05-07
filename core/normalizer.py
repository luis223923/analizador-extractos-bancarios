"""
Orquestador de parsers: selecciona el parser adecuado para cada archivo.

Cambio respecto a la versión anterior: normalize() ya no lanza ValueError
cuando ningún parser coincide; devuelve None para que app.py pueda mostrar
la interfaz de mapeo manual en lugar de un mensaje de error.
"""

import pandas as pd
from banks.base import BankParser
from banks.bbva import BBVAParser
from banks.generic import GenericParser, detect_columns, parse_with_mapping
from core.schema import validate_standard_df

# Registro central — añadir importaciones de nuevos bancos aquí
_REGISTERED_PARSERS: list[BankParser] = [
    BBVAParser(),
    GenericParser(),
]
_REGISTERED_PARSERS.sort(key=lambda p: p.priority, reverse=True)


def normalize(df_raw: pd.DataFrame, filename: str = "") -> tuple[pd.DataFrame, str] | None:
    """
    Intenta normalizar automáticamente usando los parsers registrados.

    Returns:
        (df_standard, parser_name) si tuvo éxito.
        None si ningún parser puede manejar el archivo
              → la app mostrará la UI de mapeo manual.
    """
    for parser in _REGISTERED_PARSERS:
        try:
            if not parser.can_parse(df_raw, filename):
                continue
            df_std = parser.parse(df_raw, filename)
            errors = validate_standard_df(df_std)
            if not errors and not df_std.empty:
                return df_std, parser.bank_name
        except Exception:
            continue
    return None


def normalize_with_mapping(
    df_raw: pd.DataFrame,
    mapping: dict,
    filename: str,
) -> tuple[pd.DataFrame, str]:
    """
    Normaliza usando un mapeo manual de columnas definido por el usuario.

    mapping keys: fecha, descripcion, debito, credito, importe, saldo, referencia, cuenta
    Raises ValueError si el resultado está vacío o es inválido.
    """
    df_std = parse_with_mapping(df_raw, mapping, filename, bank_name="Manual")
    errors = validate_standard_df(df_std)
    if errors:
        raise ValueError(f"Error en el mapeo: {errors}")
    if df_std.empty:
        raise ValueError(
            "El mapeo no produjo movimientos válidos. "
            "Verifica que la columna de Fecha contenga fechas reales "
            "y la de importe contenga números."
        )
    return df_std, "Manual"


def diagnose(df_raw: pd.DataFrame) -> dict:
    """
    Devuelve información de diagnóstico sobre un DataFrame crudo.
    Usado por la UI de mapeo manual para mostrar qué se detectó y qué falta.
    """
    detected = detect_columns(df_raw)
    return {
        "columnas_disponibles": list(df_raw.columns),
        "columnas_detectadas": {k: v for k, v in detected.items() if v is not None},
        "columnas_faltantes":  [k for k, v in detected.items() if v is None],
        "n_filas": len(df_raw),
        "muestra": df_raw.head(10),
    }


def get_registered_banks() -> list[str]:
    """Lista de bancos con parser específico registrado."""
    return [p.bank_name for p in _REGISTERED_PARSERS]
