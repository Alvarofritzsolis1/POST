# GALANT POST — procedimiento obligatorio para instalar cada versión en VPS

**Este es el runbook permanente de entrega.** Para cualquier versión futura de GALANT POST, además de modificar el repositorio, se debe entregar un bloque de instalación sobre el VPS Contabo existente con un SHA fijo, comprobación de versión y recuperación segura.

## Entorno histórico (confirmar en cada instalación)

- Repositorio: `https://github.com/Alvarofritzsolis1/POST`
- Checkout VPS: `/opt/galant-post`
- Compose: `docker-compose.preview.yml`
- Variables: `.env.preview` (privado; nunca añadir a GitHub)
- Servicios: `db`, `api`, `worker`, `frontend`, `proxy`
- Puerto local de proxy por defecto: `127.0.0.1:18512` (puede variar en `.env.preview`)
- Comprobar que el remoto sea `Alvarofritzsolis1/POST` y que el proyecto antiguo `/opt/galant` quede intacto.

## Secuencia obligatoria por versión

1. Confirmar que el pull request está fusionado y que GitHub Actions pasó sobre el **SHA exacto** que se quiere instalar.
2. Confirmar que existe el checkout anterior, `.env.preview`, Docker operativo y espacio suficiente para un respaldo real.
3. Conectarse por SSH al VPS con credenciales privadas; no pegarlas en chats.
4. Guardar el SHA de 40 caracteres de la versión aprobada como `TARGET_SHA`. Nunca desplegar ciegamente un `origin/main` que haya avanzado a otra versión.
5. Ejecutar el **actualizador seguro** del repositorio. Este realiza respaldo de PostgreSQL y archivos privados, verificación de restauración aislada, migraciones controladas, reconstrucción y revisión de salud. Si el respaldo falla, abortar.
6. Verificar tanto la API como la versión visible en frontend y probar al menos dos cuentas, una de ellas residente. Revisar funcionalidad particular de la versión.
7. Conservar la ubicación de los respaldos, el SHA anterior y el registro de resultado. No declarar instalado hasta comprobar desde el VPS.

### 1. Comprobación previa (en SSH del VPS)

```bash
cd /opt/galant-post || exit 1
pwd
git remote -v
git status --short
test -f .env.preview || { echo "Falta .env.preview"; exit 1; }
df -h /opt
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
```

Detenerse si el directorio, remoto, permisos, base de datos o servicios no coinciden con la instalación existente.

### 2. Actualización controlada a un SHA aprobado

**Sustituir únicamente `TARGET_SHA` en cada entrega.** Ejemplo v8.0.0: `09d9e4f52356d07be7a11969466ff21137d2b06e`.

```bash
cd /opt/galant-post || exit 1
TARGET_SHA="09d9e4f52356d07be7a11969466ff21137d2b06e"
git fetch --no-tags origin main
git cat-file -e "${TARGET_SHA}^{commit}" || exit 1
git show "${TARGET_SHA}:scripts/update-preview.sh" > /tmp/galant-post-safe-update.sh
sudo env GALANT_DEPLOY_DIR=/opt/galant-post bash /tmp/galant-post-safe-update.sh "$TARGET_SHA"
rm -f /tmp/galant-post-safe-update.sh
```

El script **no** debe ejecutarse con errores de Git, falta de espacio, respaldos no verificables o cambios locales rastreados no resueltos. No usar `git reset --hard`, `docker compose down -v`, `docker volume prune` ni borrar archivos privados.

### 3. Comprobar instalación

```bash
cd /opt/galant-post || exit 1
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c 'from app.version import VERSION, SOURCE_COMMIT; print(VERSION, SOURCE_COMMIT)'
curl -fsS http://127.0.0.1:18512/api/v1/health
docker compose --env-file .env.preview -f docker-compose.preview.yml logs --tail=60 api worker frontend
```

Si `PORT` en `.env.preview` es diferente de 18512, ajustar la URL local. El endpoint debe mostrar la versión esperada y el SHA desplegado. No afirmar que el VPS está actualizado solo porque el commit está en GitHub.

### 4. Entrega estándar que acompañará toda versión

Cada solicitud de crear una nueva versión debe terminar con: **(a)** número de versión y SHA, **(b)** enlace al PR/commit, **(c)** estado de GitHub Actions, **(d)** bloque SSH listo para copiar con el SHA exacto, **(e)** instrucciones de respaldo/rollback, **(f)** comandos para comprobar salud y versión, **(g)** declaración explícita de si se desplegó o no en el VPS.

## Consideraciones

El script `scripts/update-preview.sh` despliega `galant-post-preview`, no el proyecto GALANT antiguo, y no está destinado a otras rutas o pilas. El rollback del código **no** equivale necesariamente a revertir migraciones de base de datos: cualquier recuperación de datos exige revisar el respaldo verificado y el estado de las migraciones. Consultar también `docs/ACTUALIZACION_SEGURA_VPS.md`.

GitHub Actions dispone de `.github/workflows/deploy-preview.yml` para SSH, pero está condicionado por variables de autorización y secretos configurados por el administrador. No asumir que un merge ejecuta un despliegue automático.
