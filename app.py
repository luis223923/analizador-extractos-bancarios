"""
Analizador de Extractos Bancarios para Tesorería
Punto de entrada principal de la aplicación Streamlit.
"""

import streamlit as st
import pandas as pd

from core.loader import load_file, reload_excel
from core.normalizer import normalize, normalize_with_mapping, diagnose, get_registered_banks
from core.schema import empty_standard_df
from modules.preview import render_preview
from modules.classifier import render_classifier
from modules.balances import render_balances
from modules.duplicates import render_duplicates
from modules.exporter import render_exporter

# ─── Configuración de página ─────────────────────────────────────────────
st.set_page_config(
    page_title="Analizador de Extractos Bancarios",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Estado global de sesión ─────────────────────────────────────────────
if "df_consolidado" not in st.session_state:
    st.session_state.df_consolidado = empty_standard_df()

if "archivos_cargados" not in st.session_state:
    st.session_state.archivos_cargados = []   # [(filename, parser_name, n_rows)]

# Archivos que no se pudieron parsear automáticamente y esperan mapeo manual.
# Cada elemento: {filename, raw_bytes, ext, sheets, selected_sheet, header_row, df_raw, diagnostic}
if "cola_mapeo" not in st.session_state:
    st.session_state.cola_mapeo = []


# ─── Funciones de renderizado ─────────────────────────────────────────────

def render_welcome():
    st.markdown(
        """
        ### Bienvenido

        Esta herramienta consolida extractos bancarios de distintos bancos,
        analiza movimientos y prepara informes de Tesorería, **sin instalar nada**.

        **Cómo empezar:**
        1. Abre el panel lateral (↖) y sube uno o varios archivos Excel o CSV.
        2. Pulsa **Procesar archivos**.
        3. Si el sistema reconoce el formato → los datos aparecen de inmediato.
        4. Si no lo reconoce → verás una pantalla de mapeo para asignar columnas manualmente.
        """
    )
    with st.expander("¿Qué estructura debe tener mi archivo?"):
        st.markdown(
            """
            El sistema detecta automáticamente las columnas. Acepta nombres como:

            | Campo | Nombres aceptados |
            |-------|------------------|
            | Fecha | Fecha, F.Valor, Fecha Movimiento, Fecha Op., Date… |
            | Descripción | Concepto, Glosa, Detalle, Movimiento, Narración… |
            | Importe | Importe, Monto, Cargo/Abono, Amount… |
            | Débito | Débito, Debe, Cargo, Egreso, Retiro, Withdrawal… |
            | Crédito | Crédito, Haber, Abono, Ingreso, Depósito, Credit… |
            | Saldo | Saldo, Balance, Saldo Disponible, Saldo Contable… |
            | Referencia | Referencia, Folio, Voucher, N° Op., Comprobante… |

            Si el archivo tiene encabezados en filas inferiores o varias hojas,
            el sistema los detecta automáticamente. Si aun así falla, te pedirá
            que asignes las columnas manualmente.
            """
        )


def render_main_tabs(df: pd.DataFrame):
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Vista previa", "Clasificación", "Saldos", "Duplicados", "Exportar",
    ])
    with tab1: render_preview(df)
    with tab2: render_classifier(df)
    with tab3: render_balances(df)
    with tab4: render_duplicates(df)
    with tab5: render_exporter(df)


