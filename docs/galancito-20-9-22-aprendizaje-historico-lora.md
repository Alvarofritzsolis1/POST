# GALANT 20.9.22-rc1 · histórico verificable + preparación de entrenamiento LoRA

**La versión no entrena pesos por sí sola** y no cambia Ollama en producción.
El histórico disponible es metadata acumulada; ver datos viejos no crea
respuestas correctas ni autoriza el tratamiento de conversaciones privadas.

## Panel de historial
GET /api/v1/admin/ai/real-learning/history?months=0 (admin)
recorre todos los períodos *todavía almacenados*: cantidad y primer/último
registro de ejecuciones, respuestas IA entregadas por Messenger, revisiones
humanas y pruebas con Qwen. Agrupa por mes sin copiar texto o identidades.
Cada competencia muestra cantidad de revisiones y errores humanos confirmados.
Sin nota histórica ficticia. El sistema de auditoría de contenido original
conserva la ventana de 30 días, privacidad individual y consentimiento.

## LoRA real, aislado y opt-in
Validar dataset local de conversaciones reales corregidas y expresamente
autorizadas, sin exportarlo a GitHub ni copiar automáticamente Facebook:

  python scripts/train_galancito_lora.py --dataset /ruta/privada/curado.jsonl

Requiere al menos 30 ejemplos de entrenamiento, 10 de validación, 10 reservados.
El reparto entre train/validation/test depende del hash del grupo de conversación
para evitar usar el mismo grupo en distintas fases. Los registros requieren:

  {"source":"human_reviewed_real","approved_by":"UUID-de-revisor",
   "usage_authorized":true,"privacy_reviewed":true,
   "case_group":"SHA256-de-identificador-no-reversible",
   "criterion":"reasoning","verifier":"exact","reference_answer":"...",
   "messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}

Las banderas `approved_by`, `privacy_reviewed` y `usage_authorized` son
**declaraciones en el archivo**, no verificaciones criptográficas ni consultas a
los registros originales. Antes de usar `--execute`, el responsable debe
comprobar fuera de banda la trazabilidad de cada aprobación y consentimiento.
Si no existe esa evidencia, NO entrenar y NO anunciar aprendizaje real.

Los ejemplos anteriores representan el **esquema**, no un dataset real. No incluir
información personal de contratistas ni otras empresas. El validador rechaza
marcadores habituales de correos, teléfonos, RUT y credenciales, pero no es
una garantía total de anonimización: se exige revisión humana y base legal.

Para entrenar realmente en un host CUDA dedicado, después de revisión de
privacidad y aceptación del dataset:

  GALANT_OFFLINE_TRAINING_APPROVED=yes python scripts/train_galancito_lora.py \
    --dataset /ruta/privada/curado.jsonl \
    --output /ruta/privada/adapter-2026-11 --execute

La herramienta carga pesos HF de Qwen/Qwen3.5-4B, entrena adaptadores LoRA con
TRL y PEFT, y compara pérdida en ejemplos reservados. Una disminución de
pérdida **no demuestra por sí sola razonamiento mejorado**. La adaptación queda
como candidata fuera de producción; nunca se instala en Ollama automáticamente.
Se requieren evaluaciones deterministas de razonamiento, seguridad y regresión,
pruebas de integración y un despliegue canario reversible para habilitarla.

## Fuentes
- https://huggingface.co/docs/transformers/main/model_doc/qwen3_5
- https://huggingface.co/docs/trl/sft_trainer
- https://huggingface.co/docs/trl/peft_integration
- https://developers.openai.com/api/docs/guides/agent-evals
- https://stanfordnlp.github.io/dspy/
