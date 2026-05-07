"""
Parser genérico con auto-detección de columnas.

Funciona cuando el usuario sube cualquier Excel/CSV con columnas de fecha,
descripción e importe, independientemente del banco. Usa heurísticas para
identificar las columnas relevantes.
"""

import re
import pandas as pd
from banks.base import BankParser
from core.schema import STANDARD_COLUMNS, empty_standard_df

# Palabras clave para identificar cada columna por su nombre
_FECHA_HINTS = ["fecha", "date", "fec", "día", "dia", "f.valor", "f.op", "f oper"]
_DESC_HINTS = ["concepto", "descripcion", "descripción", "detalle", "movimiento",
               "operacion", "operación", "glosa", "referencia texto", "comercio"]
_IMPORTE_HINTS = ["importe", "monto", "cantidad", "amount", "cargo/abono",
                  "valor", "debito", "credito", "débito", "crédito"]
_SALDO_HINTS = ["saldo", "balance", "disponible", "saldo actual"]
_REF_HINTS = ["referencia", "ref", "numero op", "nº op", "num op", "id oper"]
_CUENTA_HINTS = ["cuenta", "iban", "nº cuenta", "num cuenta"]


def _best_match(columns: list[str], hints: list[str]) -> str | None:
    """Devuelve la columna cuyo nombre normalizado mejor coincide con hints."""
    def normalize(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    norm_hints = [normalize(h) for h in hints]
    cols_norm = [(normalize(c), c) for c in columns]

    # Coincidencia exacta primero
    for norm_c, orig_c in cols_norm:
        if norm_c in norm_hints:
            return orig_c

    # Coincidencia parcial (la pista está contenida en el nombre de columna)
    for norm_c, orig_c in cols_norm:
        for hint in norm_hints:
            if hint in norm_c:
                return orig_c

    return None


class GenericParser(BankParser):
    bank_name = "Genérico"
    priority = 0  # último recurso

    def can_parse(self, df: pd.DataFrame, filename: str = "") -> bool:
        cols = list(df.columns)
        has_date = _best_match(cols, _FECHA_HINTS) is not None
        has_amount = _best_match(cols, _IMPORTE_HINTS) is not None
        return has_date and has_amount

    def parse(self, df: pd.DataFrame, filename: str = "") -> pd.DataFrame:
        cols = list(df.columns)
        col_fecha = _best_match(cols, _FECHA_HINTS)
        col_desc = _best_match(cols, _DESC_HINTS)
        col_importe = _best_match(cols, _IMPORTE_HINTS)
        col_saldo = _best_match(cols, _SALDO_HINTS)
        col_ref = _best_match(cols, _REF_HINTS)
        col_cuenta = _best_match(cols, _CUENTA_HINTS)

        if not col_fecha or not col_importe:
            raise ValueError("No se encontraron columnas de fecha e importe.")

        out = empty_standard_df()
        out["fecha"] = pd.to_datetime(df[col_fecha], dayfirst=True, errors="coerce")
        out["descripcion"] = df[col_desc].astype(str) if col_desc else "Sin descripción"
        out["importe"] = pd.to_numeric(
            df[col_importe].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce"
        )
        out["saldo"] = (
            pd.to_numeric(df[col_saldo].astype(str).str.replace(",", "."), errors="coerce")
            if col_saldo else pd.NA
        )
        out["referencia"] = df[col_ref].astype(str) if col_ref else pd.NA
        out["banco"] = self.bank_name
        out["cuenta"] = df[col_cuenta].astype(str) if col_cuenta else pd.NA
        out["archivo"] = filename

        return out.dropna(subset=["fecha", "importe"])
