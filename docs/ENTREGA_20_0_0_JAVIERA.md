# GALANT 20.0.0-rc1 — Proyecto Javiera

Candidata implementada en React/FastAPI/PostgreSQL sobre el repositorio existente. El nuevo recorrido usa un XLSX privado como fuente de contenido, edición de celdas y cláusulas en el navegador, revisiones inmutables, recálculo Calc y un único flujo Excel→PDF. El reinicio administrativo deja vacíos los documentos activos mediante archivo reversible y respaldo verificado.

**La migración integral no se declara terminada ni está desplegada en el VPS.** Persisten defectos del archivo fuente y limitaciones del editor descritos abajo. No se registraron aprobaciones profesionales ni firmas reales; la base QA quedó con cero expedientes activos y cero formatos publicados.

## Archivo recibido y base limpia

El archivo real difiere de las cifras del prompt:

| Elemento | Original recibido | Maestro limpio derivado |
|---|---:|---:|
| Hojas | 33 | 34 |
| Fórmulas | 384 | 395 |
| Recursos gráficos | 18 | 18 |
| Recursos EMF | 17 | 17 |
| Áreas de impresión | 20 | 20 |

SHA256 original: `4f063b135d5e9c0d7f9806b57d1cd340bd2ecac78fed77345ffa7ccabbead292`.

La hoja adicional `GALANT Datos` contiene entradas explícitas para la empresa mandante y la nacionalidad del representante. Los once vínculos nuevos sustituyen entradas fijas o estáticas; se mantienen las posiciones de las 384 fórmulas originales. Las fórmulas originales se corrigen únicamente donde se detectaron referencias equivocadas o datos del ejemplo.

El original se guarda separadamente, en un archivo privado de solo lectura con SHA256. La revisión limpia vacía nombres, RUT, fechas, remuneración, cantidades EPP y demás entradas del ejemplo. También retira los hipervínculos de correo de las entradas vaciadas y elimina resultados de fórmulas y textos compartidos que podían conservar copias invisibles de esos datos. Las matrices, estilos, combinaciones, dibujos y configuraciones de impresión permanecen. Se comprobó la igualdad SHA256 de los 18 recursos gráficos antes y después.

La importación original y la limpieza son dos revisiones auditables. Para conservar la trazabilidad del archivo recibido, se recomienda importar el adjunto original: GALANT crea automáticamente la revisión limpia. El Excel limpio entregado también puede utilizarse como punto de partida, con su propio hash de importación.

## Cambios funcionales

- Nueva configuración con Plantillas Excel, Matrices y cargos, y Configuración y versiones. Edición por cuadrícula, barra de fórmula, edición de fragmentos de cláusulas sin reescribir sus referencias, deshacer/rehacer, copia de estilos, altura de filas, guardado con motivo y aviso de cambios pendientes.
- Guardado directo en OOXML. El maestro no se regraba con openpyxl ni con Calc: esto evita perder los EMF. Cada modificación crea un XLSX nuevo; un control atómico de revisión impide sobrescribir cambios de otro editor.
- Navegación por las hojas originales, incluida `IRL ` con espacio final. Selección de cargo mediante sus claves exactas y acceso a las filas de las matrices del libro. No se crea otra fuente editable JSON de contenido preventivo.
- Generación por obra, empresa, trabajador, cargo y documento, con campos adicionales según el documento seleccionado. Se reutilizan los antecedentes disponibles de la empresa y las fechas contractuales registradas. Cambiar o crear otro trabajador limpia los antecedentes personales del anterior.
- Calc recalcula el libro completo en una copia aislada. Se validan errores y dependencias de las celdas utilizadas por el documento. Se exportan únicamente las hojas solicitadas, manteniendo papel y márgenes originales; el flujo nuevo no normaliza todos los PDF a A4 ni representa el documento con HTML.
- Las matrices se contrastan con los resultados del IRL/PTS por cargo. Los riesgos que superan doce registros continúan en copias de la tabla original dentro del propio Excel de conversión. Los datos preventivos incompletos o procedimientos de clave duplicada incompatibles bloquean su emisión.
- Caché privado por organización, contenido del maestro, datos, cargo, modo y versión del renderizador; deduplicación de solicitudes concurrentes; verificación del hash de cada PDF reutilizado. Las emisiones existentes conservan su archivo e instantánea.
- Servicio Calc persistente mediante UNO, con una conversión por servicio, límite de espera, tiempo máximo y contenedor limitado. La API admite hasta dos solicitudes de conversión concurrentes. La conversión CLI de Calc sigue disponible si no se configura el servicio persistente; es el mismo motor, no otro generador documental.
- Se mantienen autenticación, CSRF, aislamiento por organización y designación de revisores. Publicar requiere una revisión profesional registrada por alguien distinto del autor y una vista previa comprobada del formato.

