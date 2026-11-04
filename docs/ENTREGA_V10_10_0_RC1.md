# GALANT POST 10.10.0-rc1 — Contratistas activos y estabilidad

## Cambios implementados

- El backend `GET /api/v1/ops/contractors` devuelve solo detalles escalares de la empresa y la obra seleccionada. Esto corrige el caso identificado donde React intentaba renderizar un objeto anidado `worksites` y perdía toda la pantalla.
- Los módulos de contratistas y trabajadores quedan aislados por un Error Boundary que permite reintentar sin cerrar la sesión.
- Contratistas tienen filtro de Activos (predeterminado), Inactivos y Todos; semáforos con texto verde y rojo; tabla simplificada; ficha con pestañas de resumen, trabajadores, documentos e historial.
- El control documental mensual marca como **no exigibles** a contratistas inactivos durante el mes actual y meses futuros, excluyéndolos de las métricas. No destruye los registros históricos ni inventa retrospectivamente fechas de baja.
- El módulo de asistencia evita nuevas revisiones obligatorias para contratistas inactivos en períodos actuales/futuros. Revisiones y firmas históricas se conservan.
- Dashboard documental distingue inactivos en vez de presentarlos como pendientes.

## Limitación histórica importante

El esquema de GALANT todavía no registra una fecha de vigencia confiable para **todos los cambios históricos** de estado. No es posible garantizar qué contratistas estaban activos en meses anteriores solo mirando su estado actual. Por seguridad, la versión **no anula retroactivamente** obligaciones previas: se conserva su información hasta revisar fechas efectivas y evidencia documental. Una fase posterior puede incorporar una línea de tiempo auditable de actividad por obra.

## Validaciones obligatorias

1. Ejecutar `python -m pytest -q` desde `apps/backend`.
2. Ejecutar `npm ci && npm run build` desde `apps/frontend`.
3. Probar manualmente o con Playwright la apertura de fichas de contratistas que tienen `ContractorDetails.values.worksites` anidado y verificar que no aparezcan pantallas blancas.
4. Probar filtros combinados CT/CE/CI y ACTIVOS/INACTIVOS/TODOS en varias obras.
5. Probar paso a trabajadores, retorno, búsqueda y consulta de finiquitos/contratos.
6. Verificar que la revisión documental actual de inactivos no genere incumplimientos ni pendientes nuevos y que el período anterior conserve su historial.
7. Revisar fallas de consola, red y visualización bajo datos nulos y cambios rápidos de obra.
8. Auditar TLS del VPS (`galant.dpdns.org`) en forma separada; **no se ha modificado el certificado, DNS ni Caddy**.

## Auditoría por especialidad

- Arquitectura: separación de estado por relación contratista-obra y conservación histórica.
- Frontend: componentes que renderizan datos anidados, filtros y semáforos.
- Backend: comprobación de exigibilidad y protecciones de permisos.
- QA: tests de API y ejecución de GitHub Actions.
- Supervisión: revisión independiente del PR antes de merge, despliegue seguro y reimportación.

No afirmar que estas revisiones fueron ejecutadas por agentes autónomos si no se tiene evidencia de sus ejecuciones.

## Instalación segura

Solo después de CI y QA satisfactorios, fusionar y utilizar el SHA exacto aprobado del merge en `docs/INSTALACION_VPS_CADA_VERSION.md`. El actualizador `scripts/update-preview.sh` realiza respaldo, restauración aislada y comprobaciones de salud. **El VPS no se modifica al crear esta rama o PR.**
