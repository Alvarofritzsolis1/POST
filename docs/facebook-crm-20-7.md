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


## Regla adicional: simplificar cuando el interesado pide ayuda
Cuando una persona expresamente dice "no entiendo", "no sé cómo sacar papeles",
"qué documentos necesito" o envía un mensaje de voz, GALANT:
1. No infiere escolaridad ni capacidad por faltas de ortografía.
2. Marca **Necesita orientación** y envía una notificación interna a administradores,
   enlazada a la conversación; no alerta a residentes ni expone contenido privado.
3. No le manda seis documentos de golpe. Hace una pregunta sencilla y espera respuesta.
4. Verifica paso a paso si trabaja con sociedad o a nombre propio, y si tiene empleados.
5. La revisión documental se conserva y se solicita después, por un canal seguro.
6. En un independiente sin trabajadores no pide constitución de sociedad ni
   contratos de trabajadores inexistentes, y orienta el F-30 según su rol.
7. Da ejemplos preventivos apropiados al oficio, sin inventar habilitaciones,
   ni afirmar que es suficiente para entrar a obra.
8. Permite que administración cierre la alerta después de ayudar.
9. Una señal de ayuda prevalece sobre la respuesta automática de IA externa.


## Galancito 20.7.1 — un asistente para todo GALANT

**Nombre oficial:** Galancito. Se identifica como asistente virtual tanto dentro de
GALANT como al conversar con pequeños contratistas desde la página de Facebook.

### Respuestas automáticas de Messenger (solo si están habilitadas)

1. La página recibe un mensaje nuevo por un webhook de Meta firmado.
2. Galancito responde localmente con una sola pregunta informada: explica
   que puede utilizar IA de OpenAI y solicita SÍ o NO. No envía contenido del
   chat a OpenAI antes de la aceptación expresa.
3. Si la persona responde **SÍ**, registra el consentimiento y las respuestas
   posteriores se generan con IA, incluyendo la guía de especialidad
   aprobada cuando corresponda, con límite diario de respuestas y ventana
   estándar de mensajería.
4. Si dice **NO**, no utiliza IA externa, informa que será atendida por una
   persona y envía una notificación interna de seguimiento.
5. Si solicita ayuda documental, expresa confusión o envía una nota de voz,
   pasa a apoyo humano con una respuesta breve. Nunca presenta la lista
   completa de documentos al primer contacto.
6. El administrador puede pausar Galancito desde el contacto; cualquier
   respuesta manual también lo pausa automáticamente.
7. Mensajes de resultado incierto no se reintentan sin inspección humana.

La bandeja de Facebook se actualiza cada diez segundos mientras está visible,
sin borrar los campos de la ficha del contacto que el administrador esté editando.

### Galancito dentro de GALANT y Red de Obras

La ayuda es de solo lectura y está disponible con sesión iniciada. En la
pantalla principal muestra guías sencillas sobre las funciones de GALANT;
en Red de Obras utiliza solo títulos de requerimientos **publicados** en la
organización del usuario. No transmite descripciones privadas, documentos
subidos, historial de Messenger, RUT ni datos de otro cliente.

El usuario debe marcar expresamente la casilla de IA externa antes de que se
envíe su consulta a un proveedor; de otro modo Galancito ofrece una guía
local sin envío de datos.

### Variables privadas para habilitar servicio real

```env
FACEBOOK_AUTOPUBLISH_ENABLED=true
FACEBOOK_MESSAGING_ENABLED=true
FACEBOOK_AI_ENABLED=true
FACEBOOK_AI_AUTO_REPLY_ENABLED=true
FACEBOOK_AI_API_KEY=<clave privada de OpenAI>
GALANCITO_AI_ENABLED=true
GALANCITO_AI_API_KEY=<clave privada separada para Galancito interno>
```

**NO activar por defecto.** Confirmar antes App Review y permisos
`pages_messaging`, Webhooks `messages`, Meta Page ID, App Secret,
verificación del webhook HTTPS, token de página válido y organización GALANT.
El VPS debe recibir las variables en un archivo privado. Es un cambio
operativo que no ejecuta GitHub por sí mismo.

El contenedor API tiene una red de salida HTTPS independiente
(`galancito-egress`) para consultas explícitas de IA. El publicador conserva
su propia salida para mensajes Messenger y anuncios; nunca exponer las claves
en frontend, logs, repositorio ni capturas.
