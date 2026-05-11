"""
Orquestador de parsers: selecciona el parser adecuado para cada archivo.

Cambio respecto a la versión anterior: normalize() ya no lanza ValueError
cuando ningún parser coincide; devuelve None para que app.py pueda mostrar
la interfaz de mapeo manual en lugar de un mensaje de error.
"""

import pandas as pd
from banks.base import BankParser
from banks.bbva import BBVAParser
from banks.generic import GenericParser, detect_columns, parse_with_mapping, _parse_single_number
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
    Raises ValueError con causa específica si el resultado está vacío o es inválido.
    """
    df_std = parse_with_mapping(df_raw, mapping, filename, bank_name="Manual")
    errors = validate_standard_df(df_std)
    if errors:
        raise ValueError(f"Error en el mapeo: {errors}")
    if df_std.empty:
        causa = _diagnose_empty_result(df_raw, mapping)
        raise ValueError(causa)
    return df_std, "Manual"


def _diagnose_empty_result(df_raw: pd.DataFrame, mapping: dict) -> str:
    """Determina la causa concreta por la que parse_with_mapping devolvió 0 filas."""
    from utils.text_cleaning import parse_date

    if df_raw.empty:
        return "La hoja parece vacía — no se encontraron filas de datos."

    col_fecha = mapping.get("fecha")
    col_deb   = mapping.get("debito")
    col_cred  = mapping.get("credito")
    col_imp   = mapping.get("importe")

    # Verificar fechas
    if col_fecha and col_fecha in df_raw.columns:
        fechas = pd.to_datetime(
            df_raw[col_fecha].apply(parse_date), errors="coerce"
        )
        n_fecha = int(fechas.notna().sum())
        if n_fecha == 0:
            sample = df_raw[col_fecha].dropna().head(3).tolist()
            return (
                f"No se encontraron fechas válidas en la columna '{col_fecha}'. "
                f"Muestra de valores: {sample}. "
                "Prueba con otra columna o ajusta la fila de encabezado."
            )
    else:
        return "No se seleccionó una columna de Fecha válida."

    # Verificar importes
    has_valid_amount = False
    for col in [col_deb, col_cred, col_imp]:
        if col and col in df_raw.columns:
            parsed = df_raw[col].apply(_parse_single_number)
            if parsed.notna().any():
                has_valid_amount = True
                break

    if not has_valid_amount:
        cols_usadas = [c for c in [col_deb, col_cred, col_imp] if c]
        return (
            f"No se encontraron montos válidos en las columnas {cols_usadas}. "
            "Verifica que contengan números (acepta formatos 1.234,56 y 1,234.56)."
        )

    n_total = len(df_raw)
    return (
        f"El encabezado fue detectado pero las {n_total} filas de datos quedaron vacías "
        "tras filtrar por fecha válida. "
        "Revisa la fila de encabezado seleccionada o el separador del archivo."
    )


def diagnose(df_raw: pd.DataFrame) -> dict:
    """
    Devuelve información de diagnóstico detallada sobre un DataFrame crudo.
    Incluye estadísticas de parsing para facilitar la resolución de problemas.
    """
    from utils.text_cleaning import parse_date

    detected = detect_columns(df_raw)

    n_total = len(df_raw)
    n_all_empty = int(df_raw.apply(
        lambda row: row.isna().all() or (row.astype(str).str.strip() == "").all(), axis=1
    ).sum())

    # Estadísticas de fechas
    col_fecha = detected.get("fecha")
    n_fecha_valida = 0
    if col_fecha and col_fecha in df_raw.columns:
        fechas = pd.to_datetime(df_raw[col_fecha].apply(parse_date), errors="coerce")
        n_fecha_valida = int(fechas.notna().sum())

    # Estadísticas de importes
    n_debito_valido  = 0
    n_credito_valido = 0
    n_importe_valido = 0
    for key, counter in [("debito", "n_debito_valido"), ("credito", "n_credito_valido"), ("importe", "n_importe_valido")]:
        col = detected.get(key)
        if col and col in df_raw.columns:
            parsed = df_raw[col].apply(_parse_single_number)
            val = int(parsed.notna().sum())
            if key == "debito":   n_debito_valido = val
            elif key == "credito": n_credito_valido = val
            else: n_importe_valido = val

    # Intento de parseo real para contar movimientos
    n_movimientos = 0
    causa_falla = ""
    col_deb = detected.get("debito")
    col_cred = detected.get("credito")
    col_imp = detected.get("importe")
    has_amount = any(detected.get(k) for k in ("importe", "debito", "credito"))

    if col_fecha and has_amount:
        try:
            df_try = parse_with_mapping(df_raw, detected, "_diagnose_")
            n_movimientos = len(df_try)
        except Exception:
            n_movimientos = 0

    if n_movimientos == 0:
        if n_total == 0:
            causa_falla = "La hoja parece vacía"
        elif not col_fecha:
            causa_falla = "No se detectó columna de Fecha"
        elif n_fecha_valida == 0:
            causa_falla = "No se encontraron fechas válidas en la columna detectada"
        elif not has_amount:
            causa_falla = "No se detectó columna de Débito, Crédito ni Importe"
        elif n_debito_valido == 0 and n_credito_valido == 0 and n_importe_valido == 0:
            causa_falla = "No se encontraron débitos/créditos válidos"
        else:
            causa_falla = "Encabezado detectado pero filas de datos vacías tras filtrado"

    return {
        "columnas_disponibles":       list(df_raw.columns),
        "columnas_detectadas":        {k: v for k, v in detected.items() if v is not None},
        "columnas_faltantes":         [k for k, v in detected.items() if v is None],
        "n_filas":                    n_total,
        "n_filas_vacias":             n_all_empty,
        "n_fecha_valida":             n_fecha_valida,
        "n_debito_valido":            n_debito_valido,
        "n_credito_valido":           n_credito_valido,
        "n_importe_valido":           n_importe_valido,
        "n_movimientos_estimados":    n_movimientos,
        "causa_falla":                causa_falla,
        "muestra":                    df_raw.head(10),
    }


def get_registered_banks() -> list[str]:
    """Lista de bancos con parser específico registrado."""
    return [p.bank_name for p in _REGISTERED_PARSERS]
