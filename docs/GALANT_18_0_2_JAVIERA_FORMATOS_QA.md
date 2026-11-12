# GALANT 18.0.2-rc1 — Reconstrucción controlada de impresión de Proyecto Javiera

## Objetivo real

Proyecto Javiera prepara documentos para **imprimir y obtener firma manuscrita posteriormente**. Generar el PDF NO acredita firma, recepción, capacitación, entrega de EPP ni aprobación normativa.

## Causa raíz hallada en el archivo Excel real

Se recuperó la copia de Excel GALANT 18 conservada privadamente en la Biblioteca del usuario; no se agregará el libro a un repositorio público. La hoja `INDUCCION PREVENCION` tiene diez bloques, pero **los membretes y controles de código son Drawing/Shapes OOXML**, no filas textuales. Forzar los saltos antes de los títulos textuales (9,58,116,159,206,262,304,355,404,452) divide el dibujo de su contenido y causa páginas con solo encabezado.

Los encabezados gráficos comienzan en filas Excel: **1, 48, 104, 149, 197, 253, 298, 345, 394, 442** (las anclas originales Drawing son cero-indexadas). En la prueba visual de LibreOffice, imponer un salto manual en la fila 298 generó una página aislada con solamente la tabla de control. Se omitió ese salto: LibreOffice conserva la paginación automática que agrupa la cabecera y el texto del PTS. Se conservan los saltos antes de los encabezados de las filas 48,104,149,197,253,345,394,442.

**No repetir filas 1:8 como títulos en libros que ya tienen dibujos corporativos:** eso superpone un segundo encabezado con el original. Para pruebas sintéticas sin dibujos, sí es posible usar títulos de filas de la hoja.

## Código modificado

- `apps/backend/app/javiera_excel.py`: nuevas constantes de inicio de secciones, configuración de saltos manuales sobre la copia Excel efímera convertida a PDF. No modifica el origen privado.
- `apps/backend/app/javiera_v18_api.py`: análisis del PDF para alertar sobre páginas casi vacías en documentos de inducción y tipografía menor a 8 pt.
- `apps/frontend/src/JavieraV17.tsx`: muestra motivos concretos y páginas observadas.
- Nuevas pruebas unitarias y de integración `test_javiera_excel_layout.py` y `test_javiera_v18.py`.
- Versión en backend/frontend/lockfile: `18.0.2-rc1`.

## Excel revisado (solo entrega privada)

Archivo del usuario: `GALANT_18_0_2_JAVIERA_FORMATOS_EXCEL_REVISADOS.xlsx`. Se conserva fuera del repositorio público. Conserva las **22 hojas originales, 381 fórmulas, 250 combinaciones originales y dos archivos Drawing**. Se agregó una hoja de control (23 hojas en total) con los inicios exactos de cada formulario; ajustes de envoltura de texto y alto en párrafos de la inducción, sin cambiar las cláusulas. **La hoja original sigue siendo la fuente oficial de los diez bloques**; no se crean copias incompletas de los membretes o espacios de firma.

El catálogo activo continúa mostrando solo los diez tipos documentales ya existentes. Al importar una nueva fuente a GALANT se crea una nueva versión privada, preservando las anteriores en historial; no se ejecuta una eliminación destructiva de plantillas/expedientes.

## Evidencias de QA local, parciales

- Fórmulas originales conservadas: **381 / 381** (estructura OOXML).
- Rangos combinados originales: **250 / 250**.
- Archivos de dibujos: **2 / 2**.
- El ZIP XLSX no contiene errores de compresión.
- Conversión experimental de la inducción a PDF con LibreOffice: el salto en fila 298 producía un membrete aislado. Sin ese salto, la muestra pasó de 21 a 20 páginas totales del libro de prueba y desapareció esa página de 349 caracteres. **La muestra incluía otras hojas y referencias sin recálculo; NO equivale a emisión final GALANT ni certifica todas las páginas**, y mostró errores de fórmula en las páginas temporales del archivo sin materializar.
- Las pruebas sobre el motor final FastAPI, la conversión del Excel privado en el VPS, los diez PDF emitidos, las firmas y la comparación de cada página deberán confirmarse por CI y revisión visual antes del despliegue.

## Evaluaciones independientes: siete responsabilidades de revisión

| Perfil | Control aplicado | Estado |
|---|---|---|
| Arquitectura documental | Diez puntos de inicio con control de encabezados Drawing | Implementado; inspección física pendiente |
| Diseño editorial | Superposición de cabeceras detectada y eliminada | Corregido en la ruta de impresión; evaluación humana pendiente |
| Especialista Excel | Conteos de hojas, fórmulas, combinaciones y dibujos | Verificación estructural satisfactoria |
| Ingeniero PDF | Pruebas de saltos y detección de páginas aisladas | Validación parcial local; producción pendiente |
| Revisor laboral/preventivo | Textos originales no reemplazados por supuestos | Revisión humana de contenido pendiente |
| Ingeniería QA | Tests de saltos, ausencia de falsos formularios, preflight | Implementados, ejecución de GitHub Actions pendiente |
| Auditoría independiente final | Cero fallas críticas y objetivo 95/100 | NO aprobado todavía |

No se afirma que estos perfiles hayan sido agentes externos autónomos ejecutados. Son perspectivas de auditoría explicitadas para la aceptación de producto. **Ninguna puntuación 95/100 se da por conseguida sin validación real de cada PDF.**

## Criterios de aprobación / seguridad

1. Importar el nuevo XLSX privado desde la Biblioteca a través de interfaz GALANT (no subirlo al repositorio).
2. Utilizar modo administrador único para validar visualmente y habilitar impresión; no registrar una firma ni recepción ficticia.
3. Emitir la inducción con datos sintéticos o de prueba y revisar las páginas del PDF. No usar el PDF de conversión experimental como documento definitivo.
4. Revisar cada una de las diez plantillas, incluyendo PTS/IRL, con la vista previa y controles técnicos.
5. Si alguna página contiene un encabezado aislado, contenido truncado o letra ilegible, mantener el estado pendiente y corregir el Excel.
6. Conservar historial, archivos originales, datos documentales y todos los módulos operativos.
7. Fusionar en `main` y desplegar en VPS **solo con CI verde, respaldo y verificación del propio PDF real en servidor**.

## Despliegue

El PR parte de `main`. No se toca la VPS directamente. GitHub Actions hace las pruebas, y después de aprobarse el PR podrá seguirse el flujo habitual de despliegue. No ejecutar comandos que eliminen volúmenes, plantillas o la base PostgreSQL.
