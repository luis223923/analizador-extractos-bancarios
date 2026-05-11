"""
Carga de archivos Excel, CSV y ZIP desde objetos subidos por Streamlit.

Devuelve un LoadInfo con el DataFrame crudo y metadatos de diagnóstico:
hoja seleccionada, fila de encabezado detectada, hojas disponibles, etc.
El normalizer decide qué parser usar; el loader sólo lee.

Para archivos ZIP: extrae entradas Excel/CSV con banco y cuenta derivados
del nombre de carpeta y del nombre de archivo respectivamente.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field

import pandas as pd


# ─── Palabras clave para puntuar filas candidatas a encabezado ────────
_HEADER_KEYWORDS = [
    "fecha", "date", "fec", "valor", "operacion", "operación",
    "concepto", "descripcion", "descripción", "glosa", "detalle", "movimiento",
    "importe", "monto", "cantidad", "amount",
    "cargo", "abono", "debito", "credito", "débito", "crédito",
    "debe", "haber", "ingreso", "egreso", "retiro", "deposito", "depósito",
    "saldo", "balance", "referencia", "ref", "folio", "comprobante",
]

# ─── Aliases de bancos (clave en MAYÚsCULAS, valor = nombre canónico) ────
_BANK_ALIASES: dict[str, str] = {
    "BMSCZ":       "Banco Mercantil Santa Cruz",
    "BMSC":        "Banco Mercantil Santa Cruz",
    "MERCANTIL":   "Banco Mercantil Santa Cruz",
    "BNB":         "BNB",
    "BCP":         "BCP",
    "BGA":         "Banco Ganadero",
    "GNA":         "Banco Ganadero",
    "GANADERO":    "Banco Ganadero",
    "BISA":        "Banco Bisa",
    "UNION":       "Banco Unión",
    "UNIÓN":       "Banco Unión",
    "BEC":         "Banco Económico",
    "ECONOMICO":   "Banco Económico",
    "ECONÓMICO":   "Banco Económico",
    "FIE":         "Banco FIE",
    "PRODEM":      "Banco Prodem",
    "BANCOSOL":    "BancoSol",
    "CIDRE":       "CIDRE",
    "CJN":         "CJN",
    "CONTINENTAL": "Continental",
}

# Palabras a ignorar al buscar el número de cuenta en el filename
_IGNORE_IN_FILENAME = re.compile(
    r"\b(BOB|USD|EUR|Bs|Sus|\$us|Bolivianos|Dólares|Dolares|Euros|"
    r"Extracto|Historico|Histórico|Estado|Cuenta|Movimientos?|"
    r"BNB|BCP|BMSCZ?|BISA|UNION|UNIÓN|FIE|PRODEM|CIDRE|CJN|"
    r"CONTINENTAL|GANADERO|BGA|GNA|MERCANTIL|BEC|ECONOMICO|ECONÓMICO|"
    r"BANCOSOL)\b",
    flags=re.IGNORECASE,
)

# Patrón de fecha (para excluirla del número de cuenta)
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T\d\.]*")


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


@dataclass
class ZipFileEntry:
    """Metadatos de un archivo individual extraído de un ZIP."""
    raw_bytes: bytes
    filename: str       # nombre del archivo (sin ruta)
    zip_path: str       # ruta completa dentro del ZIP
    folder: str         # carpeta inmediata padre dentro del ZIP
    bank: str           # nombre de banco normalizado
    cuenta: str         # número de cuenta extraído del filename
    moneda: str         # moneda detectada (BOB / USD / EUR)


# ─── Normalización de nombre de banco ───────────────────────────────────

def normalize_bank_name(folder_name: str) -> str:
    """
    Convierte el nombre de una carpeta al nombre canónico del banco.
    Si no reconoce el alias, devuelve el nombre de carpeta tal como está.
    """
    key = folder_name.strip().upper()
    for alias, canonical in _BANK_ALIASES.items():
        if alias in key:
            return canonical
    return folder_name.strip()


# ─── Extracción de número de cuenta desde el nombre del archivo ─────────

def extract_account_from_filename(filename: str) -> str:
    """
    Intenta detectar el número de cuenta a partir del nombre del archivo.
    Elimina monedas, bancos y fechas antes de buscar patrones numéricos.
    Ejemplos:
      701-504803-2-9.xlsx  →  701-504803-2-9
      100602748 - Bs.xlsx  →  100602748
      BCP 701-504803-2-9 USD.xlsx  →  701-504803-2-9
      ExtractoHistorico - 2026-04-08T190506.868.xls  →  ExtractoHistorico - 2026-04-08T190506.868
    """
    name = filename.rsplit(".", 1)[0]
    clean = _IGNORE_IN_FILENAME.sub("", name)
    clean = _DATE_PATTERN.sub("", clean).strip(" -_")

    # Patrón con dashes: dígitos-dígitos-... (al menos 5 caracteres totales)
    m = re.search(r"\d[\d\-]{3,}\d", clean)
    if m:
        return m.group(0)

    # Solo dígitos (al menos 5)
    m = re.search(r"\d{5,}", clean)
    if m:
        return m.group(0)

    # Fallback: nombre completo sin extensión
    return name.strip()


# ─── Detección de moneda desde texto ────────────────────────────────────

def detect_moneda_from_name(name: str) -> str | None:
    """
    Detecta la moneda a partir del nombre de archivo o carpeta.
    Devuelve "BOB", "USD", "EUR" o None si no detecta.
    """
    n = name.upper()
    if any(k in n for k in ["USD", "DOLAR", "DOLARES", "DÓLARES", "$US", "SUS"]):
        return "USD"
    if any(k in n for k in ["EUR", "EURO", "EUROS"]):
        return "EUR"
    if any(k in n for k in ["BOB", " BS", "-BS", "_BS", "BOLIVIANO", "BOLIVIANOS"]):
        return "BOB"
    return None


# ─── Carga de ZIP ─────────────────────────────────────────────────────────

_SKIP_PARTS = {"__macosx", ".ds_store"}
_VALID_EXTS = {"xlsx", "xls", "csv"}


def load_zip_entries(zip_bytes: bytes) -> list[ZipFileEntry]:
    """
    Extrae todas las entradas válidas (Excel/CSV) de un archivo ZIP.
    - Ignora carpetas, archivos ocultos, temporales y __MACOSX.
    - Deriva banco desde el nombre de la carpeta padre.
    - Deriva cuenta y moneda desde el nombre del archivo.
    """
    entries: list[ZipFileEntry] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size == 0:
                continue

            path = info.filename.replace("\\", "/")
            parts = [p for p in path.split("/") if p]
            basename = parts[-1]

            # Ignorar archivos temporales, ocultos y artefactos de macOS
            if basename.startswith("~$") or basename.startswith("."):
                continue
            if any(p.lower() in _SKIP_PARTS for p in parts):
                continue

            ext = basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
            if ext not in _VALID_EXTS:
                continue

            try:
                raw = zf.read(info.filename)
            except Exception:
                continue
            if not raw:
                continue

            folder = parts[-2] if len(parts) >= 2 else ""
            bank = normalize_bank_name(folder) if folder else "Genérico"
            cuenta = extract_account_from_filename(basename)

            # Moneda: primero en filename, luego en folder, luego BOB por defecto
            moneda = (
                detect_moneda_from_name(basename)
                or detect_moneda_from_name(folder)
                or "BOB"
            )

            entries.append(ZipFileEntry(
                raw_bytes=raw,
                filename=basename,
                zip_path=path,
                folder=folder,
                bank=bank,
                cuenta=cuenta,
                moneda=moneda,
            ))

    return entries


def load_zip_entry_to_loadinfo(entry: ZipFileEntry) -> LoadInfo:
    """Convierte un ZipFileEntry en un LoadInfo listo para normalizar."""
    ext = entry.filename.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xls"):
        return _load_excel_smart(entry.raw_bytes, entry.filename, ext)
    elif ext == "csv":
        return _load_csv_smart(entry.raw_bytes, entry.filename)
    else:
        raise ValueError(f"Formato no soportado: {entry.filename}")


# ─── Punto de entrada para archivos individuales ────────────────────────

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
    """Puntuúa cuánto se parece una fila a un encabezado de extracto bancario."""
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
            try:
                float(cell.replace(",", ".").replace(" ", ""))
            except ValueError:
                score += 1
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


# ─── Carga CSV ──────────────────────────────────────────────────────────

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
