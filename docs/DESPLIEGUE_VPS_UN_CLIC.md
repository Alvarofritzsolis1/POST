# GALANT · Actualización del VPS desde GitHub Actions (un clic)

## Resultado esperado

Al entrar al repositorio **Alvarofritzsolis1/POST → Actions → GALANT - Desplegar VPS (un clic) → Run workflow**, seleccionar **main** y pulsar **Run workflow**, se ejecutan **primero todas las pruebas** y, si todas terminan bien, el flujo realiza el despliegue al VPS.

**Ningún push, PR, merge, cron ni ejecución de CI común despliega GALANT automáticamente.** El flujo `galant-deploy-manual.yml` usa exclusivamente `workflow_dispatch` en `main`, y es el único responsable de invocar el actualizador del servidor. Los cambios en código siguen siendo independientes de las actualizaciones de producción.

## Configuración inicial (se realiza una sola vez)

1. En GitHub abrir **Settings → Secrets and variables → Actions → Secrets**. Configurar los secretos obligatorios `VPS_SSH_KEY` (clave privada de despliegue exclusiva para este servidor) y `VPS_KNOWN_HOSTS` (clave pública del servidor en formato `known_hosts`, con huella verificada fuera de GitHub). Los secretos anteriores pueden reutilizarse si corresponden al VPS actual. **Nunca subir la clave privada al repositorio ni pegarla en chats.**
2. En **Variables** o **Secrets** se pueden configurar `VPS_HOST`, `VPS_USER` y `VPS_PORT`. Si no se establecen, el flujo utiliza la dirección actual del VPS, usuario `root` y puerto 22. Este es el comportamiento compatible con el script existente; por seguridad, evaluar un usuario de despliegue con privilegios mínimos y política de sudo restringida en una etapa posterior.
3. En **Settings → Environments**, buscar o crear **GALANT-VPS**. Si el plan de GitHub permite aprobaciones de despliegue, configurar revisores obligatorios y restringir ramas de despliegue a `main`. El workflow funciona también sin revisores configurados, pero **no debe confundirse con una aprobación manual adicional**.
4. Recomendado: proteger la rama `main` con solicitud de PR y comprobaciones CI obligatorias, limitar permisos de administración del repositorio y proteger el secreto SSH. El disparador manual requiere permiso de escritura sobre el repositorio.
5. Confirmar en el VPS que el checkout existe en `/opt/galant-post`, que `.env.preview` y Docker Compose están disponibles, que el servidor reconoce la clave SSH y que puede conectarse a su repositorio GitHub.

### Cómo preparar una clave exclusiva cuando no existe

Desde **PowerShell en el equipo propio**, ejecutar `ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\galant_github_actions" -C "galant-github-actions"`. Agregar **solo la clave pública** `.pub` al archivo `~/.ssh/authorized_keys` del usuario autorizado en el VPS, ajustando permisos SSH a 700/600. Guardar el **contenido privado** del archivo sin extensión exclusivamente como secreto `VPS_SSH_KEY` de GitHub.

Para `VPS_KNOWN_HOSTS`, obtener el valor mediante `ssh-keyscan -t ed25519 <HOST>` desde un equipo confiable y **comparar su fingerprint con el mostrado directamente en la consola del VPS** (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`); no confiar a ciegas en un escaneo no verificado. **No compartir claves, tokens ni contraseñas en la conversación.**

## Procedimiento de despliegue

1. Abrir [Actions del repositorio](https://github.com/Alvarofritzsolis1/POST/actions).
2. Seleccionar **GALANT - Desplegar VPS (un clic)**.
3. Pulsar **Run workflow** (seleccionar `main`) y confirmar **Run workflow**.
4. GitHub repite las pruebas de backend, frontend, Compose, restauración sintética y QA navegador/usuarios.
5. Solo si pasan todas: autorizar el entorno cuando tenga revisores, y conectarse por SSH de forma verificada.
6. Antes de modificar el VPS, se comprueba que el commit elegido siga siendo la cabeza actual de `main`. Un cambio posterior detiene el despliegue de esa ejecución.
7. El script del repositorio `scripts/update-preview.sh` crea respaldo de PostgreSQL y archivos privados, verifica restauración en una BD aislada, reconstruye contenedores, ejecuta migración controlada y comprueba versión/commit en `/api/v1/health`. Si algo falla, intenta revertir el código y contenedores; **la reversión no sustituye una restauración completa de la base de datos**, que requiere un procedimiento supervisado si hubiera fallos de migración.
8. El historial y los registros quedan en la ejecución de Actions. El VPS no cambia si faltan secretos, falla la CI o no se autoriza el ambiente.

## Compatibilidad con GALANT

- El script conserva `/opt/galant-post`, `.env.preview`, `docker-compose.preview.yml` y el endpoint `/api/v1/health`.
- No crea ni elimina volúmenes de producción, ni usa `docker compose down -v`.
- Las pruebas utilizan datos sintéticos y entorno aislado, no la base real del VPS.
- El disparador CI normal (`ci.yml`) ya no despliega el VPS y puede invocarse de forma reutilizable por el flujo manual.
- Es compatible con las versiones GALANT 15.0.3-rc1 y posteriores; el código correcto se fija al SHA del commit de `main` que inicia el flujo.

## Limitaciones pendientes antes del primer despliegue

Las credenciales y reglas de GitHub se gestionan en la interfaz privada del propietario. Desde esta integración no es posible confirmar el valor o la existencia de `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`, ni habilitar revisores del entorno. **Preparar el flujo no significa haber desplegado ni haber comprobado las credenciales SSH reales.**

La verificación final consiste en lanzar manualmente Actions y comprobar que la ejecución completa termina en verde, que `/api/v1/health` devuelve la misma versión/commit y que los documentos y datos siguen accesibles.
