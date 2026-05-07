"""
Módulo de vista previa de movimientos.

Renderiza el DataFrame estándar con formato visual apropiado para Tesorería:
importes coloreados, fechas legibles, filtros interactivos.
"""

import pandas as pd
import streamlit as st


def render_preview(df: pd.DataFrame) -> None:
    """Muestra la tabla de movimientos con controles de filtrado."""
    if df.empty:
        st.info("No hay movimientos para mostrar.")
        return

    st.subheader("Vista previa de movimientos")

    # --- Filtros rápidos en columnas ---
    col1, col2, col3 = st.columns(3)

    with col1:
        bancos = ["Todos"] + sorted(df["banco"].dropna().unique().tolist())
        banco_sel = st.selectbox("Banco", bancos, key="preview_banco")

    with col2:
        fecha_min = df["fecha"].min().date()
        fecha_max = df["fecha"].max().date()
        rango = st.date_input(
            "Rango de fechas",
            value=(fecha_min, fecha_max),
            min_value=fecha_min,
            max_value=fecha_max,
            key="preview_fecha",
        )

    with col3:
        tipo = st.selectbox(
            "Tipo de movimiento",
            ["Todos", "Ingresos", "Gastos"],
            key="preview_tipo",
        )

    # --- Aplicar filtros ---
    filtered = df.copy()

    if banco_sel != "Todos":
        filtered = filtered[filtered["banco"] == banco_sel]

    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        filtered = filtered[
            (filtered["fecha"].dt.date >= rango[0]) &
            (filtered["fecha"].dt.date <= rango[1])
        ]

    if tipo == "Ingresos":
        filtered = filtered[filtered["importe"] > 0]
    elif tipo == "Gastos":
        filtered = filtered[filtered["importe"] < 0]

    # --- Métricas de resumen ---
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    total_ingresos = filtered[filtered["importe"] > 0]["importe"].sum()
    total_gastos = filtered[filtered["importe"] < 0]["importe"].sum()
    neto = total_ingresos + total_gastos

    col_m1.metric("Movimientos", f"{len(filtered):,}")
    col_m2.metric("Total ingresos", f"{total_ingresos:,.2f} €")
    col_m3.metric("Total gastos", f"{total_gastos:,.2f} €")
    col_m4.metric("Saldo neto", f"{neto:,.2f} €", delta_color="normal")

    st.divider()

    # --- Tabla formateada ---
    display_df = filtered[["fecha", "descripcion", "importe", "saldo", "referencia", "banco", "archivo"]].copy()
    display_df["fecha"] = display_df["fecha"].dt.strftime("%d/%m/%Y")
    display_df = display_df.rename(columns={
        "fecha": "Fecha",
        "descripcion": "Descripción",
        "importe": "Importe (€)",
        "saldo": "Saldo (€)",
        "referencia": "Referencia",
        "banco": "Banco",
        "archivo": "Archivo",
    })

    st.dataframe(
        display_df.style.map(
            lambda v: "color: #28a745" if isinstance(v, float) and v > 0
            else ("color: #dc3545" if isinstance(v, float) and v < 0 else ""),
            subset=["Importe (€)"],
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Mostrando {len(filtered):,} de {len(df):,} movimientos")
