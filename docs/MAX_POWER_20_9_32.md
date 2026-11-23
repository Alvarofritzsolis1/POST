# GALANT 20.9.32-rc1 · MAX POWER y fichas profesionales

La candidata parte de `main` en `c8384bc`. La migración agrega `facebook_leads.employee_count` como columna opcional. Las fichas anteriores conservan sus valores y su historial.

## Conversación y ficha

- Galancito reconoce consultas breves como «cuánto pagan» y «tienen cupos» aunque falte el signo de interrogación. Atiende esa consulta antes de seguir con la ficha. Si el turno aporta una declaración profesional, la captura igualmente.
- Las reglas distinguen búsqueda de empleo, oferta de servicios o ambas, empresa o trabajo independiente, cuadrilla disponible y personal contratado. «Puedo ir con dos ayudantes» declara tres personas en total. «Tengo dos trabajadores contratados» declara personal contratado y deja pendiente la capacidad de acudir a una obra.
- Las fechas relativas usan la fecha del mensaje en Chile. Una respuesta ambigua se conserva como tal hasta que la persona dé un dato concreto. El historial atrasado no restaura un dato corregido. Se respetan los datos manuales confirmados.
- Los estados y la referencia al mensaje se guardan junto a los datos. El teléfono y el correo voluntarios se procesan por separado y no intervienen en la completitud profesional. Se puede continuar por Messenger.
- La auditoría de respuestas reales revisa preguntas repetidas sobre campos reconocidos, menús, autopresentaciones, prioridad de la consulta y ciertos problemas de privacidad o promesas. El historial parcial permite esos controles, pero no acredita la exactitud de una ficha real ni el trato humano de la respuesta.

## Qué ejecuta MAX POWER

1. Revisa permisos, recursos, trabajo en curso y cola de Messenger. Los trabajos reales autorizados conservan la prioridad.
2. Si faltan casos reales, completa una práctica de fichas con la misma extracción, normalización y persistencia transaccional de Messenger sobre una base SQLite separada. Guarda los recuentos y diagnósticos, sin fichas ni texto de los casos en el informe.
3. Si Qwen 4B aislado está disponible, prueba en un conjunto pequeño una instrucción para responder la consulta antes del llenado. Guarda un resultado por caso y separa desarrollo de reserva. Cambiar la instrucción de laboratorio no altera las instrucciones de producción.
4. Cuando se agotan los casos válidos, queda encendido a la espera de novedades. Un reinicio conserva los resultados y las pruebas en cola. Si se apaga durante la inferencia, la sesión anterior pierde autorización para registrar su resultado.

El panel da los denominadores de las verificaciones y muestra 45/25/20/10 como pesos objetivo. El trato humano queda sin nota automática. Las señales de estilo son comprobaciones parciales. El entrenamiento LoRA firmado conserva su canal y sus checkpoints. Qwen 0.8B y Qwen 4B tienen arquitecturas distintas y sus adaptadores no son intercambiables.

## Comparación reproducible de reglas

Casos sintéticos diseñados para esta evaluación, con resultados esperados definidos por caso. La referencia es el código de 20.9.31-rc1. Doce casos quedaron reservados para la comparación. Las cifras cuentan verificaciones y no equivalen a un porcentaje de calidad en producción.

| Casos reservados | 20.9.31-rc1 | 20.9.32-rc1 |
| --- | ---: | ---: |
| Valores o estados de ficha correctos | 30 / 45 | 45 / 45 |
| Consultas con respuesta pertinente según la comprobación | 0 / 2 | 2 / 2 |
| Controles de continuidad | 5 / 10 | 10 / 10 |
| Señales objetivas de estilo | 15 / 20 | 20 / 20 |
| Datos completados sin sustento detectados | 4 | 0 |

La referencia usa su extracción y respuestas originales. El evaluador adapta las firmas de las funciones antiguas, reproduce sus llamadas de contacto y aplica a ambas versiones la misma comprobación de preguntas. La disponibilidad de estados y sus referencias se evalúa como parte del contrato de ficha.

```bash
git worktree add --detach ../galant-20-9-31 c8384bc
python scripts/evaluate_max_power_practice.py --reference ../galant-20-9-31 --output /tmp/galant-reference.json
python scripts/evaluate_max_power_practice.py --output /tmp/galant-candidate.json
cd apps/backend
python -m pytest -q tests/test_max_power_practice.py tests/test_max_power_recovery.py tests/test_max_power_messenger.py
```

## Despliegue y recuperación

Validar CI y el respaldo de PostgreSQL y de los archivos persistentes antes de programar la publicación. Usar el procedimiento de [despliegue de GALANT](DESPLIEGUE_VPS_UN_CLIC.md), que aplica las migraciones antes de iniciar los contenedores. Validar el webhook, el panel y un contacto de prueba de la organización antes de encender MAX POWER. La práctica de reglas funciona con SQLite aislado. Para la prueba de Qwen se requiere el servicio de Ollama de laboratorio y el modelo exacto `qwen3.5:4b-q4_K_M`.

Ante una degradación, apagar MAX POWER desde Administración, conservar PostgreSQL y los volúmenes y seguir el procedimiento de reversión del despliegue. La columna agregada admite valores nulos y puede permanecer al volver al código anterior. El resultado sintético persistido se deduplica por organización, huella del dataset y versión del protocolo. Para recuperar LoRA, el supervisor revisa la huella y el checkpoint que corresponde al modelo y al conjunto autorizado.

## Límites de la evidencia

El banco sintético no es un historial de Messenger ni un dataset autorizado para entrenar. El ensayo mide reglas y respuestas. La evaluación humana de naturalidad y una medición comparativa de producción siguen pendientes. No se ejecutó LoRA en esta entrega: faltó un dataset real autorizado y firmado, y el preflight local informó margen de memoria insuficiente en el cgroup durante la prueba.
