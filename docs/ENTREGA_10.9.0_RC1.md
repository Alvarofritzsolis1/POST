# GALANT POST v10.9.0-rc1 — Carga masiva de contratistas

## Alcance

Corrección del flujo especializado `/api/v1/ops/imports/bulk` y de su interfaz React. **Esta es una versión candidata; no constituye una instalación ni una corrección automática de datos en el VPS.**

- **Plantilla de 11 encabezados exactos:** `ID | OBRA | ESPECIALIDAD | NOMBRECONTRATISTA | RUT | COD | ESTADO | TELEFONO | CORREO | REPRESENTANTE LEGAL | RUTR.LEGAL`.
- **COD por obra:** `CT` = fijo, `CE` = esporádico, `CI` = independiente. Sin categorías inferidas ni campos NATURALEZA/FRECUENCIA en la plantilla especializada.
- **ESTADO por obra:** `ACTIVO` o `INACTIVO`, independientes del COD. En PostgreSQL se guardan como `active`/`inactive` en la relación contratista-obra.
- **Reimportación controlada:** RUT + obra para localizar relaciones existentes; vista previa de cambios, confirmación explícita, protección ante ediciones concurrentes, auditoría y rechazo de duplicados.
- **Conservación de relaciones:** se actualizan entidades en su lugar; no se borran contratos, trabajadores, finiquitos ni documentos.
- **Especialidad e ID de origen por obra:** se conservan dentro de `ContractorDetails.values.worksites[site_id]` sin agregar columnas ni cambiar claves foráneas.
- **Módulos operativos:** clasificación visible y reglas documentales usan el COD de la relación con la obra, con lectura heredada para registros antiguos sin COD válido.

## Precauciones

1. Los registros anteriores **no se corrigen automáticamente al desplegar**. Se corrigen mediante reimportación del Excel original y aprobación manual de diferencias.
2. No importar en producción hasta tener respaldo **verificado con restauración de prueba**, según `docs/INSTALACION_VPS_CADA_VERSION.md`.
3. No borrar ni fusionar automáticamente los duplicados históricos. Se requiere revisión de relaciones si se detectan conflictos.
4. Antes de aprobar cambios masivos, comprobar los COD y ESTADO por obra y los listados de trabajadores. El campo NATURALEZA heredado puede no representar adecuadamente una empresa con códigos distintos en obras diferentes; el COD por obra es el criterio autoritativo.
5. El flujo antiguo de importación genérica sigue disponible para formatos operativos históricos; la plantilla exacta corresponde **solo** al importador especializado de contratistas.

## Verificación

Se añadieron pruebas para validación de columnas, códigos, estados, relaciones por obra, rechazos y reimportación segura en `apps/backend/tests/test_platform.py`. Ejecutar CI del PR y QA antes del merge. No declarar pruebas aprobadas sin registrar resultados de ejecución.

## Instalación en VPS — después de aprobación y merge

Usar el **SHA exacto del commit fusionado**, no un SHA provisional de rama. El procedimiento seguro está en `docs/INSTALACION_VPS_CADA_VERSION.md`.

```bash
cd /opt/galant-post || exit 1
git remote -v
git status --short
test -f .env.preview || exit 1
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
git fetch --no-tags origin main
TARGET_SHA="REEMPLAZAR_CON_SHA_APROBADO_DE_40_CARACTERES"
git cat-file -e "${TARGET_SHA}^{commit}" || exit 1
git show "${TARGET_SHA}:scripts/update-preview.sh" > /tmp/galant-post-safe-update.sh
sudo env GALANT_DEPLOY_DIR=/opt/galant-post bash /tmp/galant-post-safe-update.sh "$TARGET_SHA"
rm -f /tmp/galant-post-safe-update.sh
docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c 'from app.version import VERSION, SOURCE_COMMIT; print(VERSION, SOURCE_COMMIT)'
curl -fsS http://127.0.0.1:18512/api/v1/health
```

El script crea respaldo, verifica su restauración, aplica migraciones controladas y realiza comprobaciones de salud. Si falla, no continuar con reimportaciones. No realizar despliegue desde una rama ni asumir que GitHub equivale a VPS actualizado.
