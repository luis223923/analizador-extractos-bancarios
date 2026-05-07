# Analizador de Extractos Bancarios para Tesorería

Herramienta web para consolidar extractos bancarios de distintos bancos, analizar movimientos y generar informes de Tesorería — sin instalar nada en tu ordenador.

---

## ¿Para qué sirve?

Si en tu empresa manejas extractos de varios bancos (en Excel o CSV) y necesitas:

- Ver todos los movimientos en un solo lugar
- Filtrar por fecha, banco o tipo de operación
- Detectar ingresos y gastos de un vistazo
- Exportar un consolidado a Excel

Esta herramienta lo hace por ti, desde el navegador.

---

## Cómo ejecutarla (sin instalar nada)

### Opción 1 — Streamlit Community Cloud (recomendada)

1. Ve a [share.streamlit.io](https://share.streamlit.io)
2. Conéctala con este repositorio de GitHub
3. Indica que el archivo principal es `app.py`
4. Pulsa **Deploy** — en segundos tendrás tu URL pública

### Opción 2 — Google Colab

Ejecuta esta celda en [Google Colab](https://colab.research.google.com):

```python
!pip install streamlit pandas openpyxl xlrd pyngrok -q
!git clone https://github.com/TU_USUARIO/analizador-extractos-bancarios
%cd analizador-extractos-bancarios

from pyngrok import ngrok
import subprocess, time

proc = subprocess.Popen(["streamlit", "run", "app.py", "--server.port=8501"])
time.sleep(3)
print(ngrok.connect(8501))
```

### Opción 3 — Si tienes Python en tu equipo

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Cómo usar la aplicación

1. **Sube tus archivos** — Abre el panel lateral y selecciona uno o varios archivos Excel o CSV. Puedes subir extractos de distintos bancos a la vez.

2. **Pulsa "Procesar archivos"** — El sistema detecta automáticamente el formato de cada banco.

3. **Explora las pestañas:**
   - **Vista previa** — Tabla de movimientos con filtros por fecha, banco e importe
   - **Clasificación** — *(próximamente)* Categorizar movimientos por tipo
   - **Saldos** — *(próximamente)* Evolución del saldo por cuenta
   - **Duplicados** — *(próximamente)* Detectar apuntes repetidos
   - **Exportar** — Descarga el consolidado como Excel

---

## Qué formatos acepta

| Formato | Extensión | Notas |
|---------|-----------|-------|
| Excel moderno | `.xlsx` | Recomendado |
| Excel antiguo | `.xls` | Compatible |
| CSV | `.csv` | Separador automático (`;`, `,`, tabulador) |

El sistema reconoce automáticamente las columnas de fecha, descripción e importe aunque tengan nombres diferentes.

---

## Bancos soportados

| Banco | Detección | Estado |
|-------|-----------|--------|
| BBVA | Columnas específicas del formato oficial | Incluido |
| Cualquier banco | Auto-detección por nombre de columna | Incluido |

Para añadir soporte explícito a un banco nuevo, consulta la sección de desarrollo más abajo.

---

## Estructura del proyecto (para desarrolladores)

```
analizador-extractos-bancarios/
│
├── app.py                   ← Aplicación principal (Streamlit)
├── requirements.txt         ← Dependencias Python
│
├── core/                    ← Motor central del sistema
│   ├── schema.py            ← Esquema estándar de columnas
│   ├── loader.py            ← Lectura de archivos Excel y CSV
│   └── normalizer.py        ← Selección automática del parser correcto
│
├── banks/                   ← Un archivo por banco
│   ├── base.py              ← Clase base que deben implementar todos los parsers
│   ├── generic.py           ← Parser genérico con auto-detección
│   └── bbva.py              ← Parser específico para BBVA
│
├── modules/                 ← Módulos funcionales independientes
│   ├── preview.py           ← Vista previa con filtros
│   ├── classifier.py        ← Clasificación por categorías (en desarrollo)
│   ├── balances.py          ← Análisis de saldos (en desarrollo)
│   ├── duplicates.py        ← Detección de duplicados (en desarrollo)
│   └── exporter.py          ← Exportación a Excel
│
└── data/samples/            ← Archivos de ejemplo para pruebas
```

### Añadir soporte para un nuevo banco

1. Crea el archivo `banks/nombre_banco.py`
2. Implementa una clase que herede de `BankParser`:

```python
from banks.base import BankParser
from core.schema import empty_standard_df
import pandas as pd

class MiBancoParser(BankParser):
    bank_name = "Mi Banco"
    priority = 70  # mayor = se prueba antes

    def can_parse(self, df: pd.DataFrame, filename: str = "") -> bool:
        # Devuelve True si reconoces el formato de este DataFrame
        cols = {c.strip().lower() for c in df.columns}
        return {"fecha valor", "concepto", "importe"}.issubset(cols)

    def parse(self, df: pd.DataFrame, filename: str = "") -> pd.DataFrame:
        out = empty_standard_df()
        out["fecha"] = pd.to_datetime(df["Fecha Valor"], dayfirst=True, errors="coerce")
        out["descripcion"] = df["Concepto"].astype(str)
        out["importe"] = pd.to_numeric(df["Importe"], errors="coerce")
        out["saldo"] = pd.NA
        out["referencia"] = pd.NA
        out["banco"] = self.bank_name
        out["cuenta"] = pd.NA
        out["archivo"] = filename
        return out.dropna(subset=["fecha", "importe"])
```

3. Importa la clase en `core/normalizer.py`:

```python
from banks.mi_banco import MiBancoParser

_REGISTERED_PARSERS = [
    BBVAParser(),
    MiBancoParser(),   # ← añadir aquí
    GenericParser(),
]
```

Eso es todo. No hay que tocar nada más.

---

## Tecnologías utilizadas

- [Streamlit](https://streamlit.io) — interfaz web interactiva
- [Pandas](https://pandas.pydata.org) — procesamiento de datos
- [OpenPyXL](https://openpyxl.readthedocs.io) — lectura y escritura de Excel

---

## Licencia

Uso interno. Proyecto de código abierto para adaptación libre.
