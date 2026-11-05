# GALANT · Despliegue automático y manual seguro desde GitHub Actions

## Resultado esperado · desde GALANT 15.0.5-rc1

**Automático:** al fusionar en `main` una **nueva versión** aprobada (aumento simultáneo de `apps/backend/app/version.py`, `apps/frontend/package.json` y `apps/frontend/package-lock.json`), el flujo **GALANT - Despliegue automatico seguro** verifica la integridad de la versión, ejecuta todas las pruebas y, solo si pasan, actualiza el VPS sin PowerShell ni pulsar ningún botón.

**No actualizan el VPS:** commits sin incremento de versión, PR, ramas distintas de `main`, cron, ejecución de CI normal, versiones que retroceden y versiones que no coinciden entre backend, frontend y lockfile. Si `main` cambia mientras se ejecutan pruebas, el despliegue de ese commit falla antes de tocar el servidor para evitar publicar código desactualizado.

**Manual:** permanece disponible el flujo **GALANT - Desplegar VPS (un clic)**: entrar al repositorio → Actions → Run workflow → seleccionar `main`. Repite la CI y usa las mismas protecciones.

**Aprobación:** una nueva versión se considera aprobada para auto-despliegue al integrarla deliberadamente en `main` y superar todas las pruebas. Se recomienda **proteger `main` con PR obligatorio y revisiones**, ya que los permisos de escritura directos sobre `main` equivalen a autorizar un despliegue. Si `GALANT-VPS` tiene revisores obligatorios, estos seguirán interviniendo antes de actualizar el VPS.

Ambas rutas comparten bloqueo de concurrencia y usan exclusivamente el actualizador seguro `scripts/update-preview.sh`.

## Configuración inicial (se realiza una sola vez)

1. En GitHub abrir **Settings → Secrets and variables → Actions → Secrets**. Configurar los secretos obligatorios `VPS_SSH_KEY` (clave privada de despliegue exclusiva para este servidor) y `VPS_KNOWN_HOSTS` (clave pública del servidor en formato `known_hosts`, con huella verificada fuera de GitHub). Los secretos anteriores pueden reutilizarse si corresponden al VPS actual. **Nunca subir la clave privada al repositorio ni pegarla en chats.**
2. En **Variables** o **Secrets** se pueden configurar `VPS_HOST`, `VPS_USER` y `VPS_PORT`. Si no se establecen, el flujo utiliza la dirección actual del VPS, usuario `root` y puerto 22. Este es el comportamiento compatible con el script existente; por seguridad, evaluar un usuario de despliegue con privilegios mínimos y política de sudo restringida en una etapa posterior.
3. En **Settings → Environments**, buscar o crear **GALANT-VPS**. Si el plan de GitHub permite aprobaciones de despliegue, configurar revisores obligatorios y restringir ramas de despliegue a `main`. El workflow funciona también sin revisores configurados, pero **no debe confundirse con una aprobación manual adicional**.
4. Recomendado: proteger la rama `main` con solicitud de PR y comprobaciones CI obligatorias, limitar permisos de administración del repositorio y proteger el secreto SSH. Solo los colaboradores autorizados deben poder fusionar nuevas versiones a \`main\`; el disparador manual requiere permiso de escritura sobre el repositorio.
5. Confirmar en el VPS que el checkout existe en `/opt/galant-post`, que `.env.preview` y Docker Compose están disponibles, que el servidor reconoce la clave SSH y que puede conectarse a su repositorio GitHub.

### Cómo preparar una clave exclusiva cuando no existe

Desde **PowerShell en el equipo propio**, ejecutar `ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\galant_github_actions" -C "galant-github-actions"`. Agregar **solo la clave pública** `.pub` al archivo `~/.ssh/authorized_keys` del usuario autorizado en el VPS, ajustando permisos SSH a 700/600. Guardar el **contenido privado** del archivo sin extensión exclusivamente como secreto `VPS_SSH_KEY` de GitHub.

Para `VPS_KNOWN_HOSTS`, obtener el valor mediante `ssh-keyscan -t ed25519 <HOST>` desde un equipo confiable y **comparar su fingerprint con el mostrado directamente en la consola del VPS** (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`); no confiar a ciegas en un escaneo no verificado. **No compartir claves, tokens ni contraseñas en la conversación.**

## Procedimiento de despliegue manual

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
- El disparador CI normal (`ci.yml`) no despliega por sí solo: el flujo automático o manual llama a sus pruebas de manera reutilizable y condiciona el despliegue a su aprobación.
- Es compatible con las versiones GALANT 15.0.3-rc1 y posteriores; el código correcto se fija al SHA del commit de `main` que inicia el flujo.

## Verificación y limitaciones

El primer despliegue manual de GALANT 15.0.3-rc1 ya demostró que las claves SSH, el respaldo y la prueba de estado pueden funcionar en el VPS. El auto-despliegue reutiliza exactamente esas credenciales, sin solicitar la contraseña del servidor. No se comprueban directamente los valores de los secretos ni se modifican reglas del environment desde esta integración.

Para confirmar la **primera ejecución automática**, revisar la ejecución **GALANT - Despliegue automatico seguro** en [Actions](https://github.com/Alvarofritzsolis1/POST/actions). Debe verse `comprobar_version = success`, toda la CI en verde y `desplegar = success`. El VPS debe responder desde `/api/v1/health` con la versión y el commit `main` aprobados.

Si falla una prueba, falta un secreto o hay restricciones del entorno, **la actualización no ocurre**. Si el despliegue comienza y falla después, el script intenta revertir los contenedores. Un rollback de código no garantiza revertir automáticamente cambios ya aplicados a la base de datos; una restauración completa de BD requiere control explícito.
