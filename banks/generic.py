"""
Parser genérico con auto-detección avanzada de columnas.

Detecta columnas por palabras clave (español, inglés y variantes bancarias
de Latinoamérica y España). Soporta tanto columna única de Importe como
columnas separadas de Débito y Crédito.
"""

import re
import math
import pandas as pd
from banks.base import BankParser
from core.schema import empty_standard_df


# ─── Sinónimos exhaustivos por campo estándar ────────────────────────────
_FECHA_HINTS = [
    "fecha", "date", "fec", "día", "dia",
    "f.valor", "f.op", "f oper", "fechaoperacion", "fechavalor",
    "fecha movimiento", "fecha operacion", "fecha valor", "fecha op",
    "fecha mov", "fecoper", "fecval", "fec op", "fec mov",
    "transaction date", "value date", "booking date", "posting date",
    "fecha proceso", "fecha registro", "fecha contable",
]
_DESC_HINTS = [
    "concepto", "descripcion", "descripción", "detalle", "movimiento",
    "operacion", "operación", "glosa", "referencia texto", "comercio",
    "texto", "narracion", "narración", "nota", "observacion", "observación",
    "descripcion movimiento", "descripcion operacion", "concepto operacion",
    "motivo", "beneficiario", "ordenante", "remitente", "destinatario",
    "description", "details", "narrative", "particulars", "memo",
    "denominacion", "denominación", "nombre operacion",
]
_IMPORTE_HINTS = [
    "importe", "monto", "cantidad", "amount",
    "cargo/abono", "cargo abono", "debe/haber", "debe haber",
    "importe operacion", "monto operacion", "monto bs", "monto usd",
    "importe eur", "importe €", "valor operacion", "movimiento",
]
_DEBITO_HINTS = [
    "debito", "débito", "debe", "cargo", "cargos",
    "egreso", "egresos", "retiro", "retiros", "salida", "salidas",
    "pago", "gasto", "gastos", "debit", "withdrawal", "out",
    "monto debito", "monto débito", "importe debito", "importe débito",
    "debitos", "débitos",
]
_CREDITO_HINTS = [
    "credito", "crédito", "haber", "abono", "abonos",
    "ingreso", "ingresos", "deposito", "depósito", "depositos", "depósitos",
    "entrada", "entradas", "credit", "deposit", "in",
    "monto credito", "monto crédito", "importe credito", "importe crédito",
    "creditos", "créditos",
]
_SALDO_HINTS = [
    "saldo", "balance", "disponible",
    "saldo actual", "saldo contable", "saldo disponible",
    "saldo final", "saldo cuenta", "saldo al cierre",
    "running balance", "saldo despues", "saldo después",
]
_REF_HINTS = [
    "referencia", "ref", "numero op", "nº op", "num op", "id oper",
    "numero referencia", "nro referencia", "nro. referencia",
    "numero operacion", "num operacion", "nro operacion",
    "codigo", "código", "folio", "numero transaccion", "transaction id",
    "voucher", "comprobante", "nro comprobante", "id transaccion",
    "numero documento", "num documento", "nro documento",
]
_CUENTA_HINTS = [
    "cuenta", "iban", "nº cuenta", "num cuenta", "numero cuenta",
    "cuenta origen", "cuenta destino", "account", "nro cuenta",
]


# ─── Utilidades de matching ───────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_column(columns: list, hints: list, exclude: set = None) -> str | None:
    """
    Devuelve la columna cuyo nombre mejor coincide con los hints dados.
    Excluye columnas ya asignadas a otros campos.
    """
    exclude = exclude or set()
    norm_hints = [_norm(h) for h in hints]
    candidates = [(_norm(c), c) for c in columns if c not in exclude]

    # 1. Coincidencia exacta normalizada
    for nc, orig in candidates:
        if nc in norm_hints:
            return orig

    # 2. El hint está contenido en el nombre de columna
    for nc, orig in candidates:
        for nh in norm_hints:
            if len(nh) >= 3 and nh in nc:
                return orig

    # 3. El nombre de columna está contenido en el hint
    for nc, orig in candidates:
        if len(nc) >= 3:
            for nh in norm_hints:
                if nc in nh:
                    return orig

    return None


