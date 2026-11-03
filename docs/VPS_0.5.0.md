# Actualización revisable a 0.5.0-rc1

No ejecutar contra producción antes de revisar la PR y completar aceptación en QA. Este documento no es una autorización para desplegar. Conservar los controles de aprobación de los workflows existentes; no habilitar despliegue automático por esta entrega.

## Respaldo y recuperación antes del esquema

La BD y `preview-storage` se mantienen en sus ubicaciones actuales. No ejecutar `down -v`, `dropdb`, `TRUNCATE`, borrados de volúmenes ni actualizaciones manuales masivas de `org_id`.

En el VPS, desde la instalación existente:

```bash
cd /opt/galant-post
sudo bash scripts/backup-preview.sh
```

El comando devuelve `BACKUP_PATH`. Registrar esa ruta y ensayar la restauración aislada:

```bash
sudo bash scripts/verify-restore-preview.sh /opt/galant-post-backups/RUTA_DEVUELTA
```

El script restaura un PostgreSQL temporal sin puertos y comprueba archivos. Si falla, detener el procedimiento. Conservar el respaldo protegido fuera del VPS y comprobar espacio antes de construir imágenes.

La recuperación completa ante desastre requiere detener escritores, restaurar el dump en una BD de reemplazo aislada, recuperar los archivos privados y validar identidades/cantidades/referencias antes de cambiar el servicio. No restaurar encima de una base con operaciones posteriores sin conciliarlas. El rollback de código del actualizador no revierte datos recientes.

## Revisión de cuentas

Una vez instalada esta versión en QA, comparar las cuentas sin consultar contraseñas:

```bash
cd /opt/galant-post
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli diagnose-user --email ADMIN_REAL@EMPRESA.CL
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli diagnose-user --email XIMENA_REAL@EMPRESA.CL
```

Si ambas muestran el mismo `org_id`, revisar obra/permisos y repetir aceptación antes de plantear un traslado. Si son diferentes y la organización origen tiene datos, el sistema bloquea su vinculación. Elaborar un inventario y mapeo de RUT, obras, contratos, documentos y autores; ensayar en una restauración y validar todas las referencias. No se ofrece una fusión automática.

Cuenta nueva: crearla desde Configuración → Administración de usuarios, o conservar el comando existente:

```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-user --email NUEVA@EMPRESA.CL --admin-email ADMIN_REAL@EMPRESA.CL --role analyst
```

Cuenta existente sin información propia: primero ejecutar únicamente el plan:

```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli link-user --email XIMENA_REAL@EMPRESA.CL --admin-email ADMIN_REAL@EMPRESA.CL --role analyst
```

Tras revisar el plan y el ensayo de restauración, copiar el dump de ese respaldo al contenedor sin publicarlo y aplicar explícitamente:

```bash
cd /opt/galant-post
api_container=$(sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps -q api)
sudo docker cp /opt/galant-post-backups/RUTA_DEVUELTA/postgres.dump "$api_container:/tmp/galant-link-backup.dump"
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec -u root api sh -c 'chown 10001:10001 /tmp/galant-link-backup.dump && chmod 600 /tmp/galant-link-backup.dump'
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli link-user --email XIMENA_REAL@EMPRESA.CL --admin-email ADMIN_REAL@EMPRESA.CL --role analyst --apply --backup /tmp/galant-link-backup.dump
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api rm /tmp/galant-link-backup.dump
```

Se conserva auditoría de origen/destino y hash del respaldo. El cliente `pg_restore` se incluye en la imagen. Las sesiones con el `org_id` anterior quedan invalidadas; iniciar sesión en la organización destino. Las otras sesiones de la organización continúan recibiendo actualizaciones normalmente.

## Actualizar un commit revisado

Tras aprobar la versión y las verificaciones de QA, usar el SHA completo de la PR aprobada. No sustituirlo por `main` o por el nombre mutable de una rama.

```bash
cd /opt/galant-post
git status --short
git fetch origin feat/galant-shared-organization
git rev-parse origin/feat/galant-shared-organization
```

Revisar el SHA obtenido. Luego ejecutar con ese valor exacto:

```bash
sudo bash scripts/update-preview.sh SHA_COMPLETO_APROBADO_DE_40_CARACTERES
```

El actualizador exige checkout limpio y `.env.preview`, respalda BD/archivos, verifica una restauración aislada, construye y sustituye los servicios, ejecuta `init-db` y verifica salud. La inicialización agrega seis tablas sin modificar las existentes. No cambiar credenciales, nombre de proyecto Compose, volúmenes ni ruta privada. En el VPS normal no se requieren las CA especiales usadas por el proxy de este entorno de desarrollo.

Comprobar después:

```bash
curl -fsS http://127.0.0.1:18512/api/v1/health
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps
```

La API debe informar `0.5.0-rc1`. La interfaz muestra la versión del backend.

## Aceptación obligatoria en el VPS

Usar primero una restauración de QA y cuentas autorizadas, sin escribir datos sintéticos en producción. Abrir dos navegadores independientes y comprobar mismos IDs de obra/contratista/trabajador; cambios e importaciones visibles en hasta 10 segundos sin cerrar sesión; cotizaciones y aprobaciones conservadas al recargar; viewer sin escritura; otra organización sin acceso; informe del mismo período y denominadores correctos. Comprobar acceso a documentos históricos y cantidades antes/después. Completar el ensayo de 24 horas descrito en `ACTUALIZACION_SEGURA_VPS.md` y registrar sus resultados.

No declarar solucionado el incidente real de Ximena hasta superar esta aceptación con sus cuentas autorizadas.
