# GALANT 10.10.0-rc1 — estados, documentos y recuperación de navegación

> **Candidata para revisión.** No significa que esté fusionada ni desplegada.
> El VPS no se modifica desde este PR.

## Resumen técnico

### Auditor 1 — Datos y modelo de contratista
- `ops_api.contractors` limita la respuesta de `ContractorDetails.values` a campos escalares y los detalles de la obra solicitada. El campo `worksites` ya no viaja como objeto anidado al renderizador JSX.
- Los registros históricos y sus identificadores permanecen intactos. No se ejecutan migraciones destructivas.

### Auditor 2 — Exigibilidad por estado
- `document_policy.py` determina si la relación contratista-obra está activa y si el período es histórico.
- `control/matrix` **no genera exigibilidad nueva** en meses actuales o futuros para relaciones inactivas. Las evidencias anteriores siguen consultables y pueden revisarse.
- Para un mes histórico sin evidencia, no se presume que una empresa estuvo activa ni se inventa fecha de baja. Un responsable habilitado regulariza exigibilidad en `control/applicability` **con justificación obligatoria**.
- Las revisiones existentes de un período histórico permanecen y el sistema permite corregirlas sin reactivar la obra.
- `monthly-documents` y `control/reviews` rechazan la creación de exigencias nuevas a inactivos; los registros existentes siguen editables según permisos.
- Las matrices y los reportes operativos excluyen incumplimientos nuevos de inactivos. Los resultados anteriores se conservan.
- Estados legados `suspended` y `offboarding` se consideran no activos a efectos de obligaciones nuevas; no se alteran silenciosamente los valores almacenados.

### Auditor 3 — React y recuperación
- Nueva ficha de contratista en cinco pestañas y filtros `Activos | Inactivos | Todos`, predeterminado `Activos`.
- Estado visible por texto+color, distinto del semáforo documental.
- Trabajadores, contratos y finiquitos se consultan desde la API laboral compartida por obra.
- `ErrorBoundary` impide que errores de panel eliminen toda la navegación, permite reintentar o regresar al listado.
- Datos de detalles anidados no se interpolan directamente en JSX.

### Auditor 4 — Pruebas y regresiones
- `apps/backend/tests/test_v1010_active_documentation.py` prueba inactivos, documentación histórica, escenarios multiobra y JSON seguro.
- `scripts/qa_v1010_browser.py` usa un stack local desechable: crea Excel sintético, importa, abre y cierra fichas, cambia pestañas, verifica filtros, recarga, captura consola y pantalla.
- Integrado en GitHub Actions, con capturas artefacto cuando pasa.

## Advertencia sobre historial

**El archivo Excel actual no contiene fecha efectiva de baja.** Sin esa fecha no es correcto afirmar que un contratista estaba inactivo en un mes anterior. Esta versión conserva las evidencias registradas y permite corrección explícita de meses históricos; no inventa periodos ni los borra.

En una evolución posterior se recomienda capturar la fecha efectiva del cambio de estado como campo explícito y auditable.

## HTTPS y mensaje «No seguro»

La captura en navegador por sí sola no identifica la causa. Auditar en el VPS antes de modificar Caddy, Nginx o DNS:
- `curl -Iv https://galant.dpdns.org` desde un equipo de prueba (muestra certificado y código TLS).
- `docker compose --env-file .env.preview -f docker-compose.preview.yml logs --tail=150 proxy`.
- Comprobar certificado, SAN, confianza, vencimiento, redirección HTTP→HTTPS y contenido mixto desde las herramientas de desarrollador.
- No desactivar verificaciones TLS para resolverlo ni exponer secretos.

## Instalación VPS

El runbook obligatorio sigue en `docs/INSTALACION_VPS_CADA_VERSION.md`.
**No desplegar desde la rama**. Esperar merge y CI verde, utilizar SHA fijo del commit aprobado y `scripts/update-preview.sh` con respaldo PostgreSQL y verificación de restauración.
Después comprobar salud y versiones del frontend y backend, los filtros y el acceso al contratista antes de reimportar Excel.
