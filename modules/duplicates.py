"""
Módulo de detección de duplicados con criterios de riesgo.

Detecta posibles transacciones duplicadas usando scoring 0-100 basado en:
- Mismo importe (base)
- Misma referencia (+30)
- Proximidad de fechas (+20/12/8/5)
- Similitud de descripción (+15/8/3)
- Misma cuenta (+5)
- Traspasos: importe opuesto, misma fecha, mismo valor absoluto

Riesgo: Alto >=85 | Medio >=65 | Bajo >=45
"""

import difflib
import io

import pandas as pd
import streamlit as st

from core.schema import fmt_amount

ESTADOS = [
    "Pendiente",
    "Confirmado duplicado",
    "No es duplicado",
    "Traspaso",
    "Requiere respaldo",
    "Débito no autorizado",
    "Regularizado",
]


# ─────────────────────────────────────────────────────────────────────────────
# Detection engine
# ─────────────────────────────────────────────────────────────────────────────

def _text_sim(s1: str, s2: str) -> float:
    """Ratio de similitud entre dos cadenas (0.0 – 1.0)."""
    if not s1 or not s2:
        return 0.0
    return difflib.SequenceMatcher(None, str(s1).lower(), str(s2).lower()).ratio()


def _score_pair(r1: pd.Series, r2: pd.Series, max_days: int) -> tuple:
    """
    Calcula (score, motivo, tipo_alerta) para un par de movimientos.
    Requiere que r1 e r2 ya tengan el mismo importe (redondeado).
    """
    score = 0
    motivos = []

    imp1 = float(r1.get("importe", 0) or 0)
    imp2 = float(r2.get("importe", 0) or 0)

    # ── Traspaso: signo opuesto, mismo valor absoluto ──────────────────────
    if abs(imp1) > 0 and abs(abs(imp1) - abs(imp2)) < 0.01 and (imp1 * imp2) < 0:
        fecha1 = pd.to_datetime(r1.get("fecha"), errors="coerce")
        fecha2 = pd.to_datetime(r2.get("fecha"), errors="coerce")
        if pd.notna(fecha1) and pd.notna(fecha2):
            diff_days = abs((fecha1 - fecha2).days)
            if diff_days <= max_days:
                return 65, "Traspaso: importe opuesto mismo valor", "Traspaso"

    # ── Base: mismo importe ────────────────────────────────────────────────
    if abs(imp1 - imp2) < 0.01:
        score += 50
        motivos.append("Mismo importe")

    # ── Referencia idéntica ────────────────────────────────────────────────
    ref1 = str(r1.get("referencia", "") or "").strip()
    ref2 = str(r2.get("referencia", "") or "").strip()
    if ref1 and ref2 and ref1 != "nan" and ref2 != "nan" and ref1 == ref2:
        score += 30
        motivos.append("Misma referencia")

    # ── Proximidad de fechas ───────────────────────────────────────────────
    fecha1 = pd.to_datetime(r1.get("fecha"), errors="coerce")
    fecha2 = pd.to_datetime(r2.get("fecha"), errors="coerce")
    if pd.notna(fecha1) and pd.notna(fecha2):
        diff_days = abs((fecha1 - fecha2).days)
        if diff_days == 0:
            score += 20
            motivos.append("Misma fecha")
        elif diff_days == 1:
            score += 12
            motivos.append("Fecha +-1 dia")
        elif diff_days == 2:
            score += 8
            motivos.append("Fecha +-2 dias")
        elif diff_days == 3:
            score += 5
            motivos.append("Fecha +-3 dias")

    # ── Similitud de descripción ───────────────────────────────────────────
    desc1 = str(r1.get("descripcion", "") or "")
    desc2 = str(r2.get("descripcion", "") or "")
    sim = _text_sim(desc1, desc2)
    if sim >= 0.85:
        score += 15
        motivos.append(f"Descripcion similar ({sim:.0%})")
    elif sim >= 0.60:
        score += 8
        motivos.append(f"Descripcion parcial ({sim:.0%})")
    elif sim >= 0.40:
        score += 3
        motivos.append(f"Descripcion leve ({sim:.0%})")

    # ── Misma cuenta ───────────────────────────────────────────────────────
    cta1 = str(r1.get("cuenta", "") or "").strip()
    cta2 = str(r2.get("cuenta", "") or "").strip()
    if cta1 and cta2 and cta1 == cta2 and cta1 not in ("nan", "No identificada"):
        score += 5
        motivos.append("Misma cuenta")

    # ── Mismo archivo (carga duplicada) ───────────────────────────────────
    arch1 = str(r1.get("archivo", "") or "").strip()
    arch2 = str(r2.get("archivo", "") or "").strip()
    if arch1 and arch2 and arch1 == arch2 and arch1 != "nan":
        motivos.append("Mismo archivo origen")

    # ── Tipo de alerta ─────────────────────────────────────────────────────
    if score >= 85:
        tipo = "Duplicado probable"
    elif score >= 65:
        tipo = "Posible duplicado"
    else:
        tipo = "Revisar"

    return min(score, 100), "; ".join(motivos) if motivos else "Sin criterio", tipo


