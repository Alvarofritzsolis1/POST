# PROMPT MAESTRO DE EJECUCIÓN — GALANT 19 · Migración controlada de Proyecto Javiera

## Meta
Convertir Proyecto Javiera en un generador de documentos A4 con plantillas HTML/CSS mantenibles, no dependientes de las imágenes incrustadas ni de los saltos de página del Excel. Todos los formularios se **imprimen para obtener firmas manuscritas posteriormente**. El PDF, por sí solo, no acredita entrega, firma, capacitación, recepción o cumplimiento normativo.

## Reglas inviolables
- No eliminar, reimportar destructivamente ni modificar archivos Excel originales, fórmulas, PDF emitidos, registros históricos ni otras tablas de GALANT.
- El documento debe mostrar los datos que ya existen en expedientes documentales **locales** de Javiera. No dar de alta ni modificar trabajadores/contratistas operativos, asistencias o cumplimiento mensual.
- No incluir el nombre, logo o código de GALANT dentro de los formularios PDF impresos.
- No inventar contenido de prevención: riesgos IRL solo desde matrices aprobadas de la misma organización; inducción solo desde temario que el usuario registre explícitamente; Reglamento Interno debe tener versión identificada.
- Permisos estrictos de ADMIN, expediente limitado a la organización del solicitante; sin URLs externas, HTML arbitrario, macros o datos reales de ejemplo en el repositorio.
- Mantener la emisión XLSX existente como opción estable hasta validar la equivalencia documental y que el usuario apruebe la migración definitiva.

## Plan por fases, con entregables medibles
### Fase 1: piloto de impresión nativa en paralelo
1. Instalar tres plantillas HTML separadas: Recepción Reglamento Interno, IRL, Inducción, con CSS corporativo A4 compartido.
2. Datos de entrada vinculados a la base documental y a IRL aprobado, sin usar Excel para el PDF piloto.
3. Validar texto, fecha, persona, empresa, obra, cargo, versión, matriz y temario; rechazar campos faltantes. Escapar todo texto proveniente de usuarios.
4. Construir PDF con PyMuPDF Story y paginación dinámica, evitando que el texto pierda tamaño por intentar caber en una sola página.
5. Añadir indicador «VISTA PREVIA», paginación y firmas manuscritas. No emitir PDF definitivo ni modificar historiales.
6. Incorporar un botón en Revisión e impresión que solo abra la vista previa nativa, dejando el sistema Excel actual intacto.

**Implementación inicial de esta rama**
- Nuevo motor: apps/backend/app/javiera_native.py
- Nuevas plantillas: apps/backend/app/javiera_native_templates/*.html y print.css
- Nueva API privada: POST /api/v1/javiera/v19/preview y GET /formats
- Integración: main.py, JavieraV166.tsx, JavieraWorkspace.tsx
- QA: apps/backend/tests/test_javiera_v19.py

### Fase 2: conservar contenidos y fórmulas
1. Inventariar el Excel original: contar y registrar el texto y ubicación de **todas** las fórmulas (última auditoría de usuario: 423), nombres de hoja, dependencias y matrices.
2. Distinguir datos visuales de algoritmos necesarios para cada PDF (remuneraciones, fechas, periodos, formatos numéricos, roles).
3. Migrar cada cálculo requerido a funciones backend deterministas, con pruebas de paridad contra valores reales calculados por Excel y casos extremos.
4. Mantener el Excel original como respaldo sin alteraciones. **No afirmar que las 423 fórmulas ya fueron migradas**: en fase 1 no se usan y todavía deben ser evaluadas individualmente.

### Fase 3: reconstrucción documental completa
- Migrar los siete documentos restantes a HTML/CSS después de inventariar íntegramente su texto y firmantes: contrato, anexos, declaración jurada, EPP, PTS y recepción PTS.
- Convertir imágenes de tablas IRL en texto estructurado solo tras revisar cuidadosamente la transcripción y aprobar su equivalencia. Nunca sustituir las matrices preventivas por contenido inventado.
- Un único estilo con controles de página, tabla y firmas; no forzar PTS o IRL extensos a una sola hoja si el contenido no cabe con letra legible.
- Dar prioridad a reglas de impresión reales y a la fidelidad documental, no a decoración.

### Fase 4: emisión definitiva y reemplazo gradual
- Solo después de verificar cada documento, introducir emisión nativa inmutable con versión, hash, responsable, historial, motivo de reemisión y trazabilidad.
- Mantener el Excel como modo de compatibilidad y reversión. Activar motor nativo por documento y organización, sin sustituir masivamente datos ni documentos ya emitidos.
- Respaldar y comparar resultados en VPS antes de activar producción.

## Perspectivas de QA (siete funciones, no agentes externos inventados)
1. Ingeniería backend: modelo documental, seguridad y salida PDF.
2. Maquetación editorial: jerarquía visual, márgenes, títulos, firmas.
3. Especialista Excel: referencias, fórmulas y paridad.
4. Prevención de riesgos: fidelidad de IRL/PTS y contenido realmente registrado.
5. Laboral: contenido de constancias y contratos sin inventar cláusulas.
6. QA automatizado: pruebas unitarias, integración, regresión y casos largos.
7. Auditoría de aceptación: verificación visual de **todas las páginas** y cero defectos críticos.

## Matriz de aceptación
- 30 % integridad de datos y contenido, 20 % legibilidad, 20 % impresión y paginación, 15 % firmas/encabezados, 10 % accesibilidad del flujo, 5 % pruebas.
- Meta **95/100** y cero textos cortados, páginas vacías, firmas falsas, errores de RUT, riesgos inventados o salidas fuera del A4.
- Las cifras son criterios objetivo, no calificaciones efectivamente alcanzadas.
- CI de Python y React, pruebas de Chromium y PDF de los diez documentos reales; prueba con nombres y direcciones extensas, riesgos largos y varias páginas.
- No desplegar ni fusionar con fallos críticos, y nunca declarar pruebas pasadas si no se han ejecutado.

## Estado del primer piloto
**Tres vistas previas HTML/CSS en paralelo; NO migración definitiva ni reemplazo del motor Excel.** Los siete formatos restantes y la comparación de las fórmulas siguen pendientes. Cualquier error se comunica en lugar de ocultarlo.

## Código VPS
Tras CI verde, revisión del Pull Request y fusión explícita, utilizar el flujo de despliegue controlado GitHub Actions ya existente. No pedir contraseñas ni hacer cambios directos sin validación de respaldos, endpoints /api/v1/version y /api/v1/health.
