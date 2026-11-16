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


## Nuevo apartado superior «Publicar en Facebook» · prueba

Visible exclusivamente para administradores dentro de Red de Obras.
El modo de ensayo es independiente de los anuncios automáticos. Después de
fusionar la actualización, completar el respaldo y desplegar el código,
configura en el archivo PRIVADO /opt/galant-post/.env.preview:

    FACEBOOK_MANUAL_TESTING_ENABLED=true
    FACEBOOK_AUTOPUBLISH_ENABLED=false
    FACEBOOK_PAGE_ID=1489275590928529
    FACEBOOK_PAGE_TOKEN=TOKEN_PRIVADO_DE_PAGINA

Reiniciar API y facebook-publisher mediante el procedimiento de despliegue.
NO activar la difusión automática para probar un solo anuncio.

Flujo de uso:
1. Abrir Red de Obras > Publicar en Facebook.
2. Pulsar **Comprobar conexión**. Esta acción consulta desde el worker el nombre
   y ID de la página, sin publicar. La identidad del token NO garantiza el
   permiso para crear publicaciones; eso se comprueba al publicar la prueba.
3. Completar obra, comuna, región, especialidad, dotación, fechas, partidas,
   requisitos comerciales y contacto. Se puede precargar un requerimiento
   existente, pero nunca se copian notas ni documentos privados.
4. Pulsar **Generar vista previa**. Esta operación valida todos los datos y
   devuelve el texto exacto SIN publicarlo en Facebook.
5. Marcar aceptación de visibilidad pública y pulsar **Publicar prueba real**.
   El sistema solicita confirmación adicional. El post contiene una leyenda
   inequívoca «PUBLICACIÓN DE PRUEBA — NO ES UNA CONVOCATORIA REAL».
6. Comprobar el ID y enlace en Historial. Si el resultado es incierto, revisar
   la página directamente antes de intentar otra operación.
7. Pulsar **Retirar prueba** para solicitar eliminación y verificar resultado.

La primera versión admite publicaciones de TEXTO, no fotos, carruseles ni
publicaciones en grupos externos. No pegar el token en el formulario, código,
GitHub, capturas ni chats. Solo el worker tiene acceso a esa credencial.
