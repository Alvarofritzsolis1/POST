# Qwen contextual LoRA — laboratorio exclusivo de entrenamiento

Fecha: 2026-11-27. Esta rama cambia el corpus y el entrenador aislado, no las reglas de Messenger. No activa un adaptador en producción.

- 32 familias originales con dos formulaciones cada una: jerga, negaciones, cifras incompletas, atribución de terceros, contradicciones, modismos, comprensión de consultas, seguridad y contexto.
- El objetivo supervisado es JSON d/i/q/r como en el protocolo contextual de Messenger, no una frase fija ni una regla de Python. Las referencias solo participan en el entrenamiento y en la pérdida de evaluación, nunca en la inferencia de Messenger.
- Se conserva el corpus anterior para repaso y su asignación de familias; la versión/digest nuevo impide reanudar un checkpoint anterior con otro corpus.
- El piloto CPU de 40 pasos selecciona hasta 80 microejemplos (dos por paso), prioriza los casos estructurados y usa repaso del corpus anterior. No equivale a 40 épocas ni a entrenar todos los ejemplos.
- Validación y test por familias disjuntas. Pérdida de test es diagnóstico, no demuestra calidad conversacional. La prueba de producción debe generar respuestas nuevas con la plantilla y cuantización finales, verificar campos, evidencia, naturalidad, latencia y ausencia de regresiones; el adaptador sintético nunca se promueve automáticamente.
- Para un entrenamiento completo, preferir SFT con LoRA BF16 sobre GPU compatible y el modelo oficial Qwen/Qwen3.5-2B, no el GGUF Q4 de servicio. Comenzar con 1–3 épocas, validación y parada temprana; ajustar tras medir. En CPU conservar el límite y protección existente. No enviar datos reales sin revisión y autorización.

Referencias: https://unsloth.ai/docs/models/qwen3.5/fine-tune ; https://huggingface.co/docs/trl/en/sft_trainer ; https://huggingface.co/Qwen/Qwen3.5-2B .

Estado: cambio de software preparado; la actualización de pesos y su calidad deben verificarse en el entorno de entrenamiento real.
