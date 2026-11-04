# GALANT POST — v8.1.0-rc1 · Guía de revisión y publicación

**Estado: CANDIDATA, NO PRODUCCIÓN.** PR #16 en rama `feature/galant-v8-1-three-roles-foundation`.
No instalar ni fusionar hasta obtener pruebas verificables en el SHA definitivo.

## Alcance funcional implementado

- Únicamente tres roles nuevos: `admin`, `administrative`, `resident`, con aislamiento por obra y organización.
- Administrativo: asistencia semanal con búsqueda por nombre/RUT, entrada tardía con motivo, trazabilidad nominal y contratos de trabajo sin archivos.
- Calendario nuevo: 4, 5 o 6 segmentos por mes, comenzando lunes y terminando domingo, recortados al mes calendario.
- Conversión aditiva de datos de cinco bloques históricos a calendario real; preserva las tablas originales y marca datos reproyectados para revisión manual. No marca automáticamente como completada una semana antigua reproyectada.
- Gestión de obligaciones por contratista/semana/obra/administrativo, responsables asignados, exención con justificación y notas de 1,0 a 7,0 al cierre del mes.
- Fórmula inicial: 70 % cumplimiento + 30 % puntualidad; permite cambiar el peso en configuración. Con cero obligaciones exigibles, la nota no se genera.
- El Administrador ve la cantidad de inicios de sesión del mes, **sin** considerarlos en la nota.
- Cuadre entre días de asistencia completados y días pagados manualmente: faltante es `null` (pendiente), no cero. Nunca retener o sancionar automáticamente.
- Búsquedas por contratista y carga de detalle solo al seleccionarlo; configuración por obra de días/hora de vencimiento con zona `America/Santiago`.
- Bloqueo de escrituras en las cinco semanas históricas una vez aplicada la migración v8.1.

## Aún obligatorio antes de producción

1. CI con resultado **SUCCESS sobre el SHA exacto**: backend completo, compilación frontend, QA sintética con dos cuentas, backup/restore y validación Docker. Revisar logs, no fiarse de que un job haya sido creado.
2. Pruebas con datos representativos: 3 obras, alta carga de trabajadores, meses de 4/5/6 segmentos, periodos históricos, cambios de responsable, fines de contrato, usuarios legacy y fechas de cambio de horario de Chile.
3. Ensayo de restauración de `postgres.dump` y archivos privados en BD/almacenamiento aislados; comparación de conteos y fechas firmadas antes/después de migrar. No suponer compatibilidad de las tablas antiguas solo por un `pg_restore --list`.
4. Revisar que Administrativos y Residentes existentes tengan **nombre completo y obras asignadas**. Perfiles antiguos quedan bloqueados hasta asignación explícita por Administrador, sin eliminar cuentas ni evidencias.
5. Revisar consumo real de RAM y disco en VPS y comportamiento de consultas con datos grandes; no afirmar que la refactorización de rendimiento esté totalmente validada sin medidas.
6. PR fusionada, SHA de `main` aprobado y plan de ventana de actualización (migración detiene temporalmente API/worker). Comprobar permisos DNS/Caddy y espacio libre.

## Sólo cuando los controles anteriores estén aprobados: actualizar VPS

Las rutas siguientes son históricas, confirmar en SSH **antes de ejecutar**:
`/opt/galant-post`, `.env.preview`, `docker-compose.preview.yml`.

```bash
cd /opt/galant-post || exit 1
git remote -v
git status --short
test -f .env.preview || exit 1
df -h /opt
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
```

Recuperar el **SHA completo aprobado** desde la PR fusionada (no copiar un SHA antiguo). Tras confirmar CI verde, respaldos y permisos:

```bash
cd /opt/galant-post || exit 1
git fetch --no-tags origin main
TARGET_SHA="$(git rev-parse origin/main)"
echo "Versión aprobada a instalar: $TARGET_SHA"
git show "$TARGET_SHA:scripts/update-preview.sh" > /tmp/galant-post-v81-safe-update.sh
sudo env GALANT_DEPLOY_DIR=/opt/galant-post bash /tmp/galant-post-v81-safe-update.sh "$TARGET_SHA"
rm -f /tmp/galant-post-v81-safe-update.sh
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c 'from app.version import VERSION,SOURCE_COMMIT; print(VERSION,SOURCE_COMMIT)'
curl -fsS http://127.0.0.1:18512/api/v1/health
```

**No ejecutar este bloque mientras PR #16 esté en borrador ni si CI falla o no ha terminado.** Asegurar que `origin/main` corresponda al SHA autorizado; un avance de rama posterior requiere otra revisión.

**Nunca** `docker compose down -v`, `git reset --hard`, borrar volúmenes ni sobrescribir `.env.preview` para actualizar. La reversión de código no sustituye un plan de recuperación de datos. Ver `scripts/update-preview.sh` y `docs/INSTALACION_VPS_CADA_VERSION.md`.

## Validación funcional posterior al despliegue

- Verificar health, número de versión visible y SHA real coincidente.
- Administrador: evaluaciones, asignación de obligaciones, exenciones, notas y cuadre previsional.
- Administrativo: sólo obras asignadas, búsqueda, semanas reales, registro tardío, contratos sin PDF.
- Residente: sólo Red de Obras; puede leer publicaciones de toda la organización, publica en sus obras.
- Revisar trazabilidad por nombre, primeras fechas de cierre inalteradas y documentos históricos intactos.
- Confirmar que ninguna firma se perdió durante la reproyección y que pagos pendientes no se convierten en deuda o retención automática.
