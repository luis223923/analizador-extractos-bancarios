"""
Analizador de Extractos Bancarios para Tesorería
Punto de entrada principal de la aplicación Streamlit.
"""

import streamlit as st
import pandas as pd

from core.loader import load_file
from core.normalizer import normalize, get_registered_banks
from core.schema import empty_standard_df
from modules.preview import render_preview
from modules.classifier import render_classifier
from modules.balances import render_balances
from modules.duplicates import render_duplicates
from modules.exporter import render_exporter

# ---------------------------------------------------------------------------
# Configuración de página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Analizador de Extractos Bancarios",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Estado global de sesión
# ---------------------------------------------------------------------------
if "df_consolidado" not in st.session_state:
    st.session_state.df_consolidado = empty_standard_df()

if "archivos_cargados" not in st.session_state:
    st.session_state.archivos_cargados = []  # [(filename, parser_name, n_rows)]


# ---------------------------------------------------------------------------
# Barra lateral — carga de archivos
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🏦 Extractos Bancarios")
    st.caption("Herramienta de Tesorería")
    st.divider()

    st.subheader("Cargar extractos")
    st.markdown(
        "Sube uno o varios extractos. El sistema detecta automáticamente "
        "el formato del banco."
    )

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

            progress = st.progress(0, text="Procesando...")
            for i, f in enumerate(uploaded_files):
                try:
                    df_raw, filename = load_file(f)
                    df_std, parser_name = normalize(df_raw, filename)
                    nuevos_frames.append(df_std)
                    st.session_state.archivos_cargados.append(
                        (filename, parser_name, len(df_std))
                    )
                except ValueError as e:
                    errores.append(f"**{f.name}**: {e}")
                progress.progress((i + 1) / len(uploaded_files), text=f"Procesando {f.name}…")

            progress.empty()

            if nuevos_frames:
                st.session_state.df_consolidado = pd.concat(
                    [st.session_state.df_consolidado, *nuevos_frames],
                    ignore_index=True,
                )
                st.success(f"✓ {len(nuevos_frames)} archivo(s) cargado(s) correctamente.")

            for err in errores:
                st.error(err)

    st.divider()

    # --- Archivos procesados ---
    if st.session_state.archivos_cargados:
        st.subheader("Archivos procesados")
        for fname, parser, n in st.session_state.archivos_cargados:
            st.markdown(f"- **{fname}** — {parser} ({n:,} mov.)")

        if st.button("Limpiar todo", use_container_width=True):
            st.session_state.df_consolidado = empty_standard_df()
            st.session_state.archivos_cargados = []
            st.rerun()

    st.divider()

    # --- Bancos soportados ---
    with st.expander("Bancos soportados"):
        for bank in get_registered_banks():
            st.markdown(f"- {bank}")
        st.caption("El parser Genérico funciona con cualquier Excel que tenga columnas de fecha e importe.")


# ---------------------------------------------------------------------------
# Contenido principal — pestañas de módulos
# ---------------------------------------------------------------------------
st.title("Analizador de Extractos Bancarios")

df = st.session_state.df_consolidado

if df.empty:
    # --- Pantalla de bienvenida ---
    st.markdown(
        """
        ### Bienvenido

        Esta herramienta te permite consolidar extractos bancarios de distintos bancos,
        analizar movimientos y preparar informes de Tesorería sin necesidad de instalar
        ningún programa.

        **Cómo empezar:**
        1. Abre el panel lateral (↖) y sube uno o varios archivos Excel o CSV.
        2. Pulsa **Procesar archivos**.
        3. Navega por las pestañas para analizar los datos.

        **Formatos soportados:** Excel (.xlsx, .xls) y CSV.

        **Bancos con detección automática:** BBVA y cualquier extracto con columnas
        identificables de fecha e importe.
        """
    )

    with st.expander("¿Qué estructura debe tener mi archivo?"):
        st.markdown(
            """
            El sistema detecta automáticamente las columnas. Para mejores resultados,
            tu archivo debe tener al menos:

            | Fecha | Descripción | Importe |
            |-------|-------------|---------|
            | 01/01/2025 | Transferencia recibida | 1.500,00 |
            | 02/01/2025 | Pago proveedor | -800,00 |

            Las columnas pueden llamarse de distintas formas:
            - **Fecha:** Fecha, Date, F.Valor, F.Operación, Día…
            - **Descripción:** Concepto, Descripcion, Detalle, Movimiento…
            - **Importe:** Importe, Monto, Cantidad, Amount, Cargo/Abono…
            """
        )
else:
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Vista previa",
        "Clasificación",
        "Saldos",
        "Duplicados",
        "Exportar",
    ])

    with tab1:
        render_preview(df)

    with tab2:
        render_classifier(df)

    with tab3:
        render_balances(df)

    with tab4:
        render_duplicates(df)

    with tab5:
        render_exporter(df)
