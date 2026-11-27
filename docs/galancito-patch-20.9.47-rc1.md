# GALANT 20.9.47-rc1

Esta candidata corrige errores reproducibles de Messenger y Red de Obras y sincroniza las versiones de backend, frontend y lockfile. Complementa la recuperación y las trazas integradas por Core Intelligence. No requiere migraciones de esquema.

## Cambios

| Problema | Comportamiento del parche |
| --- | --- |
| La autorización local configurada no llegaba a los contenedores | Docker Compose transmite `FACEBOOK_LOCAL_PROCESSING_AUTHORIZED` a API, worker y facebook-publisher, con `false` por defecto. El instalador exige respuesta explícita del responsable antes de habilitarla y conserva la configuración privada existente. |
| Una cuadrilla identificada por oficios perdía su cantidad | Una declaración como «una cuadrilla de 6 pintores y yeseros» conserva seis personas. Los equipos materiales, las negaciones y los conocidos no se convierten en dotación. No se infieren trabajadores contratados. |
| Una cantidad aproximada dependía de la extracción del modelo | Se conserva «más de 10 pintores» como declaración aproximada, sin inventar una cantidad exacta ni volver a pedirla como desconocida. |
| Una preferencia voluntaria de canal podía perderse | Se conserva «me sirve más el guasap» incluso junto a datos profesionales y sin teléfono. No se deriva una preferencia de preguntas, negaciones ni menciones de terceros. |
| La experiencia en Galilea podía perder su función | Se reconocen preguntas en tratamiento de usted y respuestas «como maestro sí». Una respuesta que distingue maestro y subcontratista conserva ambos matices. Negar una sola función no niega toda experiencia. |
| Las consultas automáticas repetían errores permanentes | Se bloquean HTTP 400 no transitorios, 401, 403, 404 y 410, además de códigos de parámetros, permisos y token. Los códigos conocidos de limitación o servicio transitorio siguen admitiendo reintento después de 15 minutos. Una lectura manual exitosa restablece la sincronización. |
| El resumen ocultaba fallos de publicaciones y mezclaba canales | Se muestran fallos de publicaciones, mensajes fallidos, pausas y fallback por canal; se distinguen mensajes referenciados de mensajes entregados y referencias ausentes de no disponibles. |
| Un porcentaje parcial podía confundirse con una ronda terminada | La exportación incluye base de puntuación, casos evaluados, objetivo y marca de parcialidad. La interfaz identifica los resultados parciales. |

La recuperación utiliza el historial persistido, mantiene evidencia por campo y respeta correcciones manuales, rechazos, pausas y derivaciones. Ningún cambio aprueba fichas o conocimiento, concede una contratación ni habilita un proveedor externo.

## Validación

Los casos añadidos usan conversaciones y registros sintéticos. La evaluación con Qwen real utiliza `qwen3.5:2b-q4_K_M`, cuantización Q4_K_M y el digest verificado por el evaluador existente. Meta se simula para evitar enviar mensajes a personas reales.

Los resultados verificables se guardan en el informe de evaluación de esta candidata y en los registros del PR. El CI ejecuta las pruebas completas, PostgreSQL, compilación frontend y evaluaciones Qwen. Un resultado del laboratorio no acredita entrega Meta real ni calidad universal del modelo.

## Instalación y comprobación

La instalación sigue [el procedimiento de versiones del VPS](INSTALACION_VPS_CADA_VERSION.md), con respaldo y comprobación de salud y SHA. El cambio coherente de versión activa el mecanismo de despliegue existente únicamente tras su integración en main. Este PR permanece separado de producción mientras se revisa.

1. Comprobar versión y SHA en `/api/v1/health` después de instalar.
2. Reparar o renovar credenciales y permisos de Meta mediante el procedimiento privado del servidor. Un parche no puede generar un token válido ni conceder permisos de la plataforma. No pegar tokens en chats, issues ni archivos del repositorio.
3. Verificar una lectura manual de la publicación afectada. Solo una respuesta exitosa restablece la sincronización automática bloqueada por errores permanentes.
4. Si corresponde al responsable habilitar procesamiento local para contactos nuevos, usar el instalador local o establecer explícitamente `FACEBOOK_LOCAL_PROCESSING_AUTHORIZED=true` en la configuración privada autorizada y recrear los servicios. Con `false` se conserva la autorización individual existente. No basta reiniciar un contenedor sin actualizar su entorno.
5. Consultar primero `POST /api/v1/network/facebook/leads/{id}/refresh-profile?dry_run=true`. Aplicar la recuperación sin `dry_run` solo tras comprobar las modificaciones y sus fuentes. Las fichas pueden seguir incompletas cuando la persona nunca declaró el dato.
6. Verificar una conversación real autorizada, su entrega y su traza de origen final. Comprobar casos de atención humana y revocación sin reactivar pausas automáticamente.
7. Generar otra exportación y comparar fallos y campos con sus denominadores. Mantener el conocimiento pendiente hasta la revisión del responsable y exigir evaluación independiente para afirmar aprendizaje de MAX POWER.

La candidata no reconstruye las trazas históricas que nunca se registraron. Los mensajes fuera de ventana o con entrega incierta requieren revisión; no se reenvían automáticamente.
