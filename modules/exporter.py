"""
Exportación a Excel con filtros avanzados.

Hoja 1 — "Movimientos estandarizados": encabezado estándar de 16 columnas.
Hoja 2 — "Auditoría de origen": trazabilidad completa (archivo, hoja, fila, ZIP…).
"""

import unicodedata
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from core.schema import fmt_amount


# ─── Constantes ───────────────────────────────────────────────────────────────
_STD_COLS = [
    "empresa", "banco", "cuenta", "fecha", "hora",
    "beneficiario", "descripcion", "referencia",
    "debito_bob", "credito_bob", "importe_bob",
    "debito_usd", "credito_usd", "importe_usd",
    "sucursal", "observaciones",
]
_STD_RENAME = {
    "empresa":       "Empresa",
    "banco":         "Banco",
    "cuenta":        "Cuenta",
    "fecha":         "Fecha",
    "hora":          "Hora",
    "beneficiario":  "Beneficiario / Ordenante",
    "descripcion":   "Descripción",
    "referencia":    "Referencia",
    "debito_bob":    "Débito Bs",
    "credito_bob":   "Crédito Bs",
    "importe_bob":   "Importe Bs",
    "debito_usd":    "Débito USD",
    "credito_usd":   "Crédito USD",
    "importe_usd":   "Importe USD",
    "sucursal":      "Sucursal",
    "observaciones": "Observaciones",
}
_AUDIT_COLS = [
    "empresa", "banco", "cuenta", "moneda", "tipo_cuenta",
    "fecha", "descripcion", "referencia",
    "debito_bob", "credito_bob", "importe_bob",
    "debito_usd", "credito_usd", "importe_usd",
    "nombre_corto", "hoja_origen", "fila_origen",
    "carpeta_origen", "ruta_zip", "archivo",
]
_AUDIT_RENAME = {
    **_STD_RENAME,
    "moneda":        "Moneda",
    "tipo_cuenta":   "Tipo cuenta",
    "nombre_corto":  "Nombre corto",
    "hoja_origen":   "Hoja origen",
    "fila_origen":   "Fila origen",
    "carpeta_origen":"Carpeta origen",
    "ruta_zip":      "Ruta ZIP",
    "archivo":       "Archivo origen",
}
_AMOUNT_COLS = ["debito_bob","credito_bob","importe_bob","debito_usd","credito_usd","importe_usd"]
_TOL_OPTIONS = {"0.01": 0.01, "1": 1.0, "10": 10.0, "100": 100.0, "1,000": 1000.0}
_FILTER_KEYS = [
    "exp_buscar","exp_banco","exp_cuenta","exp_moneda","exp_tipo",
    "exp_mmin","exp_mmax","exp_mexacto",
    "exp_tol","exp_abs","exp_rango",
]


# ─── Utilidades ───────────────────────────────────────────────────────────────
def _norm(s) -> str:
    s = str(s).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _build_search_col(df: pd.DataFrame) -> pd.Series:
    text_cols = ["empresa","banco","cuenta","hora","beneficiario",
                 "descripcion","referencia","sucursal","observaciones"]
    parts = [df["fecha"].dt.strftime("%d/%m/%Y").fillna("") if "fecha" in df.columns else ""]
    for col in text_cols:
        parts.append(df[col].fillna("").astype(str) if col in df.columns else "")
    combined = pd.Series("", index=df.index)
    for p in parts:
        combined = combined + " " + p
    return combined.apply(_norm)



def _apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df.copy()

    q = _norm(f.get("buscar", ""))
    if q and "_search" in out.columns:
        out = out[out["_search"].str.contains(q, na=False)]

    for campo, col, ninguno in [
        ("banco",  "banco",  "Todos"),
        ("cuenta", "cuenta", "Todas"),
        ("moneda", "moneda", "Todas"),
    ]:
        v = f.get(campo, ninguno)
        if v and v != ninguno and col in out.columns:
            out = out[out[col] == v]

    tipo = f.get("tipo_mov", "Todos")
    if tipo != "Todos" and "importe" in out.columns:
        imp = pd.to_numeric(out["importe"], errors="coerce")
        if tipo == "Créditos (ingresos)":   out = out[imp > 0]
        elif tipo == "Débitos (egresos)":   out = out[imp < 0]

    if "fecha" in out.columns:
        if f.get("fecha_desde"): out = out[out["fecha"].dt.date >= f["fecha_desde"]]
        if f.get("fecha_hasta"): out = out[out["fecha"].dt.date <= f["fecha_hasta"]]

    use_abs      = f.get("buscar_abs", True)
    monto_exacto = f.get("monto_exacto")
    tolerancia   = f.get("tolerancia", 0.01)
    monto_min    = f.get("monto_min")
    monto_max    = f.get("monto_max")

    def _v(col):
        s = pd.to_numeric(out[col], errors="coerce") if col in out.columns else pd.Series(pd.NA, index=out.index, dtype=float)
        return s.abs() if use_abs else s

    if monto_exacto:
        target = abs(monto_exacto) if use_abs else monto_exacto
        mask = pd.Series(False, index=out.index)
        for col in _AMOUNT_COLS:
            v = _v(col); mask |= (v - target).abs().le(tolerancia) & v.notna()
        out = out[mask]
    elif monto_min or monto_max:
        mask = pd.Series(False, index=out.index)
        for col in _AMOUNT_COLS:
            v = _v(col); m = v.notna()
            if monto_min: m &= v >= monto_min
            if monto_max: m &= v <= monto_max
            mask |= m
        out = out[mask]

    return out


