# MAX POWER y Qwen3.5 2B

Galancito, Messenger, Red de Obras y las prácticas de MAX POWER usan `qwen3.5:2b-q4_K_M` en Ollama. MAX POWER ejecuta sus inferencias en un contenedor privado separado de Messenger, limitado a 3 GiB y 2 CPU por defecto. El arranque en frío requiere 5.120 MB disponibles en el host. Si Ollama confirma que el modelo está cargado, se reservan 3.072 MB.

Al encender MAX POWER, el entrenador por CPU mide la memoria y el disco. El preflight requiere 6.000 MB disponibles en el host, un contenedor de 5 GiB y 7.000 MB libres en disco. El entrenador usa NF4 en la base `Qwen/Qwen3.5-2B` y modifica un adaptador LoRA en la última proyección MLP. Una ronda inicial realiza hasta diez pasos sobre ejemplos ficticios. Guarda el adaptador y el optimizador en checkpoints verificables para reanudar. Messenger tiene prioridad sobre la práctica y el entrenamiento.

El panel registra los pasos que modificaron el adaptador, la pérdida y el resultado de los casos reservados. Un adaptador queda como candidato de laboratorio hasta que se evalúe y se apruebe su uso en producción.

## Entrenamiento con datos autorizados

El entrenador busca estos archivos en la carpeta de la organización dentro de `GALANT_2B_APPROVED_DIR`, que apunta a `/opt/galant-2b-approved` por defecto.

- `<UUID_ORGANIZACION>/approved.jsonl`
- `<UUID_ORGANIZACION>/approval.json`

El JSONL requiere ejemplos anonimizados y autorizados, con al menos 30 casos de entrenamiento, 10 de validación y 10 reservados. El manifiesto Ed25519 autoriza el SHA-256 exacto del JSONL y el modelo `Qwen/Qwen3.5-2B`. Los archivos requieren permisos `0600` y lectura por UID 10001. Configura solo la clave pública del firmante en `GALANT_DATASET_APPROVAL_PUBLIC_KEY`. Las aprobaciones firmadas para otros modelos se conservan en su ubicación original y se requiere una firma nueva para usar esos datos con 2B.

## Actualización y diagnóstico

El despliegue descarga el modelo de producción antes de cambiar los servicios cuando el Ollama local está activado. El 2B se descarga junto a los modelos instalados. La configuración antigua de 1.7B o 4B se interpreta como Qwen3.5 2B en esta versión. El historial conserva los identificadores originales y las rondas pendientes con modelos anteriores se detienen cuando el trabajador intenta retomarlas.

```bash
cd /opt/galant-post
docker compose --profile max-power-auto --env-file .env.preview -f docker-compose.preview.yml \
  ps max-power-controller galancito-training-ollama cpu-2b-manager
docker compose --profile max-power-auto --env-file .env.preview -f docker-compose.preview.yml \
  logs --tail 50 cpu-2b-manager
```

[Modelo Ollama](https://ollama.com/library/qwen3.5:2b-q4_K_M) · [Modelo base de entrenamiento](https://huggingface.co/Qwen/Qwen3.5-2B)