def detect_columns(df: pd.DataFrame) -> dict:
    """
    Detecta las columnas más probables para cada campo estándar.
    Devuelve un dict; valor None cuando no pudo detectar el campo.
    """
    cols = list(df.columns)
    assigned: set = set()

    def pick(hints):
        col = find_column(cols, hints, exclude=assigned)
        if col:
            assigned.add(col)
        return col

    # Importe se detecta ANTES que débito/crédito para evitar que una columna
    # llamada "Importe" sea captada por hints compuestos como "importe debito".
    return {
        "fecha":       pick(_FECHA_HINTS),
        "descripcion": pick(_DESC_HINTS),
        "importe":     pick(_IMPORTE_HINTS),
        "debito":      pick(_DEBITO_HINTS),
        "credito":     pick(_CREDITO_HINTS),
        "saldo":       pick(_SALDO_HINTS),
        "referencia":  pick(_REF_HINTS),
        "cuenta":      pick(_CUENTA_HINTS),
    }


# ─── Limpieza de números ──────────────────────────────────────────────────
def _parse_single_number(raw) -> float:
    """
    Convierte un valor textual a float, manejando formatos europeos y anglosajones:
      - Europeo:       1.234,56  →  1234.56
      - Anglosajón:    1,234.56  →  1234.56
      - Simple:        1234,56   →  1234.56  /  1234.56
      - Negativo:      (1234,56) →  -1234.56  /  1234,56- → -1234.56
      - Con símbolo:   € 1.234,56  →  1234.56
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return float("nan")
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "n/a", "", "-", "—", "#"):
        return float("nan")

    # Limpiar símbolos de moneda, espacios y no-breaking spaces
    s = re.sub(r"[$€£ \s]", "", s)

    # Detectar negativos: paréntesis (1234) o guión final 1234-
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
        negative = True
    if s.endswith("-"):
        s = s[:-1]
        negative = True
    if s.startswith("-"):
        s = s[1:]
        negative = True

    if not s:
        return float("nan")

    n_dots = s.count(".")
    n_commas = s.count(",")

    try:
        if n_dots == 0 and n_commas == 0:
            result = float(s)

        elif n_dots == 0 and n_commas == 1:
            after = s.split(",")[1]
            # Si hay exactamente 3 dígitos tras la coma → separador de miles
            if len(after) == 3 and after.isdigit():
                result = float(s.replace(",", ""))
            else:
                # Decimal europeo: "1234,56"
                result = float(s.replace(",", "."))

        elif n_dots == 1 and n_commas == 0:
            # US decimal: "1234.56"  (si 3 cifras tras punto podría ser miles, pero
            # en extractos bancarios preferimos interpretarlo como decimal)
            result = float(s)

        elif n_dots == 1 and n_commas == 1:
            # Determinar cuál es miles y cuál es decimal según posición
            if s.rindex(",") > s.rindex("."):
                # "1.234,56" → europeo
                result = float(s.replace(".", "").replace(",", "."))
            else:
                # "1,234.56" → anglosajón
                result = float(s.replace(",", ""))

        elif n_dots > 1 and n_commas <= 1:
            # "1.234.567,89"
            if n_commas == 1 and s.rindex(",") > s.rindex("."):
                result = float(s.replace(".", "").replace(",", "."))
            else:
                result = float(s.replace(".", ""))

        elif n_commas > 1 and n_dots <= 1:
            # "1,234,567.89"
            if n_dots == 1 and s.rindex(".") > s.rindex(","):
                result = float(s.replace(",", ""))
            else:
                result = float(s.replace(",", ""))

        else:
            result = float(s)

    except (ValueError, IndexError):
        return float("nan")

    return -result if negative else result


def _clean_series(series: pd.Series) -> pd.Series:
    return series.apply(_parse_single_number)


# ─── Importe unificado desde columnas de débito/crédito/importe ──────────
def _resolve_importe(df: pd.DataFrame, col_deb, col_cred, col_imp) -> pd.Series:
    """
    Produce una serie de importes signados.
    Prioridad: importe con signos > débito+crédito separados > importe sin signo.
    """
    if col_imp:
        raw = _clean_series(df[col_imp])
        # Si ya tiene negativos, úsalo directamente
        if raw.dropna().lt(0).any():
            return raw
        # Si todo positivo pero hay columnas de débito/crédito, inferimos signo
        if col_deb or col_cred:
            result = _merge_deb_cred(df, col_deb, col_cred)
            # Donde no hay débito/crédito, usamos el importe tal cual
            no_dc = result.isna()
            result[no_dc] = raw[no_dc]
            return result
        return raw

    if col_deb or col_cred:
        return _merge_deb_cred(df, col_deb, col_cred)

    return pd.Series(pd.NA, index=df.index, dtype=float)


def _merge_deb_cred(df: pd.DataFrame, col_deb, col_cred) -> pd.Series:
    result = pd.Series(float("nan"), index=df.index, dtype=float)
    if col_cred:
        cred = _clean_series(df[col_cred])
        mask = cred.notna() & (cred != 0)
        result[mask] = cred[mask].abs()
    if col_deb:
        deb = _clean_series(df[col_deb])
        mask = deb.notna() & (deb != 0)
        result[mask] = -deb[mask].abs()
    return result


# ─── Función pública de parseo con mapeo explícito ───────────────────────
def parse_with_mapping(
    df: pd.DataFrame,
    mapping: dict,
    filename: str,
    bank_name: str = "Genérico",
) -> pd.DataFrame:
    """
    Convierte df al esquema estándar usando un mapeo explícito de columnas.

    mapping keys: fecha, descripcion, debito, credito, importe, saldo, referencia, cuenta
    Los valores son nombres de columna del df o None para ignorar.
    """
    col_fecha   = mapping.get("fecha")
    col_desc    = mapping.get("descripcion")
    col_debito  = mapping.get("debito")
    col_credito = mapping.get("credito")
    col_importe = mapping.get("importe")
    col_saldo   = mapping.get("saldo")
    col_ref     = mapping.get("referencia")
    col_cuenta  = mapping.get("cuenta")

    if not col_fecha:
        raise ValueError("Debes seleccionar la columna de Fecha.")
    if not col_importe and not col_debito and not col_credito:
        raise ValueError(
            "Debes seleccionar al menos una columna de importe "
            "(Importe, Débito o Crédito)."
        )

    out = empty_standard_df()
    out["fecha"]       = pd.to_datetime(df[col_fecha], dayfirst=True, errors="coerce")
    out["descripcion"] = df[col_desc].astype(str).str.strip() if col_desc else "Sin descripción"
    out["importe"]     = _resolve_importe(df, col_debito, col_credito, col_importe)
    out["saldo"]       = _clean_series(df[col_saldo])   if col_saldo  else pd.NA
    out["referencia"]  = df[col_ref].astype(str).str.strip() if col_ref else pd.NA
    out["banco"]       = bank_name
    out["cuenta"]      = df[col_cuenta].astype(str).str.strip() if col_cuenta else pd.NA
    out["archivo"]     = filename

    return out.dropna(subset=["fecha", "importe"])


# ─── Clase BankParser ─────────────────────────────────────────────────────
class GenericParser(BankParser):
    bank_name = "Genérico"
    priority = 0  # último recurso

    def can_parse(self, df: pd.DataFrame, filename: str = "") -> bool:
        d = detect_columns(df)
        has_date   = d["fecha"] is not None
        has_amount = any(d[k] is not None for k in ("importe", "debito", "credito"))
        return has_date and has_amount

    def parse(self, df: pd.DataFrame, filename: str = "") -> pd.DataFrame:
        return parse_with_mapping(df, detect_columns(df), filename, self.bank_name)
