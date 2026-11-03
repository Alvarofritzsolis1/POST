## Problema y resultado

Crear cada cuenta con `create-admin` separa a los colaboradores en organizaciones diferentes. Esta candidata agrega administración web de cuentas dentro de la organización existente y refuerza la vinculación supervisada, manteniendo los filtros de aislamiento. Las sesiones de la misma organización ven las mismas obras, contratistas, trabajadores, importaciones y controles, con actualización automática.

Se amplía el centro de importación existente con plantillas de empresas y trabajadores cuyos encabezados fueron confirmados por el usuario, validación chilena, varias obras, vista previa, diferencias aprobadas explícitamente, prevención de concurrencia y commit transaccional. Los contratos y cotizaciones se guardan en los registros existentes. Nuevo espacio de trabajo con métricas reales, cobertura y promedios ponderados, tarifa temporal de retención estimada, reportes Excel por obra, perfil, preferencias y navegación funcional sin módulos OCR BETA separados.

## Validación

- 55 pruebas Python aprobadas en PostgreSQL 16 aislado, sin omisiones: dos clientes, permisos, aislamiento, importación de 300 empresas/300 trabajadores, repetición, errores, fechas, conservación de contratos, promedios individuales, tarifa temporal, reportes y revisiones persistentes.
- Chromium con dos contextos independientes: contratista, trabajador, modificación, importación Excel de trabajadores y control previsional compartidos sin nuevo login; rutas principales y tamaños de escritorio/tablet/móvil.
- TypeScript + Vite compilan; imágenes Docker de ambos servicios construidas. Backend como UID 10001; registros y sesión preservados tras reinicio real de API con PostgreSQL persistente.
- Sintaxis shell, compilación Python y diff sin errores de espacios.

No se usaron datos laborales reales ni se accedió al VPS. La prueba de aceptación con las cuentas reales y el ensayo continuo de 24 horas siguen pendientes. No se afirma que el incidente real de Ximena esté resuelto.

## Migración y despliegue

Versión visible: **0.5.0-rc1**. Se agregan seis tablas; no se altera ni elimina ninguna tabla histórica. Requiere `init-db` después de respaldo y restauración aislada. El actualizador existente ejecuta esas salvaguardas y conserva los volúmenes. Mantener deshabilitado el despliegue automático hasta aprobar QA.

- [Entrega, evidencia y límites](docs/ENTREGA_0.5.0.md)
- [Matriz problema/causa/gravedad/solución/prueba](docs/AUDITORIA_0.5.0.md)
- [Comandos exactos de actualización y vinculación supervisada](docs/VPS_0.5.0.md)

## Alcance pendiente

No se automatizan fusiones de organizaciones con datos ni invitaciones por correo. El enlace de una cuenta ya existente entre organizaciones sigue siendo CLI con plan y respaldo. Las fichas/matriz conservan consultas completas; la paginación de cotizaciones está en backend, pero la optimización de todos los listados, una prueba de carga amplia y la auditoría completa de accesibilidad quedan pendientes. La candidata requiere revisión antes de considerarse una implementación completa de todos los puntos solicitados.
