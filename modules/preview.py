"""
Vista previa de movimientos con filtros avanzados y buscador general.

Filtros disponibles:
- Buscador de texto libre (empresa, banco, cuenta, fecha, hora, beneficiario,
  descripción, referencia, sucursal, observaciones) — ignora mayúsculas y acentos.
- Banco, Cuenta, Empresa, Moneda, Tipo de movimiento.
- Rango de fechas.
- Monto exacto (con tolerancia) o rango de montos — busca en todos los campos
  de importe (Bs y USD) por valor absoluto.
- Beneficiario, Referencia, Sucursal.

Métricas post-filtrado: movimientos, totales Bs y USD.
Descarga Excel de resultados filtrados.
"""

import unicodedata
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
    "observaciones":"Observaciones",
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


# ─── Utilidades ───────────────────────────────────────────────────────────────
def _norm(s) -> str:
    """Minúsculas, sin acentos, espacios normalizados."""
    s = str(s).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _build_search_col(df: pd.DataFrame) -> pd.Series:
    """Columna de texto combinado normalizado para búsqueda vectorizada."""
    parts = []
    for col in _SEARCH_TEXT_COLS:
        parts.append(df[col].fillna("").astype(str) if col in df.columns else "")
    if "fecha" in df.columns:
        parts.append(df["fecha"].dt.strftime("%d/%m/%Y").fillna(""))
    combined = pd.Series("", index=df.index)
    for p in parts:
        if isinstance(p, pd.Series):
            combined = combined + " " + p
        else:
            combined = combined + " " + p
    return combined.apply(_norm)


def _to_num_series(df: pd.DataFrame, col: str) -> pd.Series:
    return (
        pd.to_numeric(df[col], errors="coerce")
        if col in df.columns
        else pd.Series(pd.NA, index=df.index, dtype=float)
    )


def _to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Movimientos filtrados")
    return buf.getvalue()


# ─── Lógica de filtrado ───────────────────────────────────────────────────────
def _apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df.copy()

    # ── Buscador general ──────────────────────────────────────────────────
    q = _norm(f.get("buscar", ""))
    if q:
        if "_search_text" not in out.columns:
            out["_search_text"] = _build_search_col(out)
        out = out[out["_search_text"].str.contains(q, na=False)]

    # ── Identificación ────────────────────────────────────────────────────
    for campo, col in [("banco", "banco"), ("cuenta", "cuenta"),
                        ("empresa", "empresa"), ("moneda", "moneda")]:
        val = f.get(campo, "")
        sentinel = "Todos" if campo in ("banco",) else "Todas"
        if val and val not in (sentinel, "Todas", "Todos") and col in out.columns:
            out = out[out[col] == val]

    # ── Fechas ────────────────────────────────────────────────────────────
    if f.get("fecha_desde") and "fecha" in out.columns:
        out = out[out["fecha"].dt.date >= f["fecha_desde"]]
    if f.get("fecha_hasta") and "fecha" in out.columns:
        out = out[out["fecha"].dt.date <= f["fecha_hasta"]]

    # ── Tipo de movimiento ────────────────────────────────────────────────
    tipo = f.get("tipo_mov", "Todos")
    if tipo != "Todos" and "importe" in out.columns:
        imp_num = pd.to_numeric(out["importe"], errors="coerce")
        if tipo == "Débitos (egresos)":
            out = out[imp_num < 0]
        elif tipo == "Créditos (ingresos)":
            out = out[imp_num > 0]

    # ── Monto ─────────────────────────────────────────────────────────────
    monto_exacto = f.get("monto_exacto")
    tolerancia   = f.get("tolerancia", 0.01)
    monto_min    = f.get("monto_min")
    monto_max    = f.get("monto_max")

    if monto_exacto is not None and monto_exacto > 0:
        target = abs(monto_exacto)
        mask = pd.Series(False, index=out.index)
        for col in _AMOUNT_COLS:
            if col in out.columns:
                v = pd.to_numeric(out[col], errors="coerce").abs()
                mask |= (v - target).abs().le(tolerancia) & v.notna()
        out = out[mask]

    elif monto_min is not None or monto_max is not None:
        has_min = monto_min is not None and monto_min > 0
        has_max = monto_max is not None and monto_max > 0
        if has_min or has_max:
            mask = pd.Series(False, index=out.index)
            for col in _AMOUNT_COLS:
                if col in out.columns:
                    v = pd.to_numeric(out[col], errors="coerce").abs()
                    col_ok = v.notna()
                    if has_min:
                        col_ok &= v >= monto_min
                    if has_max:
                        col_ok &= v <= monto_max
                    mask |= col_ok
            out = out[mask]

    # ── Texto libre por campo ─────────────────────────────────────────────
    for campo, col in [("beneficiario", "beneficiario"),
                        ("referencia",   "referencia"),
                        ("sucursal",     "sucursal")]:
        txt = _norm(f.get(campo, ""))
        if txt and col in out.columns:
            out = out[out[col].fillna("").apply(_norm).str.contains(txt, na=False)]

    return out