Se retiraron del recorrido principal el editor tradicional de texto/HTML, las matrices independientes y los paneles duplicados de versiones anteriores. Las rutas y tablas históricas permanecen para conservación y rollback mientras la sustitución no esté completamente validada. No hubo borrado masivo de archivos del repositorio.

## Correcciones comprobadas del libro

- `IRL!A61:D61` contenía datos fijos de carpintería. Ahora utiliza el registro de índice 8 del cargo; `A63:D63` mantiene el índice 9. Se verificó el cambio de una actividad de PINTOR en su matriz y su recálculo en `IRL!A63` desde el navegador.
- Ciudades y obra del ejemplo en contratos/anexo de traslado pasan a referencias nativas. Se evitan restos del ejemplo cuando cambian los datos.
- La declaración jurada usa la nacionalidad del representante, el período solicitado y la mandante real, conservando las fórmulas Excel. Se bloquea cuando hay trabajador asignado o dotación incompatible.
- La prórroga exige una fecha posterior al término anterior y completa el dato de origen del anexo. EPP vacía todas las cantidades premarcadas y rellena únicamente los elementos declarados; rechaza descripciones ambiguas.

## Validación y evidencia

Pruebas realizadas en el entorno QA de esta sesión, con usuarios y antecedentes sintéticos; no contra producción.

| Verificación | Resultado |
|---|---|
| Suite completa backend, con PostgreSQL configurado | 212 aprobadas, 15 omitidas |
| Regresión documental con Calc 25.2.3 dentro de Docker | 32 aprobadas; cubre las 13 pruebas PDF omitidas por falta del ejecutable `libreoffice` en el host |
| Omisiones restantes | 2 escenarios de bloqueo no aplicables a SQLite; sus variantes PostgreSQL se ejecutaron |
| Lógica frontend | 17 aprobadas |
| TypeScript y build Vite | Aprobados |
| Importación, celda, cláusula, deshacer/rehacer, matrices y persistencia en navegador | Aprobados |
| Fórmula matriz → IRL y vista previa con expediente | Aprobados para PINTOR |
| Dos guardados PostgreSQL realmente simultáneos | Un 200 y un 409; una sola revisión creada |
| Solicitudes simultáneas del mismo contenido | Una sola conversión; reutilización comprobada |
| Caché HTTP | PDF repetido con el mismo SHA256, 30 lecturas por formato |
| Reinicio, SHA256 del respaldo, restauración y nuevo reinicio | Aprobados desde el navegador |
| Cambio de trabajador | Sueldo y domicilio anteriores vaciados |
| Datos operativos ajenos a Javiera | Preservados en pruebas de integridad y recorrido QA |
| Consola y API durante los recorridos | Sin errores de JavaScript ni respuestas 5xx |
| Anchos 1440, 1280, 1024 y 768 | Sin desbordamiento horizontal de toda la página |
| Compose adicional y sintaxis Python | Validados |

Los ocho formatos no bloqueados se generaron con datos nuevos: contrato, traslado, prórroga, declaración jurada, reglamento, EPP, PTS y entrega PTS. Se verificaron identidades nuevas y remuneración numérica/en palabras. IRL de PINTOR produjo seis páginas con trece actividades. GASFITER incorpora sus veintiséis registros, aunque estén en bloques no contiguos, en siete páginas con dos continuaciones Excel. Se comprobó que los 52 y 104 campos preventivos respectivamente aparecen completos en el PDF. Todos son borradores de QA; ninguna prueba constituye una aprobación laboral o preventiva.

## Rendimiento medido

Comparación controlada en la misma imagen Docker y versión de Calc, con idéntico maestro, datos y fuentes:

| Operación | Medición |
|---|---:|
| Contrato nuevo, Calc CLI sin proceso preparado | 4.265 ms totales; 3.559 ms de conversión |
| Contrato nuevo, Calc UNO persistente | 1.186 ms totales; 1.143 ms de conversión |
| Caché de conversión, 100 lecturas locales | p50 0,369 ms; p95 0,567 ms |
| Vista previa de contrato, HTTP + PostgreSQL | primera 1.538 ms; caché p95 36,67 ms |
| Vista previa IRL, HTTP + PostgreSQL | primera 2.627 ms; caché p95 24,34 ms |

Las mediciones HTTP incluyen la ida y vuelta local, validación, consulta y lectura del archivo. No representan tiempos de Internet ni del VPS del usuario. En una comparación adicional, el ejecutable de desarrollo del host (LibreOfficeDev 26.8 alpha) tardó 30,5 s; **no** se usa ese resultado para atribuir una mejora al proceso persistente, porque es otra versión del motor.

Se observó el contenedor del motor con 780,7 MiB y 0,15 % de CPU tras las pruebas; es una observación, no un máximo de consumo. El perfil fija 1 GiB para el motor. Quedan pendientes carga sostenida, medición de picos, apertura del módulo/editor, percentiles del VPS y pruebas prolongadas. No se declara estabilidad de 24 horas.

