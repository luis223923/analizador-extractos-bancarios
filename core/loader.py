"""
Carga de archivos Excel y CSV desde objetos subidos por Streamlit.

Devuelve siempre un DataFrame crudo (sin transformar) y el nombre del archivo.
La transformación al esquema estándar la hace el normalizer.
"""

import io
import pandas as pd
import streamlit as st


def load_file(uploaded_file) -> tuple[pd.DataFrame, str]:
    """
    Lee un archivo subido desde st.file_uploader.

    Returns:
        (df_raw, filename) — DataFrame crudo y nombre del archivo.
    Raises:
        ValueError si el formato no es soportado o el archivo está vacío.
    """
    filename = uploaded_file.name
    ext = filename.rsplit(".", 1)[-1].lower()

    raw_bytes = uploaded_file.read()
    if not raw_bytes:
        raise ValueError(f"El archivo '{filename}' está vacío.")

    if ext in ("xlsx", "xls"):
        df = _load_excel(raw_bytes, filename)
    elif ext == "csv":
        df = _load_csv(raw_bytes, filename)
    else:
        raise ValueError(f"Formato no soportado: .{ext}. Use Excel (.xlsx, .xls) o CSV.")

    if df.empty:
        raise ValueError(f"El archivo '{filename}' no contiene datos.")

    return df, filename


def _load_excel(raw_bytes: bytes, filename: str) -> pd.DataFrame:
    """Intenta leer Excel; prueba distintas filas de encabezado si falla."""
    buf = io.BytesIO(raw_bytes)
    # Primer intento: cabecera en fila 0
    df = pd.read_excel(buf, header=0, dtype=str)

    # Si la primera fila parece datos y no cabecera, prueba fila 1
    if df.shape[1] < 2 or all(str(c).startswith("Unnamed") for c in df.columns):
        buf.seek(0)
        df = pd.read_excel(buf, header=1, dtype=str)

    return df.dropna(how="all").reset_index(drop=True)


def _load_csv(raw_bytes: bytes, filename: str) -> pd.DataFrame:
    """Intenta leer CSV con distintos separadores y encodings habituales."""
    encodings = ["utf-8-sig", "latin-1", "utf-8"]
    separators = [";", ",", "\t", "|"]

    for enc in encodings:
        for sep in separators:
            try:
                buf = io.StringIO(raw_bytes.decode(enc))
                df = pd.read_csv(buf, sep=sep, dtype=str)
                if df.shape[1] >= 2:
                    return df.dropna(how="all").reset_index(drop=True)
            except Exception:
                continue

    raise ValueError(f"No se pudo leer el CSV '{filename}'. Comprueba el separador y la codificación.")
