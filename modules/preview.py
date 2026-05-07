"""
Módulo de vista previa de movimientos.

Renderiza el DataFrame estándar con filtros interactivos, métricas
por moneda y tabla formateada con columnas de empresa y cuenta.
"""

import pandas as pd
import streamlit as st

from core.schema import fmt_amount


def render_preview(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    """Muestra la tabla de movimientos con controles de filtrado y métricas."""
    if df.empty:
        st.info("No hay movimientos para mostrar.")
        return

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df_valido = df.dropna(subset=["fecha"])

    if df_valido.empty:
        st.warning("Los movimientos cargados no tienen fechas válidas.")
        st.dataframe(df.head(20), use_container_width=True)
        return

    st.subheader("Vista previa de movimientos")

    # ── Filtros ───────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        empresas_list = (
            ["Todas"] + sorted(df_valido["empresa"].dropna().unique().tolist())
            if "empresa" in df_valido.columns else ["Todas"]
        )
        empresa_sel = st.selectbox("Empresa", empresas_list, key="preview_empresa")

    with col2:
        bancos = ["Todos"] + sorted(df_valido["banco"].dropna().unique().tolist())
        banco_sel = st.selectbox("Banco", bancos, key="preview_banco")

    with col3:
        fecha_min = df_valido["fecha"].min().date()
        fecha_max = df_valido["fecha"].max().date()
        rango = st.date_input(
            "Rango de fechas",
            value=(fecha_min, fecha_max),
            min_value=fecha_min,
            max_value=fecha_max,
            key="preview_fecha",
        )

    with col4:
        tipo = st.selectbox(
            "Tipo de movimiento",
            ["Todos", "Ingresos (+)", "Gastos (-)"],
            key="preview_tipo",
        )

    # ── Aplicar filtros ───────────────────────────────────────────────────
    filtered = df_valido.copy()

    if empresa_sel != "Todas" and "empresa" in filtered.columns:
        filtered = filtered[filtered["empresa"] == empresa_sel]

    if banco_sel != "Todos":
        filtered = filtered[filtered["banco"] == banco_sel]

    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        filtered = filtered[
            (filtered["fecha"].dt.date >= rango[0]) &
            (filtered["fecha"].dt.date <= rango[1])
        ]

    imp_num = pd.to_numeric(filtered["importe"], errors="coerce")
    if tipo == "Ingresos (+)":
        filtered = filtered[imp_num > 0]
    elif tipo == "Gastos (-)":
        filtered = filtered[imp_num < 0]

    # ── Métricas con soporte multi-moneda ─────────────────────────────────
    importes       = pd.to_numeric(filtered["importe"], errors="coerce")
    monedas_pres   = (
        sorted(filtered["moneda"].dropna().unique().tolist())
        if "moneda" in filtered.columns else []
    )

    if len(monedas_pres) == 1:
        mon = monedas_pres[0]
        total_ing = float(importes[importes > 0].sum())
        total_gas = float(importes[importes < 0].sum())
        neto      = total_ing + total_gas
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Movimientos",    f"{len(filtered):,}")
        col_m2.metric("Total ingresos", fmt_amount(total_ing, mon))
        col_m3.metric("Total gastos",   fmt_amount(total_gas, mon))
        col_m4.metric("Saldo neto",     fmt_amount(neto, mon))
    else:
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Movimientos", f"{len(filtered):,}")
        col_m2.metric("Monedas", len(monedas_pres) if monedas_pres else "—")
        col_m3.metric(
            "Bancos",
            int(filtered["banco"].nunique()) if "banco" in filtered.columns else "—"
        )
        if monedas_pres:
            summary = []
            for mon in monedas_pres:
                mask_mon = (
                    filtered["moneda"] == mon
                    if "moneda" in filtered.columns
                    else pd.Series([True] * len(filtered), index=filtered.index)
                )
                imp_mon = pd.to_numeric(
                    filtered.loc[mask_mon, "importe"], errors="coerce"
                )
                summary.append({
                    "Moneda":   mon,
                    "Ingresos": fmt_amount(float(imp_mon[imp_mon > 0].sum()), mon),
                    "Gastos":   fmt_amount(float(imp_mon[imp_mon < 0].sum()), mon),
                    "Neto":     fmt_amount(float(imp_mon.sum()), mon),
                })
            st.dataframe(
                pd.DataFrame(summary),
                use_container_width=True, hide_index=True,
            )

    st.divider()

    # ── Tabla formateada ──────────────────────────────────────────────────
    display_cols = [
        "empresa", "banco", "nombre_corto", "cuenta", "moneda", "tipo_cuenta",
        "fecha", "descripcion", "referencia",
        "debito", "credito", "importe", "saldo",
        "hoja_origen", "fila_origen", "archivo",
    ]
    display_cols = [c for c in display_cols if c in filtered.columns]
    display_df = filtered[display_cols].copy()

    display_df["fecha"]   = display_df["fecha"].dt.strftime("%d/%m/%Y")
    display_df["importe"] = pd.to_numeric(display_df["importe"], errors="coerce")

    rename_map = {
        "empresa":      "Empresa",
        "banco":        "Banco",
        "nombre_corto": "Nombre corto",
        "cuenta":       "Cuenta",
        "moneda":       "Moneda",
        "tipo_cuenta":  "Tipo",
        "fecha":        "Fecha",
        "descripcion":  "Descripción",
        "referencia":   "Referencia",
        "debito":       "Débito",
        "credito":      "Crédito",
        "importe":      "Importe",
        "saldo":        "Saldo",
        "hoja_origen":  "Hoja",
        "fila_origen":  "Fila",
        "archivo":      "Archivo",
    }
    display_df = display_df.rename(columns=rename_map)

    try:
        styled = display_df.style.map(_color_importe, subset=["Importe"])
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