## Bloqueos reales y límites de esta candidata

1. **CARPINTERO:** `MATRIZ IRL`, fila 40, tiene riesgos/medidas incompletos. Su IRL se bloquea hasta completar y revisar esa información; no se inventó contenido.
2. **Inducción original:** la página 11 recorta el encabezado; el texto tiene coordenada superior aproximada de −2,46 pt. Se inspeccionó visualmente el PDF. El formato no se habilita mientras persista ese recorte. No se reescaló ni se eliminaron imágenes para ocultarlo.
3. **Editor completo:** se implementó un editor nativo de celdas, fórmulas y fragmentos de cláusulas; conserva imágenes en el archivo, pero no las reproduce en su cuadrícula y la edición de formato se limita a copiar estilos/altura. ONLYOFFICE Docs no está integrado ni probado con este libro. Se verificó su licencia AGPL-3.0 en la fuente oficial, pero no su fidelidad EMF, concurrencia ni edición de formatos. Por ello este requisito amplio del prompt continúa pendiente.
4. **Fidelidad final y cobertura:** no se ha contrastado con una impresión patrón aprobada de Microsoft Excel ni se han habilitado todos los formularios IND como emisiones independientes. Las hojas están disponibles para edición, pero no se afirma equivalencia documental completa ni cobertura de todos los cargos.
5. **Publicación y VPS:** no se hicieron revisiones profesionales reales, despliegue, limpieza de producción ni ensayo de rollback en el VPS. El objetivo de la arquitectura completa sigue pendiente de esos controles.

Referencia de licencia consultada: https://github.com/ONLYOFFICE/DocumentServer/blob/master/LICENSE.

## Reinicio administrativo

La operación está limitada a la organización y al módulo Javiera. Primero muestra el inventario de expedientes, PDF y antecedentes que saldrán del espacio activo. Requiere un motivo y el hash del plan vigente. Se respalda la información del módulo y sus archivos privados; se verifica cada archivo y el ZIP antes de archivar registros. Se vacían publicaciones antiguas y caché; se deshabilita el fallback documental antiguo para esa organización.

Los originales sujetos a conservación no se destruyen. Los registros quedan archivados y el respaldo permite revisar y restaurar la operación. Los reinicios se restauran del más reciente al anterior. Obras, empresas, trabajadores, asistencia, mensual, usuarios, permisos y Red de Obras permanecen fuera de la limpieza.

El resultado comprobado de la sesión QA es **0 expedientes activos y 0 plantillas publicadas**. No se debe interpretar como limpieza del VPS real.

## Preparación de despliegue y rollback

La rama dedicada contiene la versión `20.0.0-rc1`; la identificación exacta se entrega en `REVISION.txt`. No fusionar/activar la migración completa mientras no se acepten sus límites y se resuelvan los bloqueos aplicables.

1. Seguir el procedimiento existente de respaldo de PostgreSQL/documentos y ensayo de restauración del repositorio. Conservar el commit y las imágenes de la versión anterior.
2. Construir la imagen backend con `SOURCE_COMMIT` igual al commit entregado. La imagen instala `libreoffice-calc` y `python3-uno`.
3. Configurar en el archivo privado de entorno `JAVIERA_CALC_SECRET` con un secreto aleatorio de al menos 32 caracteres. No publicarlo en Git ni introducirlo en el chat.
4. Agregar `-f docker-compose.javiera20.yml` al comando Compose habitual. El servicio `javiera-calc` no publica puertos; la API utiliza su red interna y el secreto compartido. El perfil Compose se validó, pero no se desplegó en el VPS.
5. Ejecutar la migración aditiva con el mecanismo existente `python -m app.cli migrate-db --verified-backup-sha256 HASH_VERIFICADO`. La migración `20.0.0_excel_master_workspace` crea cinco tablas y no altera ni borra las anteriores.
6. Importar el Excel desde Configuración de automatización. El original y su hash quedan privados; se crea una revisión limpia. Ejecutar el reinicio de Javiera solo sobre el inventario revisado.
7. Resolver la calidad de matrices y la impresión de los formatos pendientes. Designar responsables, comprobar PDF con datos autorizados, registrar las revisiones profesionales y publicar únicamente los formatos aceptados.
8. Verificar `/api/v1/health`, versión/commit, acceso entre organizaciones, descarga, caché, memoria y comportamiento real en el VPS.

Para rollback, restaurar primero el reinicio de Javiera cuando corresponda y volver al commit/imágenes anteriores. Las tablas nuevas son aditivas; las históricas y los documentos emitidos permanecen disponibles. No ejecutar `docker compose down -v`. Un rollback completo de datos debe seguir el procedimiento de restauración verificada existente.
