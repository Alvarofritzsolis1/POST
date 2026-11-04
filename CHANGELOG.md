# Historial de cambios

## 8.0.0 — Red de Obras: vista global y experiencia de trazabilidad (candidata)

- Vista inicial de requerimientos y métricas compartida entre todas las obras de la misma organización; filtro «Solo mis obras» opcional, desactivado al ingresar.
- Origen de obra obtenido de los datos de la publicación; bloqueo de cambios de obra en requerimientos existentes.
- Edición de publicaciones limitada a su autor para residentes, incluso si otro residente pertenece a la misma obra.
- Historial de auditoría presentado como eventos en español, con campos permitidos y nombres reales de obra y contratista; se conserva el JSON original solo en el registro interno.
- Diseño de Red de Obras más compacto: cinco indicadores principales, requerimientos antes de gráficos, línea de tiempo visual y formularios de obra bloqueada cuando corresponde.
- Pruebas nuevas de visibilidad entre obras, integridad del origen, autorización de edición e historial seguro.
- No introduce migraciones destructivas ni modifica las reglas documentales, OCR o de pago.
- **Estado:** cambios en rama de revisión. Requiere CI, prueba QA, respaldo y aprobación antes de fusionar o desplegar.

## 0.7.0 — Red de Obras, preparada para revisión

- Portal integrado con requerimientos, partidas dinámicas, borradores y capacidad compartida. Tarjetas, lista, Kanban, calendario mensual/semanal, filtros e indicadores calculados con datos persistentes.
- Rol residente con varias obras asignadas, bloqueo de módulos administrativos en el servidor y vistas colaborativas limitadas. Se conservan los perfiles anteriores.
- Menú superior con creación de cuentas, invitaciones seguras, administración, perfil y notificaciones; suspensión y revocación de sesiones ante cambios críticos.
- Coincidencias explicables por especialidad, fechas, partidas y capacidad libre; vigencia, renovación y distinción entre estimación y confirmación.
- Coordinación formal, conversación única, participantes autorizados, adjuntos, lectura e historial. Actualización automática entre sesiones.
- Adjudicación individual, parcial y a varios contratistas por partida. Saldo separado de ejecución, bloqueos PostgreSQL, idempotencia, ampliaciones, modificaciones, revocaciones y trazabilidad.
- Habilitación documental en la obra de destino, exportación CSV por obra y migración exclusivamente aditiva `0.7.0`.
- Pruebas de integración SQLite/PostgreSQL y recorrido reproducible de navegador con dos residentes.

## 0.6.0-rc1 — candidata local, pendiente de revisión y despliegue

- Importación especializada de contratistas con `NATURALEZA` y `FRECUENCIA` independientes de `COD`; archivos anteriores siguen admitidos y sus celdas vacías no borran clasificaciones válidas. CI se interpreta como independiente; CT no presupone trabajadores ni frecuencia.
- Reconciliación administrativa de clasificaciones con procedencia por evento, vista previa firmada, conflictos visibles, corrección manual y respaldo verificable obligatorio. No se atribuyen valores sin evidencia.
- Registro de trabajadores por obra y empresa con filtros, paginación y ficha individual. Contratos con fecha pactada separada del término efectivo, anexos, PDF y auditoría; finiquitos con causal, ratificación, entrega y revisión manual.
- Semáforo de riesgos contractuales, finiquitos, cotizaciones y documentos exigibles, con centro de alertas en Inicio y acceso a los registros. Los hallazgos de pago requieren documento y revisión; una modificación posterior invalida la conclusión.
- Control de asistencia por obra, contratista y trabajador: cinco ventanas de siete días (semana 5: días 29 al fin de mes), firmas diarias, borrador/cierre/revisión semanal, respaldo, autor y fechas, alerta por semanas vencidas y balance mensual con días pagados. Exclusión o reincorporación mensual sin borrar evidencia.
- Rol de administrativa para ingreso semanal; administrador y supervisor pueden revisar. Se mantienen administrador, supervisor, revisor documental, consulta y `analyst` para cuentas anteriores. Revisores documentales no pueden modificar trabajadores ni contratistas.
- Migración aditiva versionada `0.6.0-rc1`, prueba de respaldo/restauración obligatoria en el actualizador Docker, versión y SHA del commit servidos por la API.

## 0.5.0-rc1

- Organización compartida, administración de cuentas, importaciones especializadas y controles mensuales.
