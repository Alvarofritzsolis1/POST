# GALANT · Inteligencia conversacional y memoria

## Alcance y activación

Base auditada `9f4e8c2` (`20.9.41-rc4`, PR #191). La rama del cambio es `codex/galancito-contextual-memory`. El PR #190 trabaja sobre la continuidad del entrenamiento de MAX POWER y permanece independiente. Esta propuesta conserva la numeración de la versión base durante la evaluación.

La opción `GALANCITO_CONTEXTUAL_MESSENGER_ENABLED` viene desactivada. En una instalación de prueba puede activarse en los contenedores API y publicador junto con `FACEBOOK_AI_PROVIDER=ollama` y `GALANCITO_LOCAL_AI_ENABLED=true`. Messenger conserva la autorización local por contacto. El modo local del simulador aplica la misma autorización dentro de su almacenamiento aislado por elección del operador. La reversión consiste en desactivar la opción en ambos contenedores y recrearlos. Las fichas ya guardadas siguen accesibles. El cambio reutiliza `profile_sources` y las tablas de conversación existentes.

## Causas reproducidas en la base

- `facebook_crm.ingest_facebook_payload` y `facebook_inbox_sync.sync_page_inbox` completaban la ficha con `galancito_memory.apply_messenger_message` y después decidían si crear una tarea del modelo. `next_intake_reply`, `small_talk_reply` y las rutas rápidas podían resolver el turno antes de que llegara a Qwen. [Webhook](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/facebook_crm.py#L303) [Recuperación](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/facebook_inbox_sync.py#L76) [Intake](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/galancito_intake.py#L609)
- `facebook_chat_worker.process_chat_next` seleccionaba un mensaje mediante `reply_focus` y volvía a decidir si preparar un prompt. `galancito_semantic.decode_local_reply` aceptaba una propuesta de confirmación con un único campo. `remember_confirmation` la vinculaba al envío y `consume_confirmation` esperaba un «sí». La generación de una respuesta de texto por Qwen podía dejar la ficha intacta. [Worker](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/facebook_chat_worker.py#L219) [Foco](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/galancito_memory.py#L381) [Protocolo](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/galancito_semantic.py#L85)
- `galancito_memory.messenger_context` ya incluía ficha profesional, pregunta anterior, historial redactado, recuperación y referencias. El turno actual era un texto individual. El conjunto de fragmentos sin contestar no estaba identificado como fuente de datos nueva. [Composición de contexto](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/galancito_memory.py#L136)
- Messenger y el simulador de conversación ya llamaban al mismo webhook y worker. El simulador aislaba Meta y los proveedores externos, pero usaba directamente un prompt local y tenía distinta procedencia de autorización. La práctica de entrenamiento MAX POWER tiene un circuito de laboratorio separado. Su paridad de aprendizaje queda fuera de la evidencia del simulador. [Adaptador del simulador](https://github.com/Alvarofritzsolis1/POST/blob/9f4e8c2/apps/backend/app/facebook_simulator.py#L102)
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
| Redundantes | Dar prioridad al turno estructurado sobre las preguntas calculadas para el respaldo. |
| Perjudiciales para el razonamiento | Omitir el orden fijo de preguntas y las respuestas rápidas genéricas cuando Qwen puede evaluar el turno completo. |
| Obsoletas | Mantener la regla del PR #191 que retiró los avisos de autorización externa. |
| Interferencia con Qwen | Sustituir la confirmación de un único campo por un esquema de declaraciones múltiples y validar lo pedido contra la ficha y los datos del turno. |

## Modelo y MAX POWER

El código de Messenger solicita `qwen3.5:2b-q4_K_M`. La autorización, las métricas de recursos y las recomendaciones de MAX POWER son independientes de los pesos. `galancito_local._generate` solicita el identificador del modelo configurado. El reporte del laboratorio anota el modelo devuelto, los tokens y la ruta usados. Una etiqueta igual no permite probar por sí sola una promoción LoRA en un VPS. Para eso se requieren el digest del modelo servido, la trazabilidad del adaptador, la comparación base/candidato y la prueba de rollback de esa promoción. Los resultados que acompañan este cambio corresponden al modelo base descargado del registro de Ollama.

## Evaluación

El archivo `apps/backend/tests/fixtures/galancito_contextual_holdout.jsonl` contiene 153 escenarios independientes. El primer caso reproduce el orden y el contenido semántico del incidente con un teléfono sintético. Los casos de infraestructura usan fallas controladas. El evaluador real ejecuta la ruta de webhook firmado, almacenamiento aislado y procesamiento normal de la cola. La entrega de Meta es simulada. Un caso pasa cuando satisface todos sus criterios y cuando, si corresponde, se registra salida del modelo esperado por escenario. Las métricas semánticas se limitan a los campos, intenciones y condiciones etiquetadas. La naturalidad requiere revisión de las respuestas del informe.

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

## Resultados medidos y decisión

La comparación completa ejecutó 153 conversaciones y 215 turnos por versión con Ollama 0.40.18, Qwen3.5 2B Q4_K_M y Meta simulado. El candidato del ensayo completo es `5ecba4a`. Las correcciones posteriores se comprobaron con pruebas focalizadas y quedaron separadas en el JSON. [Ejecución completa y artefactos](https://github.com/Alvarofritzsolis1/POST/actions/runs/45651604158)

| Indicador medido | Base | Candidato del ensayo completo |
| --- | ---: | ---: |
| Escenarios que cumplieron sus comprobaciones | 121/153 | 119/153 |
| Campos etiquetados con el valor esperado | 107/137 | 109/137 |
| Escenarios con salida del Qwen esperado | 146/153 | 147/153 |
| Entregas con respuesta del modelo | 129 | 52 |
| Entregas por respaldo | 32 | 99 |
| Mediana desde entrada hasta procesamiento | 11,26 s | 22,86 s |
| P95 desde entrada hasta procesamiento | 37,49 s | 31,73 s |
| Entradas guardadas una sola vez | 215/215 | 215/215 |
| Preguntas repetidas detectadas por las reglas del evaluador | 0/215 | 0/215 |

La comparación comprueba campos y condiciones etiquetados. Los conteos de intención de cada ruta se conservan en el JSON con sus etiquetas de origen. La base y el candidato usan taxonomías distintas. Una revisión de la salida encontró respuestas que copiaban la pregunta o adoptaban la voz del contratista, además de errores de atribución de datos. La comprobación original de preguntas repetidas por sí sola no detectaba esos errores.

### Incidente del contratista

La versión desplegada reportada por el usuario preguntó de nuevo «¿Qué trabajo realizas?». En el ensayo comparativo, la base describió erróneamente la cantidad de maestros como años de trayectoria. El primer candidato respondió en primera persona como contratista y tampoco completó la ficha.

La repetición local con la validación posterior agrupó los cuatro fragmentos, conservó un único registro por entrada, normalizó el teléfono sintético, clasificó el turno como ficha y entregó una sola derivación real a revisión en la base de prueba. Quedaron pendientes modalidad, procedencia, tamaño de cuadrilla, canal preferido y cobertura de oficios. En otra prueba, la pintura que solo aparecía en una pregunta de precio quedó fuera de la ficha, y la respuesta que copiaba esa pregunta se descartó.

### Pruebas, paridad y despliegue

- 242 pruebas de Messenger, memoria y simulador pasaron con SQLite y PostgreSQL. La suite específica verificó agrupación, mensajes duplicados, un borrador recuperado tras reinicio, entrada durante inferencia, idempotencia, campos manuales y guardas de salida. La regresión anterior pasó 40 de 40 y compiló el frontend.
- Una prueba real del adaptador de Messenger y el simulador produjo la misma intención, los mismos campos comparados y el mismo respaldo ante una extracción incompleta. La evidencia de paridad se limita a ese escenario.
- El CI general pasó en el commit del ensayo completo. La puerta de calidad con Qwen quedó en rojo en siete de nueve bloques. La activación del candidato quedó deshabilitada y el PR sigue en borrador. La verificación de despliegue y la comprobación de un adaptador LoRA activo en el VPS quedan pendientes. [CI general](https://github.com/Alvarofritzsolis1/POST/actions/runs/45651603993) · [PR #192](https://github.com/Alvarofritzsolis1/POST/pull/192)

El JSON consolidado incluye los mensajes anonimizados, respuestas, extracciones, criterios, latencias, causas y la comparación local de las correcciones posteriores. [Descargar el JSON desde GitHub](https://github.com/Alvarofritzsolis1/POST/raw/refs/heads/codex/galancito-contextual-memory/docs/evaluations/galancito-contextual-evaluation.json)

## Seguimiento · Evidencia por mensaje

La revisión `08e7ebd` separa la atribución de la redacción cuando el turno contiene menciones localizables. Qwen selecciona citas textuales identificadas por mensaje. Una cita inválida o ajena queda fuera de la ficha. La segunda inferencia redacta con los datos atribuidos. La ruta de extracción abierta sigue disponible para oficios y expresiones fuera del vocabulario. Cuando la redacción libre falla en una presentación profesional, se puede formular la pregunta que Qwen eligió siempre que ese campo siga pendiente en la ficha persistida. Las preguntas del remitente siguen su propia ruta. Se conserva la autorización previa y la comprobación de vigencia antes de escribir datos o enviar. [Citas de origen](https://github.com/Alvarofritzsolis1/POST/blob/08e7ebd/apps/backend/app/galancito_evidence.py#L35) · [Selección con Qwen](https://github.com/Alvarofritzsolis1/POST/blob/08e7ebd/apps/backend/app/galancito_contextual.py#L150) · [Pregunta validada](https://github.com/Alvarofritzsolis1/POST/blob/08e7ebd/apps/backend/app/galancito_contextual.py#L318)

El caso original pasó con Qwen3.5 2B real y Meta simulado. Se conservaron los oficios de yeso, pintura y carpintería en madera y metal, Concepción como procedencia, «más de 10 maestros» como cantidad aproximada y WhatsApp como canal preferido. El teléfono sintético quedó registrado. La zona de trabajo siguió pendiente y la respuesta fue «¿En qué comuna puedes trabajar?». Qwen eligió ese campo y se usó la formulación validada de GALANT después de que el texto generado falló la validación. El turno se completó con dos llamadas a Qwen y sin derivación humana. Esta ejecución local registró 11,73 s desde la última entrada hasta la entrega simulada.

El piloto de siete escenarios alcanzó cinco aprobaciones automáticas y 23 de 25 campos etiquetados correctos. Fallaron el oficio fuera del vocabulario y una ráfaga que mencionaba Los Ángeles. En la revisión manual, la respuesta de precio tampoco resolvió la pregunta, aunque cumplió las comprobaciones automáticas de ese caso. Los tres casos adicionales pasaron con datos de terceros, procedencia distinta de cobertura laboral y un oficio negado. Pasaron 29 pruebas de infraestructura, memoria y simulador en SQLite y PostgreSQL.

El mismo mensaje que distinguía Maullín como procedencia y Puerto Varas como zona de trabajo produjo la misma ficha, intención y respuesta en Messenger simulado y en el adaptador del simulador. La comparación ejecutó Qwen 2B y se limita a ese caso.

El CI volvió a comparar base y candidato sobre 153 escenarios. Se añadió un reintento acotado de la descarga de Ollama tras un fallo anterior del registro. La activación del candidato permanece deshabilitada mientras se verifica el resultado global. [Evaluación de la revisión](https://github.com/Alvarofritzsolis1/POST/actions/runs/45661705143) · [CI general](https://github.com/Alvarofritzsolis1/POST/actions/runs/45661705103)

### Comparación completa del seguimiento

Los nueve bloques terminaron con el mismo modelo base en Ollama. La comparación cubrió 153 conversaciones y 215 turnos por revisión. El caso original pasó también en el ejecutor remoto, con 12,62 s desde la última entrada hasta el envío simulado.

| Indicador | Base `9f4e8c2` | Candidato `08e7ebd` |
| --- | ---: | ---: |
| Escenarios que pasaron los criterios automáticos | 119/153 | 133/153 |
| Campos correctos de ficha | 107/138 | 128/138 |
| Turnos con respuesta de texto del modelo | 128 | 22 |
| Preguntas de respaldo sobre un campo elegido por Qwen | 0 | 55 |
| Otros respaldos | 32 | 79 |
| Mediana de turnos con respuesta y entrega simulada | 12,21 s | 12,69 s |
| P95 de turnos con respuesta y entrega simulada | 45,78 s | 23,36 s |

El CI general de `08e7ebd` pasó. La evaluación de razonamiento quedó en rojo por los 20 escenarios que todavía incumplen comprobaciones. La revisión manual también detectó una respuesta que desviaba la consulta de precio. El PR queda en borrador y la activación permanece deshabilitada. La comparación verifica una mejora sobre el caso crítico, la ficha y los criterios automáticos. La entrega real de Meta y la calidad general de la redacción quedan pendientes. [Evaluación completa](https://github.com/Alvarofritzsolis1/POST/actions/runs/45661705143) · [CI general](https://github.com/Alvarofritzsolis1/POST/actions/runs/45661705103)

## Seguimiento · Continuidad del chat y preferencia de contacto

En siete escenarios, una pregunta sobre pago por avance terminaba en una derivación que pausaba la automatización. Cuando la persona volvía a declarar su zona laboral o cambiaba de tema, la cola ya no generaba una respuesta contextual. En `2b0fa41`, una consulta sobre pago sin condiciones verificadas obtiene orientación para confirmar el monto y la modalidad con quien contrata, y la conversación sigue activa. Una declaración sobre un pago anterior no activa esa ruta. Una solicitud explícita de atención humana conserva la derivación. [Guía de pago](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/app/galancito_triage.py) · [Worker](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/app/facebook_chat_worker.py) · [Derivación](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/app/galancito_flow.py)

La ficha acepta como candidatos para Qwen oficios declarados fuera del catálogo y expresiones de empleo o trabajo a trato. Los datos conservan su vínculo con la declaración original. La preferencia de contacto exige señales en la declaración personal, como «me acomoda más el wasap». Una mención del WhatsApp de una página no cambia esa preferencia. La lista de comunas devuelve «Los Ángeles» con su grafía oficial. [Atribución](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/app/galancito_evidence.py) · [Flujo de ficha](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/app/galancito_contextual.py) · [Comunas](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/app/comunas_chile.txt)

El evaluador exige que la respuesta de pago mencione monto y modalidad y que el chat continúe activo. Tres escenarios de ubicación y teléfono pasaron a exigir el resultado operativo esperado, dado que esas rutas ya contaban con datos verificados. Ambas versiones se compararon con los mismos criterios actualizados. La prueba de concurrencia recibe un mensaje nuevo durante la primera etapa de inferencia y comprueba que el borrador obsoleto se cancela antes del envío. [Banco de escenarios](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/tests/fixtures/galancito_contextual_holdout.jsonl) · [Pruebas de infraestructura](https://github.com/Alvarofritzsolis1/POST/blob/2b0fa41/apps/backend/tests/test_galancito_contextual_infrastructure.py)

La evaluación de `2b0fa41` reprodujo una derivación omitida. Después de «¿Qué hago ahora?» y «Necesito una persona real», Galancito reenvió la pregunta previa y dejó el caso sin marcar para atención. En `b63355e`, las solicitudes inequívocas de hablar con una persona usan la ruta operativa de atención. La validación rechaza un borrador que copia preguntas breves de cualquier fragmento agrupado. La revisión también acepta «guasap» como forma de WhatsApp para que Qwen pueda atribuir la preferencia a quien escribe. En la reproducción local de la solicitud, la ficha quedó marcada para atención y el envío simulado confirmó la derivación. [Reproducción en CI](https://github.com/Alvarofritzsolis1/POST/actions/runs/45672352277) · [Corrección](https://github.com/Alvarofritzsolis1/POST/commit/b63355e)

La revisión `2b0fa41` cerró la comparación con 152 de 153 escenarios aprobados. El caso original y «me acomoda más el wasap» pasaron. La derivación anterior fue el único fallo de esa ejecución. El CI general de esa revisión pasó. [Evaluación](https://github.com/Alvarofritzsolis1/POST/actions/runs/45672352277) · [CI general](https://github.com/Alvarofritzsolis1/POST/actions/runs/45672352366)

En `b63355e` pasaron 35 pruebas locales de infraestructura, memoria y simulador con SQLite y PostgreSQL. También se repitió con Qwen real el caso que distingue un aviso de terceros en Copiapó, la procedencia de Tomé y el oficio propio de montaje de bombas hidráulicas. Messenger simulado y el simulador guardaron los mismos datos y produjeron la misma intención y respuesta en ese caso.

De seis escenarios adicionales, cuatro cumplieron sus criterios. Qwen omitió una preferencia expresada como «me sirve más el guasap» cuando llegó junto con la presentación laboral, y el respaldo derivó el turno. El otro caso pedía guardar correo como canal preferido. La ficha contextual admite WhatsApp y Messenger como canales preferidos y mantiene el correo voluntario en su campo de contacto. La naturalidad de las respuestas sigue requiriendo revisión de los diálogos.

La configuración compilada de Docker Compose confirmó que la opción contextual se propaga como `false` por omisión y como `true` cuando se activa de manera explícita. Esa comprobación se hizo con valores sintéticos y sin iniciar servicios. El ensayo usó el modelo base de Qwen. La entrega con Meta real, el despliegue y la existencia de un adaptador LoRA activo en el VPS siguen pendientes de verificación.

### Comparación final de esta ronda

Se ejecutaron 153 conversaciones y 215 turnos por versión con Qwen3.5 2B real en Ollama y Meta simulado. Las cifras de intención se limitan a los turnos etiquetados. El caso original volvió a responder «¿En qué comuna puedes trabajar?» después de guardar su ficha. La entrega simulada del turno tardó 12,62 s desde la última entrada.

| Indicador | Base `9f4e8c2` | Candidato `b63355e` |
| --- | ---: | ---: |
| Conversaciones que cumplieron los criterios | 115/153 | 153/153 |
| Campos de ficha correctos | 117/155 | 155/155 |
| Criterios de intención cumplidos | 0/5 | 5/5 |
| Turnos sin copia textual de la persona | 215/215 | 215/215 |
| Turnos que evitaron las preguntas repetidas etiquetadas | 215/215 | 215/215 |
| Escenarios con salida de Qwen | 146 | 144 |
| Llamadas locales al modelo | 159 | 307 |
| Mediana de turnos con entrega simulada | 12,88 s | 10,35 s |
| P95 de turnos con entrega simulada | 48,85 s | 22,32 s |

Pasaron la evaluación conversacional y el CI general de `b63355e`. Nueve escenarios del candidato se resolvieron por rutas operativas sin salida de Qwen y cumplían los criterios definidos para esas rutas. El PR #192 sigue en borrador y la función viene desactivada. El JSON conserva las comparaciones anteriores y los seis casos adicionales, incluidos los fallos. [Corrida con Qwen](https://github.com/Alvarofritzsolis1/POST/actions/runs/45674949068) · [CI general](https://github.com/Alvarofritzsolis1/POST/actions/runs/45674949059) · [JSON anonimizado](https://github.com/Alvarofritzsolis1/POST/raw/refs/heads/codex/galancito-contextual-memory/docs/evaluations/galancito-contextual-evaluation.json)
