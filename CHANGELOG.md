# Historial de cambios

## 12.0.0-rc1 — Auditoría de fallos ocultos (candidata)

- Corrige bypass de COD=CI en altas laborales y contratos nuevos; rechaza reclasificación incompatible con trabajadores activos.
- El endpoint mensual ya no admite nuevas vinculaciones exigibles para inactivos en período actual/futuro, preservando históricos.
- Elimina falsas alertas de clasificación de CI y corrige la clasificación por obra en opciones laborales.
- Añade pruebas dirigidas y auditorías estáticas de seguridad/dependencias, con resultados verificables en GitHub Actions.
- No se incorporan nuevas funcionalidades ni modificaciones estéticas.

## 10.10.0-rc1 — Activos e inactivos y resiliencia de fichas (candidata)

- Filtros y semáforos de estado; ficha de contratistas con trabajadores, documentación e historial.
- Corrección de detalles anidados que podían provocar pantalla blanca; aislamiento de errores React.
- Inactivos sin nuevas obligaciones documentales ni de asistencia en período vigente/futuro; históricos preservados.
- Pruebas de datos multiobra y no exigibilidad. Estado: pendiente de CI y QA de navegación.

## 10.9.0-rc1 — Importación especializada de contratistas por obra (candidata)

- Plantilla estricta de 11 columnas, sin NATURALEZA ni FRECUENCIA.
- Clasificación CT / CE / CI y estado ACTIVO / INACTIVO independientes por obra, sin asignación mediante catálogos ambiguos.
- Vista previa y actualización segura de registros previamente importados; conserva relaciones y auditoría.
- Corrección de listados, filtros, controles documentales y reglas de independientes usando COD por obra.
- Validaciones y pruebas de importación repetida, encabezados, estados y registros multiobra.
- **Estado:** rama y PR; sujeto a CI, QA y aprobación antes del VPS.

## 9.3.0-rc1 — Control de Asistencia compartido y supervisión de todas las obras (candidata)

- El administrador utiliza el mismo panel de asistencia, contratos, finiquitos y dotación que la administrativa: desaparece la obligación de buscar cada contratista por separado.
- Vista global «Todas las obras» con contratistas activos, revisiones exigibles iniciadas, completadas, pendientes y vencidas; acceso a cada obra con un clic.
- Matriz mensual interactiva (4/5 semanas laborales reales), con semáforos, semanas futuras no penalizadas y distinción de completado fuera de plazo.
- Nombre de la persona responsable asignada y de quien realizó cada revisión, sin confundir asignación con ejecución.
- Acceso directo a la asistencia y trabajadores desde cada casilla semanal del contratista; el administrador conserva su vista de balance de días.
- Datos compartidos y refresco del panel ante actividad de otras sesiones; reutiliza los endpoints y tablas existentes.
- `GET /api/v1/attendance-v81/portfolio` reservado al perfil administrador; la administrativa solo consulta sus obras.
- Pruebas de consolidado, límites de permisos y trazabilidad. Sin migraciones ni alteración de las firmas históricas de fin de semana.
- **Estado:** cambio en rama/PR, pendiente de CI y QA real antes de integración o despliegue.


## 9.2.0-rc1 — Centro laboral administrativo (candidata de revisión)

- Nuevo panel por obra con todos los contratistas activos sin buscar previamente, filtros, semáforos semanales y acceso directo a los trabajadores.
- Pestañas: asistencia semanal, contratos de trabajo, finiquitos, dotación vigente y rendimiento administrativo personal.
- Endpoint de lectura `/attendance-v81/overview` con seguridad por obra, estados laborales vigentes/históricos por fecha, contratos próximos a vencer, finiquitos y semanas de asistencia; no expone los días pagados a la administrativa.
- Reutiliza el registro de asistencia v8.1/v9.1: sin renumerar semanas, modificar firmas antiguas ni generar obligaciones sábado/domingo.
- Vista personal de evaluación mensual sin acceso a la evaluación de otras cuentas.
- Reutiliza tablas y relaciones existentes; **sin migraciones destructivas ni cambios de esquema**.
- El registro de contratos mantiene las rutas autorizadas; la validación y recepción de finiquitos permanecen en el flujo de permisos documentales vigente.
- **Estado:** versión propuesta en rama/PR. Requiere CI, revisión, respaldo verificado y despliegue aprobado. No está desplegada por crear este cambio.


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
