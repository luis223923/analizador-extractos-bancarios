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

from core.schema import fmt_amount


# ─── Normalización defensiva ──────────────────────────────────────────────

def _normalize_df(df: pd.DataFrame, moneda_default: str) -> pd.DataFrame:
    """
    Garantiza que el DataFrame tenga las columnas requeridas en minúsculas.
    Acepta columnas con nombre en mayúsculas o minúsculas.
    Añade columnas faltantes con valores neutros en lugar de fallar.
    """
    df = df.copy()

    # Normalizar nombres de columna a minúsculas sin espacios extra
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Columnas requeridas con su valor por defecto si no existen
    defaults = {
        "fecha":       pd.NaT,
        "importe":     float("nan"),
        "saldo":       float("nan"),
        "banco":       "Sin identificar",
        "cuenta":      "No identificada",
        "moneda":      moneda_default,
        "archivo":     "",
        "descripcion": "",
        "referencia":  "",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    return df


# ─── Lógica de cálculo ────────────────────────────────────────────────────

def compute_saldos_corte(
    df: pd.DataFrame,
    fecha_corte: datetime.date,
    moneda_default: str = "Sin definir",
) -> tuple:
    """
    Calcula el saldo por banco/cuenta/moneda a la fecha de corte.

    Returns:
        (df_saldos, df_corte, df_post)
        df_saldos  — una fila por grupo banco/cuenta/moneda
        df_corte   — movimientos con fecha <= fecha_corte
        df_post    — movimientos con fecha > fecha_corte
    """
    _EMPTY = pd.DataFrame(columns=[
        "banco", "cuenta", "moneda", "fecha_ult_mov",
        "saldo_corte", "es_estimado", "archivo", "observacion",
    ])
    _EMPTY_MOV = pd.DataFrame()

    df = _normalize_df(df, moneda_default)

    df["fecha"]   = pd.to_datetime(df["fecha"],  errors="coerce")
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    df["saldo"]   = pd.to_numeric(df["saldo"],   errors="coerce")   # NaN si no hay

    df = df.dropna(subset=["fecha"])
    if df.empty:
        return _EMPTY, _EMPTY_MOV, _EMPTY_MOV

    # Normalizar campos de agrupación
    for col, fallback in [("cuenta", "No identificada"), ("moneda", moneda_default), ("banco", "Sin identificar")]:
        df[col] = (
            df[col].fillna(fallback).astype(str).str.strip()
            .replace({"nan": fallback, "": fallback, "None": fallback, "NaT": fallback})
        )

    mask_corte = df["fecha"].dt.date <= fecha_corte
    df_corte   = df[mask_corte].sort_values("fecha").reset_index(drop=True)
    df_post    = df[~mask_corte].sort_values("fecha").reset_index(drop=True)

    if df_corte.empty:
        return _EMPTY, df_corte, df_post

    results = []
    for (banco, cuenta, moneda_g), grupo in df_corte.groupby(
        ["banco", "cuenta", "moneda"], sort=True
    ):
        grupo = grupo.sort_values("fecha")
        last_row = grupo.iloc[-1]

        # Saldo real: última fila con valor numérico en la columna saldo
        con_saldo = grupo.dropna(subset=["saldo"])
        if not con_saldo.empty:
            saldo_corte = float(con_saldo.iloc[-1]["saldo"])
            es_estimado = False
            observacion = "Saldo extraído del extracto"
        else:
            saldo_corte = float(grupo["importe"].sum())
            es_estimado = True
            observacion = "Saldo estimado por movimientos, validar contra extracto"

        # Acceso seguro a columna "archivo" (sin .get() deprecado)
        archivo_val = str(last_row["archivo"]) if "archivo" in last_row.index else ""

        results.append({
            "banco":        str(banco),
            "cuenta":       str(cuenta),
            "moneda":       str(moneda_g),
            "fecha_ult_mov": last_row["fecha"],
            "saldo_corte":  saldo_corte,
            "es_estimado":  es_estimado,
            "archivo":      archivo_val,
            "observacion":  observacion,
        })

    return pd.DataFrame(results), df_corte, df_post


# ─── Renderizado principal ────────────────────────────────────────────────

def render_balances(df, moneda: str = "Sin definir") -> None:
    """Renderiza la pestaña completa de saldos por fecha de corte."""

    st.subheader("Saldos por fecha de corte")
    st.caption("Versión: saldos corregido con moneda configurable")

    # ── Guardia: df vacío ─────────────────────────────────────────────────
    if df is None or (hasattr(df, "empty") and df.empty):
        st.info(
            "Carga y procesa al menos un extracto para consultar saldos. "
            "Usa el panel lateral para subir archivos."
        )
        return

    # ── Todo el módulo envuelto en try/except para no romper la app ───────
    try:
        _render_balances_body(df, moneda)
    except Exception as exc:
        st.error(
            f"Error al calcular saldos: **{type(exc).__name__}: {exc}**\n\n"
            "Verifica que el archivo cargado tenga columnas de fecha e importe válidas."
        )
        with st.expander("Detalle técnico del error"):
            import traceback
            st.code(traceback.format_exc())


def _render_balances_body(df: pd.DataFrame, moneda: str) -> None:
    """Lógica interna del módulo de saldos (separada para facilitar el manejo de errores)."""

    # Normalizar columnas antes de cualquier operación
    df_work = _normalize_df(df, moneda)
    df_work["fecha"] = pd.to_datetime(df_work["fecha"], errors="coerce")
    df_work = df_work.dropna(subset=["fecha"])

    if df_work.empty:
        st.warning(
            "Los movimientos cargados no tienen fechas válidas. "
            "Verifica que la columna de fecha esté correctamente mapeada."
        )
        return

    fecha_min = df_work["fecha"].min().date()
    fecha_max = df_work["fecha"].max().date()

    # ── Selector de fecha de corte ────────────────────────────────────────
    col_fc, col_info = st.columns([2, 3])
    with col_fc:
        fecha_corte = st.date_input(
            "Fecha de corte",
            value=fecha_max,
            min_value=fecha_min,
            max_value=fecha_max,
            help="El sistema calculará el saldo de cada cuenta con el último "
                 "movimiento igual o anterior a esta fecha.",
            key="balances_fecha_corte",
        )
    with col_info:
        st.markdown(
            f"<br><small>Rango disponible: "
            f"<b>{fecha_min.strftime('%d/%m/%Y')}</b> → "
            f"<b>{fecha_max.strftime('%d/%m/%Y')}</b> "
            f"({len(df_work):,} movimientos)</small>",
            unsafe_allow_html=True,
        )

    # Streamlit puede devolver None o una tupla en edge cases
    if fecha_corte is None:
        st.warning("Selecciona una fecha de corte válida.")
        return
    if isinstance(fecha_corte, (list, tuple)):
        fecha_corte = fecha_corte[-1]

    # ── Calcular saldos ───────────────────────────────────────────────────
    df_saldos, df_corte, df_post = compute_saldos_corte(df_work, fecha_corte, moneda)

    if df_saldos.empty:
        st.warning(
            f"No hay movimientos con fecha igual o anterior a "
            f"{fecha_corte.strftime('%d/%m/%Y')}. "
            "Prueba con una fecha de corte más reciente."
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
    n_bancos    = int(df_filtrado["banco"].nunique())
    n_cuentas   = int(df_filtrado[["banco", "cuenta"]].drop_duplicates().shape[0])
    n_sin_saldo = int(df_filtrado["es_estimado"].sum())

    def total_moneda(m: str) -> float:
        s = df_filtrado[df_filtrado["moneda"] == m]["saldo_corte"]
        return float(s.sum()) if not s.empty else 0.0

    row1 = st.columns(3)
    row1[0].metric("Bancos",   n_bancos)
    row1[1].metric("Cuentas",  n_cuentas)
    row1[2].metric(
        "Sin saldo identificado", n_sin_saldo,
        help="Cuentas cuyo saldo fue calculado por suma de importes "
             "(no tenían columna Saldo en el extracto)."
    )

    row2 = st.columns(3)
    for col_st, mon in zip(row2, ["BOB", "USD", "EUR"]):
        col_st.metric(f"Saldo total {mon}", fmt_amount(total_moneda(mon), mon))

    st.divider()

    # ── Tabla de saldos ───────────────────────────────────────────────────
    st.markdown(
        f"#### Saldos a la fecha de corte: {fecha_corte.strftime('%d/%m/%Y')}"
    )

    display = df_filtrado.copy()
    display["Fecha último movimiento"] = pd.to_datetime(
        display["fecha_ult_mov"], errors="coerce"
    ).dt.strftime("%d/%m/%Y")
    display["Saldo a la fecha de corte"] = display.apply(
        lambda r: fmt_amount(r["saldo_corte"], r["moneda"]), axis=1
    )
    display = display.rename(columns={
        "banco":       "Banco",
        "cuenta":      "Cuenta",
        "moneda":      "Moneda",
        "archivo":     "Archivo origen",
        "observacion": "Observaciones",
    })
    display = display[[
        "Banco", "Cuenta", "Moneda",
        "Fecha último movimiento",
        "Saldo a la fecha de corte",
        "Archivo origen",
        "Observaciones",
    ]]

    def _style_row(row):
        if "estimado" in str(row.get("Observaciones", "")).lower():
            return ["background-color: #fff8e1"] * len(row)
        return [""] * len(row)

    try:
        styled = display.style.apply(_style_row, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.caption(
        "Filas en amarillo = saldo estimado por suma de importes "
        "(el extracto no tiene columna Saldo)."
    )

    # ── Movimientos posteriores ───────────────────────────────────────────
    st.divider()
    label_post = (
        f"Movimientos posteriores al {fecha_corte.strftime('%d/%m/%Y')} "
        f"({len(df_post):,} movimientos)"
    )
    with st.expander(label_post, expanded=False):
        if df_post.empty:
            st.info("No hay movimientos posteriores a la fecha de corte.")
        else:
            cols_post = [c for c in ["fecha", "descripcion", "importe", "banco", "cuenta", "moneda"]
                        if c in df_post.columns]
            post_display = df_post[cols_post].copy()
            if "fecha" in post_display.columns:
                post_display["fecha"] = pd.to_datetime(
                    post_display["fecha"], errors="coerce"
                ).dt.strftime("%d/%m/%Y")
            if "importe" in post_display.columns:
                post_display["importe"] = pd.to_numeric(post_display["importe"], errors="coerce")

            total_post = float(pd.to_numeric(df_post.get("importe", pd.Series(dtype=float)), errors="coerce").sum())
            st.markdown(
                f"**{len(df_post):,} movimientos** posteriores. "
                f"Suma neta: **{fmt_amount(total_post, moneda)}**"
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

    # ── Exportar Excel ────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### Exportar reporte de saldos")
    st.write(
        "Genera un Excel con 4 hojas: **Saldos a fecha corte**, "
        "**Movimientos considerados**, **Movimientos posteriores** y "
        "**Sin saldo identificado**."
    )

    df_sin_saldo_exp = df_filtrado[df_filtrado["es_estimado"]].copy()

    try:
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
    except Exception as exc:
        st.warning(f"No se pudo generar el Excel: {exc}")


# ─── Exportación Excel ────────────────────────────────────────────────────

def _export_saldos_excel(
    df_saldos: pd.DataFrame,
    df_movs_corte: pd.DataFrame,
    df_movs_post: pd.DataFrame,
    df_sin_saldo: pd.DataFrame,
    fecha_corte: datetime.date,
) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:

        # Hoja 1 — Saldos
        hoja1 = df_saldos.copy()
        if "fecha_ult_mov" in hoja1.columns:
            hoja1["fecha_ult_mov"] = pd.to_datetime(
                hoja1["fecha_ult_mov"], errors="coerce"
            ).dt.strftime("%d/%m/%Y")
        hoja1 = hoja1.rename(columns={
            "banco": "Banco", "cuenta": "Cuenta", "moneda": "Moneda",
            "fecha_ult_mov": "Fecha último movimiento",
            "saldo_corte": "Saldo a la fecha de corte",
            "es_estimado": "Es estimado",
            "archivo": "Archivo origen", "observacion": "Observaciones",
        })
        hoja1.to_excel(writer, index=False, sheet_name="Saldos a fecha corte")

        # Hoja 2 — Movimientos considerados
        _prep_movs_for_excel(df_movs_corte).to_excel(
            writer, index=False, sheet_name="Movimientos considerados"
        )

        # Hoja 3 — Movimientos posteriores
        _prep_movs_for_excel(df_movs_post).to_excel(
            writer, index=False, sheet_name="Movimientos posteriores"
        )

        # Hoja 4 — Sin saldo identificado
        if df_sin_saldo.empty:
            hoja4 = pd.DataFrame(columns=["Banco", "Cuenta", "Moneda", "Saldo estimado", "Observaciones"])
        else:
            cols_h4 = [c for c in ["banco", "cuenta", "moneda", "saldo_corte", "observacion"] if c in df_sin_saldo.columns]
            hoja4 = df_sin_saldo[cols_h4].copy().rename(columns={
                "banco": "Banco", "cuenta": "Cuenta", "moneda": "Moneda",
                "saldo_corte": "Saldo estimado", "observacion": "Observaciones",
            })
        hoja4.to_excel(writer, index=False, sheet_name="Sin saldo identificado")

    return buf.getvalue()


def _prep_movs_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Fecha", "Descripción", "Importe", "Saldo",
                                     "Banco", "Cuenta", "Moneda", "Archivo"])
    out = df.copy()
    if "fecha" in out.columns:
        out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    rename = {
        "fecha": "Fecha", "descripcion": "Descripción",
        "importe": "Importe", "saldo": "Saldo",
        "banco": "Banco", "cuenta": "Cuenta",
        "moneda": "Moneda", "archivo": "Archivo",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    keep = [v for v in rename.values() if v in out.columns]
    return out[keep]
