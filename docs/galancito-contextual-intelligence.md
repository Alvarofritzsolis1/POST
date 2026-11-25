# GALANT · Inteligencia conversacional y memoria

## Alcance y activación

Base auditada `9f4e8c2` (`20.9.41-rc4`, PR #191). La rama del cambio es `codex/galancito-contextual-memory`. El PR #190 trabaja sobre la continuidad del entrenamiento de MAX POWER y permanece independiente. Esta propuesta conserva la numeración de la versión base durante la evaluación.

La opción `GALANCITO_CONTEXTUAL_MESSENGER_ENABLED` viene desactivada. En una instalación de prueba puede activarse en los contenedores API y publicador junto con `FACEBOOK_AI_PROVIDER=ollama` y `GALANCITO_LOCAL_AI_ENABLED=true`. Messenger conserva la autorización local por contacto. El modo local del simulador aplica la misma autorización dentro de su almacenamiento aislado por elección del operador. La reversión consiste en desactivar la opción en ambos contenedores y recrearlos. Las fichas ya guardadas siguen accesibles. El cambio reutiliza `profile_sources` y las tablas de conversación existentes.

## Causas reproducidas en la base

- `facebook_crm.ingest_facebook_payload` y `facebook_inbox_sync.sync_page_inbox` completaban la ficha con `galancito_memory.apply_messenger_message` y después decidían si crear una tarea del modelo. `next_intake_reply`, `small_talk_reply` y las rutas rápidas podían resolver el turno antes de que llegara a Qwen.
- `facebook_chat_worker.process_chat_next` seleccionaba un mensaje mediante `reply_focus` y volvía a decidir si preparar un prompt. `galancito_semantic.decode_local_reply` aceptaba una propuesta de confirmación con un único campo. `remember_confirmation` la vinculaba al envío y `consume_confirmation` esperaba un «sí». La generación de una respuesta de texto por Qwen podía dejar la ficha intacta.
- `galancito_memory.messenger_context` ya incluía ficha profesional, pregunta anterior, historial redactado, recuperación y referencias. El turno actual era un texto individual. El conjunto de fragmentos sin contestar no estaba identificado como fuente de datos nueva.
- Messenger y el simulador de conversación ya llamaban al mismo webhook y worker. El simulador aislaba Meta y los proveedores externos, pero usaba directamente un prompt local y tenía distinta procedencia de autorización. La práctica de entrenamiento MAX POWER tiene un circuito de laboratorio separado. Su paridad de aprendizaje queda fuera de la evidencia del simulador.
- El webhook y la recuperación comparten el bloqueo de escritura de PostgreSQL y la unicidad de los identificadores de Meta. La base cancelaba borradores con nuevas entradas, sin una espera persistente para reunir fragmentos ni una recuperación específica de borradores de IA abandonados antes del envío. Una salida ya entregada a Meta con resultado incierto sigue requiriendo revisión manual.

## Flujo propuesto

1. El webhook persiste mensajes, valida la firma y captura contactos voluntarios. Conserva clasificación local para disponibilidad verificada, publicaciones, identidad, voz, derechos de privacidad y solicitudes explícitas de apoyo.
2. La cola da un margen de 700 ms desde la última entrada que actualizó el trabajo, con un tope de tres segundos desde su creación. Consolida tareas de IA sin reclamar. Persiste el estado de borrador y lo puede recuperar tras 150 segundos. Volver a tomar un envío con estado `sending` podría duplicarlo, por lo que ese estado se conserva para el tratamiento operativo existente.
3. `galancito_contextual.memory_text` entrega una ficha acumulada, historial anterior acotado, última pregunta, referencias y guía aprobada. Una sección separada contiene hasta seis mensajes nuevos en orden cronológico. El teléfono y el correo se redactan antes de inferir y solo se usan indicadores de disponibilidad de contacto.
4. Ollama recibe el esquema estructurado, la memoria y los mensajes nuevos. Una llamada genera intención, pregunta, respuesta y declaraciones. La aplicación comprueba el esquema, exige que cada dato cite un fragmento real, aplica guardas de privacidad y coherencia, y permite una reevaluación acotada si falla la respuesta.
5. Se bloquea el contacto antes de reconciliar los datos. Las fuentes por mensaje, las ediciones manuales, los rechazos y el orden temporal limitan las escrituras. La cuadrilla aproximada vive como declaración textual, la procedencia se distingue de la cobertura laboral y el canal preferido se conserva con su evidencia. La ficha y el cambio a `sending` se confirman antes de la llamada a Meta.
6. La conducta operativa de contingencia conserva Meta y la derivación. Un respaldo externo requiere autorización de equipo vigente, ruta habilitada y contexto permitido. El simulador nunca usa esa ruta. Un borrador obsoleto se descarta antes de que el worker confirme el envío.

### Reglas de la base

| Clase | Decisión |
| --- | --- |
| Seguridad e integridad | Conservar firma, alcance de la organización, ventana de Meta, pausa y revocación, protección de datos, distinción de avisos y ficha, y prioridad de ediciones manuales. |
| Operación | Conservar confirmación de entrega, deduplicación, respuestas sustentadas por obras y control del equipo humano. |
| Redundantes | Omitir la segunda selección de preguntas de ficha y la reescritura guionada en el camino contextual autorizado. |
| Perjudiciales para el razonamiento | Omitir el orden fijo de preguntas y las respuestas rápidas genéricas cuando Qwen puede evaluar el turno completo. |
| Obsoletas | Mantener la regla del PR #191 que retiró los avisos de autorización externa. |
| Interferencia con Qwen | Sustituir la confirmación de un único campo por un esquema de declaraciones múltiples y validar lo pedido contra la ficha y los datos del turno. |

## Modelo y MAX POWER

El código de Messenger solicita `qwen3.5:2b-q4_K_M`. La autorización, las métricas de recursos y las recomendaciones de MAX POWER son independientes de los pesos. `galancito_local._generate` solicita el identificador del modelo configurado. El reporte del laboratorio anota el modelo devuelto, los tokens y la ruta usados. Una etiqueta igual no permite probar por sí sola una promoción LoRA en un VPS. Para eso se requieren el digest del modelo servido, la trazabilidad del adaptador, la comparación base/candidato y la prueba de rollback de esa promoción. Los resultados que acompaña este cambio corresponden al modelo base descargado del registro de Ollama.

## Evaluación

El archivo `apps/backend/tests/fixtures/galancito_contextual_holdout.jsonl` contiene 153 escenarios independientes. El primer caso reproduce el orden y el contenido semántico del incidente con un teléfono sintético. Los casos de infraestructura usan fallas controladas. El evaluador real ejecuta la ruta de webhook firmado, almacenamiento aislado y procesamiento normal de la cola. La entrega de Meta es simulada. Un caso pasa cuando satisface todos sus criterios y cuando, si corresponde, se registra una llamada al modelo. Las métricas semánticas se limitan a los campos, intenciones y condiciones etiquetadas. La naturalidad requiere revisión de las respuestas del informe.

```bash
python scripts/evaluate_galancito_conversations.py \
  --source-root RUTA_A_LA_BASE \
  --cases apps/backend/tests/fixtures/galancito_contextual_holdout.jsonl \
  --real-local --ollama-loopback --output /tmp/galancito-base.json

python scripts/evaluate_galancito_conversations.py \
  --cases apps/backend/tests/fixtures/galancito_contextual_holdout.jsonl \
  --real-local --ollama-loopback --contextual --output /tmp/galancito-candidato.json
```

Puede omitirse `--ollama-loopback` si se ejecuta dentro de la red privada configurada. Los argumentos `--offset` y `--limit` permiten reproducir subconjuntos con el mismo banco. Las latencias desde recepción hasta confirmación de entrega corresponden a Graph simulado. El informe distingue esa medida de la duración de la inferencia y de los tiempos de un VPS de producción.