def render_mapping_ui(pending: dict):
    """
    Pantalla de mapeo manual para un archivo que no se pudo parsear automáticamente.
    Permite cambiar hoja y fila de encabezado, ver diagnóstico y asignar columnas.
    """
    filename  = pending["filename"]
    raw_bytes = pending["raw_bytes"]
    ext       = pending["ext"]
    sheets    = pending["sheets"]
    diag      = pending["diagnostic"]
    df_raw    = pending["df_raw"]
    total_pendientes = len(st.session_state.cola_mapeo)

    st.subheader("Mapeo manual de columnas")
    st.markdown(
        f"El archivo **{filename}** no pudo procesarse automáticamente. "
        "Asigna las columnas para que el sistema pueda leerlo."
    )
    if total_pendientes > 1:
        st.caption(f"Archivo 1 de {total_pendientes} pendientes de mapeo.")

    # ── Ajuste de hoja y fila de encabezado (solo Excel) ──────────────────
    if ext in ("xlsx", "xls") and sheets:
        st.markdown("#### Ajustar lectura del archivo")
        col_s, col_h, col_btn = st.columns([3, 2, 2])
        with col_s:
            sheet_sel = st.selectbox(
                "Hoja del Excel",
                sheets,
                index=sheets.index(pending["selected_sheet"])
                      if pending["selected_sheet"] in sheets else 0,
                key="mapeo_sheet",
            )
        with col_h:
            header_sel = st.number_input(
                "Fila de encabezado (0 = primera fila)",
                min_value=0, max_value=50,
                value=int(pending["header_row"]),
                step=1,
                key="mapeo_header",
            )
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Recargar con estos ajustes", use_container_width=True):
                try:
                    new_df = reload_excel(raw_bytes, filename, sheet_sel, int(header_sel))
                    pending["selected_sheet"] = sheet_sel
                    pending["header_row"] = int(header_sel)
                    pending["df_raw"] = new_df
                    pending["diagnostic"] = diagnose(new_df)
                    st.session_state.cola_mapeo[0] = pending
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al recargar: {e}")

    # ── Panel de diagnóstico ──────────────────────────────────────────────
    labels_campo = {
        "fecha": "Fecha", "descripcion": "Descripción",
        "debito": "Débito", "credito": "Crédito",
        "importe": "Importe", "saldo": "Saldo",
        "referencia": "Referencia", "cuenta": "Cuenta",
    }

    with st.expander("Diagnóstico del archivo", expanded=True):
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.write(f"**Filas leídas:** {diag['n_filas']}")
            st.write(f"**Columnas encontradas:** {len(diag['columnas_disponibles'])}")
            if diag["columnas_detectadas"]:
                st.write("**Detección automática:**")
                for k, v in diag["columnas_detectadas"].items():
                    st.markdown(f"&nbsp;&nbsp;✓ **{labels_campo.get(k, k)}** → `{v}`")
        with col_d2:
            if diag["columnas_faltantes"]:
                st.write("**No detectadas automáticamente:**")
                for k in diag["columnas_faltantes"]:
                    st.markdown(f"&nbsp;&nbsp;✗ {labels_campo.get(k, k)}")
            else:
                st.success("Todas las columnas fueron detectadas.")

        st.write("**Primeras 10 filas del archivo:**")
        st.dataframe(diag["muestra"], use_container_width=True, hide_index=True)

    # ── Selectores de mapeo ───────────────────────────────────────────────
    st.markdown("#### Asigna las columnas")
    st.info(
        "Selecciona qué columna del archivo corresponde a cada campo. "
        "Usa **(no usar)** para campos que no existen en tu archivo. "
        "**Opción A:** selecciona Importe si la columna ya tiene valores positivos y negativos. "
        "**Opción B:** selecciona Débito y Crédito si vienen en columnas separadas."
    )

    detected = diag["columnas_detectadas"]
    opciones = ["(no usar)"] + list(df_raw.columns)

    def default_idx(campo: str) -> int:
        col = detected.get(campo)
        return opciones.index(col) if (col and col in opciones) else 0

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Campos de identificación**")
        c_fecha = st.selectbox("Fecha *",              opciones, index=default_idx("fecha"),       key="map_fecha")
        c_desc  = st.selectbox("Descripción / Glosa",  opciones, index=default_idx("descripcion"), key="map_desc")
        c_saldo = st.selectbox("Saldo",                opciones, index=default_idx("saldo"),       key="map_saldo")
        c_ref   = st.selectbox("Referencia / Folio",   opciones, index=default_idx("referencia"),  key="map_ref")
    with col_r:
        st.markdown("**Importe — elige A o B (no ambas)**")
        st.markdown("*Opción A: columna única con signo*")
        c_imp   = st.selectbox("Importe (con signo)",        opciones, index=default_idx("importe"), key="map_imp")
        st.markdown("*Opción B: columnas separadas*")
        c_deb   = st.selectbox("Débito / Cargo / Egreso",   opciones, index=default_idx("debito"),  key="map_deb")
        c_cred  = st.selectbox("Crédito / Abono / Ingreso", opciones, index=default_idx("credito"), key="map_cred")

    st.divider()

    col_ok, col_skip = st.columns([3, 1])
    with col_ok:
        if st.button("Confirmar y procesar", type="primary", use_container_width=True):
            def resolve(v):
                return v if v != "(no usar)" else None

            mapping = {
                "fecha":       resolve(c_fecha),
                "descripcion": resolve(c_desc),
                "importe":     resolve(c_imp),
                "debito":      resolve(c_deb),
                "credito":     resolve(c_cred),
                "saldo":       resolve(c_saldo),
                "referencia":  resolve(c_ref),
            }
            try:
                df_std, parser_name = normalize_with_mapping(df_raw, mapping, filename)
                st.session_state.df_consolidado = pd.concat(
                    [st.session_state.df_consolidado, df_std],
                    ignore_index=True,
                )
                st.session_state.archivos_cargados.append(
                    (filename, parser_name, len(df_std))
                )
                st.session_state.cola_mapeo.pop(0)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    with col_skip:
        if st.button("Descartar archivo", use_container_width=True):
            st.session_state.cola_mapeo.pop(0)
            st.rerun()

    # ── Mini-resumen de datos ya consolidados ─────────────────────────────
    if not st.session_state.df_consolidado.empty:
        n = len(st.session_state.df_consolidado)
        st.divider()
        st.caption(
            f"Ya tienes {n:,} movimientos consolidados de archivos anteriores. "
            "La vista completa aparecerá cuando termines el mapeo."
        )


