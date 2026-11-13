# GALANT — Plan de calidad y prevención de errores de Proyecto Javiera

**Versión objetivo:** 20.2.3-rc1. **Estado:** plan verificable; no prometer 100 % sin el Excel privado y expedientes reales.

## Causa raíz del incidente C11

1. El Reglamento Interno requería `extra.employer_city` pero no `extra.employer_commune`, pese a que el Excel tiene `Datos Contrato!C11`.
2. `source_leaks` buscaba cualquier aparición del valor original en todo el PDF y la atribuía a la celda C11. Una comuna puede aparecer legítimamente en el nombre de una obra, en una ciudad o en la dirección de un trabajador.
3. La misma lógica concatenaba todos los números impresos para buscar RUT, pudiendo formar coincidencias entre campos no relacionados.
4. La validación final de PDF es independiente de la validación de campos, por lo que ambos controles deben estar conectados al estado de la interfaz.

## Fase P0 — Corregida por 20.2.3

- Exigir comuna del empleador para Reglamento Interno y mostrar la etiqueta en el formulario; recuperar el dato de Contratistas cuando exista.
- Detectar coincidencias geográficas solo por frases completas, considerando otras ubicaciones actuales del expediente.
- Cuando la ubicación aparece explícitamente etiquetada como comuna de la empresa, bloquear si conserva un dato original ajeno al expediente.
- Verificar RUT y números como secuencias delimitadas; no concatenar todas las cifras del PDF.
- Mantener RUT, nombres y fechas con controles independientes estrictos.
- Llevar al usuario desde la tarjeta al campo faltante y explicar hoja, celda y motivo.

**Criterios de aceptación:** fecha antigua real bloqueada, fecha repetida legítima aceptada; comuna de obra legítima aceptada; comuna antigua atribuida al empleador bloqueada; RUT antiguo real bloqueado y cifras separadas no asociadas.

## Fase P1 — Auditoría de todos los datos de entrada

| Grupo | Origen Excel | Riesgo |
| --- | --- | --- |
| Empresa | C5–C14 | Razón social, RUT, representante, teléfono, dirección, comuna, ciudad, correo |
| Trabajador | C17–C26 | Identidad, RUT, nacionalidad, nacimiento, estado civil, dirección y contacto |
| Contrato y obra | C29–C40 | Cargo, jornada, sueldo, descuentos, fechas y constancia |
| Varios | C43–C45 y D30 | Destinos, asignación, períodos y obra |

- Inventariar qué documento realmente utiliza cada campo, incluyendo fórmulas indirectas, `CONCAT`, `VLOOKUP`/`BUSCARV`, `INDIRECT`, celdas combinadas y textos fijos.
- Comparar los requerimientos de cada documento con las dependencias reales de las **34 hojas** del Excel utilizado en producción.
- Registrar la referencia exacta en la hoja imprimible, no únicamente `Datos Contrato!C11`.
- Cada documento debe pedir solamente los datos que realmente necesita, sin copiar valores no comprobados entre ciudad/comuna/obra.

**Bloqueo:** no dar por completada esta fase sin inspeccionar el Excel privado versionado.

## Fase P2 — Validación de resultados y prevención de duplicados

- Mantener la revisión del PDF real antes de habilitar la emisión.
- Usar el hash de Excel, revisión publicada, datos del expediente, matrices y versión del motor para invalidar correctamente cachés.
- No usar una vista previa con marcas de agua como PDF definitivo.
- Mantener original, nuevas revisiones, firmas y evidencia de entrega separados.
- Rechazar RUT inválido, fechas imposibles, valores de muestra inequívocos, fórmulas con errores, páginas recortadas, matrices incompletas y campos requeridos vacíos.
- No ocultar fallas ni saltarse aprobaciones de nuevas plantillas.

## Fase P3 — Pruebas de regresión e interfaz

Matriz automática mínima: **10 documentos × 2 flujos (nuevo/existente) × 3 condiciones (correcto/faltante/incorrecto)**; añadir permisos, nueva revisión, dos obras, variables compartidas y pruebas de impresión PDF/Excel.

- Las tarjetas deben distinguir `LISTO`, `FALTAN_DATOS`, `VALIDANDO`, `BLOQUEADO` y `ERROR_TEMPORAL`.
- El mensaje debe indicar documento, causa, dato y acción. Botón «Completar» enfoca el campo.
- Probar escritorio, móvil, recuperación de expediente, descarga individual, ZIP, reemisión y protección ante doble clic.
- Conservar capturas e informes de fallas de CI.

## Fase P4 — Verificación en entorno real, despliegue y reversión

1. Importar **una copia** del Excel maestro y crear expedientes ficticios representativos; comparar manualmente cada PDF con su hoja de origen.
2. Ejecutar pruebas automatizadas, inspección visual y revisión laboral/preventiva de los formatos.
3. Respaldar base de datos y archivos; probar restauración.
4. Desplegar únicamente si CI completa está aprobada y verificar el commit, `/health`, versión, PDF descargable y ausencia de regresiones.
5. Si un PDF presenta datos cruzados o filtrados, bloquear la emisión y revertir la actualización.

**Métricas:** 0 fugas de identidad en casos de prueba, 0 falsos positivos en ubicaciones compartidas contempladas, 0 botones PDF habilitados antes del preflight, 100 % de las rutas de descarga probadas y tiempos p50/p95 medidos, no prometidos.

### Limitación importante

Ninguna suite sintética demuestra por sí sola que los datos y referencias del **Excel privado de producción** están al 100 % correctos. La aprobación final exige verificar los archivos reales con responsables autorizados. Nunca corregir en silencio un documento laboral o preventivo ya aprobado.
