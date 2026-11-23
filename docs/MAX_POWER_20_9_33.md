# GALANT 20.9.33-rc1 · Actividad en vivo y simulador de Messenger

## Actividad de MAX POWER

El panel de Inteligencia artificial → MAX POWER muestra el estado de la práctica de fichas, Qwen 4B y LoRA CPU por separado. La pestaña consulta al servidor cada cinco segundos mientras está visible. La fecha del controlador refleja su última comprobación. Durante una comparación A/B se muestra la respuesta que Qwen está preparando y cuántas de las dos respuestas terminó.

En la prueba con 6.224 MB libres y 16 casos operativos disponibles, el controlador registró las 21 fichas sintéticas. Qwen 4B conservó su mínimo de 8.192 MB y la atención de Messenger mantuvo prioridad. Una evaluación de fichas vigente se conserva para evitar contar el mismo trabajo cada vez que el controlador revisa los recursos.

## Simulador Messenger

En Inteligencia artificial → Simulador Messenger, un administrador puede enviar mensajes, revisar la intención y los cambios de la ficha, y calificar cada respuesta por naturalidad y utilidad. La simulación usa el flujo normal de recepción y respuesta de Messenger sobre una base aislada. Puede consultar los avisos públicos vigentes de la organización. El modo Modelo local requiere que Ollama esté habilitado y pide permiso antes de usarlo. La entrega y la evaluación manual pertenecen a la conversación de prueba.

«Vi una postulacion de trabajo» recibe «¿Qué aviso viste? Con el nombre de la obra o el link te puedo orientar para postular». La consulta y los datos referidos al aviso quedan separados de las declaraciones personales. Las solicitudes de permiso se presentan con texto breve y siguen reconociendo las respuestas a solicitudes antiguas.

Se comprobó en Chromium la actualización del panel con RAM limitada, el chat de prueba, la evaluación de un turno y la ficha. Se ejecutó una respuesta del modelo Qwen 4B real en Ollama local después del consentimiento de prueba. La validación en Meta y el entrenamiento LoRA se mantienen como pruebas operativas separadas.
