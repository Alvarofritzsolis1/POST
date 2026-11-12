# GALANT 17.0.0-rc1 — Biblioteca inteligente de Proyecto JAVIERA

## Objetivo y origen de las 10 plantillas

El usuario proporcionó un libro XLSX original y una copia editada de aproximadamente 408 KiB:
`GALANT_JAVIERA_10_PLANTILLAS_EDITABLES.xlsx`.

Contiene 10 hojas imprimibles más hojas de datos y matrices. **El archivo XLSX no se almacena en GitHub**: debe seleccionarse una vez desde el computador en la nueva Biblioteca inteligente de Proyecto JAVIERA. El backend lo valida, lo guarda en el repositorio documental privado de la organización y genera 10 borradores editables para revisión, conservando su formato original.

No se inventan cláusulas laborales ni se publica automáticamente nada. La fuente aprobada de cada PDF es el Excel original, una vez importado y aprobado.

## Nuevo funcionamiento

1. Abre **Proyecto JAVIERA → Biblioteca inteligente**.
2. Selecciona el Excel previamente preparado o una copia corregida. La importación unificada exige las **10 hojas reconocidas**. Si falta una, la API responde qué hoja es.
3. GALANT genera las 10 fichas editables, muestra los estados reales y evita crear duplicados cuando se vuelve a importar exactamente el mismo archivo (SHA-256).
4. Cada hoja se puede previsualizar como **PDF de muestra**, sin datos laborales reales, antes de la publicación.
5. El autor puede ajustar diseño o texto desde **Diseños Excel originales**, conservando versiones. No es necesario volver a transcribir los textos ni editar cada documento para cada persona.
6. El administrador crea una cuenta con perfil **Revisor documental**, le asigna especialidad laboral o preventiva y registra su designación.
7. La persona revisora accede a una mesa limitada, comprueba la vista previa, marca cada requisito y registra fundamento de al menos 40 caracteres. En una misma acción registra el acta **y publica esa revisión**; nunca puede revisar sus propios documentos.
8. Una vez aprobada una plantilla, el administrador puede preparar los PDF por empresa/trabajador desde el generador independiente de v16.6; los archivos emitidos conservan historial e inmutabilidad.

## Seguridad y criterios

- Los usuarios con rol `doc_reviewer` solo pueden consumir `/api/v1/javiera/v17/review/*`, login y logout. No pueden acceder a contratistas, trabajadores, asistencia, configuración general, importaciones ni documentos privados fuera de la revisión designada.
- El perfil existe en la gestión de cuentas sin requerir acceso a una obra; debe ser designado por un administrador **distinto del usuario receptor**.
- Es obligatorio contar con autorización por especialidad en `JavieraReviewerAuthorization`.
- Separación autor/revisor se aplica en el servidor. Una revisión nunca se convierte en una certificación legal automática.
- Los archivos Excel se guardan por organización en almacenamiento privado; nunca se incorporan al repositorio ni a datos operativos.
- Reimportar el mismo SHA-256 no reemplaza ni borra versiones previas. Un Excel corregido genera nuevas versiones en borrador.
- Siguen vigentes la integridad PDF, los archivos ya emitidos, las matrices preventivas aprobadas y las exigencias de evidencia de actos reales (entrega, inducción, recepción).

## Tipos de documentos

| Sección | Documento | Hoja de referencia |
|---|---|---|
| Subcontratos | Contrato de trabajo | Contrato Imprimible |
| Subcontratos | Anexo de traslado | Anexo Traslado |
| Subcontratos | Prórroga | Anexo extension contrato |
| Subcontratos | Declaración jurada | DECLARACION JURADA |
| Prevención | Reglamento Interno | REGLAMENTO INTERNO |
| Prevención | Entrega de EPP | Registros Entrega EPP |
| Prevención | IRL | IRL |
| Prevención | PTS | PTS. |
| Prevención | Recepción de PTS | ENTREGA PTS |
| Prevención | Inducción | INDUCCION PREVENCION |

## Pruebas exigidas antes de despliegue

- Suite backend, frontend TypeScript, Docker Compose, backup/restauración y QA en navegador.
- Importación XLSX de 10 hojas sin efectos operativos, idempotencia y aislamiento por organización.
- Creación de revisor limitado y rechazo de operaciones en módulos operativos.
- Impedimento de autoaprobación y de aprobar otra especialidad o revisión antigua.
- Vista previa con identidades sintéticas, generación PDF individual y batch; comparar visualmente con el Excel original real.
- Prueba de versión/commit y salud del VPS después de integrarlo.

**Límites de esta PR:** el XLSX real debe importarse desde la interfaz por el administrador; no está empaquetado en el repositorio. Tampoco se ejecutan automáticamente aprobaciones ni se pueden certificar firmas reales por el PDF. No afirmar que está en el VPS sin resultado exitoso del flujo de despliegue y verificación de su endpoint de salud.

## Actualización

Tras CI verde, revisión del PR, respaldos y aprobación explícita de publicación, la integración en `main` activará el despliegue seguro existente. El servidor utiliza `/opt/galant-post` y no `/root/POST`. Ver `scripts/update-preview.sh` para el procedimiento exacto con respaldo, restauración verificada, migración aditiva, pruebas de salud y rollback.
