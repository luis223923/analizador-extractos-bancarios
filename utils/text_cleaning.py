"""
Utilidades de limpieza y parsing de texto para extractos bancarios.
"""
import re
import math
from datetime import datetime
import pandas as pd


def parse_amount(raw) -> float:
    """
    Convierte un valor textual a float.
    Soporta formatos europeo (1.234,56), anglosajón (1,234.56),
    negativos entre paréntesis y signo al final.
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return float("nan")
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "n/a", "", "-", "—", "#"):
        return float("nan")

    s = re.sub(r"[$€£Bs\s\xa0]", "", s)

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

    n_dots   = s.count(".")
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


_DATE_FORMATS = [
    "%d/%m/%Y", "%d/%m/%y",
    "%Y-%m-%d",
    "%m/%d/%Y", "%m/%d/%y",
    "%d-%m-%Y", "%d-%m-%y",
    "%d.%m.%Y", "%d.%m.%y",
    "%Y%m%d",
]

_DATETIME_FORMATS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
]

# Rango de números de serie Excel que corresponden a fechas (aprox. 1990-2060)
_EXCEL_SERIAL_MIN = 32874   # 1990-01-01
_EXCEL_SERIAL_MAX = 58849   # 2061-01-01
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def parse_date(raw) -> "pd.Timestamp | float":
    """
    Convierte un valor a Timestamp.
    Soporta: formatos string dd/mm/yyyy, yyyy-mm-dd, ISO con T,
             números de serie Excel, objetos datetime/Timestamp.
    Devuelve float('nan') si no puede parsear.
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return float("nan")
    if isinstance(raw, (pd.Timestamp, datetime)):
        return pd.Timestamp(raw)

    # Número de serie Excel (puede llegar como int o float cuando dtype=str no aplica)
    if isinstance(raw, (int, float)):
        n = int(raw)
        if _EXCEL_SERIAL_MIN <= n <= _EXCEL_SERIAL_MAX:
            try:
                return _EXCEL_EPOCH + pd.Timedelta(days=n)
            except Exception:
                pass
        return float("nan")

    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return float("nan")

    # Número de serie Excel representado como string (e.g. "44927")
    if re.match(r"^\d{5,6}$", s):
        try:
            n = int(s)
            if _EXCEL_SERIAL_MIN <= n <= _EXCEL_SERIAL_MAX:
                return _EXCEL_EPOCH + pd.Timedelta(days=n)
        except Exception:
            pass

    for fmt in _DATETIME_FORMATS + _DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue

    try:
        return pd.to_datetime(s, dayfirst=True)
    except Exception:
        return float("nan")


def extract_time(raw) -> str:
    """
    Extrae la parte de hora de un valor de fecha/hora.
    Devuelve string "HH:MM" o "" si no hay hora.
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return ""
    s = str(raw).strip()
    m = re.search(r"\d{1,2}:\d{2}(:\d{2})?", s)
    if m:
        parts = m.group(0).split(":")
        return f"{parts[0].zfill(2)}:{parts[1]}"
    return ""
