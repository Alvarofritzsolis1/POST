# GALANT 20.7 — Facebook CRM + asistente para maestros contratistas

## Perfil de los contactos
La audiencia principal son pequeños contratistas de construcción (gasfíteres, carpinteros,
pintores, enfierradores, albañiles y demás especialidades). Algunas personas escriben
con errores, envían mensajes muy cortos, desconocen documentos o prefieren voz.
**Nadie será rechazado ni marcado como incumplidor por su forma de escribir.**

## Qué hace esta versión
- La pestaña de Facebook deja de mostrar un segundo formulario de anuncios. Los
  requerimientos de Red de Obras siguen publicándose desde su formulario, si están
  seleccionados y el VPS está correctamente habilitado.
- Bandeja de Messenger: recepción mediante webhook verificado con HMAC SHA-256, deduplicación,
  estado leído/no leído, fichas de interesado y respuestas en cola con token aislado.
- La primera respuesta automática, cuando está habilitada, se redacta localmente con palabras
  sencillas y pregunta por el oficio. **La IA externa está desactivada por defecto.**
- Notas de voz: se identifican como recibidas, pero se remiten para escucha humana en Meta.
  No se transcriben ni se descargan automáticamente en esta versión.
- Fichas: oficio, empresa declarada (si la tiene), personas disponibles, fecha y experiencia.
  Las coincidencias son orientativas y se explican criterio por criterio. No crean empresa en
  la base maestra ni hacen adjudicaciones.
- Guías de especialidades editables por administración: nombres y apodos de oficios,
  explicación sencilla, documentos confirmados para orientar **solo cuando se soliciten**.
  Se pueden ingresar las 26 labores de la empresa, no se inventan automáticamente.
- Borrador de respuesta asistido por IA y redacción de anuncios. El modelo no tiene poderes
  para publicar por sí mismo, otorgar permisos, ni contratar personal.
- La conversación se envía a un proveedor de IA solo cuando este servicio esté habilitado
  y conste autorización del contacto en su ficha. El administrador debe confirmar el consentimiento.

## Requisitos de Meta y del servidor
Según documentación de Messenger y Webhooks de Meta, deben aprobarse los permisos aplicables,
incluido `pages_messaging` para recibir/responder; configurar el producto Webhooks con
campo `messages`, instalar la app en la página, usar token de página con permiso MESSAGING
y configurar el webhook público con HTTPS y HMAC. Para recibir mensajes de terceros puede
requerirse revisión y modo Live de la aplicación.

**Variables privadas de despliegue** (valores reales nunca en GitHub, chats ni logs):
```env
FACEBOOK_AUTOPUBLISH_ENABLED=true
FACEBOOK_PAGE_ID=<ID de página>
FACEBOOK_PAGE_TOKEN=<token de página privado>
FACEBOOK_MESSAGING_ENABLED=true
FACEBOOK_ORG_ID=<UUID de organización de GALANT>
FACEBOOK_APP_SECRET=<App Secret privado de Meta>
FACEBOOK_WEBHOOK_VERIFY_TOKEN=<cadena larga aleatoria>
FACEBOOK_AI_ENABLED=false
FACEBOOK_AI_AUTO_REPLY_ENABLED=false
FACEBOOK_AI_AD_ENABLED=false
FACEBOOK_AI_API_KEY=
```
Endpoint público para Meta: `GET/POST /api/v1/network/facebook/webhook`.
La respuesta a GET utiliza `hub.challenge` tras comprobar `hub.verify_token`.
En POST se verifica `X-Hub-Signature-256` antes de analizar el contenido.

**No encender el sistema entero sin probar primero una página de ensayo**; al activar
la difusión real, las nuevas necesidades marcadas se podrán publicar automáticamente.

## Respuestas y protección
- Solo a personas que ya escribieron a la página, dentro de la ventana normal
  de 24 h; fuera de esa ventana esta versión no responde.
- La IA explica por qué se solicita un documento y pide solo **una cosa a la vez**.
- Nunca pide ClaveÚnica, contraseñas, fotos de cédula, datos de salud, sexo, edad,
  nacionalidad, ni documentos laborales por mensajes.
- Una persona que trabaja sola también puede dejar su interés. Los requisitos para
  ingresar a obra los determina administración según el caso, no el asistente.
- Mensajes con resultado incierto no se reintentan automáticamente para evitar duplicados.
- Los datos no salen de GALANT hacia un modelo si falta permiso explícito.

## Limitaciones y próximos pasos
- No existe entrenamiento de los pesos del modelo. La adaptación se logra con instrucciones
  especializadas, una base de guías aprobadas y contexto controlado. El contenido se puede
  actualizar sin volver a entrenar un modelo.
- No se han implementado transcripción automática de audios, lectura de comentarios
  públicos ni importación de conversaciones antiguas. Las conversaciones nuevas llegan
  vía webhook cuando Meta activa la suscripción. Para audios, revisión humana en Meta.
- La IA no califica legalmente ni valida F30/F30-1, y las coincidencias no crean
  contratistas habilitados.
- Revisión humana de mensajes y políticas de retención de datos antes de activar
  respuestas completamente automáticas. Se recomienda habilitar primero solo borradores.

## QA
Ejecutar compilación TypeScript, backend completo, pruebas de webhook HMAC, aislamiento
por organización, no duplicados, ventana de 24h, consentimientos y navegación real.
Crear respaldo verificado antes de migrar tablas aditivas. Probar contra Meta en
una página administrada, nunca contra personas reales sin autorización.
