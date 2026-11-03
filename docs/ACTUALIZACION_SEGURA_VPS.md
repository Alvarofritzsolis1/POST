# Aplicación controlada de GALANT 0.4.0-rc1 en Contabo

Este procedimiento está diseñado para el checkout existente **`/opt/galant-post`** y el stack aislado **`galant-post-preview`**. No tocar `/opt/galant`, el proyecto anterior ni sus volúmenes.

## Condiciones para autorizar la publicación

- PR #6 revisado y fusionado a `main` **solo después de las pruebas y aprobación correspondiente**.
- GitHub Actions en verde sobre el SHA exacto a desplegar: backend, frontend, compose y respaldo/restauración sintética.
- `.env.preview` existente y protegido dentro de `/opt/galant-post`.
- Se conoce la organización y permisos de las dos cuentas internas; no se confunden `create-admin` y `create-user`.
- El importador fue probado con una **copia autorizada** del Excel histórico (no sobrescribe empresas, pero los contratos conflictivos se rechazan).
- Se ejecutó un ensayo de 24 horas con dos cuentas de prueba y se revisaron sus resultados.
- Capacidad de disco suficiente para la copia de PostgreSQL, PDFs y una base temporal de restauración.

**Estado actual:** GitHub CI comprobó respaldo y restauración con datos sintéticos. **No se ha ejecutado la restauración del VPS real ni las 24 horas de prueba.** No marcar como validado antes de hacerlo.

## 1. Identificar el checkout y estado en SSH

```bash
cd /opt/galant-post
pwd
git remote -v
git status --short
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
```

Abortar ante un directorio diferente, cambios locales rastreados o un stack que no sea `galant-post-preview`.

## 2. Prueba continua de 24 horas

El script `scripts/soak_24h.py` realiza consultas de solo lectura a salud, organización, obras y requisitos mensuales. No requiere PDFs ni carga información en el servidor.

Configurar en una terminal protegida las variables `GALANT_SOAK_EMAIL_A`, `GALANT_SOAK_PASSWORD_A`, `GALANT_SOAK_EMAIL_B`, `GALANT_SOAK_PASSWORD_B` para **dos cuentas sintéticas de la misma organización**. No publicar contraseñas, ni copiarlas a GitHub.

Ejemplo de comprobación desde el VPS o un túnel privado SSH, con el script de esta rama ya disponible:

```bash
python3 scripts/soak_24h.py \
  --url http://127.0.0.1:18512 \
  --period 2026-09 \
  --duration-seconds 86400 \
  --interval-seconds 60 \
  --output /var/tmp/galant-soak-24h.json
```

La prueba debe **completar los 86.400 segundos** y generar `result: PASS`, `failure_count: 0`, `mismatches: 0`. No ejecutar el test si las cuentas aún no existen, los valores de acceso no son seguros o el endpoint de previsualización no está disponible.

El script de la nueva rama debe estar accesible en la máquina donde se ejecuta la prueba. La prueba debe realizarse **antes** de publicar la versión como validada; es posible usar una instancia aislada para evitar efectos sobre documentos reales.

## 3. Fusión y actualización segura

Solo con las condiciones anteriores aprobadas y el PR #6 fusionado en `main`:

```bash
cd /opt/galant-post
git fetch --no-tags origin main
target_sha="$(git rev-parse origin/main)"
git show "${target_sha}:scripts/update-preview.sh" > /tmp/galant-safe-update.sh
sudo env GALANT_DEPLOY_DIR=/opt/galant-post bash /tmp/galant-safe-update.sh "$target_sha"
rm -f /tmp/galant-safe-update.sh
```

El nuevo script de actualización **crea un respaldo** en `/opt/galant-post-backups`, comprueba sus SHA256, restaura PostgreSQL en un contenedor temporal sin red, verifica cada archivo PDF/imagen registrado y **solo después** sustituye los servicios e inicializa las tablas faltantes. Si falla, cancela la actualización; en determinados fallos se ejecuta rollback del checkout y servicios. Conservar siempre el respaldo.

**No usar** `docker compose down -v`, `docker volume prune`, `git reset --hard` ni `DROP DATABASE`.

## 4. Comprobación del despliegue

```bash
cd /opt/galant-post
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c "from app.version import VERSION; print(VERSION)"
curl -fsS http://127.0.0.1:18512/api/v1/health
docker compose --env-file .env.preview -f docker-compose.preview.yml logs --tail=60 api worker
```

Verificar después desde **dos usuarios distintos** que ambos ven el mismo contratista y mes. Crear un registro sintético por obra, aprobar manualmente sin PDF, revisar historial, reiniciar los servicios **sin borrar volúmenes** y comprobar persistencia. Exportar un XLSX CT/CI y la matriz del mismo período. En el dashboard, la ausencia de requisitos evaluables debe mostrarse como «Sin evaluar».

Si falla algún paso, **no declarar la actualización completada**: conservar los logs, la copia y el SHA anterior para recuperar el servicio de forma supervisada. No compartir credenciales ni documentos laborales en incidencias públicas.
