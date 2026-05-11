"""
Parser genérico con auto-detección avanzada de columnas.

Detecta columnas por palabras clave (español, inglés y variantes bancarias
de Latinoamérica y España). Soporta tanto columna única de Importe como
columnas separadas de Débito y Crédito.

Lógica de importe: Importe = Crédito - Débito (valores absolutos en la fuente).
Solo se descartan filas sin fecha válida; filas con importe 0 o indeterminado
se conservan.
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
    "motivo", "description", "details", "narrative", "particulars", "memo",
    "denominacion", "denominación", "nombre operacion",
    "tipo transac", "tipo transaccion", "tipo movimiento", "tipo operacion",
    "tipo dep", "tipo deposito",
]
_HORA_HINTS = [
    "hora", "time", "hour", "hh:mm", "hora operacion", "hora mov",
    "hora transaccion", "hora registro", "hora proceso",
]
_BENEFICIARIO_HINTS = [
    "beneficiario", "ordenante", "remitente", "destinatario",
    "nombre beneficiario", "nombre ordenante", "pagador", "receptor",
    "beneficiary", "payee", "payer", "counterpart", "contraparte",
    "originador", "nom destinatario", "nombre destinatario",
    "nombre denominacion depositante", "denominacion depositante",
    "nombre depositante", "depositante",
]
_SUCURSAL_HINTS = [
    "sucursal", "agencia", "canal", "oficina", "branch",
    "punto atencion", "punto de atención", "canal origen",
    "terminal", "cajero", "atm", "ciudad origen", "ciudad",
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
    # Columnas específicas de bancos bolivianos
    "cod bca", "codbca", "cod.bca", "nro cheque", "nrocheque",
    "cod dep", "coddep", "num doc", "num doc depositante",
    "originador ach", "originadorach", "nro planilla", "nro nom planilla",
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
    Los hints al inicio de la lista tienen mayor prioridad.
    Excluye columnas ya asignadas a otros campos.
    """
    exclude = exclude or set()
    norm_hints = [_norm(h) for h in hints]
    candidates = [c for c in columns if c not in exclude]
    norm_cands  = {c: _norm(c) for c in candidates}

    # 1. Coincidencia exacta normalizada — itera hints en orden de prioridad
    for nh in norm_hints:
        for c in candidates:
            if norm_cands[c] == nh:
                return c

    # 2. El hint está contenido en el nombre de columna
    for nh in norm_hints:
        if len(nh) < 3:
            continue
        for c in candidates:
            if nh in norm_cands[c]:
                return c

    # 3. El nombre de columna está contenido en el hint
    for c in candidates:
        nc = norm_cands[c]
        if len(nc) < 3:
            continue
        for nh in norm_hints:
            if nc in nh:
                return c

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
        "fecha":        pick(_FECHA_HINTS),
        "descripcion":  pick(_DESC_HINTS),
        "importe":      pick(_IMPORTE_HINTS),
        "debito":       pick(_DEBITO_HINTS),
        "credito":      pick(_CREDITO_HINTS),
        "saldo":        pick(_SALDO_HINTS),
        "referencia":   pick(_REF_HINTS),
        "cuenta":       pick(_CUENTA_HINTS),
        "hora":         pick(_HORA_HINTS),
        "beneficiario": pick(_BENEFICIARIO_HINTS),
        "sucursal":     pick(_SUCURSAL_HINTS),
    }


