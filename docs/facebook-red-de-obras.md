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
- Al crear un requerimiento publicado con la casilla «Publicar también en Facebook» activada, se guarda una tarea en PostgreSQL. La casilla aparece marcada por defecto en el nuevo formulario, pero el usuario puede desmarcarla; el servidor debe estar habilitado.
- Los requerimientos previos a la migración tienen la preferencia desactivada y NO se difunden retroactivamente.
- Si se desmarca Facebook al editar una necesidad ya difundida, el worker solicita retirar la publicación de la página conectada.
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


## Diagnóstico seguro HTTP 400 y listado de publicaciones

En **Red de Obras > Facebook > Publicaciones y estados**, el administrador ve:
- Pendiente / Enviando: trabajo de la cola, **aún no confirmado por Meta**.
- Publicado en Facebook: Meta devolvió un ID de publicación y GALANT guardó su enlace.
- Rechazado por Meta: error confirmado, con código numérico y recomendación segura.
- Revisar en Meta: resultado incierto; verificar la página antes de intentar de nuevo.
- Retirado: GALANT registró el borrado solicitado; las historias de 24 horas no son parte de esta integración.

El enlace de cada anuncio publicado abre Facebook. El estado mostrado representa la última acción de GALANT; no verifica en tiempo real si una publicación fue retirada directamente desde Facebook. La bandeja no debe presentar publicaciones confirmadas como «Sin sincronizar».

Para investigar un **HTTP 400**, revisar el código **Meta** incluido en la nueva descripción:
- **190 / 102**: token inválido o caducado. Renovar el token **de página**.
- **200 / 10 / 283**: revisar `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`, tarea `CREATE_CONTENT`, rol en página y acceso de la app.
- **100**: ID, destino o parámetros inválidos.
- **368**: restricción de la página; no forzar reintentos.
- **506**: publicación duplicada; comprobar la página antes de otra acción.
- Otros códigos: usar el `fbtrace_id` seguro para soporte de Meta, nunca el token.

Operación privada en el VPS, **sin copiar secretos en la conversación ni GitHub**:

```sh
cd /opt/galant-post
# Revisar manualmente el archivo privado .env.preview:
# FACEBOOK_AUTOPUBLISH_ENABLED=true
# FACEBOOK_PAGE_ID=<ID numérico de tu página>
# FACEBOOK_PAGE_TOKEN=<token privado de página>
# Reiniciar SOLO mediante el procedimiento habitual de despliegue.
docker compose --env-file .env.preview -f docker-compose.preview.yml ps facebook-publisher
# Comprobar presencia, NUNCA imprimir el token.
docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T facebook-publisher sh -c 'if [ -n "$FACEBOOK_PAGE_TOKEN" ]; then echo "Token presente"; else echo "Token faltante"; fi'
```

La publicación real requiere autorización de Meta y el VPS configurado. Subir el código de este parche a GitHub no vincula por sí solo un token ni publica los anuncios antiguos.

**Historias / estados de 24 horas:** no se publican mediante el endpoint de texto `/{page-id}/feed`. Necesitan material gráfico propio (foto o video) y el flujo independiente de Page Stories; no deben etiquetarse como publicadas por el éxito de un post normal.


## Messenger: página verificada pero envíos HTTP 401

**Página verificada** solo confirma que el Page Access Token reconoce esa página. No demuestra que el token y la aplicación estén habilitados para enviar mensajes a un destinatario concreto. El envío de GALANT usa el endpoint oficial `POST /{page-id}/messages`, con `messaging_type=RESPONSE` y el PSID recibido del webhook. No cambiar a `/me` por un error genérico.

Si un envío falla, **Red de Obras > Facebook > Conversaciones** muestra el último estado de Messenger por separado de Galancito, más `HTTP`, `código Meta`, `subcódigo` y una referencia de soporte si Meta los entrega. El sistema no almacena mensajes de error crudos ni reenvía automáticamente una respuesta fallida.

Guía según código de **Meta**, no únicamente estado HTTP:
- `190` o `102`: token de página inválido, revocado o vencido. Renovarlo en `.env.preview` y recrear `facebook-publisher`; nunca copiarlo al navegador/soporte.
- `10`, `200`, `230` o `283`: revisar autorización `pages_messaging` realmente concedida al token y a la aplicación, la tarea **MESSAGING** de la página para quien lo generó, acceso avanzado/App Review y los roles o usuarios de prueba permitidos por Meta.
- Sin código de Meta: revisar el permiso de envío y aportar únicamente la **referencia** de Meta a soporte; no asumir que un token de página válido garantiza autorización.
- `551` o límites: revisar si ese destinatario acepta respuestas y las restricciones de Meta.

Si entra un mensaje y falla la respuesta, el webhook y la generación de Galancito ya funcionaron; la falla está en la solicitud de salida a Meta. La ventana de 24 horas se valida por separado. Probar únicamente con un usuario autorizado que haya enviado un mensaje reciente y **sin enviar publicaciones de prueba ni repetir automáticamente mensajes fallidos**.
