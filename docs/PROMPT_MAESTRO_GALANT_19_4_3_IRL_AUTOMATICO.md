# PROMPT MAESTRO MEJORADO — GALANT · PROYECTO JAVIERA IRL

**Propuesta de versión:** GALANT 19.4.3-rc1 (rama de revisión, no producción).
**Prioridad:** funcionalidad verificable > integridad documental > facilidad de uso > estética.

## Mandato

Actúa como equipo técnico de React/FastAPI/PostgreSQL, revisión preventiva chilena,
QA y UX empresarial. Implementa, no solo describe. Antes de tocar código,
construye una matriz de trazabilidad «problema → causa → corrección → prueba → evidencia».
No aceptes mejoras cosméticas como solución a fallos de vinculación.

### 1. Auditoría inicial y reglas de datos

Inspecciona las APIs v193/v194/v195, las cinco matrices, la importación XLSX,
la vista IRL, el PDF nativo y los expedientes. Confirma rama/base, migraciones,
configuración y despliegue real antes de afirmar que una versión está en línea.
Comprueba el hash del Excel fuente y los recuentos: 25 cargos, 338 registros
brutos IRL, 26 PTS, 26 perfiles, 27 puestos y 27 sustancias.
No alteres las filas originales, sus números ni sus revisiones históricas.

### 2. Reglas de consolidación trazable

- Solo consolida automáticamente registros cuyos contenidos técnicos son
  idénticos, admitiendo normalización puramente tipográfica comprobada.
- Si un alias de cargo cambia solo el rótulo de la tarea pero no los campos
  técnicos, permite una consolidación de vista con referencia de todas las
  filas fuente y sin actualización de la base original.
- Para GASFITER conserva 26 filas brutas (2–14 y 80–92) y presenta 13 pares
  de riesgos idénticos en la vista. Los dos registros de PERFILES, PUESTOS,
  SUSTANCIAS y PTS son idénticos en el catálogo existente: precompleta su
  contenido, registra ambas procedencias y NO exige elegir arbitrariamente.
- No reduzcas dos actividades cuando difiera peligro, consecuencia o medida.
  Exige revisión preventiva de variantes realmente distintas.
- Nunca apruebes matrices ni habilites emisión por resolver un duplicado.

### 3. Autocompletado coherente por cargo

Fuente preferente para documento emitible: matriz aprobada vigente y del
mismo ámbito organizacional. Para edición: referencia Excel o borrador
identificado explícitamente. Registra por campo origen, revisión, fila y fecha.
Vincula PERFILES (descripción), PUESTOS (4 condiciones), IRL (4 columnas),
PTS (17 apartados), SUSTANCIAS (12 campos/HDS) sin depender del mismo texto
libre para todas las relaciones.

### 4. Revisión inteligente controlada

Examina coherencia actividad → peligro → consecuencia → control. Detecta
repeticiones, erratas y controles dudosos, sin sustituir la matriz preventiva.
Distingue automáticamente «corrección ortográfica segura» de «propuesta de
cambio de contenido técnico» y registra diferencias y auditoría.
No inventes HDS, peligros, normas, sustancias, límites, métodos, firmas,
certificaciones ni controles. Identifica labores condicionales (soldadura,
altura, zanja, espacios confinados) para confirmación por tarea real.
Valida contra el D.S. 44, artículo 15, el programa y matriz de riesgos
de la empresa y referencias oficiales actuales:
- https://www.bcn.cl/leychile/navegar?i=1205298
- https://www.dt.gob.cl/portal/1628/w3-article-99183.html
- https://www.mutual.cl/portal/wcm/connect/260d781a-004a-4a59-b008-8a7cc4c6328b/reflexion-2-faja-lumbar.pdf

### 5. Interfaz compacta para personal administrativo

Flujo: OBRA/EMPRESA/TRABAJADOR → CARGO Y LABORES →
MATRICES/OBSERVACIONES → VISTA A4/IMPRESIÓN.
No repitas la selección del trabajador; lectura de expediente autorizada,
sin crearlo ni modificar el módulo de trabajadores, asistencia o contratistas.
Utiliza selectores de búsqueda, navegación por labores, subpaneles plegables,
barra de acciones fija y mensajes de estado agrupados. No mostrar una docena
de alertas idénticas; mantener problemas reales accesibles.
Diferenciar claramente «vista de referencia por cargo» y «expediente real».

### 6. Copiar y pegar matriz

Admitir TSV del portapapeles Excel (4 columnas, cabecera opcional),
incluidas comillas y saltos de línea de celdas. Antes de aplicar:
validar cuatro campos, cantidad y duplicados; previsualizar; elegir
reemplazar/agregar; permitir deshacer. Aplicación = borrador local,
NO guardado ni aprobación. El guardado existente mantiene evaluación
de impacto y permisos. No ejecutar HTML o fórmulas pegadas.

### 7. Plantilla y calidad de impresión

Conservar las cuatro columnas IRL, cabecera, 4 condiciones, 12 campos
de sustancias, cinco gráficos originales del XLSX privado, declaración
y espacio de firma A4. No introducir textos de admin en la impresión.
Si falta la fuente privada, informar la ausencia sin fabricar imágenes.
No declarar paridad total mientras no se comprueben las 74 fórmulas IRL,
las relaciones con las otras hojas y las diferencias visuales por página.

### 8. Seguridad, datos personales y aprobaciones

La consulta y generación solo pueden leer expedientes permitidos por
organización/obra/rol. El componente de referencia no consulta ni expone
identidades de ejemplo. Las acciones de revisión deben ser trazables
y aplicar controles de acceso de backend; la aprobación la realiza quien
tenga atribuciones. Nunca sobrescribir PDF anteriores o matrices aprobadas.

### 9. Aceptación obligatoria

P0: GASFITER presenta 13 labores únicas (de 26 originales) y recupera las
cuatro matrices relacionadas sin aviso de ambigüedad falsa. Diferencias
técnicas nunca se consolidan. CARPINTERO fila 40 permanece incompleta y
bloqueada para aprobación automática. PAISAJISMO no se convierte en
PAISAJISTA químico sin validación.

P1: pruebas para 25 cargos y permisos; pegado TSV correcto/incorrecto,
duplicados, comillas, orden y deshacer; edición durable al guardar borrador;
comparación A4 HTML/PDF con Excel real; cinco imágenes, formularios y firmas.
No declarar pruebas realizadas si no se ejecutaron.

### 10. Flujo GitHub y despliegue

Crear rama dedicada y PR inicialmente en borrador. Ejecutar backend,
frontend, tipado, linter, pruebas de regresión, control de cambios y
prueba en navegador. Registrar resultados reales. No fusionar ni desplegar
automáticamente sin QA verde y revisión preventiva sobre contenido técnico.
Entregar archivos modificados, SHA, enlaces a PR/CI, riesgos pendientes,
instrucciones VPS condicionadas a la ruta/compose reales y rollback.
No solicitar credenciales privadas por chat ni imprimirlas en logs.

**Definición de terminado:** el sistema automatiza de manera trazable,
permite editar sin conocimientos técnicos y produce IRL correctos por cargo
a partir de fuentes autorizadas, sin inventar contenido ni aprobarlo solo.
Si hay faltantes, informar con precisión cuáles siguen bloqueados.
