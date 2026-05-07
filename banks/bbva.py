"""
Parser para extractos del banco BBVA (formato Excel oficial).

Columnas típicas del extracto BBVA España:
  F.Valor | F.Operación | Concepto | Movimiento | Importe | Saldo

Este archivo sirve como plantilla para implementar parsers de bancos concretos.
Para agregar otro banco, duplica este archivo y adapta la lógica.
"""

import pandas as pd
from banks.base import BankParser
from core.schema import empty_standard_df

# Columnas exactas del extracto BBVA; ajustar si cambia el formato
_BBVA_SIGNATURE_COLS = {"f.valor", "concepto", "importe", "saldo"}


class BBVAParser(BankParser):
    bank_name = "BBVA"
    priority = 80  # alta prioridad: si detecta columnas BBVA, lo toma antes que genérico

    def can_parse(self, df: pd.DataFrame, filename: str = "") -> bool:
        cols_norm = {c.strip().lower() for c in df.columns}
        return _BBVA_SIGNATURE_COLS.issubset(cols_norm)

    def parse(self, df: pd.DataFrame, filename: str = "") -> pd.DataFrame:
        # Normalizar nombres de columna para búsqueda insensible a mayúsculas/espacios
        df = df.copy()
        df.columns = [c.strip().lower() for c in df.columns]

        out = empty_standard_df()
        out["fecha"] = pd.to_datetime(df["f.valor"], dayfirst=True, errors="coerce")
        out["descripcion"] = df["concepto"].astype(str)
        out["importe"] = pd.to_numeric(
            df["importe"].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce"
        )
        out["saldo"] = pd.to_numeric(
            df["saldo"].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce"
        )
        out["referencia"] = df.get("referencia", pd.Series(dtype=str)).astype(str)
        out["banco"] = self.bank_name
        out["cuenta"] = df.get("cuenta", pd.Series(dtype=str)).astype(str)
        out["archivo"] = filename

        return out.dropna(subset=["fecha", "importe"])
