"""
Vista previa — buscador avanzado con filtros rápidos.
"""

import unicodedata
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from core.schema import fmt_amount


# ─── Constantes ──────────────────────────────────────────────────────────────
_DISPLAY_COLS = [
    "empresa", "banco", "cuenta", "fecha", "hora",
    "beneficiario", "descripcion", "referencia",
    "debito_bob", "credito_bob", "importe_bob",
    "debito_usd", "credito_usd", "importe_usd",
    "sucursal", "observaciones",
]
_RENAME = {
    "empresa":      "Empresa",
    "banco":        "Banco",
    "cuenta":       "Cuenta",
    "fecha":        "Fecha",
    "hora":         "Hora",
    "beneficiario": "Beneficiario / Ordenante",
    "descripcion":  "Descripción",
    "referencia":   "Referencia",
    "debito_bob":   "Débito Bs",
    "credito_bob":  "Crédito Bs",
    "importe_bob":  "Importe Bs",
    "debito_usd":   "Débito USD",
    "credito_usd":  "Crédito USD",
    "importe_usd":  "Importe USD",
    "sucursal":     "Sucursal",
    "observaciones": "Observaciones",
}
_AMOUNT_COLS = [
    "debito_bob", "credito_bob", "importe_bob",
    "debito_usd", "credito_usd", "importe_usd",
]
_SEARCH_TEXT_COLS = [
    "empresa", "banco", "cuenta", "hora",
    "beneficiario", "descripcion", "referencia",
    "sucursal", "observaciones",
]
_TOL_OPTIONS = {"0.01": 0.01, "1": 1.0, "10": 10.0, "100": 100.0, "1,000": 1000.0}
_FILTER_KEYS = [
    "prev_buscar", "prev_banco", "prev_cuenta", "prev_moneda", "prev_tipo",
    "prev_rango", "prev_mmin", "prev_mmax", "prev_mexacto",
    "prev_tol", "prev_abs",
]


# ─── Utilidades ───────────────────────────────────────────────────────────────
def _norm(s) -> str:
    s = str(s).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _build_search_col(df: pd.DataFrame) -> pd.Series:
    parts = [df["fecha"].dt.strftime("%d/%m/%Y").fillna("") if "fecha" in df.columns else ""]
    for col in _SEARCH_TEXT_COLS:
        parts.append(df[col].fillna("").astype(str) if col in df.columns else "")
    combined = pd.Series("", index=df.index)
    for p in parts:
        combined = combined + " " + (p if isinstance(p, pd.Series) else p)
    return combined.apply(_norm)


def _num_series(df: pd.DataFrame, col: str, use_abs: bool) -> pd.Series:
    v = pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(pd.NA, index=df.index, dtype=float)
    return v.abs() if use_abs else v


def _apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df.copy()

    # Búsqueda general
    q = _norm(f.get("buscar", ""))
    if q and "_search" in out.columns:
        out = out[out["_search"].str.contains(q, na=False)]

    # Identificación
    banco = f.get("banco", "Todos")
    if banco and banco != "Todos" and "banco" in out.columns:
        out = out[out["banco"] == banco]

    cuenta = f.get("cuenta", "Todas")
    if cuenta and cuenta != "Todas" and "cuenta" in out.columns:
        out = out[out["cuenta"] == cuenta]

    moneda = f.get("moneda", "Todas")
    if moneda and moneda != "Todas" and "moneda" in out.columns:
        out = out[out["moneda"] == moneda]

    # Tipo de movimiento
    tipo = f.get("tipo_mov", "Todos")
    if tipo != "Todos" and "importe" in out.columns:
        imp = pd.to_numeric(out["importe"], errors="coerce")
        if tipo == "Créditos (ingresos)":
            out = out[imp > 0]
        elif tipo == "Débitos (egresos)":
            out = out[imp < 0]

    # Fechas
    if "fecha" in out.columns:
        fd = f.get("fecha_desde")
        fh = f.get("fecha_hasta")
        if fd:
            out = out[out["fecha"].dt.date >= fd]
        if fh:
            out = out[out["fecha"].dt.date <= fh]

    # Monto
    use_abs      = f.get("buscar_abs", True)
    monto_exacto = f.get("monto_exacto")
    tolerancia   = f.get("tolerancia", 0.01)
    monto_min    = f.get("monto_min")
    monto_max    = f.get("monto_max")

    if monto_exacto:
        target = abs(monto_exacto) if use_abs else monto_exacto
        mask = pd.Series(False, index=out.index)
        for col in _AMOUNT_COLS:
            v = _num_series(out, col, use_abs)
            mask |= (v - target).abs().le(tolerancia) & v.notna()
        out = out[mask]
    elif monto_min or monto_max:
        mask = pd.Series(False, index=out.index)
        for col in _AMOUNT_COLS:
            v = _num_series(out, col, use_abs)
            col_ok = v.notna()
            if monto_min:
                col_ok &= v >= monto_min
            if monto_max:
                col_ok &= v <= monto_max
            mask |= col_ok
        out = out[mask]

    return out


