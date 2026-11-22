# GALANT — Parche focalizado de Práctica Bot (aislado de PR #144)

## Alcance
Este parche sale de `main` en SHA `ffee779a4e07db020b8a625dbac2f5c6166588eb`.
NO modifica el PR #144, NO publica un despliegue y NO cambia la versión visible hasta integrar el trabajo concurrente.

- Corrige equivalencias numéricas en respuestas de la práctica interna (ej. **un contratista** = **1 contratista**), con límites explícitos para evitar falsos positivos.
- Ajusta el prompt sintético: responder con los resultados de la herramienta simulada cuando está disponible, sin declarar falta de acceso a producción.
- La utilidad deja de aprobar una respuesta incorrecta solo por su longitud.
- Incrementa la versión del evaluador interno a 4 para impedir comparar silenciosamente metodologías distintas.
- Introduce `focus_categories` opcional en POST `/api/v1/admin/ai/training/rounds` solo para el perfil `interno` y suites sintéticas. Ejemplo: `{"profile":"interno","suite":"practice","cases":8,"cycles":3,"focus_categories":["seguimiento","contratistas"],"model":"ollama"}` (los demás valores permanecen sujetos a configuración y validación normal).
- Al completar un ciclo sintético de `practice`, recopila categorías de errores y agrega hasta tres instrucciones PREDEFINIDAS al prompt de los ciclos siguientes. Nunca aplica texto libre generado ni se filtra hacia `reference`, `holdout` o `live`.
- Registra tiempos de inferencia de cada turno y, si están disponibles, tiempos nativos de Ollama (carga/prompt/generación/transporte), además de sus promedios en la exportación.
- Añade parada anticipada opcional (por defecto, tres ciclos sintéticos completos consecutivos sin errores) mediante `stop_after_clean_cycles` (`0` la desactiva). Se informa la cantidad de casos omitidos; **no** se interpreta como aprobación del objetivo completo ni aplica en pruebas operativas/holdout.
- Reduce de 140 a 96 tokens el máximo de salida en respuestas sintéticas internas, y dimensiona los hilos del entrenamiento local a núcleos efectivamente asignados (1 a 4), en lugar de fijar 1. El efecto sobre la velocidad no está validado aún.

## Qué significa aprendizaje real
`synthetic_coaching` prueba que una instrucción de corrección se aplicó a la práctica posterior; **no es aprendizaje del modelo en producción ni ajuste de pesos**. `synthetic_coached_cases` informa a cuántos casos se aplicó. El campo `real_learning_demonstrated` permanece falso para rondas sintéticas.

El flujo operacional YA EXISTENTE en `galancito_real_learning.py`, `galancito_trainer.py` y `galancito_training_api.py` requiere un conjunto de datos operativos autorizados, ciclos de entrenamiento, dos ciclos finales A/B reservados, mejora sin regresiones críticas y promoción con aprobación administrativa. Solo entonces puede aplicarse conocimiento validado al chat general. No se amplían permisos ni se promueve aprendizaje sintético.

## Verificación obligatoria antes de despliegue
1. Revisar CI y pruebas: `python -m pytest -q tests/test_galancito_internal_training.py tests/test_galancito_real_learning.py tests/test_galancito_training.py`.
2. Probar `focus_categories` con datos sintéticos en el ambiente de QA sin interferir con el PR #144.
3. En el VPS, medir el modelo Qwen3.5 4B real con mismo hardware y carga (antes/después): p50/p95, tokens/s, `load_ms`, `prompt_ms`, `generation_ms`, recursos y cola.
4. Ejecutar práctica corta, comprobar que `synthetic_coached_cases > 0` solo tras un ciclo con errores y que no aparezca ningún cambio en el conocimiento productivo.
5. Ejecutar una ronda `live` y evaluar pares A/B realmente independientes antes de promover conocimiento. No declarar ganancia si `real_learning_demonstrated` es falso.
6. Fusionar/rebasar contra PR #144 después de que cambie su estado, resolver conflictos en archivos compartidos, volver a ejecutar CI y asignar nueva versión definitiva.

**Estado a fecha de implementación:** código en rama aislada; pruebas CI y benchmark VPS pendientes de confirmación. No se ha desplegado ni verificado una reducción numérica de latencia.


## Auditoría técnica adicional
- **Error corregido:** `int(1.5)` reducía la cuota Docker de 1,5 CPU a un solo hilo. Se usa techo matemático con límite de cuatro hilos; el valor típico pasa a 2, sin cambiar la cuota de CPU del contenedor Ollama.
- **Error corregido:** `galancito_local._generate` imponía 512 tokens mínimos de generación para cualquier llamada con pensamiento activo, incluso en el entrenador. Ahora los presupuestos de *training* se respetan y el comportamiento de producción permanece intacto.
- **Plan de inferencia operativo:** conteos sencillos sin `think`, con máximo 128 tokens; cálculos comparativos con `think` y máximo 320 tokens. Debe medirse en el VPS para confirmar mejora sin pérdida de exactitud.
- **Puntuación:** la práctica sintética interna informa tasa de casos completamente aprobados con `score_basis=synthetic_case_pass_rate`, no la antigua combinación de dimensiones correlacionadas que producía 97/100. La evaluación operativa informa `score_basis=verified_numeric_case_pass_rate`.
- **Telemetría:** se añaden muestras reales de inferencia de respuestas de modelo, p50/p95 (ventana reciente de 512 turnos), desglose nativo Ollama y total de casos omitidos en parada anticipada. Las respuestas de reglas no son muestras de latencia de IA.
- **Focalización:** los ciclos sintéticos fallidos registran categorías y aplican instrucciones específicas con allowlist a ciclos sintéticos posteriores. Nunca se inyectan en referencia, reserva A/B ni producción.
- **Restricción física:** `docker-compose.preview.yml` fija por defecto `GALANCITO_OLLAMA_CPUS=1.5`, `OLLAMA_NUM_PARALLEL=1` y 3 GB de RAM. Sin una medición real de tokens/s, CPU y carga en el VPS no se puede prometer una respuesta de 2–5 segundos.
- **Integración/deploy:** `.github/workflows/deploy-preview.yml` despliega exclusivamente desde `main` y exige versión explícita e incremento sincronizado. El flujo manual también exige `main` y secretos SSH. No es seguro ni autorizado saltarse esa restricción para un PR aislado. El PR #144 sigue abierto; coordinar integración luego de resolver su CI, antes de publicar una versión nueva.
- **Compatibilidad de prácticas activas:** el cambio de versión del evaluador/dataset invalida por diseño nuevas inferencias sobre rondas anteriores que usaban semántica distinta. No desplegar mientras existan prácticas activas; finalizar, pausar o exportar antes según procedimiento autorizado.

### Estado de comprobación
El PR #145 pasó su CI principal y auditorías independientes en el SHA anterior `b4dbeda8fd5c07eb7375b421acfc972bd14926ec`. Las modificaciones posteriores deben superar CI otra vez. El PR #144 tenía tres pruebas de migraciones fallidas en su propia CI; no forma parte de este parche. No se ha probado el VPS ni se ha desplegado esta rama. 
