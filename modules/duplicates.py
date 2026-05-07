"""
Módulo de detección de movimientos duplicados.

[MÓDULO PENDIENTE — estructura preparada para implementación futura]

Plan de implementación:
- Detección exacta: misma fecha + importe + descripción
- Detección aproximada: misma fecha ±1 día + mismo importe (posibles errores)
- Interfaz para marcar/descartar duplicados manualmente
"""

import pandas as pd
import streamlit as st


def render_duplicates(df: pd.DataFrame) -> None:
    st.subheader("Detección de duplicados")
    st.info(
        "Este módulo está en desarrollo. Próximamente podrás detectar "
        "movimientos duplicados —tanto exactos como aproximados— y marcarlos "
        "para revisión antes de exportar."
    )
