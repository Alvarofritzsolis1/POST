# GALANT Messenger: postmortem — saludo → autorización → respuesta vacía (2026-11-23)

**Estado:** corrección candidata en PR #156; no acreditar reparación del VPS sin despliegue y prueba externa.

## Evidencia observada

Un contacto escribió «hola buenos dias». La página respondió con un permiso largo para la IA local. Tras «si», GALANT respondió «Ahora no tengo una respuesta confirmada. Dejé tu consulta para que la revise nuestro equipo». El problema era una conversación de cortesía, no una consulta factual sin respuesta.

## Causa del código

1. `galancito_triage.analyze` no reconocía la combinación «hola buenos dias» como saludo; sí reconocía saludos aislados. Su expresión regular admitía «hola buen dia», pero no «hola buenos dias».
2. `galancito_intake.small_talk_reply` tampoco incluía esa variante. `next_intake_reply` no consideraba el turno como conversación iniciada. `facebook_crm.webhook` podía solicitar consentimiento antes de ofrecer una respuesta local.
3. Después de «si», `facebook_chat_worker` intenta retomar el último mensaje significativo. Al reexaminar el saludo no reconocido, el cálculo de respuesta rápida puede quedar vacío. Como tampoco corresponde usar un modelo para ese saludo, se alcanza la rama de error («respuesta no confirmada») y se activa una alerta humana innecesaria.
4. Esta ruta **no demuestra** pérdida de aprendizaje, falla de pesos ni indisponibilidad del 4B. Un error de clasificación y enrutamiento basta para explicar el fallo. Los registros reales aún se necesitan para atribuir todas las condiciones de ese envío específico.

## Corrección candidata

- Una sola función `is_pure_greeting`, reutilizada por triage e intake, admite saludos combinados comunes sin tragar frases con solicitudes o preguntas.
- El primer saludo obtiene una respuesta local inmediata, con presentación breve de automatización una sola vez, sin pedir autorización innecesaria ni API.
- El worker no declara fracaso de inferencia ni atención humana por un turno de autorización cuyo contenido no requiere modelo.
- La reconciliación de Inbox usa la misma ruta rápida que el webhook, incluso para contactos previamente consentidos.
- El control de seguridad para preguntas complejas, revalidación antes del envío, derivación humana real y ventanas de Meta se mantienen.

## Práctica y validación: criterios verificables

La práctica sintética existente sigue identificada como **sintética**, nunca como evidencia de mejora neuronal. Este parche añade una batería de regresión de flujo **con webhook firmado, cola persistida y worker real**, sustituyendo únicamente el envío a Meta y la inferencia por dobles controlados. La CI ejecuta el archivo `tests/test_messenger_conversation_regression.py` junto a las pruebas Galancito.

Casos de aceptación:
1. «hola buenos dias» recibe una respuesta útil sin permiso ni inferencia.
2. Saludos combinados y variaciones no se convierten en autorizaciones.
3. «hola, ¿cuánto pagan?» no pierde su pregunta por el detector de saludo.
4. Una consulta compleja solicita permiso cuando corresponde; «si» retoma la consulta y no una respuesta genérica.
5. Una conversación heredada que ya pidió permiso a un saludo continúa sin falsa alarma.
6. Saludos sucesivos no repiten presentación automática.
7. Meta sigue aislado en pruebas; no se usan tokens, contactos ni mensajes de clientes reales.
8. El despliegue requiere QA completa, prueba controlada de cuenta externa y verificación de commit/versión del VPS.

**No confundir:** una CI verde acredita rutas verificadas con servicios simulados; la salud del servidor, disponibilidad real de Ollama, recepción por webhook y confirmaciones Meta deben medirse separadamente en el VPS. La calificación de calidad real de Messenger requiere evidencia de conversaciones reales revisadas, no solo aprobar escenarios construidos.
