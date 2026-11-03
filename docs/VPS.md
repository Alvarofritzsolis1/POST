# Vista previa POST en VPS Contabo Ubuntu 24.04

Este despliegue es independiente de /opt/galant (antiguo) y /opt/galant2-preview. No usar documentación laboral real en este punto.

Requisitos: Docker Engine, Compose v2, Git, Ubuntu 24.04, al menos 2.5 GB RAM libres, 5.5 GB disco libre. El instalador se niega a continuar sin recursos mínimos; no toca puertos 80 y 443.

Pasos en VPS:

    git clone https://github.com/Alvarofritzsolis1/POST.git /opt/galant-post
    cd /opt/galant-post
    sudo bash scripts/install-preview.sh

Después de fusionar main, ya se podrá clonar sin especificar rama. Crear admin (contraseña ingresada localmente):

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email ADMIN@EMPRESA.CL

## Actualización automática desde GitHub

El job `Deploy VPS` actualiza `/opt/galant-post` después de que la CI termine correctamente para cada push a `main`. El despliegue queda activo por defecto; para detenerlo durante una incidencia, configura temporalmente la variable de repositorio `VPS_AUTODEPLOY` con el valor `false`. Los pushes a ramas de trabajo no despliegan el VPS.

Configura estos secretos del repositorio en GitHub para que el despliegue pueda conectarse al servidor:

- `VPS_SSH_KEY`: clave privada exclusiva para este despliegue.
- `VPS_KNOWN_HOSTS`: línea de clave de host SSH verificada para el VPS.

La configuración usa por defecto `89.117.144.140`, el usuario `root` y el puerto `22`. Si cambian, define `VPS_HOST`, `VPS_USER` o `VPS_PORT` como variables o secretos del repositorio.

El VPS debe conservar acceso de solo lectura al repositorio para que `git fetch origin` pueda obtener el commit. El flujo valida los servicios y la versión de la API; si falla, vuelve al commit anterior sin borrar volúmenes ni `preview-storage`.

En Windows PowerShell nuevo:

    ssh -N -L 18512:127.0.0.1:18512 root@89.117.144.140

En navegador Windows: http://127.0.0.1:18512

Diagnóstico VPS:

    cd /opt/galant-post
    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps
    sudo bash scripts/diagnose.sh

Detener solo POST sin borrar datos:

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml stop

No usar down -v. No modificar puertos públicos ni dominio hasta ensayar el OCR, los accesos y la seguridad. `init-db` agrega las tablas operativas y las tres obras sin borrar documentos OCR. No se auditó ni actualizó el VPS en esta ejecución porque no hubo acceso al servidor ni confirmación de sus secretos de CI. Para una publicación en Internet, Nginx deberá actuar como proxy HTTPS del puerto interno 18512 y establecer SECURE_COOKIES=true en el entorno de API.
