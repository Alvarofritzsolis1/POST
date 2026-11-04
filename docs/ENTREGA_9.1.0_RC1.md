# GALANT POST V9.1.0-rc1 — entrega candidata

**Estado:** rama de revisión, no producción. Base v8.1.0-rc1.
**Regla:** no actualizar el VPS ni mezclar la versión sin controles completos de CI y copia restaurable.

## Implementado

- Asistencia semanal por fichas de trabajador, cuadrícula compacta de hasta cinco días hábiles. Se elimina la tabla horizontal.
- Progreso por trabajador y días marcados. El pendiente no es cero; registrar 0 días requiere acción explícita. Las exclusiones exigen motivo.
- Solo lunes-viernes. Sábado/domingo no generan casilla, obligación ni puntuación. Las semanas visibles se numeran de 1 a 4/5.
- Compatibilidad: identificadores internos de semanas 8.1 intactos. Noviembre de 2026 conserva slot interno 1 (domingo) sin obligación; la primera semana visible corresponde al slot interno 2. No borrar evidencia.
- Consolidado mensual solo cuenta fechas laborales sin borrar firmas históricas.
- Menú de administrador retráctil, opción conservada por navegador, acceso móvil y soporte para movimiento reducido.
- Versión API/frontend alineada a 9.1.0-rc1.

## Revisores independientes ejecutables

El workflow .github/workflows/v91-review-agents.yml ejecuta tres validadores determinísticos:
1. Calendario e integridad de ordinales históricos.
2. Interfaz, accesibilidad y diseño adaptable.
3. Permisos, obra, auditoría y fechas.

El supervisor falla si cualquiera falla, se cancela o no se ejecuta. **No son agentes IA** y no sustituyen revisión humana ni CI. La suite general de CI comprueba backend, frontend, Docker y respaldo/restauración.

## Pruebas manuales obligatorias

- Noviembre 2026: cinco semanas visibles, domingo 1 sin casilla y lunes 30 con casilla.
- Octubre 2026: no mostrar sábados ni domingos.
- Trabajador sin ingresar permanece pendiente; cero días solo por acción, futuros bloqueados; motivo atraso exigible.
- Meses de 4/5 semanas, datos históricos, cientos de trabajadores, administrativos y administradores.
- Pantallas 320px, 768px, 1366px y 1920px; teclado y menú retráctil; sin desbordamiento horizontal de pantalla.
- Exclusiones con motivo, trazabilidad nominal, días pagados versus firmados, sin retenciones automáticas.
- Backups y restauración en ambiente aislado.

## Despliegue seguro (solo después de aprobar PR y CI)

Seguir docs/INSTALACION_VPS_CADA_VERSION.md y scripts/update-preview.sh. En SSH del VPS:

    cd /opt/galant-post || exit 1
    git fetch --no-tags origin main
    TARGET_SHA="$(git rev-parse origin/main)"
    git show "$TARGET_SHA:scripts/update-preview.sh" > /tmp/galant-post-v91-update.sh
    sudo env GALANT_DEPLOY_DIR=/opt/galant-post bash /tmp/galant-post-v91-update.sh "$TARGET_SHA"
    rm -f /tmp/galant-post-v91-update.sh
    docker compose --env-file .env.preview -f docker-compose.preview.yml ps
    docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c 'from app.version import VERSION,SOURCE_COMMIT; print(VERSION,SOURCE_COMMIT)'
    curl -fsS http://127.0.0.1:18512/api/v1/health

No ejecutar docker compose down -v, borrar volúmenes o sobrescribir .env.preview.

## Pendientes antes de publicar

- CI final en SHA exacto; capturas y revisión real en navegador.
- Agentes IA semánticos todavía no implementados. Validadores actuales son determinísticos.
- Verificación de versión instalada en VPS con acceso SSH.