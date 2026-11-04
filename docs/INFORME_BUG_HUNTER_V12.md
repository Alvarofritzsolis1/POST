# GALANT 12.0.0-rc1 — Informe de auditoría BUG HUNTER

**Base auditada:** GALANT POST `10.10.0-rc1` en `main`, SHA `07453a42d6f75258e7b389cc97eb44e7e05a34c1`.

**Alcance real:** revisión dirigida de permisos y reglas documentales/laborales, clasificación CT/CE/CI, aislamiento por obra, API FastAPI, PostgreSQL y cobertura de regresión; auditores automáticos de código y dependencias. Esto **no** equivale a certificar todo el proyecto ni a ejecutar diez agentes autónomos.

## Hallazgos identificados por inspección del código

| ID | Severidad | Ruta/archivo | Reproducción programada | Corrección |
| --- | --- | --- | --- | --- |
| BH12-01 | P1 | `labor_api.py:POST /labor/workers` | Empresa con COD=CT en obra A y COD=CI en B; la naturaleza global 'with_workers' permitía crear un trabajador en B | Restringe por COD de la **relación obra-contratista** |
| BH12-02 | P1 | `ops_api.py:PATCH /contractors/{id}` | Cambiar a CI una asociación CT con trabajadores activos no comprobaba sus asignaciones | Rechaza transición incompatible con HTTP 409 |
| BH12-03 | P1 | `monthly_api.py:POST /monthly-documents` | El frontend ocultaba formularios, pero el endpoint aceptaba documentos exigibles en mes actual de una asociación inactiva | Regla temporal centralizada; bloqueo en backend y bloqueo de concurrencia de la asociación |
| BH12-04 | P2 | `labor_api.py:GET /labor/alerts` | CI válido con frecuencia legada 'unclassified' generaba una alerta falsa | Solo COD explícito CT/CE/CI define la clasificación |
| BH12-05 | P1 (preventivo) | `labor_api.py:POST /labor/contracts` | Una asignación heredada con COD=CI permitía registrar otro contrato laboral | Impide nuevos contratos dependientes bajo CI |
| BH12-06 | P2 | `labor_api.py:GET /labor/contractors` | Las opciones del selector mostraban naturaleza global, equivocada para CI en una de dos obras | Respuesta por obra y clasificación efectiva |

**Nota:** la severidad refleja impacto potencial; pasar una prueba de regresión confirma que la conducta está corregida en el código probado, no demuestra que la plataforma completa está libre de defectos.

## Pruebas de regresión nuevas

`apps/backend/tests/test_v12_bug_hunter.py` cubre:

1. Empresa compartida entre dos obras (CT en una, CI en la otra), con intentos de crear trabajadores prohibidos y creación válida en CT.
2. Denegación de reclasificación CT → CI cuando tiene trabajadores activos.
3. Denegación de contratos nuevos bajo CI con asignaciones históricas inconsistentes.
4. Rechazo de nuevos vínculos documentales de inactivos en mes actual; consulta y revisión de evidencia anterior sin pérdida.
5. Ausencia de falsas alertas de clasificación en CI legítimo con frecuencia heredada sin completar.

La suite existente continúa siendo requerida: `python -m pytest -q` y `npm run build`.

## Auditorías independientes

`.github/workflows/bug-hunter-v12.yml` ejecuta análisis estático con Ruff y auditorías de dependencias npm y pip. Sus informes JSON quedan almacenados en los artefactos de GitHub Actions. Son análisis **informativos**: vulnerabilidades detectadas requieren validación y las herramientas no reemplazan un pentest ni certifican la ausencia de problemas.

La suite principal incluye Docker Compose, restauración sintética de respaldo, pruebas de frontend, pruebas backend y navegador en QA aislada.

## Limitaciones y riesgos no resueltos

- Los meses anteriores a la baja necesitan fecha efectiva auditada; la aplicación no retrocede obligaciones históricas sin evidencia.
- La auditoría no tuvo acceso de shell al VPS de producción, por lo que no verificó certificados HTTPS, CPU/RAM reales, DNS, secretos ni ocupación de volúmenes.
- No se realizaron pruebas de penetración reales ni cargas de 5.000 trabajadores en infraestructura productiva. Cualquier benchmark debe ejecutarse en QA con datos sintéticos.
- No se inició una tarea remota Codex: el conector de tareas no ofreció acciones ejecutables en esta sesión. Los chequeos independientes de GitHub Actions son verificables, pero no deben presentarse como diez agentes distintos.
- Las métricas de optimización quedan pendientes de medición reproducible. No afirmar reducciones de consumo sin un perfil comparativo.
- El código del repositorio no equivale a lo instalado en el VPS; el despliegue debe ser decisión separada, con SHA aprobado y backup/restauración probados.

## Entrega

Versión candidata: `12.0.0-rc1`, rama `audit/galant-v12-0-bug-hunter-20261104`.

**Estado de validación al redactar:** inspección y pruebas implementadas; resultados de GitHub Actions pendientes. No fusionar ni desplegar si falla cualquier test obligatorio.

Para instalar tras aprobar la PR, seguir `docs/INSTALACION_VPS_CADA_VERSION.md` y el script `scripts/update-preview.sh` con el SHA exacto del commit fusionado.
