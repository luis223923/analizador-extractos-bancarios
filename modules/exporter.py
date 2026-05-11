"""
Módulo de exportación a Excel con formato de Tesorería.
Incluye todas las columnas del esquema extendido incluyendo trazabilidad ZIP:
empresa, banco, cuenta, nombre_corto, moneda, tipo_cuenta,
debito, credito, importe, saldo, carpeta_origen, ruta_zip,
hoja_origen, fila_origen, observaciones.
"""

import io
import pandas as pd
import streamlit as st


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

    # Orden de columnas para la exportación
    cols = [
        "empresa", "banco", "cuenta", "nombre_corto", "moneda", "tipo_cuenta",
        "fecha", "descripcion",
    ]
    if include_ref:
        cols.append("referencia")
    cols += ["debito", "credito", "importe"]
    if include_saldo:
        cols.append("saldo")
    cols += [
        "archivo", "carpeta_origen", "ruta_zip",
        "hoja_origen", "fila_origen", "observaciones",
    ]

    # Solo columnas que existen en el DataFrame
    df_cols_lower = {str(c).strip().lower(): c for c in df.columns}
    cols_exist = [c for c in cols if c in df_cols_lower]

    # Construir export_df con los nombres originales de columna
    export_df = df[[df_cols_lower[c] for c in cols_exist]].copy()
    export_df.columns = cols_exist  # normalizar a minúsculas

    export_df["fecha"] = pd.to_datetime(export_df["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")

    rename_map = {
        "empresa":        "Empresa",
        "banco":          "Banco",
        "cuenta":         "Cuenta",
        "nombre_corto":   "Nombre corto",
        "moneda":         "Moneda",
        "tipo_cuenta":    "Tipo cuenta",
        "fecha":          "Fecha",
        "descripcion":    "Descripción",
        "referencia":     "Referencia",
        "debito":         "Débito",
        "credito":        "Crédito",
        "importe":        "Importe neto",
        "saldo":          "Saldo",
        "archivo":        "Archivo origen",
        "carpeta_origen": "Carpeta origen",
        "ruta_zip":       "Ruta ZIP",
        "hoja_origen":    "Hoja origen",
        "fila_origen":    "Fila origen",
        "observaciones":  "Observaciones",
    }
    export_df = export_df.rename(columns={k: v for k, v in rename_map.items() if k in export_df.columns})

    excel_bytes = _to_excel(export_df)

    st.download_button(
        label="Descargar Excel",
        data=excel_bytes,
        file_name="extractos_consolidados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.caption("Vista previa de las primeras 5 filas:")
    st.dataframe(export_df.head(5), use_container_width=True, hide_index=True)


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Movimientos")
    return buf.getvalue()
