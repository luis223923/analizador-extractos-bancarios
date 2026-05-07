"""
Módulo de vista previa de movimientos.

Renderiza el DataFrame estándar con formato visual apropiado para Tesorería:
importes coloreados, fechas legibles, filtros interactivos y moneda dinámica.
"""

import pandas as pd
import streamlit as st

from core.schema import MONEDA_PREFIJO


def _fmt_metric(value: float, moneda: str) -> str:
    """Formatea un número con el prefijo de moneda correcto."""
    prefix = MONEDA_PREFIJO.get(moneda, "")
    abs_val = abs(value)
    formatted = f"{abs_val:,.2f}"
    result = f"{prefix} {formatted}".strip() if prefix else formatted
    return f"-{result}" if value < 0 else result


def render_preview(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    """Muestra la tabla de movimientos con controles de filtrado y métricas."""
    if df.empty:
        st.info("No hay movimientos para mostrar.")
        return

    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df_valido = df.dropna(subset=["fecha"])

    if df_valido.empty:
        st.warning("Los movimientos cargados no tienen fechas válidas.")
        st.dataframe(df.head(20), use_container_width=True)
        return

    st.subheader("Vista previa de movimientos")

    # ── Filtros ───────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        bancos = ["Todos"] + sorted(df_valido["banco"].dropna().unique().tolist())
        banco_sel = st.selectbox("Banco", bancos, key="preview_banco")

    with col2:
        fecha_min = df_valido["fecha"].min().date()
        fecha_max = df_valido["fecha"].max().date()
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
            ["Todos", "Ingresos (+)", "Gastos (-)"],
            key="preview_tipo",
        )

    # ── Aplicar filtros ───────────────────────────────────────────────────
    filtered = df_valido.copy()

    if banco_sel != "Todos":
        filtered = filtered[filtered["banco"] == banco_sel]

    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        filtered = filtered[
            (filtered["fecha"].dt.date >= rango[0]) &
            (filtered["fecha"].dt.date <= rango[1])
        ]

    if tipo == "Ingresos (+)":
        filtered = filtered[filtered["importe"] > 0]
    elif tipo == "Gastos (-)":
        filtered = filtered[filtered["importe"] < 0]

    # ── Métricas con moneda dinámica ──────────────────────────────────────
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    importes  = pd.to_numeric(filtered["importe"], errors="coerce")
    total_ing = float(importes[importes > 0].sum())
    total_gas = float(importes[importes < 0].sum())
    neto      = total_ing + total_gas

    col_m1.metric("Movimientos",    f"{len(filtered):,}")
    col_m2.metric("Total ingresos", _fmt_metric(total_ing, moneda))
    col_m3.metric("Total gastos",   _fmt_metric(total_gas, moneda))
    col_m4.metric("Saldo neto",     _fmt_metric(neto, moneda))

    st.divider()

    # ── Encabezados de columna dinámicos según moneda ─────────────────────
    if moneda and moneda != "Sin definir":
        header_importe = f"Importe ({moneda})"
        header_saldo   = f"Saldo ({moneda})"
    else:
        header_importe = "Importe"
        header_saldo   = "Saldo"

    # ── Tabla formateada ──────────────────────────────────────────────────
    display_cols = ["fecha", "descripcion", "importe", "saldo", "referencia", "banco", "moneda", "archivo"]
    # Sólo incluir columnas que existan (compatibilidad con datos cargados antes de la columna moneda)
    display_cols = [c for c in display_cols if c in filtered.columns]
    display_df = filtered[display_cols].copy()
    display_df["fecha"] = display_df["fecha"].dt.strftime("%d/%m/%Y")
    display_df["importe"] = pd.to_numeric(display_df["importe"], errors="coerce")

    rename_map = {
        "fecha":       "Fecha",
        "descripcion": "Descripción",
        "importe":     header_importe,
        "saldo":       header_saldo,
        "referencia":  "Referencia",
        "banco":       "Banco",
        "moneda":      "Moneda",
        "archivo":     "Archivo",
    }
    display_df = display_df.rename(columns=rename_map)

    # Colorear sólo si la columna de importe tiene valores numéricos
    try:
        styled = display_df.style.map(_color_importe, subset=[header_importe])
    except Exception:
        styled = display_df

    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption(f"Mostrando {len(filtered):,} de {len(df_valido):,} movimientos")


def _color_importe(val) -> str:
    try:
        v = float(val)
        if v > 0:
            return "color: #28a745; font-weight: bold"
        if v < 0:
            return "color: #dc3545; font-weight: bold"
    except (TypeError, ValueError):
        pass
    return ""
