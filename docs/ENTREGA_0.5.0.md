# GALANT POST 0.5.0-rc1 — implementación y evidencia

Esta entrega se basa en `main` 289616b (incluye las PR #6 y #7), no en el checkout inicial antiguo. Es una candidata para revisión: no se conectó al VPS ni se modificaron datos de producción.

## Diagnóstico multiusuario

`create-admin` crea una organización nueva, no incorpora un colaborador a una organización existente. Repetirlo para cada persona genera organizaciones distintas, aunque sus nombres coincidan. Los endpoints operativos y OCR filtran por `org_id`; quitar esos filtros expondría información entre organizaciones. `main` ya contenía `create-user` y `link-user`; esta entrega los conserva y refuerza.

No se ha inspeccionado la cuenta real de Ximena ni la base del VPS. Para establecer la causa en esa instalación hay que comparar el `org_id` de ambas cuentas con `diagnose-user`. No se afirma que estén vinculadas ni que el incidente de producción esté resuelto.

Cambios: creación de cuentas desde Configuración dentro de la organización del administrador, roles validados en backend, habilitación/deshabilitación y protección de la propia cuenta administradora; diagnóstico CLI, vinculación inicialmente en modo plan y bloqueo si existen registros, otras cuentas u obras/períodos personalizados. La aplicación de una vinculación vacía exige `--apply --backup`, valida el dump con `pg_restore --list`, registra su SHA256 y conserva la organización origen. Una fusión con datos queda bloqueada: requiere un plan particular, respaldo restaurado, mapeo de identidades y validación supervisada.

Los clientes consultan información actualizada cada 10 segundos y al recuperar el foco, con `Cache-Control: no-store`. Los cambios de permisos se comprueban en cada petición. Una sesión rechazada limpia la interfaz. Las preferencias controlan apariencia, densidad, obra inicial y avisos de actividad.

## Importaciones e integración

Se extiende el router y el lector XLSX/CSV existentes. Dos flujos especializados comparten el centro de importaciones. Se mantienen las rutas antiguas para archivos históricos y los importadores de contratos/anexos.

Encabezados de empresas confirmados por el usuario, en este orden:

`ID | OBRA | ESPECIALIDAD | NOMBRECONTRATISTA | RUT | COD | ESTADO | TELEFONO | CORREO | REPRESENTANTE LEGAL | RUTR.LEGAL`

Encabezados de trabajadores:

`NOMBRE CONTRATISTA | NOMBRE TRABAJADOR | RUT | F.INGRESO | F.TERMINO | CONTRATO | TIPO`

La obra de una plantilla de trabajadores sin OBRA procede del selector superior. También se admite columna OBRA y un RUT del contratista opcional mediante mapeo. Los espacios sin encabezado se ignoran sin desplazar posiciones. Se aceptan fechas chilenas, fechas de Excel e ISO. Indefinido y por obra admiten término vacío; plazo fijo requiere término. No se inventa significado para columnas vacías. `CONTRATO` conserva su referencia y `TIPO` determina la modalidad validada.

RUT + organización identifica la persona/empresa, y la relación con cada obra es independiente. El nombre normalizado del contratista y la obra solo vinculan trabajadores si la coincidencia es única. El RUT opcional resuelve homónimos. Se conservan episodios laborales en `contract_register`, usados por contratos, calendario y controles existentes. No se crea una segunda tabla de contratos ni de cotizaciones.

La vista previa muestra nuevos, existentes, actualizables, errores y observaciones; presenta diferencias exactas y permite editar/cargar correcciones y descargar observaciones Excel. Los cambios a existentes necesitan aprobación explícita. Un token de 30 minutos vincula usuario, organización, contenido y estado revisado; una edición concurrente exige volver a revisar. El commit es transaccional, con bloqueo de organización en PostgreSQL y restricciones únicas. Reimportar no duplica identidades, relaciones ni contratos. Se audita archivo, huella, usuario, fecha, valores y resultado. El lector limita bytes, contenido descomprimido, hojas, filas y columnas. Los Excel generados neutralizan celdas de fórmula.

`ID` permanece externo. COD no asigna CT/CI/ESP por sí solo; el administrador debe definir un mapeo explícito o clasificar la ficha. ESTADO usa un catálogo configurable. Las obras desconocidas no se crean automáticamente: debe hacerlo un administrador desde Configuración antes de revisar de nuevo.

## Cotizaciones, documentación e interfaz

Los controles de cotizaciones persisten en `contribution_controls`. Las revisiones de empresa persisten en `monthly_documents`, por lo que la interfaz anterior y la nueva leen los mismos datos. Solo las revisiones específicas de trabajadores requieren una tabla adicional. Se preservan aprobaciones y su invalidación cuando cambian las bases del control.

Se diferencian asistencia, días exigibles confirmados manualmente, días registrados, confirmación de pago, justificaciones y ausencia de información. Los contratos aportan una sugerencia de días, nunca una obligación confirmada automáticamente. Diferencia = requeridos − pagados; faltantes = máximo(0, diferencia). No se compensan faltantes con excedentes de otras personas. Estimación = faltantes × tarifa guardada en el control. Tarifas mensuales con vigencia desde el día 1; valor inicial $4.950 CLP. Cambiar el catálogo no reescribe controles históricos: al revisar/guardar se usa la tarifa aplicable y queda auditada.

El promedio usa los registros individuales con días informados, incluye ceros y excluye nulos; muestra denominador, cobertura, promedio de registros confirmados y datos faltantes. Nunca promedia promedios de empresas. Reporte XLSX con consolidado, hojas por obra y promedios por contratista/obra/general. CT/CI por naturaleza explícita; los esporádicos quedan fuera salvo filtro. Cada reporte pertenece a una competencia; cambiar mes no mezcla registros.

La navegación ofrece Inicio, Contratistas, Trabajadores, Control documental, Cotizaciones y asistencia, Importación masiva, Gestión administrativa, Informes y Configuración. La gestión administrativa reutiliza contratos/anexos, calendario, tareas y bajas existentes. Se retiran Historial OCR y Revisión OCR BETA de la navegación, conservando documentos, motor y visor como apoyo dentro de cotizaciones.

Dashboard con métricas reales, acceso a detalle, estados con texto y símbolos, actividad reciente, filtros de obra/período, perfil y preferencias persistentes. Una empresa sin clasificación o sin información permanece pendiente, sin atribuirle incumplimiento confirmado. Los documentos no aplicables no disminuyen su cumplimiento.

## Esquema y preservación

Se agregan seis tablas: `user_preferences`, `organization_settings`, `contractor_details`, `import_batches`, `retention_rates`, `worker_document_reviews`. No hay DROP, TRUNCATE ni ALTER de tablas históricas; `init-db` crea las faltantes. Los índices y restricciones se crean con las tablas nuevas. No se cambia el volumen PostgreSQL ni el almacenamiento privado.

El procedimiento de actualización existente hace backup de BD/archivos y ensayo de restauración aislada antes de sustituir contenedores. Leer [actualización de esta versión](VPS_0.5.0.md). El rollback de código conserva las tablas aditivas; no restaura la BD automáticamente sobre datos nuevos.

## Evidencia ejecutada

- Suite Python completa: 55 aprobadas en PostgreSQL 16 aislado, con `TEST_DATABASE_URL` y `PLATFORM_TEST_DATABASE_URL` explícitos. Sin pruebas omitidas. Incluye 8 nuevos escenarios de aceptación parametrizables para SQLite/PostgreSQL.
- 300 empresas, 300 trabajadores y repetición de archivos: verificadas las cantidades persistidas y ausencia de duplicados; encabezados exactos, columnas vacías y contratos históricos comprobados.
- Dos clientes HTTP independientes: mismos IDs de obras, contratistas, trabajadores y cotizaciones; modificaciones visibles sin volver a autenticar; viewer y organización externa rechazados.
- Chromium real, dos contextos aislados: creación y edición de contratista, creación de trabajador, importación Excel de trabajadores y cotizaciones visibles en la otra sesión; se abrieron todas las secciones. Capturas y comprobación de desbordamiento horizontal a 1440, 820 y 390 píxeles. Script: `scripts/qa_shared_browser.py`; requiere cuentas sintéticas y `QA_PASSWORD`.
- `npm run build`: TypeScript y Vite aprobados; versión 0.5.0-rc1.
- Imágenes backend y frontend construidas en Docker; en este entorno se montó la CA del proxy solo durante la instalación. API ejecutada como UID 10001 e inicialización aditiva verificada. Frontend servido por Nginx.
- Reinicio real del contenedor API: misma sesión autenticada y respuestas idénticas de contratistas, trabajadores, cotizaciones, revisiones y perfil contra la BD persistente.
- Shell: `bash -n scripts/*.sh`; Python compilado y `git diff --check`.

## Límites y verificaciones pendientes

- La aceptación con la cuenta real de Ximena y los datos reales debe ejecutarse en QA del VPS; no se utilizó información laboral real en pruebas.
- No se ejecutó una observación continua de 24 horas, una prueba de carga de gran escala ni un ensayo de recuperación del respaldo real del VPS en esta sesión. Existen scripts previos de QA/restore/soak para ello. El reinicio local de API no demuestra recuperación completa de un VPS.
- La vinculación de cuentas ya existentes entre organizaciones es un procedimiento supervisado en CLI, no un botón que mueva información desde la interfaz. Las invitaciones por correo y su entrega no se implementan; la creación de cuentas está operativa.
- La paginación y filtros del control de cotizaciones se sirven desde backend; las fichas y la matriz todavía cargan conjuntos completos antes de paginar visualmente. No se afirma optimización de todos los listados para decenas de miles de registros.
- Las revisiones y reglas son administrativas; no se conecta a Previred/DT/AFP para confirmar pagos. Los parámetros adicionales de cumplimiento normativo y un editor visual completo de catálogos quedan para revisión de negocio; los catálogos actuales se guardan realmente mediante validación de backend.
- La revisión responsive verifica rutas y desbordamiento; no equivale a una auditoría completa de accesibilidad ni a probar todas las acciones a cada tamaño.
