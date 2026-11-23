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

### Firma de autorización y QLoRA

El script requiere **un manifiesto firmado con Ed25519** que apruebe exactamente
el hash SHA256 de un dataset revisado. La clave privada y los registros de
consentimiento quedan fuera de GitHub y del equipo de entrenamiento. El
manifiesto JSON incluye exactamente los campos:

- `dataset_sha256`: SHA256 del JSONL privado.
- `approved_by`: UUID de responsable.
- `approved_at`: fecha UTC `YYYY-MM-DDTHH:MM:SSZ`.
- `privacy_reviewed` y `usage_authorized`: booleanos verdaderos.
- `training_model`: `Qwen/Qwen3.5-4B`.
- `purpose`: `offline_galant_finetune_qwen`.
- `signature_ed25519`: firma en hexadecimal sobre el JSON **sin la firma**,
  serializado con `json.dumps(fields, ensure_ascii=False, sort_keys=True,
  separators=(",", ":")).encode("utf-8")`.

Este control autentica quién firmó las declaraciones y detecta modificaciones
del dataset, pero **no prueba** por sí mismo que existió consentimiento. Eso
debe contrastarse con registros reales antes de firmar.

Para reducir la memoria GPU se entrena por **QLoRA NF4 (bitsandbytes + PEFT)**.
La configuración actual exige como criterio preventivo 16 GiB de VRAM libre:
no garantiza que el entrenamiento quepa en cualquier GPU; deben vigilarse
memoria, temperatura y fallos CUDA. No usar el VPS donde atiende Messenger.

Luego de revisar el dataset, aprobarlo con la clave privada externa y verificar
la firma en un host CUDA dedicado. La variable `GALANT_PUBLIC_KEY_HEX` debe
provenir del custodio de la clave y contener 64 caracteres hexadecimales.
Nunca cargues la clave privada ni mensajes personales a GitHub:

```bash
GALANT_OFFLINE_TRAINING_APPROVED=yes \
GALANT_DATASET_APPROVAL_PUBLIC_KEY="${GALANT_PUBLIC_KEY_HEX}" \
python scripts/train_galancito_lora.py \
  --dataset /ruta/privada/curado.jsonl \
  --approval-manifest /ruta/privada/aprobacion.json \
  --output /ruta/privada/adapter-2026-11 --execute
```

La herramienta carga pesos HF de Qwen/Qwen3.5-4B, entrena adaptadores QLoRA con
TRL y PEFT, y compara pérdida en ejemplos reservados. Una disminución de
pérdida **no demuestra por sí sola razonamiento mejorado**. La adaptación queda
como candidata fuera de producción; nunca se instala en Ollama automáticamente.
Se requieren evaluaciones deterministas de razonamiento, seguridad y regresión,
pruebas de integración y un despliegue canario reversible para habilitarla.

## Fuentes
- https://huggingface.co/docs/transformers/main/model_doc/qwen3_5
- https://huggingface.co/docs/trl/sft_trainer
- https://huggingface.co/docs/trl/peft_integration
- https://huggingface.co/docs/peft/developer_guides/quantization
- https://developers.openai.com/api/docs/guides/agent-evals
- https://stanfordnlp.github.io/dspy/
