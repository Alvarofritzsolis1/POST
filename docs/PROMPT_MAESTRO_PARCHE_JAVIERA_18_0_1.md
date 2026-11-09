# PROMPT MAESTRO · GALANT 18.0.1-rc1 · PARCHE JAVIERA SOLO PDF

## Contexto innegociable
Proyecto JAVIERA es exclusivamente un generador documental: toma datos aislados, prepara un PDF, lo imprime y se solicita firma manuscrita. No es firma electrónica, no certifica capacitación, entrega de EPP, recepción de reglamento ni cumplimiento laboral. Está prohibido crear/alterar trabajadores, contratistas o asistencias del sistema operativo al crear una ficha documental.

## Objetivo
Auditar y corregir la última versión de GALANT respetando React + FastAPI + PostgreSQL + Docker. Para el piloto, un solo administrador debe poder habilitar los formatos de impresión sin crear otro usuario ni simular revisión por un profesional independiente. Mantener los controles de acceso de administrador y la trazabilidad de acciones; NO declarar una validación profesional cuando solo se habilitó el formato para imprimir. La separación de roles queda disponible como modo avanzado para futuras etapas.

## Fallos reproducidos por capturas y código
1. PUT /javiera/admin/reviews/reviewers rechaza la designación propia con 403 («Otro administrador debe acreditar la designación de revisor»). No exigir esa designación en el piloto de impresión.
2. La mesa muestra diseño v1, v2 y sucesivos como documentos duplicados. Mostrar solo la mayor revisión por código documental; conservar el historial en un control secundario. Las revisiones antiguas nunca se deben publicar sobre la vigente.
3. /admin/excel/import crea versiones adicionales al subir el mismo XLSX. Debe ser idempotente según hash y organización.
4. Checklists de DS44 sobre riesgos, sustancias, matrices, etc. se aplican indiscriminadamente a una simple recepción de reglamento. Separar la comprobación del FORMATO PARA IMPRESIÓN de cualquier validación técnica/jurídica del CONTENIDO. En el piloto pedir únicamente revisión visual del PDF, consistencia de datos variables y espacio de firma.
5. El motor bloquea impresión de «Recepción reglamento», «Entrega EPP», «Recepción PTS» o «Inducción» cuando event_confirmed != true. Es conceptualmente incorrecto: se necesita imprimir ANTES para conseguir la firma. No cambiar automáticamente ninguna situación de entrega/firma al generar o imprimir.
6. La vista previa de PDF abre ventana solo tras una espera asíncrona y puede ser bloqueada. Reservar la pestaña sincrónicamente con el clic; informar errores de conversión.
7. No permitir usar un formato antiguo publicado si existe una revisión más nueva pendiente. Bloquear emisión hasta habilitar la revisión vigente; explicar el motivo.
8. La interfaz contiene nombres de estado y mensajes contradictorios: «aprobado» vs «PDF para firma física». Mostrar «Habilitado para imprimir» sin sugerir firma, recepción ni validación profesional.

## Flujo UX obligatorio
(1) Elegir empresa nueva/existente → (2) Elegir documento(s) mediante casillas → (3) Recuperar datos documentales, sin crear altas operativas → (4) Completar solamente campos faltantes → (5) Ver vista previa fiel del XLSX → (6) Habilitar formato para impresión una sola vez por versión → (7) Descargar o imprimir PDF → (8) Recibir firma física fuera de GALANT. No pedir que el paso 8 suceda antes del 7.
Vista principal: solo 10 tipos documentales únicos, estado claro y accesos «Vista previa», «Habilitar impresión» y «Preparar PDF». Historial colapsado. No listas de 20/30 versiones en el selector. No desplegar códigos técnicos ni IDs en lenguaje de usuario.

## Separación y seguridad
- Configuración de piloto explícita, con posibilidad de desactivarla más adelante.
- Endpoint de habilitación restringido a ADMIN autenticado de la organización.
- Registrar actor, fecha, versión y recurso en auditoría con acción específica de habilitación para impresión; no inventar firmas, actas ni especialidad.
- Mantener autorización real de «revisor documental» en el flujo profesional cuando se desactive piloto.
- Nunca eliminar documentos antiguos ni sobrescribir PDF ya emitidos.
- Mantener verificación de RUT/fechas, rangos, datos obligatorios, fórmulas/celdas, fuente XLSX privada, integridad hash y marcadores no resueltos. No falsificar datos que faltan para poder imprimir.
- Un expediente documental no crea Worker, WorkerAssignment, Contractor ni ContractorWorksite.
- Mantener control por organización y no filtrar datos privados al repositorio.

## Pruebas obligatorias
A. Importar el mismo XLSX tres veces: 10 documentos visibles, no 30 revisiones nuevas.
B. Corregir una celda: se crea v2, v1 queda en historial, solo v2 se ofrece para habilitar.
C. Intentar publicar v1 tras crear v2: rechazo HTTP 409; sin pérdida de historial.
D. Usuario ADMIN solo: abre vista previa, confirma visualmente, habilita formato; no necesita otro revisor.
E. Usuario RESIDENTE y ADMINISTRATIVA: sin autorización para habilitar formato.
F. Revisor documental futuro: conserva permisos mínimos y no puede autoaprobar su propia plantilla.
G. Preparar recepción reglamento, EPP, PTS e inducción sin evento ocurrido, porque serán firmados después; los datos requeridos y las matrices, cuando correspondan, siguen validándose.
H. PDF conserva encabezados, textos, logotipos, márgenes, zonas de firma, fórmulas y tamaño de papel del archivo Excel.
I. PDF final no incluye datos sintéticos de ejemplos, ni códigos de plantilla ni placeholders sin reemplazar.
J. Impresión/descarga disponible con protección frente a pop-ups y errores visibles.
K. Crear ficha documental no incrementa tablas operativas de trabajadores/contratistas ni altera su estado.
L. Revisar PDF de prueba de los 10 documentos y diferencias con Excel: número de páginas, campos y apariencia.
M. Validar permisos multi-organización, importaciones simultáneas, conservación de PDF históricos y reemisión justificada.
N. Ejecutar CI de backend/frontend, build TypeScript, regresiones y smoke HTTP antes de combinar en main. No declarar CI aprobada si no se observó.
O. Confirmar versión efectiva en /api/v1/version y /api/v1/health tras despliegue. Si falla, rollback seguro.

## Entregables
- Diagnóstico con causa raíz, archivo y línea; severidad y solución.
- Cambios mínimos y compatibles sobre la rama de la última versión, sin reescribir todo GALANT.
- Pruebas automatizadas y reporte de resultados reales (aprobado, fallido, no ejecutado).
- Pull request con changelog; no desplegar hasta que pase CI y la versión coincida.
- Instrucciones seguras para actualizar el VPS desde GitHub Actions; sin compartir contraseñas.
- Validación de producto final: el usuario debe completar una ficha y obtener el PDF imprimible en un flujo claro, y obtener la firma en papel después.

## Criterio de aceptación final
Una persona ADMIN puede preparar el PDF de Recepción del Reglamento Interno, imprimirlo y presentarlo para firma física sin crear otro administrador, sin marcar la recepción como ocurrida, sin duplicar versiones de plantilla y sin crear trabajadores operativos. Si esto no funciona, el parche NO se considera completo.
