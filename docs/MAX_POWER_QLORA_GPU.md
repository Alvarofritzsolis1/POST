# GALANT MAX POWER 20.9.25-rc1 — Entrenamiento neuronal QLoRA real

La práctica de MAX POWER en CPU realiza inferencia y evaluación, NO modifica pesos. El ejecutor opcional scripts/train_galancito_lora.py actualiza adaptadores LoRA **de verdad** con PyTorch, TRL, PEFT y optimizador de GPU CUDA aislado.

## Requisitos verificables

- Máquina con GPU CUDA dedicada, al menos 16 GiB de VRAM libre según el preflight conservador. El VPS actual no tiene GPU CUDA confirmada y Ollama Q4 no es un motor de entrenamiento. Verifica con nvidia-smi y torch.cuda.is_available().
- En la máquina GPU: instalar PyTorch CUDA apropiado y las dependencias de scripts/requirements-galancito-training.txt.
- Modelo base de entrenamiento Hugging Face: Qwen/Qwen3.5-4B. El archivo cuantizado de Ollama no se entrena directamente. La conversión y compatibilidad del adaptador para Ollama se debe evaluar aparte, nunca suponerla.
- Dataset JSONL privado de ejemplos **reales, revisados, consentidos y anonimizados**. El validador exige al menos 30 ejemplos para entrenamiento, 10 para validación, 10 para test reservado, y separación por grupos. No extraer conversaciones privadas de Messenger sin consentimiento.
- Manifest firmado **Ed25519** que autorice exactamente el SHA256 del dataset y el modelo. No basta con una bandera de aprobación. La prueba de formato y firma se encuentra en apps/backend/tests/test_ai_historical_learning.py.

## Canal de progreso seguro

Configurar en .env.preview del VPS, exclusivamente en el backend API, una clave aleatoria distinta a las claves del resto de GALANT:

    GALANT_FINETUNE_METRICS_SECRET=<al menos 48 caracteres aleatorios>

Para generarla: python3 -c "import secrets; print(secrets.token_urlsafe(48))".

Tras desplegar el backend, un administrador abre MAX POWER y pulsa "Vincular trabajador GPU" y "Copiar credenciales GPU". Este botón proporciona un token firmado específico para su organización; guardarlo solo en la máquina GPU, nunca en Git ni en capturas de pantalla.

En la máquina GPU configurar estas tres variables:

    GALANT_FINETUNE_TELEMETRY_TOKEN=<token específico de organización>
    GALANT_FINETUNE_ORG=<uuid de organización>
    GALANT_FINETUNE_TELEMETRY_URL=https://<dominio HTTPS GALANT>/api/v1/admin/ai/max-power/finetune/telemetry

Solo HTTPS. El trabajador publica datos numéricos verificados por callbacks de TRL cada paso (loss, eval_loss, epoch, grad_norm, learning_rate, VRAM, checkpoints y estado), firmados con HMAC y marca de tiempo. El dashboard actualiza las mediciones cada cinco segundos sin inventar barras, porcentajes ni curvas. Si la red cae, la telemetría queda guardada en el archivo local privado training-metrics.jsonl; el dashboard informa que perdió la señal.

## Ejecución en GPU aislada

Variables de autorización:

    export GALANT_DATASET_APPROVAL_PUBLIC_KEY=<clave Ed25519 pública hex>
    export GALANT_OFFLINE_TRAINING_APPROVED=yes

Validación sin entrenamiento neuronal:

    python scripts/train_galancito_lora.py --dataset /privado/aprobado.jsonl

Entrenamiento genuino sobre GPU CUDA (directorio de salida nuevo y privado):

    python scripts/train_galancito_lora.py \
      --dataset /privado/aprobado.jsonl \
      --approval-manifest /privado/approval.json \
      --output /privado/runs/run1 \
      --epochs 2 --execute \
      --telemetry-url "$GALANT_FINETUNE_TELEMETRY_URL" \
      --telemetry-org "$GALANT_FINETUNE_ORG"

Reanudar tras un corte usando el mismo dataset, manifest, salida, modelo y configuración:

    python scripts/train_galancito_lora.py \
      --dataset /privado/aprobado.jsonl \
      --approval-manifest /privado/approval.json \
      --output /privado/runs/run1 \
      --epochs 2 --execute --resume \
      --telemetry-url "$GALANT_FINETUNE_TELEMETRY_URL" \
      --telemetry-org "$GALANT_FINETUNE_ORG"

Se guardan los checkpoints periódicamente y la configuración de la sesión. Reanudar implica volver al último checkpoint confirmado; no puede recuperar automáticamente gradientes posteriores a ese checkpoint. El reporte evaluation.json permite comparar test reservado antes y después; si no satisface las condiciones, no se publica un candidato.

## Cómo leer los gráficos

- Los pasos son actualizaciones reales de pesos LoRA ejecutadas por TRL, no preguntas o simulaciones.
- La pérdida de entrenamiento y validación es medible, pero una pérdida menor NO prueba razonamiento general mejor.
- El porcentaje se calcula de pasos registrados sobre el total reportado por el entrenador y se distingue de los checkpoints.
- La VRAM es memoria medida por PyTorch; no se presenta una ocupación de GPU que no esté medida.
- El test reservado muestra pérdidas, aciertos verificables y regresiones. Un adaptador aceptado en laboratorio permanece aislado: nunca se publica en Messenger o Galancito sin otras evaluaciones, compatibilidad y despliegue reversible.

## Límites actuales

Este cambio instala infraestructura de **entrenamiento neuronal real y visualización**, pero NO inicia ni contrata automáticamente una GPU externa, NO genera un dataset real consentido sin autorización y NO demuestra todavía mejoras del modelo. Si no hay GPU y dataset firmado, el panel debe mostrar que no hay entrenamiento neuronal. Nunca confundir una CI verde con un entrenamiento real concluido.

Fuentes: https://huggingface.co/docs/trl/sft_trainer ; https://huggingface.co/docs/trl/peft_integration ; https://huggingface.co/Qwen/Qwen3.5-4B
