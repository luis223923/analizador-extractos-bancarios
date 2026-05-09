# Sistema de Control de Deuda Bancaria

Aplicación web desarrollada con **Python + Streamlit** para el control, monitoreo y análisis de la deuda bancaria empresarial. Diseñada para equipos de Tesorería que gestionan múltiples líneas de crédito, préstamos directos, boletas de garantía, refinanciamientos y garantías.

---

## ¿Qué hace la aplicación?

- Centraliza toda la deuda bancaria de la empresa en un solo lugar.
- Permite cargar información desde Excel y validar su integridad.
- Calcula indicadores financieros clave (KPIs) automáticamente.
- Muestra un dashboard ejecutivo con gráficos y métricas.
- Genera alertas críticas, altas, medias e informativas.
- Mantiene trazabilidad entre préstamos originales y refinanciamientos.
- Permite exportar reportes consolidados en Excel.

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone <url-del-repositorio>
cd analizador-extractos-bancarios

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux / Mac
venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt
```

### Dependencias requeridas

```
streamlit>=1.35.0
pandas>=2.2.0
openpyxl>=3.1.0
plotly>=5.20.0
xlsxwriter>=3.2.0
xlrd>=2.0.1
```

---

## Cómo ejecutar la aplicación

```bash
streamlit run app.py
```

La aplicación se abrirá automáticamente en el navegador en `http://localhost:8501`.

---

## Flujo de trabajo

### 1. Descargar la plantilla Excel

Desde el menú **Cargar Excel**:

- **Plantilla vacía**: estructura lista para completar con datos reales.
- **Plantilla con datos de ejemplo**: incluye 5 préstamos, 3 líneas de crédito, 5 boletas de garantía y 2 refinanciamientos de muestra.

### 2. Completar la información

Abra el archivo Excel descargado y complete las hojas correspondientes. Respete los formatos de fecha (`dd/mm/yyyy`) y use los valores de la hoja **Parametros** para los campos de tipo lista.

### 3. Cargar el archivo

Desde **Cargar Excel**, use el cargador de archivos para subir el Excel completado. La aplicación validará y procesará automáticamente cada hoja.

### 4. Revisar el Dashboard y las Alertas

- **Dashboard**: KPIs ejecutivos y gráficos de deuda, vencimientos y exposición.
- **Alertas**: listado priorizado de inconsistencias y vencimientos críticos.

### 5. Exportar reportes

Desde **Exportar Reportes** descargue el reporte consolidado o reportes específicos.

---

## Hojas de la plantilla Excel

| Hoja | Descripción |
|---|---|
| **Base_Deuda** | Registro principal de todas las operaciones de crédito |
| **Cronograma_Pagos** | Cuotas programadas de capital, intereses y comisiones |
| **Lineas_Credito** | Líneas de crédito aprobadas, utilizadas y disponibles |
| **Boletas_Garantia** | Boletas de garantía emitidas por banco y beneficiario |
| **Refinanciamientos** | Relación entre operaciones anteriores y nuevas |
| **Bancos_Cuentas** | Cuentas bancarias por empresa y banco |
| **Garantias** | Garantías reales (hipotecas, prendas, fianzas, etc.) |
| **Pagos_Realizados** | Historial de pagos efectuados con comprobante |
| **Parametros** | Listas de valores válidos para validaciones |
| **Alertas** | Hoja de referencia para registrar acciones correctivas |

---

## KPIs calculados automáticamente

| Indicador | Descripción |
|---|---|
| Deuda bancaria total | Suma de Saldo_Actual de todas las operaciones |
| Deuda por banco | Agrupado por institución financiera |
| Deuda por empresa | Agrupado por razón social |
| Deuda por moneda | CLP, USD, EUR, UF |
| Deuda por tipo de operación | Préstamo, línea, boleta, etc. |
| Tasa promedio ponderada | `sum(Saldo × Tasa) / sum(Saldo)` |
| Capital próximo a pagar | 7, 30, 60 y 90 días desde el cronograma |
| Intereses próximos a pagar | 7, 30, 60 y 90 días desde el cronograma |
| Líneas aprobadas / utilizadas / disponibles | Desde hoja Lineas_Credito |
| Boletas vigentes / vencidas / por vencer | Desde hoja Boletas_Garantia |
| Operaciones vencidas | Estado Vigente con fecha de vencimiento pasada |
| Exposición total bancaria | Deuda + Líneas utilizadas + Boletas vigentes |
| Interés mensual estimado | `Saldo × Tasa_Anual / 100 / 12` |

