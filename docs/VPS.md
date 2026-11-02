# Vista previa POST en VPS Contabo Ubuntu 24.04

Este despliegue es independiente de /opt/galant (antiguo) y /opt/galant2-preview. No usar documentación laboral real en este punto.

Requisitos: Docker Engine, Compose v2, Git, Ubuntu 24.04, al menos 2.5 GB RAM libres, 5.5 GB disco libre. El instalador se niega a continuar sin recursos mínimos; no toca puertos 80 y 443.

Pasos en VPS:

    git clone https://github.com/Alvarofritzsolis1/POST.git /opt/galant-post
    cd /opt/galant-post
    sudo bash scripts/install-preview.sh

Después de fusionar main, ya se podrá clonar sin especificar rama. Crear admin (contraseña ingresada localmente):

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email ADMIN@EMPRESA.CL

En Windows PowerShell nuevo:

    ssh -N -L 18512:127.0.0.1:18512 root@89.117.144.140

En navegador Windows: http://127.0.0.1:18512

Diagnóstico VPS:

    cd /opt/galant-post
    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps
    sudo bash scripts/diagnose.sh

Detener solo POST sin borrar datos:

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml stop

No usar down -v. No modificar puertos públicos ni dominio hasta ensayar el OCR, los accesos y la seguridad. La versión v0.2.0 está preparada localmente, pero estas instrucciones solo serán aplicables a ese código cuando se publique en la rama que se clone. No se auditó el VPS en esta ejecución porque no hubo acceso al servidor. Para la eventual publicación, Nginx deberá actuar como proxy HTTPS del puerto interno 18512 y establecer SECURE_COOKIES=true en el entorno de API.
