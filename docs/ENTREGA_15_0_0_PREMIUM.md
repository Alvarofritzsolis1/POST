# GALANT POST 15.0.0-rc1 — Entrega Premium UX

**Versión de partida:** main 13.1.0-rc1, commit `b91052939b21e286334a0e5d5cde2dece9460675`.
**Objetivo:** mejorar legibilidad, jerarquía y flujo documental sin reconstruir la aplicación.
**Estado:** candidata en rama para revisión, sin despliegue a VPS.

## Cambios reales
- Se añade `v15-premium.css`, una capa compartida para la shell del administrador y Configuración General; conserva las preferencias de modo oscuro y movimiento reducido.
- La ficha de contratista en `Operations.tsx` inicia en Documentación, muestra una sola cabecera y dos indicadores principales.
- La cifra de cumplimiento utiliza `required_count` y `approved_count` de la matriz existente; sin obligaciones evaluables no se declara 100%.
- Las prioridades permiten navegar al requisito mensual correspondiente; el período de la tabla y los indicadores se mantiene sincronizado.
- Revisiones manuales en `MonthlyDocuments.tsx`: un botón desplegable por requisito, observaciones visibles y refresco del indicador superior tras guardar.
- Se mantiene el archivo histórico cuando está disponible, sin crear cargas nuevas de documentación.
- Los contratistas se presentan en orden alfabético para facilitar búsqueda.
- Los valores de versión frontend y backend pasan a `15.0.0-rc1`.

## Alcance conservado
- Asistencia semanal, sus plazos, retroactividad, firmas y permisos.
- Gestión administrativa, evaluación y Red de Obras.
- La configuración general 13.1 con exigencia de Portería, periodos históricos, excepciones y auditoría.
- Aislamiento entre organizaciones, roles, APIs, OCR, cotizaciones y cálculo de retenciones.
- Esquemas PostgreSQL y migraciones existentes.

## No completado aún
Este incremento **no representa la implementación total de todas las fases del prompt maestro**. Quedan pendientes la revisión visual individual de todas las secciones, pruebas de usabilidad con usuarios reales, corrección iterativa de responsive y validación de datos de VPS. No se han ejecutado pruebas del servidor productivo.

## Pruebas pendientes para aprobar PR
```bash
cd apps/frontend
npm ci
npm run build
cd ../backend
pytest -q
```

Además, QA con datos sintéticos y al menos 390, 768, 1024, 1280, 1440 y 1920 px. Validar apertura y cierre de ficha, Atrás/Adelante, período, revisión manual, indicador actualizado, prioritarias, restricciones de roles, informes de Portería y ausencia de carga documental en Configuración General.

## VPS
No desplegar ni ejecutar migraciones hasta confirmar CI, pruebas visuales, respaldo y simulación de restauración de PostgreSQL/documentos. No usar `docker compose down -v`. Para un despliegue posterior, utilizar el script de actualización segura del repositorio con SHA fijado y verificación de `/api/v1/health`.
