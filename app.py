"""
Analizador de Extractos Bancarios para Tesorería
Punto de entrada principal de la aplicación Streamlit.
"""

import re
import streamlit as st
import pandas as pd

from core.loader import load_file, reload_excel
from core.normalizer import normalize, normalize_with_mapping, diagnose, get_registered_banks
from core.schema import empty_standard_df, MONEDAS, TIPOS_CUENTA, EMPRESAS, BANCOS
from core.accounts import load_accounts
from modules.preview import render_preview
from modules.classifier import render_classifier
from modules.balances import render_balances
from modules.duplicates import render_duplicates
from modules.exporter import render_exporter

# ─── Configuración de página ─────────────────────────────────────────────────
st.set_page_config(
    page_title="Analizador de Extractos Bancarios",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Estado global de sesión ─────────────────────────────────────────────────
if "df_consolidado" not in st.session_state:
    st.session_state.df_consolidado = empty_standard_df()

if "archivos_cargados" not in st.session_state:
    st.session_state.archivos_cargados = []

if "cola_mapeo" not in st.session_state:
    st.session_state.cola_mapeo = []


# ─── Helpers de metadatos ─────────────────────────────────────────────────────

def _safe_key(filename: str, size: int) -> str:
    """Convierte nombre+tamaño en una clave segura para widgets de Streamlit."""
    return re.sub(r"[^a-zA-Z0-9]", "_", f"{filename}_{size}")


# ─── Detección automática desde nombre de archivo ────────────────────────────

def _detect_bank_from_filename(filename: str) -> str:
    """Deduce el banco desde el nombre del archivo."""
    name = filename.upper()
    if any(k in name for k in ["BMSC", "MERCANTIL"]):
        return "Banco Mercantil Santa Cruz"
    if "BNB" in name:
        return "BNB"
    if "BCP" in name:
        return "BCP"
    if any(k in name for k in ["BGA", "GANADERO"]):
        return "Banco Ganadero"
    if "BISA" in name:
        return "Banco Bisa"
    if any(k in name for k in ["UNION", "UNIÓN"]):
        return "Banco Unión"
    if "FIE" in name:
        return "Banco FIE"
    if any(k in name for k in ["ECONOMICO", "ECONÓMICO"]):
        return "Banco Económico"
    return "Genérico"


def _detect_moneda_from_filename(filename: str) -> str:
    """Deduce la moneda desde el nombre del archivo."""
    name = filename.upper()
    if any(k in name for k in ["USD", "DOLAR", "DOLARES", "$US"]):
        return "USD"
    if any(k in name for k in ["EUR", "EURO", "EUROS"]):
        return "EUR"
    if any(k in name for k in ["BOB", "BOLIVIANO", "BOLIVIANOS"]):
        return "BOB"
    return "BOB"


def _auto_metadata_from_filename(filename: str, cuentas: list) -> dict:
    """
    Genera metadatos automáticos a partir del nombre del archivo.
    Prioridad: maestro de cuentas → detección en nombre → valores por defecto.
    """
    banco_auto  = _detect_bank_from_filename(filename)
    moneda_auto = _detect_moneda_from_filename(filename)

    # Buscar coincidencia en el maestro de cuentas (por nombre de banco en el filename)
    for c in cuentas:
        banco_maestro = c.get("banco", "")
        if banco_maestro and banco_maestro.upper() in filename.upper():
            nc = c.get("nombre_corto") or f"{c.get('banco', '')} - {c.get('numero_cuenta', '')}"
            return {
                "empresa":       c.get("empresa", "Sin definir"),
                "banco":         c.get("banco", banco_auto),
                "cuenta":        c.get("numero_cuenta", "No identificada"),
                "nombre_corto":  nc or "Cuenta no identificada",
                "moneda":        c.get("moneda", moneda_auto),
                "tipo_cuenta":   c.get("tipo_cuenta", "Sin definir"),
                "observaciones": "",
            }

    nc = (
        f"{banco_auto} - No identificada"
        if banco_auto != "Genérico"
        else "Cuenta no identificada"
    )
    return {
        "empresa":       "Sin definir",
        "banco":         banco_auto,
        "cuenta":        "No identificada",
        "nombre_corto":  nc,
        "moneda":        moneda_auto,
        "tipo_cuenta":   "Sin definir",
        "observaciones": "",
    }


def _get_file_metadata(filename: str, size: int, cuentas: list) -> dict:
    """
    Devuelve metadatos del archivo.
    Si no está en modo edición → auto-detección desde nombre de archivo.
    Si está en modo edición → lee los widgets del formulario.
    """
    safe = _safe_key(filename, size)

    if not st.session_state.get(f"meta_{safe}_edit", False):
        return _auto_metadata_from_filename(filename, cuentas)

    master_key = f"meta_{safe}_master"
    master_sel = st.session_state.get(master_key, "Manual")
    nombres    = ["Manual"] + [c.get("nombre_corto", "") for c in cuentas]
    master_idx = nombres.index(master_sel) if master_sel in nombres else 0
    prefix     = f"meta_{safe}_idx{master_idx}"
    auto       = _auto_metadata_from_filename(filename, cuentas)
    return {
        "empresa":       st.session_state.get(f"{prefix}_empresa",       auto["empresa"]),
        "banco":         st.session_state.get(f"{prefix}_banco",         auto["banco"]),
        "cuenta":        st.session_state.get(f"{prefix}_cuenta",        auto["cuenta"]),
        "nombre_corto":  st.session_state.get(f"{prefix}_nombre_corto",  auto["nombre_corto"]),
        "moneda":        st.session_state.get(f"{prefix}_moneda",        auto["moneda"]),
        "tipo_cuenta":   st.session_state.get(f"{prefix}_tipo_cuenta",   auto["tipo_cuenta"]),
        "observaciones": st.session_state.get(f"{prefix}_observaciones", auto["observaciones"]),
    }


def _render_file_metadata_form(f, cuentas: list) -> None:
    """
    Muestra un resumen auto-detectado del archivo.
    Solo si el usuario activa 'Editar datos del extracto' se despliega el formulario completo.
    """
    safe = _safe_key(f.name, f.size)
    auto = _auto_metadata_from_filename(f.name, cuentas)

    # Resumen automático (siempre visible)
    col_a, col_b, col_c = st.columns(3)
    col_a.caption(f"Banco: **{auto['banco']}**")
    col_b.caption(f"Moneda: **{auto['moneda']}**")
    col_c.caption(f"Empresa: **{auto['empresa']}**")

    edit_key  = f"meta_{safe}_edit"
    show_edit = st.checkbox("Editar datos del extracto", key=edit_key, value=False)

    if not show_edit:
        return

    # ── Formulario completo (solo si el usuario lo activa) ────────────────
    master_key      = f"meta_{safe}_master"
    nombres_maestro = ["Manual"] + [c.get("nombre_corto", "") for c in cuentas]

    if cuentas:
        st.caption("Cargar desde maestro:")
    master_sel = st.selectbox(
        "Cuenta del maestro", nombres_maestro, key=master_key,
        help="Pre-rellena los campos con datos del maestro",
        label_visibility="collapsed",
    )

    cuenta_data = next((c for c in cuentas if c.get("nombre_corto") == master_sel), None)

    def dv(campo, fallback=""):
        if cuenta_data:
            return cuenta_data.get(campo, fallback)
        return auto.get(campo, fallback)

    master_idx = nombres_maestro.index(master_sel) if master_sel in nombres_maestro else 0
    prefix     = f"meta_{safe}_idx{master_idx}"

    c1, c2 = st.columns(2)
    with c1:
        emp_def = dv("empresa", "Sin definir")
        emp_idx = EMPRESAS.index(emp_def) if emp_def in EMPRESAS else len(EMPRESAS) - 1
        st.selectbox("Empresa", EMPRESAS, index=emp_idx, key=f"{prefix}_empresa")
        st.text_input("N° Cuenta", value=dv("numero_cuenta", auto["cuenta"]),
                      key=f"{prefix}_cuenta", placeholder="000000000")
        mon_def = dv("moneda", auto["moneda"])
        mon_idx = MONEDAS.index(mon_def) if mon_def in MONEDAS else 0
        st.selectbox("Moneda", MONEDAS, index=mon_idx, key=f"{prefix}_moneda")
    with c2:
        st.text_input("Banco", value=dv("banco", auto["banco"]),
                      key=f"{prefix}_banco", placeholder="BNB / BCP…")
        st.text_input("Nombre corto", value=dv("nombre_corto", auto["nombre_corto"]),
                      key=f"{prefix}_nombre_corto", placeholder="BNB Cte BOB")
        tipo_def = dv("tipo_cuenta", "Sin definir")
        tipo_idx = TIPOS_CUENTA.index(tipo_def) if tipo_def in TIPOS_CUENTA else len(TIPOS_CUENTA) - 1
        st.selectbox("Tipo cuenta", TIPOS_CUENTA, index=tipo_idx, key=f"{prefix}_tipo_cuenta")

    st.text_input("Observaciones", value=dv("observaciones", ""),
                  key=f"{prefix}_observaciones", placeholder="Opcional")


def _apply_metadata_to_df(
    df_std: pd.DataFrame,
    meta: dict,
    selected_sheet: str = "",
    header_row: int = 0,
    is_excel: bool = False,
) -> pd.DataFrame:
    """
    Enriquece el DataFrame normalizado con los metadatos del usuario:
    empresa, nombre_corto, moneda, tipo_cuenta, hoja_origen, fila_origen,
    observaciones, y deriva debito/credito desde importe.
    """
    df = df_std.copy()

    df["empresa"] = meta.get("empresa") or "Sin identificar"

    if meta.get("banco"):
        df["banco"] = meta["banco"]
    if meta.get("cuenta"):
        df["cuenta"] = meta["cuenta"]

    nc = meta.get("nombre_corto") or meta.get("cuenta") or ""
    if not nc and not df.empty and "cuenta" in df.columns:
        nc = str(df["cuenta"].iloc[0])
    df["nombre_corto"] = nc or "Sin nombre"

    df["moneda"]        = meta.get("moneda") or "BOB"
    df["tipo_cuenta"]   = meta.get("tipo_cuenta") or "Sin definir"
    df["observaciones"] = meta.get("observaciones") or ""
    df["hoja_origen"]   = selected_sheet or ""

    fila_base = (header_row + 2) if is_excel else 2
    df["fila_origen"] = [str(fila_base + i) for i in range(len(df))]

    imp = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    df["debito"]  = (-imp).clip(lower=0.0)
    df["credito"] = imp.clip(lower=0.0)

    return df


# ─── Funciones de renderizado ─────────────────────────────────────────────────

def render_welcome():
    st.markdown(
        """
        ### Bienvenido

        Esta herramienta consolida extractos bancarios de distintos bancos,
        analiza movimientos y prepara informes de Tesorería, **sin instalar nada**.

        **Cómo empezar:**
        1. Sube uno o varios archivos Excel o CSV en el panel lateral.
        2. Completa los **datos del extracto** (empresa, banco, cuenta, moneda).
        3. Pulsa **Procesar archivos**.
        4. Si el sistema reconoce el formato → los datos aparecen de inmediato.
        5. Si no lo reconoce → verás una pantalla de mapeo para asignar columnas.
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
            el sistema los detecta automáticamente.
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
    """
    filename  = pending["filename"]
    raw_bytes = pending["raw_bytes"]
    ext       = pending["ext"]
    sheets    = pending["sheets"]
    diag      = pending["diagnostic"]
    df_raw    = pending["df_raw"]
    meta      = pending.get("metadata", {})
    total_pendientes = len(st.session_state.cola_mapeo)

    st.subheader("Mapeo manual de columnas")
    st.markdown(
        f"El archivo **{filename}** no pudo procesarse automáticamente. "
        "Asigna las columnas para que el sistema pueda leerlo."
    )
    if total_pendientes > 1:
        st.caption(f"Archivo 1 de {total_pendientes} pendientes de mapeo.")

    if any(meta.get(k) for k in ["empresa", "banco", "cuenta"]):
        st.info(
            f"Datos del extracto: **{meta.get('empresa', '')}** | "
            f"{meta.get('banco', '')} | {meta.get('cuenta', '')} | "
            f"{meta.get('moneda', 'BOB')}"
        )

    if ext in ("xlsx", "xls") and sheets:
        st.markdown("#### Ajustar lectura del archivo")
        col_s, col_h, col_btn = st.columns([3, 2, 2])
        with col_s:
            sheet_sel = st.selectbox(
                "Hoja del Excel", sheets,
                index=sheets.index(pending["selected_sheet"])
                      if pending["selected_sheet"] in sheets else 0,
                key="mapeo_sheet",
            )
        with col_h:
            header_sel = st.number_input(
                "Fila de encabezado (0 = primera fila)",
                min_value=0, max_value=50,
                value=int(pending["header_row"]),
                step=1, key="mapeo_header",
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

    st.markdown("#### Asigna las columnas")
    st.info(
        "Selecciona qué columna del archivo corresponde a cada campo. "
        "Usa **(no usar)** para campos que no existen en tu archivo. "
        "**Opción A:** selecciona Importe si la columna ya tiene valores positivos y negativos. "
        "**Opción B:** selecciona Débito y Crédito si vienen en columnas separadas."
    )

    detected = diag["columnas_detectadas"]
    opciones  = ["(no usar)"] + list(df_raw.columns)

    def default_idx(campo: str) -> int:
        col = detected.get(campo)
        return opciones.index(col) if (col and col in opciones) else 0

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Campos de identificación**")
        c_fecha = st.selectbox("Fecha *",                    opciones, index=default_idx("fecha"),       key="map_fecha")
        c_desc  = st.selectbox("Descripción / Glosa",  opciones, index=default_idx("descripcion"), key="map_desc")
        c_saldo = st.selectbox("Saldo",                      opciones, index=default_idx("saldo"),       key="map_saldo")
        c_ref   = st.selectbox("Referencia / Folio",         opciones, index=default_idx("referencia"),  key="map_ref")
    with col_r:
        st.markdown("**Importe — elige A o B (no ambas)**")
        st.markdown("*Opción A: columna única con signo*")
        c_imp  = st.selectbox("Importe (con signo)",             opciones, index=default_idx("importe"), key="map_imp")
        st.markdown("*Opción B: columnas separadas*")
        c_deb  = st.selectbox("Débito / Cargo / Egreso",   opciones, index=default_idx("debito"),  key="map_deb")
        c_cred = st.selectbox("Crédito / Abono / Ingreso", opciones, index=default_idx("credito"), key="map_cred")

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
                df_std = _apply_metadata_to_df(
                    df_std, meta,
                    selected_sheet=pending.get("selected_sheet", ""),
                    header_row=pending.get("header_row", 0),
                    is_excel=pending.get("ext", "") in ("xlsx", "xls"),
                )
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

    if not st.session_state.df_consolidado.empty:
        n = len(st.session_state.df_consolidado)
        st.divider()
        st.caption(
            f"Ya tienes {n:,} movimientos consolidados de archivos anteriores. "
            "La vista completa aparecerá cuando termines el mapeo."
        )


# ─── Barra lateral ────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("\U0001f3e6 Extractos Bancarios")
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
        cuentas = load_accounts()
        st.markdown("---")
        st.markdown("**Datos de los extractos**")
        if cuentas:
            st.caption("Carga desde el maestro o completa manualmente.")
        else:
            st.caption("Completa los datos de cada archivo antes de procesar.")

        for f in uploaded_files:
            with st.expander(f"\U0001f4c4 {f.name}", expanded=True):
                if cuentas:
                    st.caption("Maestro de cuentas:")
                _render_file_metadata_form(f, cuentas)

        st.markdown("---")
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
                    meta = _get_file_metadata(f.name, f.size, cuentas)
                    info = load_file(f)
                    resultado = normalize(info.df_raw, info.filename)

                    if resultado is not None:
                        df_std, parser_name = resultado
                        df_std = _apply_metadata_to_df(
                            df_std, meta,
                            selected_sheet=info.selected_sheet,
                            header_row=info.header_row,
                            is_excel=info.ext in ("xlsx", "xls"),
                        )
                        nuevos_frames.append(df_std)
                        st.session_state.archivos_cargados.append(
                            (info.filename, parser_name, len(df_std))
                        )
                    else:
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
                            "metadata":       meta,
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

    with st.expander("Maestro de cuentas bancarias"):
        cuentas_disp = load_accounts()
        if cuentas_disp:
            for c in cuentas_disp:
                st.markdown(
                    f"- **{c.get('nombre_corto', '')}** — "
                    f"{c.get('banco', '')} | {c.get('moneda', '')} | "
                    f"{c.get('tipo_cuenta', '')}"
                )
            st.caption("Edita `config/cuentas_bancarias.json` para agregar cuentas.")
        else:
            st.caption("No hay cuentas registradas. Edita `config/cuentas_bancarias.json`.")


# ─── Área principal ───────────────────────────────────────────────────────────
st.title("Analizador de Extractos Bancarios")
st.caption("Versión: carga simplificada con datos automáticos")
st.divider()

cola = st.session_state.cola_mapeo
df   = st.session_state.df_consolidado

if cola:
    render_mapping_ui(cola[0])
elif not df.empty:
    render_main_tabs(df)
else:
    render_welcome()
