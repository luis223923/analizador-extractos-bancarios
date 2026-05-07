"""
Módulo de saldos por fecha de corte.

Calcula el saldo de cada combinación banco/cuenta/moneda para una fecha
dada, usando el último saldo disponible del extracto o, si no existe,
la suma acumulada de importes (saldo estimado).
"""

import io
import datetime
import pandas as pd
import streamlit as st

from core.schema import MONEDA_PREFIJO, fmt_amount


# ─── Lógica de cálculo ────────────────────────────────────────────────────

def compute_saldos_corte(
    df: pd.DataFrame,
    fecha_corte: datetime.date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Calcula el saldo por banco/cuenta/moneda a la fecha de corte.

    Returns:
        df_saldos   — tabla de saldos consolidados (una fila por grupo)
        df_corte    — movimientos con fecha <= fecha_corte
        df_post     — movimientos con fecha > fecha_corte
    """
    df = df.copy()
    df["fecha"]   = pd.to_datetime(df["fecha"],   errors="coerce")
    df["importe"] = pd.to_numeric(df["importe"],  errors="coerce").fillna(0)
    df["saldo"]   = pd.to_numeric(df["saldo"],    errors="coerce")   # NaN si no hay

    df = df.dropna(subset=["fecha"])

    # Normalizar campos de agrupación
    df["cuenta"] = (
        df["cuenta"].fillna("No identificada")
        .astype(str).str.strip()
        .replace({"nan": "No identificada", "": "No identificada", "None": "No identificada"})
    )
    df["moneda"] = (
        df["moneda"].fillna("Sin definir")
        .astype(str).str.strip()
        .replace({"nan": "Sin definir", "": "Sin definir"})
    )
    df["banco"] = df["banco"].fillna("Sin identificar").astype(str).str.strip()

    mask_corte    = df["fecha"].dt.date <= fecha_corte
    df_corte      = df[mask_corte].sort_values("fecha").reset_index(drop=True)
    df_post       = df[~mask_corte].sort_values("fecha").reset_index(drop=True)

    _EMPTY_SALDOS = pd.DataFrame(columns=[
        "banco", "cuenta", "moneda", "fecha_ult_mov",
        "saldo_corte", "es_estimado", "archivo", "observacion",
    ])

    if df_corte.empty:
        return _EMPTY_SALDOS, df_corte, df_post

    results = []

    for (banco, cuenta, moneda_g), grupo in df_corte.groupby(
        ["banco", "cuenta", "moneda"], dropna=False, sort=True
    ):
        grupo = grupo.sort_values("fecha")
        last_row = grupo.iloc[-1]

        # Intentar obtener saldo real: última fila con saldo válido
        con_saldo = grupo.dropna(subset=["saldo"])
        if not con_saldo.empty:
            saldo_corte  = float(con_saldo.iloc[-1]["saldo"])
            es_estimado  = False
            observacion  = "Saldo extraído del extracto"
        else:
            saldo_corte  = float(grupo["importe"].sum())
            es_estimado  = True
            observacion  = "Saldo estimado por movimientos, validar contra extracto"

        results.append({
            "banco":        str(banco),
            "cuenta":       str(cuenta),
            "moneda":       str(moneda_g),
            "fecha_ult_mov": last_row["fecha"],
            "saldo_corte":  saldo_corte,
            "es_estimado":  es_estimado,
            "archivo":      str(last_row.get("archivo", "")),
            "observacion":  observacion,
        })

    return pd.DataFrame(results), df_corte, df_post


# ─── Renderizado principal ────────────────────────────────────────────────

def render_balances(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    """Renderiza la pestaña completa de saldos por fecha de corte."""
    st.subheader("Saldos por fecha de corte")

    if df.empty:
        st.info("Carga al menos un extracto para consultar saldos.")
        return

    df_clean = df.copy()
    df_clean["fecha"] = pd.to_datetime(df_clean["fecha"], errors="coerce")
    df_clean = df_clean.dropna(subset=["fecha"])

    if df_clean.empty:
        st.warning("Los movimientos cargados no tienen fechas válidas.")
        return

    fecha_min = df_clean["fecha"].min().date()
    fecha_max = df_clean["fecha"].max().date()

    # ── Selector de fecha de corte ────────────────────────────────────────
    col_fc, col_info = st.columns([2, 3])
    with col_fc:
        fecha_corte = st.date_input(
            "Fecha de corte",
            value=fecha_max,
            min_value=fecha_min,
            max_value=fecha_max,
            help="Se calculará el saldo de cada cuenta con el último movimiento "
                 "igual o anterior a esta fecha.",
            key="balances_fecha_corte",
        )
    with col_info:
        st.markdown(
            f"<br><small>Rango de movimientos: "
            f"<b>{fecha_min.strftime('%d/%m/%Y')}</b> — "
            f"<b>{fecha_max.strftime('%d/%m/%Y')}</b></small>",
            unsafe_allow_html=True,
        )

    # ── Calcular saldos ───────────────────────────────────────────────────
    df_saldos, df_corte, df_post = compute_saldos_corte(df_clean, fecha_corte)

    if df_saldos.empty:
        st.warning(
            f"No hay movimientos con fecha igual o anterior a "
            f"{fecha_corte.strftime('%d/%m/%Y')}."
        )
        return

    # ── Filtros ───────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=False):
        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            bancos_opts = ["Todos"] + sorted(df_saldos["banco"].unique().tolist())
            f_banco = st.selectbox("Banco", bancos_opts, key="bal_banco")
        with cf2:
            cuentas_opts = ["Todas"] + sorted(df_saldos["cuenta"].unique().tolist())
            f_cuenta = st.selectbox("Cuenta", cuentas_opts, key="bal_cuenta")
        with cf3:
            monedas_opts = ["Todas"] + sorted(df_saldos["moneda"].unique().tolist())
            f_moneda = st.selectbox("Moneda", monedas_opts, key="bal_moneda")

    df_filtrado = df_saldos.copy()
    if f_banco  != "Todos":  df_filtrado = df_filtrado[df_filtrado["banco"]  == f_banco]
    if f_cuenta != "Todas":  df_filtrado = df_filtrado[df_filtrado["cuenta"] == f_cuenta]
    if f_moneda != "Todas":  df_filtrado = df_filtrado[df_filtrado["moneda"] == f_moneda]

    # ── Métricas superiores ───────────────────────────────────────────────
    n_bancos   = df_filtrado["banco"].nunique()
    n_cuentas  = df_filtrado[["banco", "cuenta"]].drop_duplicates().shape[0]
    n_sin_saldo = int(df_filtrado["es_estimado"].sum())

    def total_moneda(m: str) -> float:
        s = df_filtrado[df_filtrado["moneda"] == m]["saldo_corte"]
        return float(s.sum()) if not s.empty else 0.0

    row1 = st.columns(3)
    row1[0].metric("Bancos",   n_bancos)
    row1[1].metric("Cuentas",  n_cuentas)
    row1[2].metric("Sin saldo identificado", n_sin_saldo,
                   help="Cuentas sin columna Saldo en el extracto; valor calculado por suma de importes.")

    row2 = st.columns(3)
    for col_st, mon in zip(row2, ["BOB", "USD", "EUR"]):
        val = total_moneda(mon)
        col_st.metric(f"Saldo total {mon}", fmt_amount(val, mon))

    st.divider()

    # ── Tabla de saldos ───────────────────────────────────────────────────
    st.markdown(
        f"#### Saldos a la fecha de corte: "
        f"{fecha_corte.strftime('%d/%m/%Y')}"
    )

    display = df_filtrado.copy()
    display["fecha_ult_mov"] = pd.to_datetime(
        display["fecha_ult_mov"], errors="coerce"
    ).dt.strftime("%d/%m/%Y")
    display["Saldo a la fecha de corte"] = display.apply(
        lambda r: fmt_amount(r["saldo_corte"], r["moneda"]), axis=1
    )
    display = display.rename(columns={
        "banco":        "Banco",
        "cuenta":       "Cuenta",
        "moneda":       "Moneda",
        "fecha_ult_mov": "Fecha último movimiento",
        "archivo":      "Archivo origen",
        "observacion":  "Observaciones",
    })
    display = display[[
        "Banco", "Cuenta", "Moneda",
        "Fecha último movimiento",
        "Saldo a la fecha de corte",
        "Archivo origen",
        "Observaciones",
    ]]

    # Colorear filas estimadas en amarillo
    def _style_estimado(row):
        if "estimado" in str(row["Observaciones"]).lower():
            return ["background-color: #fff8e1"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display.style.apply(_style_estimado, axis=1),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Filas en amarillo = saldo estimado (no hay columna Saldo en el extracto)."
    )

    # ── Movimientos posteriores a la fecha de corte ───────────────────────
    st.divider()
    with st.expander(
        f"Movimientos posteriores a {fecha_corte.strftime('%d/%m/%Y')} "
        f"({len(df_post):,} movimientos)",
        expanded=False,
    ):
        if df_post.empty:
            st.info("No hay movimientos posteriores a la fecha de corte.")
        else:
            post_display = df_post[
                ["fecha", "descripcion", "importe", "banco", "cuenta", "moneda"]
            ].copy()
            post_display["fecha"] = pd.to_datetime(
                post_display["fecha"], errors="coerce"
            ).dt.strftime("%d/%m/%Y")
            post_display["importe"] = pd.to_numeric(post_display["importe"], errors="coerce")

            st.markdown(
                f"Existen **{len(df_post):,} movimientos** con fecha posterior "
                f"a la fecha de corte. Suma neta: **{fmt_amount(float(df_post['importe'].sum()), moneda)}**"
            )
            st.dataframe(
                post_display.rename(columns={
                    "fecha": "Fecha", "descripcion": "Descripción",
                    "importe": "Importe", "banco": "Banco",
                    "cuenta": "Cuenta", "moneda": "Moneda",
                }),
                use_container_width=True,
                hide_index=True,
            )

    # ── Exportar Excel de saldos ──────────────────────────────────────────
    st.divider()
    st.markdown("#### Exportar reporte de saldos")
    st.write(
        "El Excel incluye 4 hojas: Saldos a fecha de corte, "
        "Movimientos considerados, Movimientos posteriores y "
        "Cuentas sin saldo identificado."
    )

    df_sin_saldo_exp = df_filtrado[df_filtrado["es_estimado"]].copy()

    excel_bytes = _export_saldos_excel(
        df_saldos=df_filtrado,
        df_movs_corte=df_corte,
        df_movs_post=df_post,
        df_sin_saldo=df_sin_saldo_exp,
        fecha_corte=fecha_corte,
    )

    st.download_button(
        label="Descargar reporte de saldos (Excel)",
        data=excel_bytes,
        file_name=f"saldos_{fecha_corte.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ─── Exportación Excel ────────────────────────────────────────────────────

def _export_saldos_excel(
    df_saldos: pd.DataFrame,
    df_movs_corte: pd.DataFrame,
    df_movs_post: pd.DataFrame,
    df_sin_saldo: pd.DataFrame,
    fecha_corte: datetime.date,
) -> bytes:
    """Genera el Excel con 4 hojas del reporte de saldos."""

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:

        # ── Hoja 1: Saldos a fecha de corte ──────────────────────────────
        hoja1 = df_saldos.copy()
        hoja1["fecha_ult_mov"] = pd.to_datetime(
            hoja1["fecha_ult_mov"], errors="coerce"
        ).dt.strftime("%d/%m/%Y")
        hoja1 = hoja1.rename(columns={
            "banco":        "Banco",
            "cuenta":       "Cuenta",
            "moneda":       "Moneda",
            "fecha_ult_mov": "Fecha último movimiento",
            "saldo_corte":  "Saldo a la fecha de corte",
            "es_estimado":  "Es estimado",
            "archivo":      "Archivo origen",
            "observacion":  "Observaciones",
        })
        hoja1.to_excel(writer, index=False, sheet_name="Saldos a fecha corte")

        # ── Hoja 2: Movimientos considerados ─────────────────────────────
        hoja2 = _prep_movs_for_excel(df_movs_corte)
        hoja2.to_excel(writer, index=False, sheet_name="Movimientos considerados")

        # ── Hoja 3: Movimientos posteriores ──────────────────────────────
        hoja3 = _prep_movs_for_excel(df_movs_post)
        hoja3.to_excel(writer, index=False, sheet_name="Movimientos posteriores")

        # ── Hoja 4: Cuentas sin saldo identificado ────────────────────────
        hoja4 = df_sin_saldo[[
            "banco", "cuenta", "moneda", "saldo_corte", "observacion"
        ]].copy()
        hoja4 = hoja4.rename(columns={
            "banco":       "Banco",
            "cuenta":      "Cuenta",
            "moneda":      "Moneda",
            "saldo_corte": "Saldo estimado",
            "observacion": "Observaciones",
        })
        hoja4.to_excel(writer, index=False, sheet_name="Sin saldo identificado")

    return buf.getvalue()


def _prep_movs_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Fecha", "Descripción", "Importe", "Saldo",
                                     "Banco", "Cuenta", "Moneda", "Archivo"])
    out = df.copy()
    if "fecha" in out.columns:
        out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    cols_rename = {
        "fecha": "Fecha", "descripcion": "Descripción",
        "importe": "Importe", "saldo": "Saldo",
        "banco": "Banco", "cuenta": "Cuenta",
        "moneda": "Moneda", "archivo": "Archivo",
    }
    out = out.rename(columns={k: v for k, v in cols_rename.items() if k in out.columns})
    keep = [v for v in cols_rename.values() if v in out.columns]
    return out[keep]
