# GALANT POST — Difusión de Red de Obras por Facebook

Esta integración sirve exclusivamente para publicar en **una página que administras**.
No permite enviar publicaciones a grupos de terceros mediante la API oficial.

## Preparación y seguridad

- Comprueba en Meta for Developers los permisos pages_show_list, pages_read_engagement
  y pages_manage_posts. Se necesita autorización CREATE_CONTENT sobre la página.
- Revoca cualquier token que haya quedado visible en capturas o conversaciones.
- Genera un nuevo token **de página** de la app GALANT; no pegues el token en GitHub,
  código fuente, capturas, comentarios de pull requests ni chats.
- En el archivo .env.preview PRIVADO del VPS configura:

    FACEBOOK_AUTOPUBLISH_ENABLED=true
    FACEBOOK_PAGE_ID=ID_NUMERICO_DE_LA_PAGINA
    FACEBOOK_PAGE_TOKEN=TOKEN_DE_PAGINA_PRIVADO

- Configura la vigencia del token y su renovación de acuerdo con Meta.
- El token se inyecta SOLO al contenedor facebook-publisher, no al frontend ni a la API.

## Antes del despliegue

1. Comprueba los tests, migración de base de datos y copia de seguridad del VPS.
2. Activa la rama fusionada en el entorno de prueba primero.
3. Comprueba que el servicio facebook-publisher tiene salida HTTPS a graph.facebook.com.
4. Crea un requerimiento SINTÉTICO de prueba y verifica la publicación desde la página.
5. Elimina la prueba, verifica el borrado del post y solo entonces habilita producción.

## Funcionamiento

- Por defecto el sistema está desactivado. No hace publicaciones retroactivas.
- Al crear un requerimiento publicado, se guarda una tarea en PostgreSQL.
- El worker publica texto acotado: obra, especialidad, título, dotación y partidas.
- Se excluyen notas internas, descripciones detalladas, adjuntos y datos de trabajadores.
- Si cambia el requerimiento, se actualiza el post existente.
- Si se cancela, se intenta eliminar el post.
- Si Meta devuelve un error HTTP explícito, se registra como failed y puede reintentarse
  manualmente desde el detalle.
- Si no sabemos si Meta recibió un envío, se registra como uncertain: NO se reintenta
  automáticamente para evitar anuncios duplicados. Se debe conciliar manualmente.
- Si el proceso muere durante un envío puede permanecer en sending:
  comprobar primero Facebook antes de cualquier reintento.
- Los administradores tienen un botón de sincronización para requerimientos previos.

**Meta:** https://developers.facebook.com/docs/graph-api/reference/page/feed/
