"""
Módulo de exportación a Excel con formato de Tesorería.
Incluye columna Moneda y encabezados dinámicos según la moneda seleccionada.
"""

import io
import pandas as pd
import streamlit as st

from core.schema import MONEDA_PREFIJO


def render_exporter(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
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

    # Columnas base — moneda siempre incluida
    cols = ["fecha", "descripcion", "importe"]
    if include_saldo:
        cols.append("saldo")
    if include_ref:
        cols.append("referencia")
    cols += ["banco", "cuenta", "moneda", "archivo"]

    # Filtrar sólo las columnas que existen (compatibilidad con datos anteriores)
    cols = [c for c in cols if c in df.columns]

    export_df = df[cols].copy()
    export_df["fecha"] = pd.to_datetime(export_df["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")

    # Si la columna moneda no existe en datos anteriores, rellenar con la actual
    if "moneda" not in export_df.columns:
        export_df["moneda"] = moneda

    # Encabezados de columna legibles con moneda dinámica
    if moneda and moneda != "Sin definir":
        header_importe = f"Importe ({moneda})"
        header_saldo   = f"Saldo ({moneda})"
    else:
        header_importe = "Importe"
        header_saldo   = "Saldo"

    rename_map = {
        "fecha":       "Fecha",
        "descripcion": "Descripción",
        "importe":     header_importe,
        "saldo":       header_saldo,
        "referencia":  "Referencia",
        "banco":       "Banco",
        "cuenta":      "Cuenta",
        "moneda":      "Moneda",
        "archivo":     "Archivo",
    }
    export_df = export_df.rename(columns={k: v for k, v in rename_map.items() if k in export_df.columns})

    excel_bytes = _to_excel(export_df)

    st.download_button(
        label="Descargar Excel",
        data=excel_bytes,
        file_name="extractos_consolidados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # Vista previa del Excel
    st.caption("Vista previa de las primeras 5 filas:")
    st.dataframe(export_df.head(5), use_container_width=True, hide_index=True)


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Movimientos")
    return buf.getvalue()
