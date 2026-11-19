# GALANT 20.8.13-rc1 — Messenger: latencia, contexto y proveedores externos

## Propósito
Respuesta natural para oficios y Red de Obras, sin presentaciones repetidas ni
simulación de una persona humana. El contacto recibe información transparente
sobre el tratamiento con IA cuando corresponde. Responder a un saludo sencillo
no debe consumir una API generativa.

## Cambios de esta candidata
- Las cortesías y saludos comunes son respuestas locales, sin tokens.
- La ficha profesional conserva datos declarados durante el diálogo; el modelo
  recibe contexto reciente acotado (sin secretos detectados). No se envían
  documentos ni historial completo a los modelos.
- Gemini, Groq, NVIDIA Build, Z.ai, OpenAI, Mistral y OpenRouter usan exclusivamente
  las conexiones que un administrador registró y verificó en Configuración → IA.
  **No se crean claves, cuentas ni conexiones exitosas automáticamente.**
- El modelo principal asignado por administración conserva su prioridad.
  Si se activa el respaldo, se prueban como máximo dos conexiones habilitadas,
  verificadas y compatibles; se ordenan por latencias recientes medidas.
  Sin historial suficiente, no se atribuye una velocidad inventada a ningún modelo.
- Presupuesto máximo de intentos del equipo IA: alrededor de 10,5 s para
  Messenger, con timeout más corto para respaldo. El camino directo anterior
  de OpenAI reduce su timeout HTTP de 12 a 6 s. **La entrega posterior de
  Meta, la cola y las respuestas lentas del VPS son tiempos adicionales.**
- Timeout de indicadores cosméticos de escritura reducido de 3 s a 1 s.
- Un fallo transitorio (timeout, 429, HTTP 5xx) mantiene verificada la credencial
  y registra un error de uso; un fallo de autorización/modelo requiere revisar
  la configuración. No se prueban proveedores no autorizados.
- La pantalla IA muestra la latencia media observada por proveedor, función y
  resultado, además de tokens y costos configurados.

## Conexión simple de API externas
1. Como administrador, abrir **Configuración → IA**.
2. Crear conexión para un proveedor admitido. Elegir el modelo exacto y
   guardar su clave **solo en GALANT**. No pegar credenciales en GitHub/chat.
3. Pulsar **Conectar y probar**. La prueba puede consumir cuota o tener costo.
4. Activar las conexiones que realmente fueron verificadas.
5. En **Equipo de Galancito**, asignar una principal a Messenger.
6. Activar **Usar otra IA si la principal falla** únicamente cuando el operador
   autorice el consumo de varias APIs. La revisión por segunda IA también
   puede añadir latencia y tokens: activarla solo si la calidad lo justifica.
7. Confirmar `FACEBOOK_AI_ENABLED=true`, webhook y permisos de Messenger. No
   existe el antiguo requisito `FACEBOOK_AI_AUTO_REPLY_ENABLED`.
8. Probar desde una cuenta externa: verificar el estado de envío real en Meta.

## Condiciones innegociables de seguridad
- No inventar una identidad humana, contratos, pagos, cupos o adjudicaciones.
- No procesar mensajes con un proveedor externo sin consentimiento explícito
  aplicable; una respuesta local no implica consentimiento para nube.
- Respetar pausa del operador, solicitud humana, rechazo, cuota y ventana de
  respuesta de Meta. No enviar otra vez resultados de envío incierto.
- Mantener aislamiento por organización y las API keys cifradas.
- Nunca marcar «enviado» por el mero hecho de haber redactado texto.

## Pruebas de aceptación (antes de fusionar)
1. CI verde: backend, Galancito, frontend, Compose y QA de dos usuarios.
2. Saludos «hola», «cómo estás»: respuesta coherente local, sin consulta externa;
   verificar tiempo desde recepción hasta confirmación Meta.
3. «Soy carpintero» y «puedo ir con 4»: completar ficha progresivamente y
   una pregunta por turno. No inventar que tiene empleados legales.
4. Pregunta compleja después de autorizar IA: usar proveedor principal, y solo
   llamar a otra API si falló y la opción de respaldo está habilitada.
5. Desconectar proveedor y forzar 429/timeout: error visible sin deshabilitar
   automáticamente una clave que ya fue verificada.
6. «No quiero IA»: bloquear nuevas inferencias externas y derivar a humano.
7. Enviar desde un usuario externo sin rol: verificar permisos de Meta, estado
   del envío y ausencia de respuestas duplicadas.
8. Comprobar p50/p95 de latencia extremo a extremo; la **latencia media API**
   de Configuración IA por sí sola no demuestra rapidez final en Messenger.

## Pendiente: verificación de producción
Este documento no certifica latencias reales ni conexiones de proveedores en
el VPS. La versión es candidata y permanece como PR hasta aprobar CI y la
prueba de Messenger externo. Evitar despliegue si no se verifican backups,
migraciones, permisos y versión/commit de `api` y `facebook-publisher`.