# ─── Barra lateral ────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🏦 Extractos Bancarios")
    st.caption("Herramienta de Tesorería")
    st.divider()

    st.subheader("Cargar extractos")
    uploaded_files = st.file_uploader(
        "Selecciona archivos",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="Formatos soportados: Excel (.xlsx, .xls) y CSV (.csv)",
    )

    if uploaded_files:
        if st.button("Procesar archivos", type="primary", use_container_width=True):
            nuevos_frames = []
            errores = []
            necesitan_mapeo = 0

            progress = st.progress(0, text="Leyendo archivos…")
            for i, f in enumerate(uploaded_files):
                progress.progress(
                    (i + 1) / len(uploaded_files),
                    text=f"Procesando {f.name}…",
                )
                try:
                    info = load_file(f)
                    resultado = normalize(info.df_raw, info.filename)

                    if resultado is not None:
                        df_std, parser_name = resultado
                        nuevos_frames.append(df_std)
                        st.session_state.archivos_cargados.append(
                            (info.filename, parser_name, len(df_std))
                        )
                    else:
                        # Sin parser automático → mapeo manual
                        diag = diagnose(info.df_raw)
                        st.session_state.cola_mapeo.append({
                            "filename":       info.filename,
                            "raw_bytes":      info.raw_bytes,
                            "ext":            info.ext,
                            "sheets":         info.sheets,
                            "selected_sheet": info.selected_sheet,
                            "header_row":     info.header_row,
                            "df_raw":         info.df_raw,
                            "diagnostic":     diag,
                        })
                        necesitan_mapeo += 1

                except ValueError as e:
                    errores.append(f"**{f.name}**: {e}")

            progress.empty()

            if nuevos_frames:
                st.session_state.df_consolidado = pd.concat(
                    [st.session_state.df_consolidado, *nuevos_frames],
                    ignore_index=True,
                )
                st.success(f"✓ {len(nuevos_frames)} archivo(s) procesado(s).")

            if necesitan_mapeo:
                st.warning(
                    f"⚠ {necesitan_mapeo} archivo(s) requieren mapeo manual. "
                    "Revisa el área principal."
                )

            for err in errores:
                st.error(err)

    st.divider()

    if st.session_state.archivos_cargados:
        st.subheader("Archivos procesados")
        for fname, parser, n in st.session_state.archivos_cargados:
            st.markdown(f"- **{fname}** — {parser} ({n:,} mov.)")

        if st.button("Limpiar todo", use_container_width=True):
            st.session_state.df_consolidado = empty_standard_df()
            st.session_state.archivos_cargados = []
            st.session_state.cola_mapeo = []
            st.rerun()

    if st.session_state.cola_mapeo:
        n_pend = len(st.session_state.cola_mapeo)
        st.warning(f"⚠ {n_pend} archivo(s) pendientes de mapeo")

    st.divider()

    with st.expander("Bancos soportados"):
        for bank in get_registered_banks():
            st.markdown(f"- {bank}")
        st.caption(
            "El parser Genérico detecta automáticamente columnas de "
            "fecha e importe con nombres variados."
        )


# ─── Área principal ───────────────────────────────────────────────────────
cola = st.session_state.cola_mapeo
df   = st.session_state.df_consolidado

if cola:
    render_mapping_ui(cola[0])
elif not df.empty:
    render_main_tabs(df)
else:
    render_welcome()