def detect_duplicates(
    df: pd.DataFrame,
    max_days: int = 3,
    min_score: int = 50,
) -> pd.DataFrame:
    """
    Detecta posibles duplicados en df.

    Estrategia O(N*k2): agrupa por importe redondeado a 2 decimales,
    luego evalua pares dentro de cada grupo.

    Devuelve DataFrame con columnas de ambos movimientos + score + motivo + tipo.
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df = df.dropna(subset=["fecha"])
    if df.empty:
        return pd.DataFrame()

    df["_imp_round"] = pd.to_numeric(df["importe"], errors="coerce").round(2)
    df["_abs_round"] = df["_imp_round"].abs()

    # Agrupar por valor absoluto redondeado (cubre traspasos también)
    groups = df.groupby("_abs_round", sort=False)

    pairs = []
    for _key, grp in groups:
        if len(grp) < 2:
            continue
        idx = grp.index.tolist()
        for i in range(len(idx)):
            for j in range(i + 1, len(idx)):
                r1 = grp.loc[idx[i]]
                r2 = grp.loc[idx[j]]

                # Pre-filtro rapido por fecha
                f1 = r1["fecha"]
                f2 = r2["fecha"]
                if pd.notna(f1) and pd.notna(f2):
                    days_diff = abs((f1 - f2).days)
                    if days_diff > max_days:
                        # Solo continuar si es posible traspaso
                        imp1 = float(r1.get("importe", 0) or 0)
                        imp2 = float(r2.get("importe", 0) or 0)
                        if not (abs(abs(imp1) - abs(imp2)) < 0.01 and (imp1 * imp2) < 0):
                            continue

                score, motivo, tipo_alerta = _score_pair(r1, r2, max_days)
                if score < min_score:
                    continue

                riesgo = "Alto" if score >= 85 else ("Medio" if score >= 65 else "Bajo")

                pairs.append({
                    "idx_a":         idx[i],
                    "fecha_a":       r1.get("fecha"),
                    "banco_a":       r1.get("banco", ""),
                    "cuenta_a":      r1.get("cuenta", ""),
                    "moneda_a":      r1.get("moneda", "Sin definir"),
                    "descripcion_a": r1.get("descripcion", ""),
                    "importe_a":     r1.get("importe", 0),
                    "referencia_a":  r1.get("referencia", ""),
                    "archivo_a":     r1.get("archivo", ""),
                    "idx_b":         idx[j],
                    "fecha_b":       r2.get("fecha"),
                    "banco_b":       r2.get("banco", ""),
                    "cuenta_b":      r2.get("cuenta", ""),
                    "moneda_b":      r2.get("moneda", "Sin definir"),
                    "descripcion_b": r2.get("descripcion", ""),
                    "importe_b":     r2.get("importe", 0),
                    "referencia_b":  r2.get("referencia", ""),
                    "archivo_b":     r2.get("archivo", ""),
                    "score":         score,
                    "riesgo":        riesgo,
                    "tipo_alerta":   tipo_alerta,
                    "motivo":        motivo,
                    "estado":        "Pendiente",
                    "comentario":    "",
                })

    if not pairs:
        return pd.DataFrame()

    result = pd.DataFrame(pairs)
    result = result.sort_values(["score", "riesgo"], ascending=[False, True]).reset_index(drop=True)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Excel export
# ─────────────────────────────────────────────────────────────────────────────

def _export_duplicates_excel(
    df_pairs: pd.DataFrame,
    df_origen: pd.DataFrame,
    params: dict,
) -> bytes:
    buf = io.BytesIO()

    traspasos  = df_pairs[df_pairs["tipo_alerta"] == "Traspaso"].copy()
    duplicados = df_pairs[df_pairs["tipo_alerta"] != "Traspaso"].copy()

    resumen_rows = [
        {"Metrica": "Total pares analizados",      "Valor": len(df_pairs)},
        {"Metrica": "Riesgo Alto",                 "Valor": int((df_pairs["riesgo"] == "Alto").sum())},
        {"Metrica": "Riesgo Medio",                "Valor": int((df_pairs["riesgo"] == "Medio").sum())},
        {"Metrica": "Riesgo Bajo",                 "Valor": int((df_pairs["riesgo"] == "Bajo").sum())},
        {"Metrica": "Traspasos detectados",        "Valor": len(traspasos)},
        {"Metrica": "Duplicados (excl. traspaso)", "Valor": len(duplicados)},
        {"Metrica": "Dias max entre operaciones",  "Valor": params.get("max_days", 3)},
        {"Metrica": "Score minimo",                "Valor": params.get("min_score", 50)},
    ]
    df_resumen = pd.DataFrame(resumen_rows)

    def _fmt_fecha(d):
        try:
            return pd.to_datetime(d).strftime("%d/%m/%Y")
        except Exception:
            return str(d)

    for col in ("fecha_a", "fecha_b"):
        for target in (duplicados, traspasos, df_pairs):
            if col in target.columns:
                target[col] = target[col].apply(_fmt_fecha)

    df_params = pd.DataFrame([
        {"Parametro": "Dias maximos entre operaciones", "Valor": params.get("max_days", 3)},
        {"Parametro": "Score minimo de deteccion",      "Valor": params.get("min_score", 50)},
        {"Parametro": "Total movimientos analizados",   "Valor": len(df_origen)},
    ])

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_resumen.to_excel(writer, index=False, sheet_name="Resumen")
        if not duplicados.empty:
            duplicados.to_excel(writer, index=False, sheet_name="Posibles duplicados")
        else:
            pd.DataFrame({"Info": ["Sin duplicados detectados"]}).to_excel(
                writer, index=False, sheet_name="Posibles duplicados"
            )
        if not traspasos.empty:
            traspasos.to_excel(writer, index=False, sheet_name="Traspasos")
        else:
            pd.DataFrame({"Info": ["Sin traspasos detectados"]}).to_excel(
                writer, index=False, sheet_name="Traspasos"
            )
        df_params.to_excel(writer, index=False, sheet_name="Parametros")
        if not df_origen.empty:
            df_export = df_origen.copy()
            if "fecha" in df_export.columns:
                df_export["fecha"] = pd.to_datetime(df_export["fecha"], errors="coerce").dt.strftime("%d/%m/%Y")
            df_export.to_excel(writer, index=False, sheet_name="Movimientos origen")

    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────

def render_duplicates(df: pd.DataFrame) -> None:
    """Punto de entrada principal."""
    try:
        _render_duplicates_body(df)
    except Exception as exc:
        st.error(f"Error en el módulo de duplicados: {exc}")
        import traceback
        st.code(traceback.format_exc())


def _render_duplicates_body(df: pd.DataFrame) -> None:
    st.subheader("Detección de duplicados")

    if df.empty:
        st.info("Carga al menos un extracto para detectar duplicados.")
        st.caption("Versión: duplicados por criterios de riesgo")
        return

    df_work = df.copy()
    df_work.columns = [str(c).strip().lower() for c in df_work.columns]

    # ── Parámetros de detección ───────────────────────────────────────────
    with st.expander("Parámetros de detección", expanded=False):
        p1, p2 = st.columns(2)
        with p1:
            max_days = st.slider(
                "Días máximos entre operaciones",
                min_value=0, max_value=10, value=3,
                key="dup_max_days",
            )
        with p2:
            min_score = st.slider(
                "Score mínimo para reportar (0–100)",
                min_value=30, max_value=90, value=50,
                key="dup_min_score",
            )

    buscar = st.button("Buscar duplicados", type="primary", key="dup_buscar")

    if buscar or "dup_results" not in st.session_state:
        with st.spinner("Analizando movimientos..."):
            st.session_state["dup_results"] = detect_duplicates(
                df_work,
                max_days=max_days,
                min_score=min_score,
            )
            st.session_state["dup_params"] = {"max_days": max_days, "min_score": min_score}

    df_pairs: pd.DataFrame = st.session_state.get("dup_results", pd.DataFrame())
    params = st.session_state.get("dup_params", {"max_days": max_days, "min_score": min_score})

    # ── Métricas ──────────────────────────────────────────────────────────
    if df_pairs.empty:
        st.success("No se encontraron posibles duplicados con los parámetros actuales.")
        st.caption("Versión: duplicados por criterios de riesgo")
        return

    n_alto  = int((df_pairs["riesgo"] == "Alto").sum())
    n_medio = int((df_pairs["riesgo"] == "Medio").sum())
    n_bajo  = int((df_pairs["riesgo"] == "Bajo").sum())
    n_tras  = int((df_pairs["tipo_alerta"] == "Traspaso").sum())
    n_pend  = int((df_pairs["estado"] == "Pendiente").sum())
    n_total = len(df_pairs)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total pares",        f"{n_total:,}")
    m2.metric("Riesgo Alto",        f"{n_alto:,}")
    m3.metric("Riesgo Medio",       f"{n_medio:,}")
    m4.metric("Riesgo Bajo",        f"{n_bajo:,}")
    m5.metric("Traspasos",          f"{n_tras:,}")
    m6.metric("Pendientes revisar", f"{n_pend:,}")

    st.divider()

    # ── Filtros ───────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            riesgos_opts = ["Todos"] + sorted(df_pairs["riesgo"].dropna().unique().tolist())
            riesgo_sel = st.selectbox("Riesgo", riesgos_opts, key="dup_f_riesgo")
        with f2:
            alertas_opts = ["Todos"] + sorted(df_pairs["tipo_alerta"].dropna().unique().tolist())
            alerta_sel = st.selectbox("Tipo alerta", alertas_opts, key="dup_f_alerta")
        with f3:
            estados_opts = ["Todos"] + ESTADOS
            estado_sel = st.selectbox("Estado", estados_opts, key="dup_f_estado")
        with f4:
            bancos_raw = (
                pd.concat([df_pairs["banco_a"], df_pairs["banco_b"]])
                .dropna().unique().tolist()
            )
            banco_sel = st.selectbox("Banco", ["Todos"] + sorted(bancos_raw), key="dup_f_banco")

        f5, f6, f7 = st.columns(3)
        with f5:
            monedas_raw = (
                pd.concat([df_pairs["moneda_a"], df_pairs["moneda_b"]])
                .dropna().unique().tolist()
            )
            moneda_sel = st.selectbox("Moneda", ["Todas"] + sorted(monedas_raw), key="dup_f_moneda")
        with f6:
            imp_min = st.number_input(
                "Importe mínimo (abs)", min_value=0.0, value=0.0, step=100.0, key="dup_f_imp_min"
            )
        with f7:
            imp_max_default = float(
                pd.to_numeric(df_pairs["importe_a"], errors="coerce").abs().max() or 0
            )
            imp_max = st.number_input(
                "Importe máximo (abs)", min_value=0.0, value=imp_max_default, step=100.0, key="dup_f_imp_max"
            )

    # ── Aplicar filtros ───────────────────────────────────────────────────
    filtered = df_pairs.copy()

    if riesgo_sel != "Todos":
        filtered = filtered[filtered["riesgo"] == riesgo_sel]
    if alerta_sel != "Todos":
        filtered = filtered[filtered["tipo_alerta"] == alerta_sel]
    if estado_sel != "Todos":
        filtered = filtered[filtered["estado"] == estado_sel]
    if banco_sel != "Todos":
        filtered = filtered[
            (filtered["banco_a"] == banco_sel) | (filtered["banco_b"] == banco_sel)
        ]
    if moneda_sel != "Todas":
        filtered = filtered[
            (filtered["moneda_a"] == moneda_sel) | (filtered["moneda_b"] == moneda_sel)
        ]
    imp_a_abs = pd.to_numeric(filtered["importe_a"], errors="coerce").abs()
    filtered = filtered[(imp_a_abs >= imp_min) & (imp_a_abs <= imp_max)]

    st.write(f"Mostrando **{len(filtered):,}** de **{n_total:,}** pares detectados.")

    # ── Preparar tabla display ────────────────────────────────────────────
    display_cols = [
        "score", "riesgo", "tipo_alerta", "motivo",
        "fecha_a", "banco_a", "cuenta_a", "moneda_a", "descripcion_a", "importe_a", "referencia_a", "archivo_a",
        "fecha_b", "banco_b", "cuenta_b", "moneda_b", "descripcion_b", "importe_b", "referencia_b", "archivo_b",
        "estado", "comentario",
    ]
    display_cols = [c for c in display_cols if c in filtered.columns]
    display_df = filtered[display_cols].copy()

    for fc in ("fecha_a", "fecha_b"):
        if fc in display_df.columns:
            display_df[fc] = pd.to_datetime(display_df[fc], errors="coerce").dt.strftime("%d/%m/%Y")

    def _fmt_imp(row, col_imp, col_mon):
        try:
            v   = float(row[col_imp])
            mon = str(row.get(col_mon) or "Sin definir")
            return fmt_amount(v, mon)
        except Exception:
            return str(row.get(col_imp, ""))

    if "importe_a" in display_df.columns:
        display_df["importe_a"] = filtered.apply(lambda r: _fmt_imp(r, "importe_a", "moneda_a"), axis=1)
    if "importe_b" in display_df.columns:
        display_df["importe_b"] = filtered.apply(lambda r: _fmt_imp(r, "importe_b", "moneda_b"), axis=1)

    rename_display = {
        "score":         "Score",
        "riesgo":        "Riesgo",
        "tipo_alerta":   "Tipo alerta",
        "motivo":        "Motivo",
        "fecha_a":       "Fecha A",
        "banco_a":       "Banco A",
        "cuenta_a":      "Cuenta A",
        "moneda_a":      "Moneda A",
        "descripcion_a": "Descripción A",
        "importe_a":     "Importe A",
        "referencia_a":  "Referencia A",
        "archivo_a":     "Archivo A",
        "fecha_b":       "Fecha B",
        "banco_b":       "Banco B",
        "cuenta_b":      "Cuenta B",
        "moneda_b":      "Moneda B",
        "descripcion_b": "Descripción B",
        "importe_b":     "Importe B",
        "referencia_b":  "Referencia B",
        "archivo_b":     "Archivo B",
        "estado":        "Estado",
        "comentario":    "Comentario",
    }
    display_df = display_df.rename(columns={k: v for k, v in rename_display.items() if k in display_df.columns})

    # ── Tabla editable ────────────────────────────────────────────────────
    edited = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        disabled=[c for c in display_df.columns if c not in ("Estado", "Comentario")],
        column_config={
            "Estado": st.column_config.SelectboxColumn(
                "Estado",
                options=ESTADOS,
                required=True,
            ),
            "Score": st.column_config.NumberColumn("Score", format="%d"),
        },
        key="dup_editor",
    )

    # Propagar ediciones de vuelta a session_state
    if edited is not None and not edited.empty:
        idx_filtered = filtered.index.tolist()
        for i, orig_idx in enumerate(idx_filtered):
            if i < len(edited):
                st.session_state["dup_results"].at[orig_idx, "estado"]     = edited.iloc[i].get("Estado",     "Pendiente")
                st.session_state["dup_results"].at[orig_idx, "comentario"] = edited.iloc[i].get("Comentario", "")

    st.divider()

    # ── Exportar ──────────────────────────────────────────────────────────
    st.subheader("Exportar resultados")
    if st.button("Preparar Excel", key="dup_export_btn"):
        with st.spinner("Generando Excel..."):
            excel_bytes = _export_duplicates_excel(
                df_pairs=st.session_state["dup_results"].copy(),
                df_origen=df_work,
                params=params,
            )
        st.download_button(
            label="Descargar Excel de duplicados",
            data=excel_bytes,
            file_name="duplicados_detectados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dup_download",
        )

    st.caption("Versión: duplicados por criterios de riesgo")
