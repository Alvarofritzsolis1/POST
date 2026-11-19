# Galancito en Messenger

## Auditoría y cambios

La revisión partió de GALANT 20.9.0-rc1, commit `e81d861`. Esa versión ya guardaba múltiples oficios en una tabla y sugería coincidencias. El webhook seguía reemplazando el oficio principal, aplicaba dos extractores con criterios diferentes y asignaba un solo tipo de interés. La recuperación de la bandeja no actualizaba la tabla de oficios. Las confirmaciones breves se confundían con respuestas de consentimiento y la ficha abierta no reflejaba todas las correcciones.

| Área | Comportamiento implementado |
| --- | --- |
| Webhook y recuperación de Meta | Ambos usan las mismas reglas de memoria. El webhook ordena los eventos por fecha, deduplica por identificador de Meta y prepara una sola respuesta por contacto y por lote. Un mensaje tardío puede agregar un oficio o llenar un campo desconocido sin reemplazar una corrección posterior. La cola cancela respuestas obsoletas que todavía no se han enviado. |
| Ficha | Los oficios se acumulan y una rectificación explícita desactiva un oficio declarado previamente. Pueden convivir empleo y oferta de servicios. Las comunas se acumulan salvo indicaciones como «solo en». Se guardan nombre, preferencia de nombre, disponibilidad, equipo y experiencia con su origen. La capacidad de traer personas no acredita empleados contratados. |
| Conversación | Reconoce variantes chilenas como «soi carpintreo» y «conce». La respuesta local pregunta por un campo pendiente. Ante una pregunta directa sobre identidad, declara que es el asistente de IA de GALANT. |
| Privacidad | El destino autorizado queda asociado al contacto. Un «sí» requiere una solicitud de permiso ya enviada. Un cambio entre Ollama, OpenAI y el equipo de proveedores requiere renovar el permiso. El trabajador verifica nuevamente el consentimiento antes de inferir y antes de enviar. La revocación cancela respuestas que aún no se han despachado. |
| Seguimiento | La ficha muestra campos pendientes, fecha y origen de datos, y permite abrir el mensaje correspondiente cuando está en la conversación cargada. Los oficios activos se comparan con las necesidades de obra. La coincidencia es orientativa y la revisión queda a cargo de administración. |
| Rendimiento | Las respuestas locales no invocan al modelo y omiten los avisos de escritura de Meta. El contexto extendido y las guías se consultan cuando son necesarias para la inferencia. Rendimiento de Galancito muestra p50/p95 de Messenger, errores de entrega y de generación, llamadas a Meta y a modelos, y tokens cuando el proveedor los informa. |

Las 346 comunas se cargan como catálogo local. Las abreviaturas y variantes comunes son reglas acotadas. [Códigos Únicos Territoriales de SUBDERE](https://www.subdere.gov.cl/documentacion/c%C3%B3digos-%C3%BAnicos-territoriales-actualizados-al-06-de-septiembre-2018)

## Cómo ejecutar la evaluación

Desde la raíz del repositorio, con las dependencias de `apps/backend/requirements-dev.txt` instaladas.

```sh
python scripts/evaluate_galancito_conversations.py --output /tmp/galancito-regresion.json
python scripts/evaluate_galancito_conversations.py \
  --cases apps/backend/tests/fixtures/galancito_validacion_adicional.jsonl \
  --output /tmp/galancito-validacion.json
```

Cada línea de entrada es un objeto con `id` y una lista `turns`. Cada turno contiene `message` y puede declarar el cambio esperado en `profile`. Los campos omitidos mantienen su valor anterior esperado y se comparan con la ficha completa leída en una sesión nueva de base de datos. El evaluador admite `reply_contains`, `reply_excludes`, `flush: false` para dejar un turno en cola, y `replay: true` para verificar idempotencia.

```json
{"id":"ejemplo","turns":[{"message":"Soy pintora","profile":{"trades":["Pintura"]},"reply_contains":["buscas empleo"]},{"message":"También hago cerámica","profile":{"trades":["Pintura","Cerámica"]}}]}
```

El informe por turno incluye persistencia, diferencias de ficha, número de respuestas, preguntas redundantes y afirmaciones prohibidas. Para repetir en una copia limpia de la revisión base, usar el mismo evaluador y agregar `--source-root /ruta/a/la/copia-e81d861`. La prueba de regresión de 40 casos corre en CI.

## Resultados

Mediana de tres corridas alternadas sobre los mismos 55 turnos sintéticos y sin otras suites ejecutándose durante la medición.

| Indicador | Revisión base | Implementación |
| --- | ---: | ---: |
| Conversaciones aprobadas | 10/40 | 40/40 |
| Comprobaciones fallidas | 43 | 0 |
| Latencia p50 | 14,03 ms | 14,57 ms |
| Latencia p95 | 26,00 ms | 20,09 ms |
| Envíos de respuestas simulados | 52 | 52 |
| Avisos de escritura y lectura simulados | 156 | 0 |
| Llamadas a IA externa | 0 | 0 |
| Tokens de IA en la prueba local | 0 | 0 |

La evaluación adicional aprobó 12 conversaciones y 28 turnos. Las últimas seis conversaciones se agregaron después de cerrar el ajuste de reglas y pasaron en su primera ejecución.

## Alcance de las pruebas

La comparación usa un webhook firmado, una base SQLite nueva por corrida, el worker real y respuestas simuladas de Meta, sin conectar a proveedores. Los tiempos cubren el webhook y el procesamiento del worker en este entorno. La métrica instrumentada en GALANT mide desde el último mensaje entrante hasta el resultado del envío e incluye la espera de la cola. Las cifras locales varían con la carga y dejan pendiente una medición con cuentas de prueba en Meta y el proveedor configurado.

El flujo de administración se verificó en Chromium sobre GALANT local. Se comprobó el cambio de comuna y fecha al recibir un webhook firmado y la navegación al mensaje de origen desde la ficha. Se probaron por separado el consentimiento, la revocación durante el procesamiento, el cambio de proveedor y el reporte de gasto de tokens con respuestas simuladas. Las regresiones de conversación y migración se ejecutaron con SQLite y PostgreSQL 16. La suite general registró 957 aprobadas, 16 omitidas y cuatro fallos. Tres correspondían a pruebas que enumeraban las migraciones. Se actualizó el registro esperado y las tres variantes pasaron al repetirlas. La prueba de exportación de imágenes de Javiera alcanzó el límite de 50 segundos de LibreOffice en la suite general y reprodujo el mismo error al ejecutarse sobre la revisión base.

Los archivos `prompt_maestro_galancito_40_rondas.md` y `galancito_40_rondas.jsonl` no aparecieron en los adjuntos ni en el historial de las ramas remotas del repositorio. La suite de 40 y las conversaciones adicionales son sintéticas. La mejora modifica el prompt, la extracción respaldada por mensajes y la memoria de GALANT. Quedan pendientes la integración del material original, su evaluación oficial y una prueba de producción con Meta. Los pesos del modelo no se actualizaron.

Las expresiones que carecen de una declaración clara pueden quedar pendientes de aclaración. Los audios siguen requiriendo atención humana. Un envío que Meta ya está procesando no se puede retirar desde GALANT.
