# Galancito + Messenger · conexión con un comando

## Para la persona que administra GALANT

**No hace falta buscar ni copiar el token de verificación del webhook.**
Este instalador lo genera y lo registra en Meta automáticamente.

**Antes de empezar:** la versión 20.7.2 debe estar desplegada en el VPS
`/opt/galant-post`. La página de Facebook debe estar bajo tu administración,
la app de Meta ya debe tener el caso de uso **Messenger from Meta**, y necesitas
permisos suficientes en Meta. El asistente detecta y explica los permisos
insuficientes, pero no puede otorgarlos.

1. Entrar al VPS usando la conexión SSH que utilizas normalmente.
2. Ejecutar exactamente:
   ```bash
   cd /opt/galant-post
   sudo python3 scripts/setup-galancito-messenger.py
   ```
3. El asistente buscará automáticamente los datos previamente guardados.
   Solo preguntará lo que falte: **ID de app de Meta**,
   **App Secret** y **token de acceso de página**. El ID de la página
   se detecta automáticamente a partir del token. Los campos secretos se
   escriben ocultos en consola; **no debes enviarlos a ChatGPT**.
4. Se genera una contraseña webhook aleatoria, se guarda con permisos de
   archivo privado, se enlaza a GALANT y se registra el webhook y el campo
   `messages` con la API de Meta.
5. Se comprueba que la página esté suscrita a la app. El programa solo
   declara éxito cuando Meta confirma estas operaciones.
6. Por último, puedes elegir si quieres activar publicaciones automáticas
   de **nuevas** necesidades y respuestas de Galancito con IA. La API
   de OpenAI tiene un **costo por uso**; la respuesta automática generativa
   permanece apagada hasta confirmar la activación y configurar una clave.

### Lo que aún exige Meta
- Autorizar la página y conceder permisos como `pages_messaging` y
  `pages_manage_metadata`; la app no puede obtenerlos por sí sola.
- Para personas ajenas a los roles de prueba de la aplicación puede
  requerirse App Review y acceso correspondiente a la titularidad.
- Los mensajes ya recibidos antes de la suscripción no se importan.
- Si Meta rechaza alguna operación, el instalador se detiene indicando
  exactamente la etapa; no inventa un estado conectado.

### Seguridad
- Nunca subas el archivo `.env.preview` a GitHub ni compartas sus valores.
- Se crea una copia local privada del archivo, no se borra información
  ni se ejecutan migraciones de base de datos.
- El token de página está disponible solo para el contenedor publicador.
- El webhook responde `Webhook no autorizado` cuando se visita sin la
  firma o parámetros de verificación; es normal y no hay que desactivarlo.
- La IA solicita permiso explícito al contacto antes de enviar su
  conversación al proveedor. El administrador puede pausarla desde GALANT.

### Diagnóstico simple
Si el asistente falla por permisos de Meta:
- Comprueba Messenger from Meta → **Configuración de la API de Messenger**.
- Verifica que el Page Access Token corresponde a la página.
- Comprueba `pages_messaging`, `pages_manage_metadata` y, si aplica,
  la revisión pública de la aplicación.
- Revisa que el dominio HTTPS de GALANT sea realmente accesible desde Meta.
- Antes de volver a ejecutar el instalador, comprueba si Meta ya registró
  el webhook para evitar cambiar configuraciones innecesariamente.
