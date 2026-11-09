# GALANT 16.6.0-rc1 · Proyecto JAVIERA independiente (candidata)

## Alcance real implementado
- Nuevo asistente accesible desde Proyecto JAVIERA: **Empresa nueva / existente → Documentos → Antecedentes → Revisión e impresión → Historial**.
- Catálogo de las diez plantillas dividido en Zona Subcontratos y Prevención de Riesgos, selección múltiple y campos compartidos.
- Almacenamiento independiente en las tablas `javiera_local_companies`, `javiera_local_people`, `javiera_local_dossiers`, `javiera_local_issues` y `javiera_local_batches`.
- Registros operativos de empresa y trabajador utilizados como **fuente de lectura** con copia documental propia. No se utiliza `opsApi.createWorker` ni `opsApi.createContractor` en el nuevo asistente.
- Endpoints nuevos `/api/v1/javiera/v166/*`. Los endpoints previos siguen disponibles para consulta de expedientes heredados y compatibilidad, pero el nuevo asistente no los utiliza para insertar o actualizar entidades operativas.
- Emisión individual y batch con evaluación por evento correspondiente a cada documento, reemisión con motivo, archivos originales inmutables, PDF conjunto e historial.
- Estado pendiente de verificación: aprobación real de las plantillas Excel privadas y matriz legal/preventiva. Nunca asumir que un borrador equivale a documento emitible.

## Cambios de seguridad
- Todas las operaciones usan rol administrador y filtro por organización.
- La selección de persona exige pertenecer a la empresa documental y obra.
- El historial PDF se entrega exclusivamente por ruta privada validada.
- La emisión no marca automáticamente entrega de EPP, firma ni inducción.

## Diagnóstico
En GALANT 16.5 `JavieraWorkspace.tsx` llamaba a `opsApi.createWorker`/`opsApi.createContractor` en `saveDossier()`, por lo que una ficha documental terminaba incorporando entidades operativas. La versión 16.6 reemplaza ese flujo visible por identidad documental independiente.

El problema histórico de HTTP 500 por permisos de la carpeta privada en CI se corrigió previamente en v16.5; **no atribuir un fallo del VPS a esa causa sin consultar sus logs**.

## Pruebas pendientes de confirmación
CI del PR: compilación frontend/backend, migración aditiva, pruebas API nuevas y regresión, render PDF real y QA de navegador del nuevo recorrido. La verificación real en VPS depende de que el PR pase CI, se apruebe y se integre.
