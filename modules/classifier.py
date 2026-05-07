"""
Módulo de clasificación de movimientos por categoría.

[MÓDULO PENDIENTE — estructura preparada para implementación futura]

Plan de implementación:
- Reglas basadas en palabras clave en la descripción
- Categorías configurables por el usuario (Nómina, Proveedor, IVA, etc.)
- Exportación del mapeo de reglas como JSON editable
"""

import pandas as pd
import streamlit as st


def render_classifier(df: pd.DataFrame) -> None:
    st.subheader("Clasificación de movimientos")
    st.info(
        "Este módulo está en desarrollo. Próximamente podrás clasificar "
        "movimientos por categoría (Nóminas, Proveedores, IVA, Alquileres, etc.) "
        "usando reglas configurables por palabras clave."
    )
