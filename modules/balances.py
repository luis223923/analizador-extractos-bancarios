"""
Módulo de disponibilidad bancaria por fecha de corte.

Calcula el saldo de cada combinación empresa/banco/cuenta/moneda
para una fecha dada, usando el último saldo disponible del extracto
o, si no existe, la suma acumulada de importes (saldo estimado).
"""

import io
import datetime
import traceback
import pandas as pd
import streamlit as st

from core.schema import fmt_amount


# ─── Normalización defensiva ──────────────────────────────────────────────────

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Garantiza que el DataFrame tenga todas las columnas requeridas en minúsculas.
    Añade columnas faltantes con valores neutros en lugar de fallar.
    """
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    defaults = {
        "fecha":        pd.NaT,
        "importe":      float("nan"),
        "saldo":        float("nan"),
        "debito":       float("nan"),
        "credito":      float("nan"),
        "banco":        "Sin identificar",
        "cuenta":       "No identificada",
        "nombre_corto": "",
        "empresa":      "Sin identificar",
        "moneda":       "Sin definir",
        "tipo_cuenta":  "Sin definir",
        "archivo":      "",
        "hoja_origen":  "",
        "fila_origen":  "",
        "descripcion":  "",
        "referencia":   "",
        "observaciones":"",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    # nombre_corto vacío → usar cuenta
    mask_nc = df["nombre_corto"].isna() | (df["nombre_corto"].astype(str).str.strip() == "")
    df.loc[mask_nc, "nombre_corto"] = df.loc[mask_nc, "cuenta"]

    return df


# ─── Lógica de cálculo ────────────────────────────────────────────────────────

def compute_saldos_corte(
    df: pd.DataFrame,
    fecha_corte: datetime.date,
) -> tuple:
    """
    Calcula el saldo por empresa/banco/cuenta/moneda a la fecha de corte.

    Returns:
        (df_saldos, df_corte, df_post)
        df_saldos  — una fila por grupo con saldo a la fecha de corte
        df_corte   — movimientos con fecha <= fecha_corte
        df_post    — movimientos con fecha > fecha_corte
    """
    _EMPTY_SALDOS = pd.DataFrame(columns=[
        "empresa", "banco", "cuenta", "nombre_corto", "moneda",
        "fecha_ult_mov", "saldo_corte", "es_estimado", "archivo", "observacion",
    ])
    _EMPTY_MOV = pd.DataFrame()

    df = _normalize_df(df)
    df["fecha"]   = pd.to_datetime(df["fecha"],  errors="coerce")
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    df["saldo"]   = pd.to_numeric(df["saldo"],   errors="coerce")
    df = df.dropna(subset=["fecha"])

    if df.empty:
        return _EMPTY_SALDOS, _EMPTY_MOV, _EMPTY_MOV

    # Normalizar campos de agrupación
    _FALLBACKS = {
        "empresa":      "Sin identificar",
        "banco":        "Sin identificar",
        "cuenta":       "No identificada",
        "nombre_corto": "",
        "moneda":       "Sin definir",
    }
    for col, fallback in _FALLBACKS.items():
        df[col] = (
            df[col].fillna(fallback).astype(str).str.strip()
            .replace({"nan": fallback, "": fallback, "None": fallback, "NaT": fallback})
        )
    # nombre_corto vacío → cuenta
    mask_nc = df["nombre_corto"] == _FALLBACKS["nombre_corto"]
    df.loc[mask_nc, "nombre_corto"] = df.loc[mask_nc, "cuenta"]

    mask_corte = df["fecha"].dt.date <= fecha_corte
    df_corte   = df[mask_corte].sort_values("fecha").reset_index(drop=True)
    df_post    = df[~mask_corte].sort_values("fecha").reset_index(drop=True)

    if df_corte.empty:
        return _EMPTY_SALDOS, df_corte, df_post

    results = []
    for (empresa, banco, cuenta, nombre_corto, moneda_g), grupo in df_corte.groupby(
        ["empresa", "banco", "cuenta", "nombre_corto", "moneda"], sort=True
    ):
        grupo = grupo.sort_values("fecha")
        last_row = grupo.iloc[-1]

        con_saldo = grupo.dropna(subset=["saldo"])
        if not con_saldo.empty:
            saldo_corte = float(con_saldo.iloc[-1]["saldo"])
            es_estimado = False
            observacion = "Saldo extraído del extracto"
        else:
            saldo_corte = float(grupo["importe"].sum())
            es_estimado = True
            observacion = "Saldo estimado por movimientos, validar contra extracto"

        archivo_val = str(last_row["archivo"]) if "archivo" in last_row.index else ""

        results.append({
            "empresa":      str(empresa),
            "banco":        str(banco),
            "cuenta":       str(cuenta),
            "nombre_corto": str(nombre_corto),
            "moneda":       str(moneda_g),
            "fecha_ult_mov": last_row["fecha"],
            "saldo_corte":  saldo_corte,
            "es_estimado":  es_estimado,
            "archivo":      archivo_val,
            "observacion":  observacion,
        })

    return pd.DataFrame(results), df_corte, df_post


# ─── Renderizado principal ────────────────────────────────────────────────────

def render_balances(df, moneda: str = "Sin definir") -> None:
    """Renderiza la pestaña completa de disponibilidad bancaria."""

    st.subheader("Disponibilidad bancaria por fecha de corte")
    st.caption("Versión: saldos por banco, cuenta y moneda")

    if df is None or (hasattr(df, "empty") and df.empty):
        st.info(
            "Carga y procesa al menos un extracto para consultar saldos. "
            "Usa el panel lateral para subir archivos."
        )
        return

    try:
        _render_balances_body(df)
    except Exception as exc:
        st.error(
            f"Error al calcular saldos: **{type(exc).__name__}: {exc}**\n\n"
            "Verifica que el archivo cargado tenga columnas de fecha e importe válidas."
        )
        with st.expander("Detalle técnico del error"):
            st.code(traceback.format_exc())


def _render_balances_body(df: pd.DataFrame) -> None:
    """Lógica interna del módulo de disponibilidad."""

    df_work = _normalize_df(df)
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
            help="El sistema tomará el último saldo igual o anterior a esta fecha.",
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

    if fecha_corte is None:
        st.warning("Selecciona una fecha de corte válida.")
        return
    if isinstance(fecha_corte, (list, tuple)):
        fecha_corte = fecha_corte[-1]

    # ── Calcular saldos ───────────────────────────────────────────────────
    df_saldos, df_corte, df_post = compute_saldos_corte(df_work, fecha_corte)

    if df_saldos.empty:
        st.warning(
            f"No hay movimientos con fecha igual o anterior a "
            f"{fecha_corte.strftime('%d/%m/%Y')}. "
            "Prueba con una fecha de corte más reciente."
        )
        return

    # ── Filtros ───────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=False):
        cf1, cf2, cf3, cf4 = st.columns(4)
        with cf1:
            empresas_opts = ["Todas"] + sorted(df_saldos["empresa"].unique().tolist())
            f_empresa = st.selectbox("Empresa", empresas_opts, key="bal_empresa")
        with cf2:
            bancos_opts = ["Todos"] + sorted(df_saldos["banco"].unique().tolist())
            f_banco = st.selectbox("Banco", bancos_opts, key="bal_banco")
        with cf3:
            cuentas_opts = ["Todas"] + sorted(df_saldos["cuenta"].unique().tolist())
            f_cuenta = st.selectbox("Cuenta", cuentas_opts, key="bal_cuenta")
        with cf4:
            monedas_opts = ["Todas"] + sorted(df_saldos["moneda"].unique().tolist())
            f_moneda = st.selectbox("Moneda", monedas_opts, key="bal_moneda")

    df_filtrado = df_saldos.copy()
    if f_empresa != "Todas":  df_filtrado = df_filtrado[df_filtrado["empresa"] == f_empresa]
    if f_banco   != "Todos":  df_filtrado = df_filtrado[df_filtrado["banco"]   == f_banco]
    if f_cuenta  != "Todas":  df_filtrado = df_filtrado[df_filtrado["cuenta"]  == f_cuenta]
    if f_moneda  != "Todas":  df_filtrado = df_filtrado[df_filtrado["moneda"]  == f_moneda]

    # ── Métricas superiores ───────────────────────────────────────────────
    n_bancos    = int(df_filtrado["banco"].nunique())
    n_cuentas   = int(df_filtrado[["banco", "cuenta"]].drop_duplicates().shape[0])
    n_sin_saldo = int(df_filtrado["es_estimado"].sum())

    def total_mon(m: str) -> float:
        s = df_filtrado[df_filtrado["moneda"] == m]["saldo_corte"]
        return float(s.sum()) if not s.empty else 0.0

    row1 = st.columns(3)
    row1[0].metric("Bancos",                  n_bancos)
    row1[1].metric("Cuentas",                 n_cuentas)
    row1[2].metric("Sin saldo identificado",  n_sin_saldo,
                   help="Cuentas cuyo saldo fue estimado por suma de movimientos.")

    row2 = st.columns(3)
    for col_st, mon in zip(row2, ["BOB", "USD", "EUR"]):
        col_st.metric(f"Saldo total {mon}", fmt_amount(total_mon(mon), mon))

    st.divider()

    # ── Tabla: Saldos a la fecha de corte ────────────────────────────────
    st.markdown(f"#### Saldos a la fecha de corte: {fecha_corte.strftime('%d/%m/%Y')}")

    display = df_filtrado.copy()
    display["Fecha último mov."] = pd.to_datetime(
        display["fecha_ult_mov"], errors="coerce"
    ).dt.strftime("%d/%m/%Y")
    display["Saldo a la fecha"] = display.apply(
        lambda r: fmt_amount(r["saldo_corte"], r["moneda"]), axis=1
    )
    display = display.rename(columns={
        "empresa":      "Empresa",
        "banco":        "Banco",
        "cuenta":       "Cuenta",
        "nombre_corto": "Nombre corto",
        "moneda":       "Moneda",
        "archivo":      "Archivo origen",
        "observacion":  "Observaciones",
    })
    cols_tabla = [c for c in [
        "Empresa", "Banco", "Cuenta", "Nombre corto", "Moneda",
        "Fecha último mov.", "Saldo a la fecha", "Archivo origen", "Observaciones",
    ] if c in display.columns]

    def _style_estimado(row):
        if "estimado" in str(row.get("Observaciones", "")).lower():
            return ["background-color: #fff8e1"] * len(row)
        return [""] * len(row)

    try:
        styled = display[cols_tabla].style.apply(_style_estimado, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(display[cols_tabla], use_container_width=True, hide_index=True)

    st.caption(
        "Filas en amarillo = saldo estimado por suma de movimientos "
        "(el extracto no tiene columna Saldo)."
    )

    st.divider()

    # ── Vista matriz por cuenta ────────────────────────────────────────────
    st.markdown("#### Vista matriz por cuenta")
    st.caption("Saldo disponible por empresa/banco/cuenta y moneda.")

    try:
        pivot = df_filtrado.pivot_table(
            index=["empresa", "banco", "cuenta", "nombre_corto"],
            columns="moneda",
            values="saldo_corte",
            aggfunc="sum",
        ).reset_index()
        pivot.columns.name = None

        for mon in ["BOB", "USD", "EUR"]:
            if mon not in pivot.columns:
                pivot[mon] = float("nan")

        pivot = pivot.rename(columns={
            "empresa":      "Empresa",
            "banco":        "Banco",
            "cuenta":       "Cuenta",
            "nombre_corto": "Nombre corto",
            "BOB": "Saldo BOB (Bs)",
            "USD": "Saldo USD",
            "EUR": "Saldo EUR",
        })

        num_cols = {
            c: st.column_config.NumberColumn(c, format="%.2f")
            for c in ["Saldo BOB (Bs)", "Saldo USD", "Saldo EUR"]
            if c in pivot.columns
        }
        st.dataframe(pivot, use_container_width=True, hide_index=True,
                     column_config=num_cols)
    except Exception as exc:
        st.warning(f"No se pudo generar la vista matriz: {exc}")

    st.divider()

    # ── Movimientos posteriores agrupados ─────────────────────────────────
    label_post = (
        f"Movimientos posteriores al {fecha_corte.strftime('%d/%m/%Y')} "
        f"({len(df_post):,} movimientos)"
    )
    with st.expander(label_post, expanded=False):
        if df_post.empty:
            st.info("No hay movimientos posteriores a la fecha de corte.")
        else:
            grupos_post = df_post.groupby(["empresa", "banco", "cuenta", "moneda"])
            for (emp, ban, cta, mon), grp in grupos_post:
                imp_num = pd.to_numeric(grp["importe"], errors="coerce")
                neto = float(imp_num.sum())
                st.markdown(
                    f"**{emp}** | {ban} | {cta} | {mon} — "
                    f"{len(grp):,} mov. | Neto: **{fmt_amount(neto, mon)}**"
                )
                show_cols = [c for c in [
                    "fecha", "descripcion", "referencia", "debito", "credito", "importe",
                ] if c in grp.columns]
                g = grp[show_cols].copy()
                if "fecha" in g.columns:
                    g["fecha"] = pd.to_datetime(g["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
                st.dataframe(
                    g.rename(columns={
                        "fecha": "Fecha", "descripcion": "Descripción",
                        "referencia": "Ref.", "debito": "Débito",
                        "credito": "Crédito", "importe": "Importe",
                    }),
                    use_container_width=True, hide_index=True,
                )
                st.markdown("---")

    # ── Exportar Excel ────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### Exportar reporte de disponibilidad")
    st.write(
        "Genera un Excel con 6 hojas: **Resumen disponibilidad**, "
        "**Saldos a fecha de corte**, **Vista matriz por cuenta**, "
        "**Movimientos considerados**, **Movimientos posteriores** y "
        "**Cuentas sin saldo identificado**."
    )

    n_bancos_exp    = int(df_filtrado["banco"].nunique())
    n_cuentas_exp   = int(df_filtrado[["banco", "cuenta"]].drop_duplicates().shape[0])
    n_sin_saldo_exp = int(df_filtrado["es_estimado"].sum())

    try:
        excel_bytes = _export_saldos_excel(
            df_saldos     = df_filtrado,
            df_movs_corte = df_corte,
            df_movs_post  = df_post,
            fecha_corte   = fecha_corte,
            totales       = {
                "BOB": total_mon("BOB"),
                "USD": total_mon("USD"),
                "EUR": total_mon("EUR"),
            },
            estadisticas  = {
                "n_bancos":    n_bancos_exp,
                "n_cuentas":   n_cuentas_exp,
                "n_sin_saldo": n_sin_saldo_exp,
            },
        )
        st.download_button(
            label="Descargar reporte de disponibilidad (Excel)",
            data=excel_bytes,
            file_name=f"disponibilidad_{fecha_corte.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        st.warning(f"No se pudo generar el Excel: {exc}")


# ─── Exportación Excel ────────────────────────────────────────────────────────

def _export_saldos_excel(
    df_saldos: pd.DataFrame,
    df_movs_corte: pd.DataFrame,
    df_movs_post: pd.DataFrame,
    fecha_corte: datetime.date,
    totales: dict,
    estadisticas: dict,
) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:

        # ── Hoja 1: Resumen disponibilidad ────────────────────────────────
        resumen = pd.DataFrame([{
            "Fecha de corte":                  fecha_corte.strftime("%d/%m/%Y"),
            "Saldo total BOB (Bs)":            totales.get("BOB", 0.0),
            "Saldo total USD":                 totales.get("USD", 0.0),
            "Saldo total EUR":                 totales.get("EUR", 0.0),
            "Cantidad de bancos":              estadisticas.get("n_bancos", 0),
            "Cantidad de cuentas":             estadisticas.get("n_cuentas", 0),
            "Cuentas sin saldo identificado":  estadisticas.get("n_sin_saldo", 0),
        }])
        resumen.to_excel(writer, index=False, sheet_name="Resumen disponibilidad")

        # ── Hoja 2: Saldos a fecha de corte ──────────────────────────────
        hoja2 = df_saldos.copy()
        if "fecha_ult_mov" in hoja2.columns:
            hoja2["fecha_ult_mov"] = pd.to_datetime(
                hoja2["fecha_ult_mov"], errors="coerce"
            ).dt.strftime("%d/%m/%Y")
        hoja2 = hoja2.rename(columns={
            "empresa":      "Empresa",
            "banco":        "Banco",
            "cuenta":       "Cuenta",
            "nombre_corto": "Nombre corto",
            "moneda":       "Moneda",
            "fecha_ult_mov": "Fecha último movimiento",
            "saldo_corte":  "Saldo a la fecha de corte",
            "es_estimado":  "Es estimado",
            "archivo":      "Archivo origen",
            "observacion":  "Observaciones",
        })
        hoja2.to_excel(writer, index=False, sheet_name="Saldos a fecha de corte")

        # ── Hoja 3: Vista matriz por cuenta ──────────────────────────────
        try:
            pivot = df_saldos.pivot_table(
                index=["empresa", "banco", "cuenta", "nombre_corto"],
                columns="moneda",
                values="saldo_corte",
                aggfunc="sum",
            ).reset_index()
            pivot.columns.name = None
            for mon in ["BOB", "USD", "EUR"]:
                if mon not in pivot.columns:
                    pivot[mon] = float("nan")
            pivot = pivot.rename(columns={
                "empresa": "Empresa", "banco": "Banco",
                "cuenta": "Cuenta", "nombre_corto": "Nombre corto",
                "BOB": "Saldo BOB (Bs)", "USD": "Saldo USD", "EUR": "Saldo EUR",
            })
            pivot.to_excel(writer, index=False, sheet_name="Vista matriz por cuenta")
        except Exception:
            pd.DataFrame().to_excel(writer, index=False, sheet_name="Vista matriz por cuenta")

        # ── Hoja 4: Movimientos considerados ─────────────────────────────
        _prep_movs_for_excel(df_movs_corte).to_excel(
            writer, index=False, sheet_name="Movimientos considerados"
        )

        # ── Hoja 5: Movimientos posteriores ──────────────────────────────
        _prep_movs_for_excel(df_movs_post).to_excel(
            writer, index=False, sheet_name="Movimientos posteriores"
        )

        # ── Hoja 6: Cuentas sin saldo identificado ────────────────────────
        df_sin = df_saldos[df_saldos["es_estimado"]].copy()
        if df_sin.empty:
            hoja6 = pd.DataFrame(columns=[
                "Empresa", "Banco", "Cuenta", "Nombre corto",
                "Moneda", "Saldo estimado", "Observaciones",
            ])
        else:
            cols_h6 = [c for c in [
                "empresa", "banco", "cuenta", "nombre_corto",
                "moneda", "saldo_corte", "observacion",
            ] if c in df_sin.columns]
            hoja6 = df_sin[cols_h6].rename(columns={
                "empresa": "Empresa", "banco": "Banco", "cuenta": "Cuenta",
                "nombre_corto": "Nombre corto", "moneda": "Moneda",
                "saldo_corte": "Saldo estimado", "observacion": "Observaciones",
            })
        hoja6.to_excel(writer, index=False, sheet_name="Cuentas sin saldo")

    return buf.getvalue()


def _prep_movs_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara un DataFrame de movimientos para exportar a Excel."""
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "Empresa", "Banco", "Cuenta", "Nombre corto", "Moneda",
            "Fecha", "Descripción", "Referencia", "Débito", "Crédito",
            "Importe", "Saldo", "Archivo",
        ])
    out = df.copy()
    if "fecha" in out.columns:
        out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    rename = {
        "empresa": "Empresa", "banco": "Banco", "cuenta": "Cuenta",
        "nombre_corto": "Nombre corto", "moneda": "Moneda",
        "fecha": "Fecha", "descripcion": "Descripción", "referencia": "Referencia",
        "debito": "Débito", "credito": "Crédito",
        "importe": "Importe", "saldo": "Saldo", "archivo": "Archivo",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    keep = [v for v in rename.values() if v in out.columns]
    return out[keep]