> **Nota sobre tasas:** La tasa anual se ingresa en porcentaje. Si la tasa es 6.5%, ingrese `6.5`, no `0.065`.

---

## Clasificación de vencimientos

| Clasificación | Criterio |
|---|---|
| Vencido | Días al vencimiento < 0 |
| 0 a 7 días | Vence en los próximos 7 días |
| 8 a 30 días | Vence entre 8 y 30 días |
| 31 a 60 días | Vence entre 31 y 60 días |
| 61 a 90 días | Vence entre 61 y 90 días |
| Más de 90 días | Vence en más de 90 días |

---

## Validaciones realizadas

La aplicación valida automáticamente al cargar el archivo:

1. Empresa, Banco y Moneda no pueden estar vacíos.
2. `Numero_Operacion_Banco` es obligatorio.
3. `Saldo_Actual` no puede superar `Monto_Original`.
4. Operación con `Fecha_Vencimiento` pasada y Estado "Vigente" genera alerta **Crítica**.
5. `Tasa_Anual` es obligatoria para préstamos y líneas de crédito.
6. Operación con Estado "Refinanciado" sin `ID_Nueva_Operacion` genera alerta **Alta**.
7. Boleta vencida con Estado "Vigente" genera alerta **Crítica**.
8. Boleta que vence en menos de 30 días genera alerta **Media** o **Alta**.
9. Línea de crédito vencida con Estado "Vigente" genera alerta **Crítica**.
10. Operaciones sin garantía generan alerta **Informativa**.
11. Posibles duplicados por Banco + Número + Monto + Fecha generan alerta **Alta**.
12. Pagos realizados sin comprobante generan alerta **Informativa**.
13. Operaciones vigentes sin cronograma de pagos generan alerta **Informativa**.
14. Operación vencida sin estado de cierre correcto genera alerta **Crítica**.

---

## Niveles de alertas

| Nivel | Color | Ejemplos |
|---|---|---|
| **Crítica** | 🔴 Rojo | Operación vencida con estado Vigente, boleta vencida con estado Vigente |
| **Alta** | 🟠 Naranja | Vencimiento en menos de 7 días, saldo > monto original |
| **Media** | 🟡 Amarillo | Vencimiento en 30 días, falta tasa, falta garantía |
| **Informativa** | 🔵 Azul | Sin observaciones, sin comprobante, sin cronograma |

---

## Trazabilidad de refinanciamientos

La sección **Refinanciamientos** permite entender el flujo completo de una operación:

```
Préstamo original → amortización → refinanciamiento → nuevo préstamo → pago/cierre
```

Puede registrar la trazabilidad de dos formas:

1. **Hoja Refinanciamientos**: complete `ID_Operacion_Anterior` e `ID_Operacion_Nueva` junto con montos y fechas.
2. **Campo en Base_Deuda**: complete `ID_Operacion_Reemplazada` en la operación nueva para que el sistema construya la trazabilidad automáticamente.

La vista de trazabilidad muestra el número de operación anterior, banco, empresa, montos cancelados y nuevos, fecha y motivo del refinanciamiento.

---

## Reportes exportables

| Reporte | Contenido |
|---|---|
| Consolidado | Dashboard_Resumen + todas las hojas + Alertas + Trazabilidad + Vencimientos |
| Alertas | Listado priorizado de todas las alertas detectadas |
| Vencimientos 90d | Operaciones que vencen en los próximos 90 días |
| Boletas de Garantía | Tabla completa de boletas |
| Líneas de Crédito | Tabla completa de líneas con disponibilidad |
| Trazabilidad | Relación entre operaciones anteriores y nuevas |
| Exposición por Banco | Deuda + líneas + boletas por institución |

---

## Estructura del proyecto

```
app.py              ← Aplicación principal (único archivo)
requirements.txt    ← Dependencias Python
README.md           ← Este archivo
```

---

## Licencia

Uso interno corporativo — Tesorería.
