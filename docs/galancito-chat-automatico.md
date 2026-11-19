# Chat automático de Galancito

En **Facebook → Conversaciones**, el botón **Chat automatizado** controla cada
contacto. **Desactivar** cancela los borradores pendientes y deja los mensajes
nuevos para atención humana; **Activar** reanuda las respuestas desde el siguiente
mensaje entrante. Una respuesta manual del administrador solo reemplaza el turno
actual y no apaga el chat futuro.

Los mensajes simples se atienden con reglas locales, sin espera artificial ni
revisión manual. El panel muestra *pensando*, *escribiendo* y *enviando* según el
estado real de la cola. Messenger recibe `typing_on` mientras trabaja el
publicador. El texto se marca como enviado solo después de la confirmación de Meta.

Las consultas complejas pueden usar el modelo configurado para Messenger después
del consentimiento del contacto. Si está activado el **equipo IA** con proveedor
alternativo y revisor, una respuesta rechazada puede pasar a otro proveedor
verificado. Si ninguno produce una respuesta aceptable, Galancito informa que la
consulta requiere revisión y crea una notificación para administración. Las
solicitudes explícitas de una persona también generan aviso. Las respuestas de
modelo nunca deben prometer empleo, adjudicaciones o requisitos no confirmados.

La sincronización de Messenger puede responder a un mensaje reciente perdido por
el webhook. No reenvía mensajes antiguos, no duplica un mensaje ya importado y
omite las conversaciones donde Meta o un operador ya respondieron. El enlace de
la ficha con una necesidad solo se hace si hay una única necesidad activa con
oficio exacto, dotación suficiente y fecha declarada compatible. El enlace sigue
pendiente de revisión; no aprueba una contratación.

## Activación

El servidor debe tener Messenger configurado y
`FACEBOOK_AI_AUTO_REPLY_ENABLED=true`. Para usar modelos, se necesita además la
IA de Messenger o un equipo IA habilitado con proveedores verificados. El botón
por contacto no reemplaza la configuración del servidor. Comprueba la entrega
con una cuenta de prueba de Meta antes de usarlo con público general.

## Evaluación y entrenamiento

`python scripts/evaluate_galancito.py --output work/galancito-evaluation.json`
comprueba 64 casos sintéticos de comprensión determinista. El currículo de
conocimientos existente usa recuperación de contenido aprobado; no ajusta pesos
del modelo. Este repositorio no incluye un conjunto de entrenamiento etiquetado,
un proceso de ajuste fino ni una instalación local del modelo para ejecutar 50
épocas reales. Para ese entrenamiento hacen falta datos autorizados, un modelo
base y hardware de entrenamiento; las pruebas de reglas no equivalen a épocas.
