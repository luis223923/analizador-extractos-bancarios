"""
Módulo de cálculo y evolución de saldos.

[MÓDULO PENDIENTE — estructura preparada para implementación futura]

Plan de implementación:
- Gráfico de evolución del saldo por cuenta
- Tabla de saldos diarios / mensuales
- Comparativa entre cuentas y períodos
"""

import pandas as pd
import streamlit as st


def render_balances(df: pd.DataFrame) -> None:
    st.subheader("Análisis de saldos")
    st.info(
        "Este módulo está en desarrollo. Próximamente podrás ver la evolución "
        "del saldo por cuenta, comparar períodos y detectar tensiones de liquidez."
    )
