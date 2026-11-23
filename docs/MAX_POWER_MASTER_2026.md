# GALANT — MAX POWER MASTER (candidato de rama, no desplegado)

**Repositorio:** POST. **Estado:** implementación inicial en PR borrador; aún requiere CI,
revisión, QA real con Qwen/Ollama y comprobación del VPS. **No confundir con una
revisión validada en producción, ni afirmar que existe fine-tuning instalado.**

## Contrato del usuario

- Un solo control **ENCENDER / APAGAR**, sin caducidad temporal, disponible solo para administradores.
- Sin borrado de aprendizaje, métricas o sesiones al apagar. PostgreSQL guarda
  el último estado y un diario permanente por organización.
- Si el VPS reinicia con MAX POWER encendido, el controlador vuelve automáticamente
  al recuperar los servicios; el tiempo acumulado representa los intervalos en
  los que el controlador estuvo vivo, no horas de VPS apagado.
- El apagado detiene nuevas pruebas y detiene la ronda atribuida al controlador,
  preservando todos los checkpoints ya confirmados del entrenador.
- Messenger, chat interno y prácticas manuales tienen prioridad; el trabajo
  automatizado no puede suplantar un turno de usuario ni monopolizar Ollama.

## Arquitectura incluida en esta candidata

- `max_power_models.py`: estado por organización, duración, sesiones, evidencias
  y eventos. No guarda nombres, conversaciones privadas ni contraseñas.
- `max_power_api.py`: `GET /api/v1/admin/ai/max-power` y
  `POST /api/v1/admin/ai/max-power/control/{on|off}`.
- `max_power_worker.py`: controlador durable de baja prioridad; recupera
  rondas que quedaron en cola durante un reinicio; ejecuta evaluaciones numéricas
  reales basadas en agregados autorizados de POST, usando Qwen local.
- `max_power_decisions.py`: selecciona debilidades **humanamente auditadas**,
  comprueba límites de CPU, RAM, disco y cola Messenger, detecta estancamiento y
  diferencia falta de muestras, ausencia de corrección, regresiones y
  no-significancia estadística.
- `MaxPowerPanel.tsx`: panel compacto con control, tiempo, calidad observada,
  diagnóstico, histórico y evidencia de prueba.
- Una migración aditiva crea tablas y evita destruir datos históricos.

## Diagnóstico si no hay mejora

Toda prueba debe terminar en una de las razones auditables:
`no_holdout`, `regression`, `no_correction`, `plateau`,
`insufficient_significance`, `lab_gain`, `not_verified`.
El bloqueo operativo también debe explicarse:
`trainer_unavailable`, `manual_round_busy`, `resource_guard`,
`insufficient_evidence`, `awaiting_new_evidence`, `cannot_schedule`.

No está permitido repetir indefinidamente el mismo holdout y sumar intentos
como si fueran progreso; una muestra real insuficiente es **SIN NOTA**.
Una ganancia de laboratorio no acredita una ganancia en producción.
No se modifican automáticamente los pesos, prompts productivos ni claves API.

## Velocidad

Se recopila la latencia de inferencia de pruebas reales en milisegundos,
p50 y p95 cuando existen muestras; el desglose nativo de Ollama distingue
`load_ms`, `prompt_ms`, `generation_ms`, `transport_ms`.
Identificar el componente de mayor duración **no demuestra** que haya sido
optimizado; debe producir propuestas y mediciones pareadas adicionales.
Toda supuesta mejora de latencia debe conservar exactitud y seguridad, y
medir el tiempo extremo a extremo de Messenger independientemente.

## Automático no significa ilimitado ni inventado

El controlador no tiene tiempo máximo, pero las rondas discretas conservan
presupuesto de inferencia y parada segura. Como punto de partida, solo encola
evaluación real de Galancito General cuando encuentra al menos **16 casos
operativos autorizados**, suficientes para 8 pares A/B reservados. Messenger
permanece en diagnóstico histórico humano hasta implementar evaluadores reales
por intención con datos autorizados y referencias verificables.

Cuando no dispone de nueva evidencia, espera y sigue monitorizando, **no
genera pruebas ficticias para producir porcentajes**.

El aprendizaje de pesos por LoRA pertenece al trabajo independiente del PR
#148; no se invoca ni se mezcla en esta versión. No fusionar sin coordinar
las dos ramas y ejecutar toda la CI.

## Requisitos pendientes para la versión de producción

1. CI completa backend, frontend, migraciones y Compose.
2. Prueba de permisos multiempresa y de interrupción/reanudación después de
   apagar, reiniciar el contenedor y matar el proceso en mitad de una inferencia.
3. Medir consumo de CPU y RAM del VPS y calibrar umbrales, sin degradar p95 de
   Messenger; comprobar OOM, cola, latencias y presión PSI/cgroup.
4. Ampliar el evaluador automático de Messenger con referencias independientes,
   muestras reservadas y criterios de calidad abiertos; las detecciones actuales
   de repetición de oficio, saludos repetidos y afirmaciones no autorizadas son
   **parciales**. No convertir la evaluación de Qwen en una falsa nota global.
5. Completar optimización de estrategia entre rondas y experimentos pareados
   de velocidad. La candidata actual detecta causas y pruebas de razonamiento
   numérico; **todavía no modifica automáticamente parámetros de producción**
   ni demuestra mejoras de latencia.
6. Preparar reversión antes de habilitar correcciones productivas, sin borrar
   estadísticas ni restaurar toda la BD sobre datos recientes.
7. Aprobación del PR, migración tras respaldo verificado, QA con dos usuarios
   y despliegue seguro en `main` mediante el flujo existente.

## Investigación técnica

- https://dspy.ai/current/tutorials/gepa_ai_program/
- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://github.com/ollama/ollama/blob/main/docs/api/usage.mdx
- https://docs.docker.com/engine/containers/resource_constraints/
- https://www.postgresql.org/docs/current/explicit-locking.html

**Criterio de éxito:** una ganancia solo se anuncia como verificada tras
evidencia A/B reservada y, para el canal productivo, auditoría posterior.
La ausencia de ganancia debe enseñar el motivo y el próximo experimento posible.

## Actualización: aprendizaje automático sin auditores obligatorios

El nuevo `max_power_messenger.py` estudia interacciones reales consentidas y
comprueba por reglas si Galancito repite el oficio ya declarado, repite su
introducción o emite solicitudes/afirmaciones inseguras. Selecciona sin
intervención humana el siguiente caso y una de las estrategias de prueba.
La respuesta base y la candidata se generan con **el mismo Qwen local**.
Guardamos solo la decisión, la evidencia objetiva resumida, versiones y
telemetría. Nunca copiamos textos privados a los experimentos.

Una ganancia automática en estos controles es **evidencia de laboratorio por
competencia**, no una mejora desplegada ni una evaluación subjetiva general.
Las preguntas sin respuesta verificable quedan sin nota; un LLM no puede ser
su propio juez definitivo. También se preservan supervisión, permisos y
reversión para decisiones de mayor impacto; esto no impide el funcionamiento
continuo sin que el usuario esté presente.

Fuentes y límites de los evaluadores:
- https://deepeval.com/docs/metrics-introduction
- https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/
- https://arxiv.org/abs/2606.19544