# ─── Exportar ─────────────────────────────────────────────────────────────────
def _to_excel_bytes(df_raw: pd.DataFrame, filters_used: dict) -> bytes:
    """Genera Excel con hoja de resultados + hoja de resumen de filtros."""
    # Hoja 1: resultados con encabezado estándar
    for col in _DISPLAY_COLS:
        if col not in df_raw.columns:
            df_raw[col] = ""
    dl = df_raw[[c for c in _DISPLAY_COLS]].copy()
    if "fecha" in dl.columns:
        dl["fecha"] = pd.to_datetime(dl["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    dl = dl.rename(columns=_RENAME)

    # Hoja 2: resumen de filtros
    resumen = [
        ["Fecha de generación",          datetime.now().strftime("%d/%m/%Y %H:%M:%S")],
        ["Banco seleccionado",            filters_used.get("banco",        "Todos")],
        ["Cuenta seleccionada",           filters_used.get("cuenta",       "Todas")],
        ["Moneda",                        filters_used.get("moneda",       "Todas")],
        ["Tipo de movimiento",            filters_used.get("tipo_mov",     "Todos")],
        ["Texto buscado",                 filters_used.get("buscar",       "")],
        ["Fecha desde",                   str(filters_used.get("fecha_desde", ""))],
        ["Fecha hasta",                   str(filters_used.get("fecha_hasta", ""))],
        ["Monto desde",                   str(filters_used.get("monto_min",   "") or "")],
        ["Monto hasta",                   str(filters_used.get("monto_max",   "") or "")],
        ["Monto exacto",                  str(filters_used.get("monto_exacto","") or "")],
        ["Tolerancia",                    str(filters_used.get("tolerancia",  0.01))],
        ["Buscar por valor absoluto",     "Sí" if filters_used.get("buscar_abs") else "No"],
        ["Cantidad de movimientos",       len(df_raw)],
    ]
    df_resumen = pd.DataFrame(resumen, columns=["Campo", "Valor"])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        dl.to_excel(writer, index=False, sheet_name="Resultados filtrados")
        df_resumen.to_excel(writer, index=False, sheet_name="Resumen filtros")
    return buf.getvalue()


# ─── Formateo para tabla ───────────────────────────────────────────────────────
def _fmt_bob(v, col):
    try:
        f = float(v)
        return "" if (col in ("debito_bob", "credito_bob") and f == 0.0) else fmt_amount(f, "BOB")
    except (TypeError, ValueError):
        return ""


def _fmt_usd(v, col):
    try:
        f = float(v)
        return "" if (col in ("debito_usd", "credito_usd") and f == 0.0) else fmt_amount(f, "USD")
    except (TypeError, ValueError):
        return ""


# ─── Función principal ────────────────────────────────────────────────────────
def render_preview(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    # ── Estado vacío ─────────────────────────────────────────────────────
    if df.empty:
        st.info("Carga y procesa extractos para usar el buscador.")
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

    # ── Título ───────────────────────────────────────────────────────────
    st.subheader("Vista previa de movimientos")

    # ── Buscador general ─────────────────────────────────────────────────
    col_search, col_clear = st.columns([5, 1])
    with col_search:
        st.text_input(
            "🔍",
            placeholder="Buscar movimiento, glosa, beneficiario, referencia o cuenta",
            key="prev_buscar",
            label_visibility="collapsed",
        )
    with col_clear:
        if st.button("🗑 Limpiar", use_container_width=True, key="prev_btn_limpiar"):
            for k in _FILTER_KEYS:
                st.session_state.pop(k, None)
            st.rerun()

    # ── Rango de fechas ───────────────────────────────────────────────────
    rango = st.date_input(
        "Rango de fechas",
        value=(fecha_min, fecha_max),
        min_value=fecha_min,
        max_value=fecha_max,
        key="prev_rango",
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

        # Fila 1: Banco · Cuenta · Moneda · Tipo de movimiento
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)

        with r1c1:
            bancos_opts = ["Todos"] + sorted(df_valido["banco"].dropna().unique().tolist())
            st.selectbox("Banco", bancos_opts, key="prev_banco")

        with r1c2:
            banco_actual = st.session_state.get("prev_banco", "Todos")
            if banco_actual != "Todos" and "banco" in df_valido.columns:
                df_cuentas = df_valido[df_valido["banco"] == banco_actual]
            else:
                df_cuentas = df_valido
            cuentas_opts = ["Todas"] + sorted(df_cuentas["cuenta"].dropna().unique().tolist()) if "cuenta" in df_cuentas.columns else ["Todas"]
            prev_cuenta = st.session_state.get("prev_cuenta", "Todas")
            if prev_cuenta not in cuentas_opts:
                st.session_state["prev_cuenta"] = "Todas"
            st.selectbox("Cuenta", cuentas_opts, key="prev_cuenta")

        with r1c3:
            mon_opts = ["Todas"] + sorted(df_valido["moneda"].dropna().unique().tolist()) if "moneda" in df_valido.columns else ["Todas"]
            st.selectbox("Moneda", mon_opts, key="prev_moneda")

        with r1c4:
            st.selectbox(
                "Tipo de movimiento",
                ["Todos", "Créditos (ingresos)", "Débitos (egresos)"],
                key="prev_tipo",
            )

        # Fila 2: Montos
        r2c1, r2c2, r2c3 = st.columns(3)

        with r2c1:
            st.number_input("Monto desde", min_value=0.0, value=0.0, step=1.0,
                            key="prev_mmin", format="%.2f")
            st.number_input("Monto hasta", min_value=0.0, value=0.0, step=1.0,
                            key="prev_mmax", format="%.2f")

        with r2c2:
            st.number_input("Monto exacto (opcional)", min_value=0.0, value=0.0,
                            step=0.01, key="prev_mexacto", format="%.2f")
            st.selectbox("Tolerancia ±", list(_TOL_OPTIONS.keys()), key="prev_tol")

        with r2c3:
            st.markdown("<br>", unsafe_allow_html=True)
            st.checkbox("Buscar por valor absoluto", key="prev_abs", value=True)

    monto_min_val    = st.session_state.get("prev_mmin", 0.0) or 0.0
    monto_max_val    = st.session_state.get("prev_mmax", 0.0) or 0.0
    monto_exacto_val = st.session_state.get("prev_mexacto", 0.0) or 0.0
    tol_key_val      = st.session_state.get("prev_tol", "0.01")
    tolerancia_val   = _TOL_OPTIONS.get(tol_key_val, 0.01)

    filters = {
        "buscar":       st.session_state.get("prev_buscar", ""),
        "banco":        st.session_state.get("prev_banco",  "Todos"),
        "cuenta":       st.session_state.get("prev_cuenta", "Todas"),
        "moneda":       st.session_state.get("prev_moneda", "Todas"),
        "tipo_mov":     st.session_state.get("prev_tipo",   "Todos"),
        "fecha_desde":  fd_activo,
        "fecha_hasta":  fh_activo,
        "monto_min":    monto_min_val    if monto_min_val    > 0 else None,
        "monto_max":    monto_max_val    if monto_max_val    > 0 else None,
        "monto_exacto": monto_exacto_val if monto_exacto_val > 0 else None,
        "tolerancia":   tolerancia_val,
        "buscar_abs":   st.session_state.get("prev_abs", True),
    }

    filtered = _apply_filters(df_valido, filters)

    # ── Métricas ─────────────────────────────────────────────────────────
    def _sum(col):
        return float(pd.to_numeric(filtered[col], errors="coerce").fillna(0).sum()) if col in filtered.columns else 0.0

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Movimientos",  f"{len(filtered):,}")
    m2.metric("Débito Bs",    fmt_amount(_sum("debito_bob"),  "BOB"))
    m3.metric("Crédito Bs",   fmt_amount(_sum("credito_bob"), "BOB"))
    m4.metric("Importe Bs",   fmt_amount(_sum("importe_bob"), "BOB"))
    m5.metric("Débito USD",   fmt_amount(_sum("debito_usd"),  "USD"))
    m6.metric("Crédito USD",  fmt_amount(_sum("credito_usd"), "USD"))
    m7.metric("Importe USD",  fmt_amount(_sum("importe_usd"), "USD"))

    # ── Descarga ──────────────────────────────────────────────────────────
    cap_col, dl_col = st.columns([4, 2])
    cap_col.caption(f"Mostrando **{len(filtered):,}** de **{len(df_valido):,}** movimientos.")

    if not filtered.empty:
        dl_col.download_button(
            "⬇ Descargar resultados filtrados",
            data=_to_excel_bytes(filtered.copy(), filters),
            file_name="movimientos_filtrados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.divider()

    # ── Tabla estándar ────────────────────────────────────────────────────
    if filtered.empty:
        st.info("Ningún movimiento cumple los filtros actuales.")
        return

    display = filtered.copy()
    display["fecha"] = display["fecha"].dt.strftime("%d/%m/%Y")

    for col in ["debito_bob", "credito_bob", "importe_bob"]:
        if col in display.columns:
            display[col] = display[col].apply(lambda v, c=col: _fmt_bob(v, c))
    for col in ["debito_usd", "credito_usd", "importe_usd"]:
        if col in display.columns:
            display[col] = display[col].apply(lambda v, c=col: _fmt_usd(v, c))

    # Asegurar que todas las columnas estándar existan
    for col in _DISPLAY_COLS:
        if col not in display.columns:
            display[col] = ""

    st.dataframe(
        display[_DISPLAY_COLS].rename(columns=_RENAME),
        use_container_width=True,
        hide_index=True,
    )
