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

**Autorización explícita de lanzamiento:** ambos workflows GitHub exigen `GALANT_POST_RELEASE_APPROVED=true` además de sus indicadores individuales (`VPS_AUTODEPLOY`, `VPS_MANUAL_DEPLOY_ALLOWED` o `POST_AUTODEPLOY_ENABLED`). No activar esa variable antes de revisar respaldo, QA y las 24 horas reales. Deshabilitarla nuevamente después del despliegue para impedir publicaciones accidentales de commits posteriores.

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

## 2. Instancia QA aislada y ensayo real de 24 horas antes de fusionar

**No se necesita publicar la rama en producción.** La rama de prueba dispone de un stack Docker independiente con PostgreSQL `galant-post-qa`, almacenamiento `/opt/galant-post-qa/qa-storage` y proxy limitado a `127.0.0.1:18612`. Nunca reutiliza los datos laborales de `galant-post-preview`.

Primero, desde SSH como administrador, obtener el script de la rama sin cambiar el checkout actualmente operativo:

```bash
cd /opt/galant-post
git fetch --no-tags origin feat/galant-operational-control-20261103
git show FETCH_HEAD:scripts/start-qa-preview.sh > /tmp/galant-start-qa.sh
sudo env GALANT_BASE_DIR=/opt/galant-post bash /tmp/galant-start-qa.sh
rm -f /tmp/galant-start-qa.sh
```

El procedimiento comprueba memoria y espacio disponible, el repositorio remoto, que no exista otro QA previo y que los montajes y puertos de QA estén aislados. **Si falla cualquiera de estas condiciones, detenerse**; no ejecutar Docker sobre los volúmenes principales. El puerto 18612 es privado al servidor, por lo que desde Windows puede accederse mediante un túnel `ssh -L 18612:127.0.0.1:18612 root@IP_DEL_VPS` y luego `http://localhost:18612`. No abrir el puerto a Internet.

En el nuevo directorio, crear el administrador **sintético** y un segundo usuario de esa misma organización:

```bash
cd /opt/galant-post-qa
docker compose -p galant-post-qa --env-file .env.qa -f docker-compose.preview.yml -f docker-compose.qa.yml exec api python -m app.cli create-admin --email admin.qa@example.test
docker compose -p galant-post-qa --env-file .env.qa -f docker-compose.preview.yml -f docker-compose.qa.yml exec api python -m app.cli create-user --email revisor.qa@example.test --admin-email admin.qa@example.test --role analyst
```

Elegir claves exclusivas para QA e introducirlas en la terminal, no en GitHub. Registrar un contratista sintético por obra, trabajadores sintéticos, una aprobación manual mensual, asistencia y cotizaciones en la web QA. Comprobar que ambas cuentas ven los mismos registros y que la sesión de visualización no puede editar.

A continuación, configurar las cuatro variables secretas `GALANT_SOAK_EMAIL_A`, `GALANT_SOAK_PASSWORD_A`, `GALANT_SOAK_EMAIL_B`, `GALANT_SOAK_PASSWORD_B` en un entorno privado del VPS y ejecutar desde `/opt/galant-post-qa`:

```bash
python3 scripts/soak_24h.py \
  --url http://127.0.0.1:18612 \
  --period 2026-09 \
  --duration-seconds 86400 \
  --interval-seconds 60 \
  --output /var/tmp/galant-soak-24h.json
```

Esta prueba necesita **86.400 segundos reales de ejecución**; no está ejecutada desde ChatGPT. La salida debe indicar `result: PASS`, `failure_count: 0` y `mismatches: 0`, con `elapsed_seconds` de al menos 86400. Cada muestra actualiza un JSON privado por reemplazo atómico; si se corta el proceso, el archivo conserva `result: RUNNING` y `last_checked_at` antiguo, **no una aprobación**. Se deben revisar además logs, reinicio controlado, integridad de documentos y límites de RAM/CPU. Si no puede correrse en Contabo por memoria o disco, usar una instancia QA equivalente separada.

Para dejar la prueba ejecutándose aun cuando se cierre SSH, utilizar una sesión `tmux` en el VPS (instalar `tmux` mediante el administrador si falta). En esa sesión configurar primero los correos sintéticos y leer las contraseñas con `read -rsp` sin escribirlas en el historial:

```bash
cd /opt/galant-post-qa
export GALANT_SOAK_EMAIL_A='admin.qa@example.test'
export GALANT_SOAK_EMAIL_B='revisor.qa@example.test'
read -rsp 'Contraseña QA A: ' GALANT_SOAK_PASSWORD_A; echo
read -rsp 'Contraseña QA B: ' GALANT_SOAK_PASSWORD_B; echo
export GALANT_SOAK_PASSWORD_A GALANT_SOAK_PASSWORD_B
python3 scripts/soak_24h.py --url http://127.0.0.1:18612 --period 2026-09 --duration-seconds 86400 --interval-seconds 60 --output /var/tmp/galant-soak-24h.json
```

Separarse de `tmux` con **Ctrl+B, luego D**; volver mediante `tmux attach`. Consultar en otra terminal, sin contraseñas: `python3 -m json.tool /var/tmp/galant-soak-24h.json`. No mostrar el contenido de ese archivo ni las contraseñas públicamente, aunque el reporte omite RUT y nombres.

Este paso continúa **pendiente** hasta ejecutarse de verdad y analizar su reporte final.

**La prueba de dos cuentas nunca debe confundirse con comprobar 24 horas de uptime desde GitHub Actions**, ni se permite fusionar antes de examinar su resultado.

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
