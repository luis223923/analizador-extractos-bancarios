"""
Módulo de vista previa de movimientos.

Muestra solo las columnas relevantes para el usuario de Tesorería:
Fecha, Banco, Cuenta, Moneda, Descripción, Débito, Crédito, Importe, Saldo.
Las columnas técnicas (empresa, nombre_corto, hoja, fila, archivo) se mantienen
internamente pero no se muestran en la tabla principal.
"""

import pandas as pd
import streamlit as st

from core.schema import fmt_amount


def render_preview(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    """Muestra la tabla de movimientos con filtros y montos formateados."""
    if df.empty:
        st.info("No hay movimientos para mostrar.")
        return

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df_valido   = df.dropna(subset=["fecha"])

    if df_valido.empty:
        st.warning("Los movimientos cargados no tienen fechas válidas.")
        st.dataframe(df.head(20), use_container_width=True)
        return

    st.subheader("Vista previa de movimientos")

    # ── Filtros ───────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        bancos    = ["Todos"] + sorted(df_valido["banco"].dropna().unique().tolist())
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

    imp_num = pd.to_numeric(filtered["importe"], errors="coerce")
    if tipo == "Ingresos (+)":
        filtered = filtered[imp_num > 0]
    elif tipo == "Gastos (-)":
        filtered = filtered[imp_num < 0]

    # ── Métricas ──────────────────────────────────────────────────────────
    importes     = pd.to_numeric(filtered["importe"], errors="coerce")
    monedas_pres = (
        sorted(filtered["moneda"].dropna().unique().tolist())
        if "moneda" in filtered.columns else []
    )

    if len(monedas_pres) == 1:
        mon       = monedas_pres[0]
        total_ing = float(importes[importes > 0].sum())
        total_gas = float(importes[importes < 0].sum())
        neto      = total_ing + total_gas
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Movimientos",    f"{len(filtered):,}")
        m2.metric("Total ingresos", fmt_amount(total_ing, mon))
        m3.metric("Total gastos",   fmt_amount(total_gas, mon))
        m4.metric("Saldo neto",     fmt_amount(neto, mon))
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Movimientos", f"{len(filtered):,}")
        m2.metric("Monedas",     len(monedas_pres) if monedas_pres else "—")
        m3.metric("Bancos",      int(filtered["banco"].nunique()) if "banco" in filtered.columns else "—")

        if monedas_pres:
            summary = []
            for mon in monedas_pres:
                mask = filtered["moneda"] == mon if "moneda" in filtered.columns else pd.Series(True, index=filtered.index)
                imp  = pd.to_numeric(filtered.loc[mask, "importe"], errors="coerce")
                summary.append({
                    "Moneda":   mon,
                    "Ingresos": fmt_amount(float(imp[imp > 0].sum()), mon),
                    "Gastos":   fmt_amount(float(imp[imp < 0].sum()), mon),
                    "Neto":     fmt_amount(float(imp.sum()), mon),
                })
            st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

    st.divider()

    # ── Tabla principal (solo columnas relevantes para Tesorería) ─────────
    display_df = filtered.copy()

    # Columna de tipo de movimiento derivada de importe
    imp_col = pd.to_numeric(display_df["importe"], errors="coerce")
    display_df["tipo_mov"] = imp_col.apply(
        lambda x: "Ingreso" if x > 0 else ("Gasto" if x < 0 else "Neutro")
    )

    # Formatear montos con moneda por fila
    def _fmt_row(row, col):
        try:
            v   = float(row[col])
            mon = str(row.get("moneda", "Sin definir"))
            if col in ("debito", "credito") and v == 0.0:
                return ""          # no mostrar ceros en débito/crédito
            return fmt_amount(v, mon)
        except (TypeError, ValueError):
            return ""

    for col_monto in ["debito", "credito", "importe", "saldo"]:
        if col_monto in display_df.columns:
            display_df[col_monto] = display_df.apply(
                lambda r, c=col_monto: _fmt_row(r, c), axis=1
            )

    # Fecha legible
    display_df["fecha"] = display_df["fecha"].dt.strftime("%d/%m/%Y")

    # Seleccionar solo columnas visibles (en orden deseado)
    visible = [
        "fecha", "banco", "cuenta", "moneda",
        "descripcion", "debito", "credito", "importe", "saldo",
        "tipo_mov", "observaciones",
    ]
    visible = [c for c in visible if c in display_df.columns]
    display_df = display_df[visible].rename(columns={
        "fecha":        "Fecha",
        "banco":        "Banco",
        "cuenta":       "Cuenta",
        "moneda":       "Moneda",
        "descripcion":  "Descripción",
        "debito":       "Débito",
        "credito":      "Crédito",
        "importe":      "Importe",
        "saldo":        "Saldo",
        "tipo_mov":     "Tipo",
        "observaciones":"Observaciones",
    })

    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"Mostrando {len(filtered):,} de {len(df_valido):,} movimientos")