# ─── Formateo para visualización ─────────────────────────────────────────────
def _fmt_bob(val, col):
    try:
        v = float(val)
        if col in ("debito_bob", "credito_bob") and v == 0.0:
            return ""
        return fmt_amount(v, "BOB")
    except (TypeError, ValueError):
        return ""


def _fmt_usd(val, col):
    try:
        v = float(val)
        if col in ("debito_usd", "credito_usd") and v == 0.0:
            return ""
        return fmt_amount(v, "USD")
    except (TypeError, ValueError):
        return ""


def _format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "fecha" in d.columns:
        d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
    for col in ["debito_bob", "credito_bob", "importe_bob"]:
        if col in d.columns:
            d[col] = d[col].apply(lambda v, c=col: _fmt_bob(v, c))
    for col in ["debito_usd", "credito_usd", "importe_usd"]:
        if col in d.columns:
            d[col] = d[col].apply(lambda v, c=col: _fmt_usd(v, c))
    return d


# ─── Función principal ────────────────────────────────────────────────────────
def render_preview(df: pd.DataFrame, moneda: str = "Sin definir") -> None:
    """Muestra la tabla de movimientos con filtros avanzados y métricas."""
    if df.empty:
        st.info("No hay movimientos para mostrar.")
        return

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df_valido = df.dropna(subset=["fecha"]).copy()

    if df_valido.empty:
        st.warning("Los movimientos cargados no tienen fechas válidas.")
        st.dataframe(df.head(20), use_container_width=True)
        return

    # Pre-compute search text once for performance
    df_valido["_search_text"] = _build_search_col(df_valido)

    st.subheader("Vista previa de movimientos")

    # ── Buscador general ─────────────────────────────────────────────────
    buscar = st.text_input(
        "🔍 Buscar movimiento",
        placeholder="Empresa, banco, cuenta, fecha, beneficiario, descripción, referencia, sucursal…",
        key="preview_buscar",
    )

    # ── Filtros avanzados ────────────────────────────────────────────────
    with st.expander("⚙ Filtros avanzados", expanded=False):
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.markdown("**Identificación**")
            bancos_opts   = ["Todos"] + sorted(df_valido["banco"].dropna().unique().tolist())
            cuentas_opts  = ["Todas"] + sorted(df_valido["cuenta"].dropna().unique().tolist()) if "cuenta" in df_valido.columns else ["Todas"]
            emp_opts      = ["Todas"] + sorted(df_valido["empresa"].dropna().unique().tolist()) if "empresa" in df_valido.columns else ["Todas"]
            mon_opts      = ["Todas"] + sorted(df_valido["moneda"].dropna().unique().tolist()) if "moneda" in df_valido.columns else ["Todas"]

            banco_sel   = st.selectbox("Banco",   bancos_opts,  key="prev_banco")
            cuenta_sel  = st.selectbox("Cuenta",  cuentas_opts, key="prev_cuenta")
            empresa_sel = st.selectbox("Empresa", emp_opts,     key="prev_empresa")
            moneda_sel  = st.selectbox("Moneda",  mon_opts,     key="prev_moneda")

        with c2:
            st.markdown("**Fechas**")
            fecha_min = df_valido["fecha"].min().date()
            fecha_max = df_valido["fecha"].max().date()
            fecha_desde = st.date_input(
                "Fecha desde", value=fecha_min,
                min_value=fecha_min, max_value=fecha_max, key="prev_fd",
            )
            fecha_hasta = st.date_input(
                "Fecha hasta", value=fecha_max,
                min_value=fecha_min, max_value=fecha_max, key="prev_fh",
            )
            st.markdown("**Tipo de movimiento**")
            tipo_mov = st.selectbox(
                "Tipo", ["Todos", "Débitos (egresos)", "Créditos (ingresos)"],
                key="prev_tipo",
            )

        with c3:
            st.markdown("**Monto**")
            modo_monto = st.radio(
                "Modo", ["Rango", "Exacto"],
                key="prev_modo_monto", horizontal=True,
            )
            if modo_monto == "Rango":
                monto_min    = st.number_input("Desde", min_value=0.0, value=0.0, step=1.0, key="prev_mmin", format="%.2f")
                monto_max    = st.number_input("Hasta", min_value=0.0, value=0.0, step=1.0, key="prev_mmax", format="%.2f")
                monto_exacto = None
                tolerancia   = 0.01
            else:
                monto_exacto = st.number_input("Monto exacto", min_value=0.0, value=0.0, step=0.01, key="prev_mexacto", format="%.2f")
                tolerancia   = st.number_input("Tolerancia ±", min_value=0.0, value=0.01, step=0.01, key="prev_tol", format="%.2f")
                monto_min    = None
                monto_max    = None
            st.caption("Busca en Débito/Crédito/Importe Bs y USD por valor absoluto.")

        with c4:
            st.markdown("**Texto por campo**")
            benef_q = st.text_input("Beneficiario / Ordenante", key="prev_benef")
            ref_q   = st.text_input("Referencia",               key="prev_ref")
            suc_q   = st.text_input("Sucursal",                 key="prev_suc")

    # ── Construir filtros activos ─────────────────────────────────────────
    filters = {
        "buscar":       buscar,
        "banco":        banco_sel,
        "cuenta":       cuenta_sel,
        "empresa":      empresa_sel,
        "moneda":       moneda_sel,
        "fecha_desde":  fecha_desde,
        "fecha_hasta":  fecha_hasta,
        "tipo_mov":     tipo_mov,
        "monto_min":    monto_min,
        "monto_max":    monto_max,
        "monto_exacto": monto_exacto,
        "tolerancia":   tolerancia,
        "beneficiario": benef_q,
        "referencia":   ref_q,
        "sucursal":     suc_q,
    }

    filtered = _apply_filters(df_valido, filters)

    # ── Métricas post-filtrado ────────────────────────────────────────────
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

    st.caption(f"Mostrando **{len(filtered):,}** de **{len(df_valido):,}** movimientos.")
    st.divider()

    # ── Tabla principal con encabezado estándar ───────────────────────────
    display_df = _format_for_display(filtered)
    visible = [c for c in _DISPLAY_COLS if c in display_df.columns]
    st.dataframe(
        display_df[visible].rename(columns=_RENAME),
        use_container_width=True,
        hide_index=True,
    )

    # ── Descargar resultados filtrados ────────────────────────────────────
    if not filtered.empty:
        dl_raw = filtered[[c for c in _DISPLAY_COLS if c in filtered.columns]].copy()
        if "fecha" in dl_raw.columns:
            dl_raw["fecha"] = pd.to_datetime(dl_raw["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
        dl_raw = dl_raw.rename(columns=_RENAME)

        st.download_button(
            "⬇ Descargar resultados filtrados",
            data=_to_excel_bytes(dl_raw),
            file_name="movimientos_filtrados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