# ─── Generador de Excel ────────────────────────────────────────────────────────
def _to_excel(df_filtered: pd.DataFrame, filters_used: dict) -> bytes:
    for col in _STD_COLS:
        if col not in df_filtered.columns:
            df_filtered[col] = ""

    # Hoja 1: encabezado estándar
    h1 = df_filtered[_STD_COLS].copy()
    if "fecha" in h1.columns:
        h1["fecha"] = pd.to_datetime(h1["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    h1 = h1.rename(columns=_STD_RENAME)

    # Hoja 2: auditoría
    audit_present = [c for c in _AUDIT_COLS if c in df_filtered.columns]
    h2 = df_filtered[audit_present].copy()
    if "fecha" in h2.columns:
        h2["fecha"] = pd.to_datetime(h2["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    h2 = h2.rename(columns=_AUDIT_RENAME)

    # Hoja 3: resumen de filtros aplicados
    resumen = [
        ["Fecha de generación",        datetime.now().strftime("%d/%m/%Y %H:%M:%S")],
        ["Banco",                      filters_used.get("banco",        "Todos")],
        ["Cuenta",                     filters_used.get("cuenta",       "Todas")],
        ["Moneda",                     filters_used.get("moneda",       "Todas")],
        ["Tipo de movimiento",         filters_used.get("tipo_mov",     "Todos")],
        ["Texto buscado",              filters_used.get("buscar",       "")],
        ["Fecha desde",                str(filters_used.get("fecha_desde", ""))],
        ["Fecha hasta",                str(filters_used.get("fecha_hasta", ""))],
        ["Monto desde",                str(filters_used.get("monto_min",   "") or "")],
        ["Monto hasta",                str(filters_used.get("monto_max",   "") or "")],
        ["Monto exacto",               str(filters_used.get("monto_exacto","") or "")],
        ["Tolerancia ±",               str(filters_used.get("tolerancia",  0.01))],
        ["Buscar por valor absoluto",  "Sí" if filters_used.get("buscar_abs") else "No"],
        ["Movimientos exportados",     len(df_filtered)],
    ]
    h3 = pd.DataFrame(resumen, columns=["Parámetro", "Valor"])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        h1.to_excel(writer, index=False, sheet_name="Movimientos estandarizados")
        h2.to_excel(writer, index=False, sheet_name="Auditoría de origen")
        h3.to_excel(writer, index=False, sheet_name="Parámetros de exportación")
    return buf.getvalue()


# ─── Función principal ────────────────────────────────────────────────────────
def render_exporter(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    if df.empty:
        st.info("Carga y procesa extractos antes de exportar.")
        return

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df_valido   = df.dropna(subset=["fecha"]).copy()

    if df_valido.empty:
        st.warning("No hay movimientos con fechas válidas.")
        return

    df_valido["_search"] = _build_search_col(df_valido)
    fecha_min = df_valido["fecha"].min().date()
    fecha_max = df_valido["fecha"].max().date()

    st.subheader("Exportar a Excel")

    # ── Buscador ──────────────────────────────────────────────────────────
    col_s, col_cl = st.columns([5, 1])
    with col_s:
        st.text_input(
            "🔍",
            placeholder="Buscar movimiento, glosa, beneficiario, referencia o cuenta",
            key="exp_buscar",
            label_visibility="collapsed",
        )
    with col_cl:
        if st.button("🗑 Limpiar", key="exp_btn_limpiar", use_container_width=True):
            for k in _FILTER_KEYS:
                st.session_state.pop(k, None)
            st.rerun()

    # ── Rango de fechas ───────────────────────────────────────────────────
    rango = st.date_input(
        "Rango de fechas",
        value=(fecha_min, fecha_max),
        min_value=fecha_min,
        max_value=fecha_max,
        key="exp_rango",
    )
    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        fd_activo, fh_activo = rango[0], rango[1]
    elif isinstance(rango, (list, tuple)) and len(rango) == 1:
        fd_activo = fh_activo = rango[0]
    else:
        fd_activo = fh_activo = rango
    st.caption(f"Rango aplicado: {fd_activo.strftime('%d/%m/%Y')} a {fh_activo.strftime('%d/%m/%Y')}")

    # ── Filtros avanzados ─────────────────────────────────────────────────
    with st.expander("⚙ Filtros avanzados", expanded=False):
        r1, r2, r3, r4 = st.columns(4)

        with r1:
            bancos_opts = ["Todos"] + sorted(df_valido["banco"].dropna().unique().tolist())
            st.selectbox("Banco", bancos_opts, key="exp_banco")

        with r2:
            banco_sel = st.session_state.get("exp_banco", "Todos")
            df_c = df_valido[df_valido["banco"] == banco_sel] if banco_sel != "Todos" and "banco" in df_valido.columns else df_valido
            cuentas_opts = ["Todas"] + sorted(df_c["cuenta"].dropna().unique().tolist()) if "cuenta" in df_c.columns else ["Todas"]
            prev_c = st.session_state.get("exp_cuenta", "Todas")
            if prev_c not in cuentas_opts:
                st.session_state["exp_cuenta"] = "Todas"
            st.selectbox("Cuenta", cuentas_opts, key="exp_cuenta")

        with r3:
            mon_opts = ["Todas"] + sorted(df_valido["moneda"].dropna().unique().tolist()) if "moneda" in df_valido.columns else ["Todas"]
            st.selectbox("Moneda", mon_opts, key="exp_moneda")

        with r4:
            st.selectbox("Tipo de movimiento",
                         ["Todos","Créditos (ingresos)","Débitos (egresos)"],
                         key="exp_tipo")

        r2c, r2d = st.columns(2)
        with r2c:
            st.number_input("Monto desde", min_value=0.0, value=0.0, step=1.0, key="exp_mmin", format="%.2f")
            st.number_input("Monto hasta", min_value=0.0, value=0.0, step=1.0, key="exp_mmax", format="%.2f")

        with r2d:
            st.number_input("Monto exacto (opcional)", min_value=0.0, value=0.0, step=0.01, key="exp_mexacto", format="%.2f")
            st.selectbox("Tolerancia ±", list(_TOL_OPTIONS.keys()), key="exp_tol")
            st.checkbox("Buscar por valor absoluto", key="exp_abs", value=True)

    # ── Leer estado de filtros ────────────────────────────────────────────

    tol_k = st.session_state.get("exp_tol", "0.01")
    mmin  = st.session_state.get("exp_mmin", 0.0) or 0.0
    mmax  = st.session_state.get("exp_mmax", 0.0) or 0.0
    mexac = st.session_state.get("exp_mexacto", 0.0) or 0.0

    filters = {
        "buscar":       st.session_state.get("exp_buscar", ""),
        "banco":        st.session_state.get("exp_banco",  "Todos"),
        "cuenta":       st.session_state.get("exp_cuenta", "Todas"),
        "moneda":       st.session_state.get("exp_moneda", "Todas"),
        "tipo_mov":     st.session_state.get("exp_tipo",   "Todos"),
        "fecha_desde":  fd_activo,
        "fecha_hasta":  fh_activo,
        "monto_min":    mmin  if mmin  > 0 else None,
        "monto_max":    mmax  if mmax  > 0 else None,
        "monto_exacto": mexac if mexac > 0 else None,
        "tolerancia":   _TOL_OPTIONS.get(tol_k, 0.01),
        "buscar_abs":   st.session_state.get("exp_abs", True),

    }

    filtered = _apply_filters(df_valido, filters)

    # ── Métricas ──────────────────────────────────────────────────────────
    def _sum(col):
        return float(pd.to_numeric(filtered[col], errors="coerce").fillna(0).sum()) if col in filtered.columns else 0.0

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Movimientos a exportar", f"{len(filtered):,}")
    m2.metric("Débito Bs",   fmt_amount(_sum("debito_bob"),  "BOB"))
    m3.metric("Crédito Bs",  fmt_amount(_sum("credito_bob"), "BOB"))
    m4.metric("Importe Bs",  fmt_amount(_sum("importe_bob"), "BOB"))
    m5.metric("Débito USD",  fmt_amount(_sum("debito_usd"),  "USD"))
    m6.metric("Crédito USD", fmt_amount(_sum("credito_usd"), "USD"))
    m7.metric("Importe USD", fmt_amount(_sum("importe_usd"), "USD"))

    st.divider()

    # ── Descarga ──────────────────────────────────────────────────────────
    cap_col, dl_col = st.columns([4, 2])
    cap_col.caption(
        f"Se exportarán **{len(filtered):,}** de **{len(df_valido):,}** movimientos "
        f"en **3 hojas**: Movimientos estandarizados · Auditoría de origen · Parámetros."
    )

    if filtered.empty:
        dl_col.warning("Sin movimientos que exportar con los filtros actuales.")
    else:
        dl_col.download_button(
            "⬇ Exportar a Excel",
            data=_to_excel(filtered.copy(), filters),
            file_name="extractos_exportados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )

    # ── Vista previa de la exportación ───────────────────────────────────
    if not filtered.empty:
        st.caption("Vista previa (primeras 5 filas · encabezado estándar):")
        prev_cols = [c for c in _STD_COLS if c in filtered.columns]
        prev_df = filtered[prev_cols].head(5).copy()
        prev_df["fecha"] = pd.to_datetime(prev_df["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
        st.dataframe(prev_df.rename(columns=_STD_RENAME), use_container_width=True, hide_index=True)
