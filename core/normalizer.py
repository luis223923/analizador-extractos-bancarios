"""
Orquestador de parsers: selecciona el parser adecuado para cada archivo.

El registro de parsers es automático: cualquier clase que herede de BankParser
y esté importada aquí queda disponible. Para añadir un banco, sólo hay que
importar su clase en este archivo.
"""

import pandas as pd
from banks.base import BankParser
from banks.bbva import BBVAParser
from banks.generic import GenericParser
from core.schema import validate_standard_df

# Registro central de parsers — añadir aquí las importaciones de nuevos bancos
_REGISTERED_PARSERS: list[BankParser] = [
    BBVAParser(),
    GenericParser(),
]

# Ordenar por prioridad descendente (mayor prioridad = se prueba antes)
_REGISTERED_PARSERS.sort(key=lambda p: p.priority, reverse=True)


def normalize(df_raw: pd.DataFrame, filename: str = "") -> tuple[pd.DataFrame, str]:
    """
    Selecciona el parser apropiado y devuelve el DataFrame en esquema estándar.

    Returns:
        (df_standard, parser_name) — datos normalizados y nombre del parser usado.
    Raises:
        ValueError si ningún parser puede manejar el archivo.
    """
    for parser in _REGISTERED_PARSERS:
        if parser.can_parse(df_raw, filename):
            df_std = parser.parse(df_raw, filename)
            errors = validate_standard_df(df_std)
            if errors:
                raise ValueError(f"Error en parser '{parser.bank_name}': {errors}")
            return df_std, parser.bank_name

    raise ValueError(
        "No se encontró un parser compatible. "
        "Verifica que el archivo tenga columnas de fecha e importe identificables."
    )


def get_registered_banks() -> list[str]:
    """Lista de bancos soportados por el sistema."""
    return [p.bank_name for p in _REGISTERED_PARSERS]