# ─── Limpieza de números ──────────────────────────────────────────────────
def _parse_single_number(raw) -> float:
    """
    Convierte un valor textual a float, manejando formatos europeos y anglosajones.
    Devuelve NaN para valores vacíos, guiones, texto no numérico.
    Devuelve 0.0 para ceros explícitos ("0", "0.00", "0,00").
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return float("nan")
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "n/a", "", "-", "—", "#", " "):
        return float("nan")

    # Limpiar símbolos de moneda, espacios y no-breaking spaces
    s = re.sub(r"[$€£Bs\s\xa0]", "", s)
    if not s:
        return float("nan")

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
            if len(after) == 3 and after.isdigit():
                result = float(s.replace(",", ""))
            else:
                result = float(s.replace(",", "."))

        elif n_dots == 1 and n_commas == 0:
            result = float(s)

        elif n_dots == 1 and n_commas == 1:
            if s.rindex(",") > s.rindex("."):
                result = float(s.replace(".", "").replace(",", "."))
            else:
                result = float(s.replace(",", ""))

        elif n_dots > 1 and n_commas <= 1:
            if n_commas == 1 and s.rindex(",") > s.rindex("."):
                result = float(s.replace(".", "").replace(",", "."))
            else:
                result = float(s.replace(".", ""))

        elif n_commas > 1 and n_dots <= 1:
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
            no_dc = result.isna()
            result[no_dc] = raw[no_dc]
            return result
        return raw

    if col_deb or col_cred:
        return _merge_deb_cred(df, col_deb, col_cred)

    return pd.Series(pd.NA, index=df.index, dtype=float)


def _merge_deb_cred(df: pd.DataFrame, col_deb, col_cred) -> pd.Series:
    """
    Calcula Importe = Crédito - Débito (ambos son valores absolutos >= 0 en
    los extractos bancarios).

    - Ingreso: Crédito > 0, Débito = 0  →  importe positivo
    - Egreso:  Débito > 0, Crédito = 0  →  importe negativo
    - Cero:    ambos = 0                 →  importe = 0.0 (fila conservada)
    - Sin dato: ambos NaN               →  importe = NaN (fila conservada si fecha válida)
    """
    nan_s = pd.Series(float("nan"), index=df.index, dtype=float)

    cred_raw = _clean_series(df[col_cred]) if col_cred else nan_s.copy()
    deb_raw  = _clean_series(df[col_deb])  if col_deb  else nan_s.copy()

    # Filas donde al menos una columna tiene un número válido (incluyendo 0.0)
    either_valid = cred_raw.notna() | deb_raw.notna()

    # Importe = crédito - débito (NaN se trata como 0 cuando la otra columna es válida)
    cred_filled = cred_raw.fillna(0.0)
    deb_filled  = deb_raw.fillna(0.0)

    result = nan_s.copy()
    result[either_valid] = cred_filled[either_valid].abs() - deb_filled[either_valid].abs()
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

    mapping keys: fecha, descripcion, debito, credito, importe, saldo,
                  referencia, cuenta, hora, beneficiario, sucursal
    Los valores son nombres de columna del df o None para ignorar.

    Solo se descartan filas sin fecha válida.  Las filas con importe 0 o NaN
    (pero fecha válida) se conservan en el resultado.
    """
    from utils.text_cleaning import extract_time, parse_date

    col_fecha        = mapping.get("fecha")
    col_desc         = mapping.get("descripcion")
    col_debito       = mapping.get("debito")
    col_credito      = mapping.get("credito")
    col_importe      = mapping.get("importe")
    col_saldo        = mapping.get("saldo")
    col_ref          = mapping.get("referencia")
    col_cuenta       = mapping.get("cuenta")
    col_hora         = mapping.get("hora")
    col_beneficiario = mapping.get("beneficiario")
    col_sucursal     = mapping.get("sucursal")

    if not col_fecha:
        raise ValueError("Debes seleccionar la columna de Fecha.")
    if not col_importe and not col_debito and not col_credito:
        raise ValueError(
            "Debes seleccionar al menos una columna de importe "
            "(Importe, Débito o Crédito)."
        )

    out = empty_standard_df()

    # Fecha: parsing robusto multi-formato
    out["fecha"] = pd.to_datetime(
        df[col_fecha].apply(parse_date), errors="coerce"
    )

    out["descripcion"] = df[col_desc].astype(str).str.strip() if col_desc else "Sin descripción"
    out["importe"]     = _resolve_importe(df, col_debito, col_credito, col_importe)
    out["saldo"]       = _clean_series(df[col_saldo])   if col_saldo  else pd.NA
    out["referencia"]  = df[col_ref].astype(str).str.strip() if col_ref else pd.NA
    out["banco"]       = bank_name
    out["cuenta"]      = df[col_cuenta].astype(str).str.strip() if col_cuenta else pd.NA
    out["archivo"]     = filename

    # Campos opcionales de la cabecera estándar
    if col_hora:
        out["hora"] = df[col_hora].astype(str).str.strip()
    else:
        out["hora"] = df[col_fecha].apply(extract_time) if col_fecha else ""

    if col_beneficiario:
        out["beneficiario"] = df[col_beneficiario].astype(str).str.strip()
    if col_sucursal:
        out["sucursal"] = df[col_sucursal].astype(str).str.strip()

    # Solo se descartan filas sin fecha válida; el importe puede ser 0 o NaN
    return out.dropna(subset=["fecha"])


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
