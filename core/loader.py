"""
Carga de archivos Excel y CSV desde objetos subidos por Streamlit.

Devuelve un LoadInfo con el DataFrame crudo y metadatos de diagnóstico:
hoja seleccionada, fila de encabezado detectada, hojas disponibles, etc.
El normalizer decide qué parser usar; el loader sólo lee.
"""

import io
import re
from dataclasses import dataclass, field
import pandas as pd


# ─── Palabras clave para puntuar filas candidatas a encabezado ────────────
_HEADER_KEYWORDS = [
    "fecha", "date", "fec", "valor", "operacion", "operación",
    "concepto", "descripcion", "descripción", "glosa", "detalle", "movimiento",
    "importe", "monto", "cantidad", "amount",
    "cargo", "abono", "debito", "credito", "débito", "crédito",
    "debe", "haber", "ingreso", "egreso", "retiro", "deposito", "depósito",
    "saldo", "balance", "referencia", "ref", "folio", "comprobante",
]


@dataclass
class LoadInfo:
    """Resultado enriquecido de la carga de un archivo."""
    df_raw: pd.DataFrame
    filename: str
    ext: str
    sheets: list = field(default_factory=list)   # vacío para CSV
    selected_sheet: str = ""                      # vacío para CSV
    header_row: int = 0                           # fila de encabezado (0-based)
    raw_bytes: bytes = field(default=b"", repr=False)


# ─── Punto de entrada principal ───────────────────────────────────────────
def load_file(uploaded_file) -> LoadInfo:
    """Lee un archivo subido por Streamlit y devuelve LoadInfo."""
    filename = uploaded_file.name
    ext = filename.rsplit(".", 1)[-1].lower()
    raw_bytes = uploaded_file.read()

    if not raw_bytes:
        raise ValueError(f"El archivo '{filename}' está vacío.")

    if ext in ("xlsx", "xls"):
        return _load_excel_smart(raw_bytes, filename, ext)
    elif ext == "csv":
        return _load_csv_smart(raw_bytes, filename)
    else:
        raise ValueError(f"Formato no soportado: .{ext}. Use Excel (.xlsx, .xls) o CSV.")


def reload_excel(raw_bytes: bytes, filename: str, sheet_name: str, header_row: int) -> pd.DataFrame:
    """Re-lee un Excel con hoja y fila de encabezado específicas (para el mapeo manual)."""
    buf = io.BytesIO(raw_bytes)
    df = pd.read_excel(buf, sheet_name=sheet_name, header=header_row, dtype=str)
    return df.dropna(how="all").reset_index(drop=True)


# ─── Carga Excel ──────────────────────────────────────────────────────────
def _load_excel_smart(raw_bytes: bytes, filename: str, ext: str) -> LoadInfo:
    buf = io.BytesIO(raw_bytes)
    try:
        xl = pd.ExcelFile(buf)
        sheets = [str(s) for s in xl.sheet_names]
    except Exception as e:
        raise ValueError(f"No se pudo abrir '{filename}': {e}")

    selected_sheet = _pick_best_sheet(raw_bytes, sheets)
    header_row = _detect_header_row(raw_bytes, selected_sheet)
    df = reload_excel(raw_bytes, filename, selected_sheet, header_row)

    if df.empty:
        raise ValueError(f"La hoja '{selected_sheet}' de '{filename}' no contiene datos.")

    return LoadInfo(
        df_raw=df,
        filename=filename,
        ext=ext,
        sheets=sheets,
        selected_sheet=selected_sheet,
        header_row=header_row,
        raw_bytes=raw_bytes,
    )


def _pick_best_sheet(raw_bytes: bytes, sheets: list) -> str:
    """Elige la hoja con más celdas no vacías (la principal de datos)."""
    if len(sheets) == 1:
        return sheets[0]
    best, best_score = sheets[0], -1
    for sheet in sheets:
        try:
            buf = io.BytesIO(raw_bytes)
            df = pd.read_excel(buf, sheet_name=sheet, header=None, dtype=str, nrows=60)
            score = int(df.notna().sum().sum())
            if score > best_score:
                best_score = score
                best = sheet
        except Exception:
            continue
    return best


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _header_row_score(row: pd.Series) -> int:
    """Puntúa cuánto se parece una fila a un encabezado de extracto bancario."""
    score = 0
    cells = [str(v).strip() for v in row if pd.notna(v) and str(v).strip() not in ("", "nan")]
    if len(cells) < 2:
        return 0

    for cell in cells:
        norm = _norm_text(cell)
        matched_kw = False
        for kw in _HEADER_KEYWORDS:
            if _norm_text(kw) in norm:
                score += 3
                matched_kw = True
                break
        if not matched_kw:
            # Texto no numérico = probablemente encabezado, no dato
            try:
                float(cell.replace(",", ".").replace(" ", ""))
            except ValueError:
                score += 1  # texto libre → leve punto positivo

    return score


def _detect_header_row(raw_bytes: bytes, sheet_name: str, max_scan: int = 30) -> int:
    """Escanea las primeras filas y devuelve la que más parece un encabezado."""
    try:
        buf = io.BytesIO(raw_bytes)
        df_raw = pd.read_excel(buf, sheet_name=sheet_name, header=None, dtype=str, nrows=max_scan)
    except Exception:
        return 0

    best_row, best_score = 0, -1
    for i, row in df_raw.iterrows():
        score = _header_row_score(row)
        if score > best_score:
            best_score = score
            best_row = int(i)

    return best_row


# ─── Carga CSV ────────────────────────────────────────────────────────────
def _load_csv_smart(raw_bytes: bytes, filename: str) -> LoadInfo:
    encodings = ["utf-8-sig", "latin-1", "utf-8", "cp1252"]
    separators = [";", ",", "\t", "|"]

    for enc in encodings:
        for sep in separators:
            try:
                buf = io.StringIO(raw_bytes.decode(enc))
                df = pd.read_csv(buf, sep=sep, dtype=str)
                if df.shape[1] >= 2 and not df.empty:
                    return LoadInfo(
                        df_raw=df.dropna(how="all").reset_index(drop=True),
                        filename=filename,
                        ext="csv",
                        sheets=[],
                        selected_sheet="",
                        header_row=0,
                        raw_bytes=raw_bytes,
                    )
            except Exception:
                continue

    raise ValueError(
        f"No se pudo leer el CSV '{filename}'. "
        "Comprueba el separador (;, , o tabulador) y la codificación."
    )
