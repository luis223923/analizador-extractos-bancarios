"""
Módulo de exportación a Excel con formato de Tesorería.

[MÓDULO PARCIALMENTE IMPLEMENTADO — exportación básica disponible]

Exportación básica: descarga el DataFrame estándar como .xlsx.
Plan de mejora:
- Hoja de resumen con tablas dinámicas
- Formato condicional (importes en rojo/verde)
- Hoja de movimientos clasificados
- Hoja de saldos por cuenta
"""

import io
import pandas as pd
import streamlit as st


def render_exporter(df: pd.DataFrame) -> None:
    st.subheader("Exportar a Excel")

    if df.empty:
        st.warning("Carga al menos un extracto antes de exportar.")
        return

    st.write(f"Se exportarán **{len(df):,} movimientos** al archivo Excel.")

    col1, col2 = st.columns(2)
    with col1:
        include_saldo = st.checkbox("Incluir columna de saldo", value=True)
    with col2:
        include_ref = st.checkbox("Incluir referencia", value=True)

    cols = ["fecha", "descripcion", "importe"]
    if include_saldo:
        cols.append("saldo")
    if include_ref:
        cols.append("referencia")
    cols += ["banco", "cuenta", "archivo"]

    export_df = df[cols].copy()
    export_df["fecha"] = export_df["fecha"].dt.strftime("%d/%m/%Y")

    excel_bytes = _to_excel(export_df)

    st.download_button(
        label="Descargar Excel",
        data=excel_bytes,
        file_name="extractos_consolidados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Movimientos")
    return buf.getvalue()
