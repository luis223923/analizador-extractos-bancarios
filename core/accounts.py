"""
Módulo de acceso al maestro de cuentas bancarias.
Lee config/cuentas_bancarias.json para pre-rellenar los formularios
de metadatos en la carga de extractos.
"""

import json
from pathlib import Path

_ACCOUNTS_FILE = Path(__file__).parent.parent / "config" / "cuentas_bancarias.json"


def load_accounts() -> list[dict]:
    """
    Carga el maestro de cuentas desde config/cuentas_bancarias.json.
    Devuelve lista vacía si el archivo no existe o no puede leerse.
    """
    if not _ACCOUNTS_FILE.exists():
        return []
    try:
        with open(_ACCOUNTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
