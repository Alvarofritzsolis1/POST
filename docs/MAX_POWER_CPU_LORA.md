# GALANT 20.9.26-rc1 — entrenamiento neuronal de pesos con CPU actual

## Estado y alcance

Este módulo OPCIONAL realiza actualizaciones genuinas de pesos LoRA sobre Qwen/Qwen3.5-0.8B usando PyTorch y PEFT, dentro de un contenedor aislado. El Qwen3.5 4B de producción y Messenger NO se modifican. El adaptador 0.8B no es compatible con los pesos del 4B.

La modalidad NO se inicia automáticamente al desplegar ni al encender MAX POWER. No genera ejemplos sintéticos ni inventa resultados. El servidor actual observado dispone de seis vCPU y alrededor de 12 GB de RAM, sin GPU CUDA comprobada. El proceso puede ser muy lento, exceder el límite de 5 GB y fallar. No prometemos mejoras antes de una prueba con recursos reales.

Recursos: contenedor limitado a 1,5 vCPU y 5 GiB RAM, sin swap, puerto abierto, acceso a Docker.sock, base de datos ni carpeta de documentos de GALANT. Tiene su red de salida y volumen privado distintos. Solo arranca mediante --profile cpu-lora y una orden explícita.

## Preflight sin descargar pesos

La comprobación mide:
- mínimo 6 GB de RAM disponibles para todo el host;
- al menos 4,3 GB libres dentro del cgroup con límite de al menos 4,8 GB;
- al menos 7 GB libres de disco;
- memoria consumida por el propio proceso.

En el VPS, preparar una carpeta segura para UID 10001:

    sudo install -d -o 10001 -g 10001 -m 700 /opt/galant-cpu-lora-private
    sudo install -d -o 10001 -g 10001 -m 700 /opt/galant-cpu-lora-private/runs

Construir imagen opcional (la construcción descarga PyTorch CPU; no debe coincidir con horario de carga máxima):

    cd /opt/galant-post
    docker compose --env-file .env.preview -f docker-compose.preview.yml --profile cpu-lora build cpu-lora

Comprobar recursos sin modificar pesos:

    docker compose --env-file .env.preview -f docker-compose.preview.yml --profile cpu-lora run --rm --no-deps cpu-lora --preflight

Si ready=false no entrenar ni forzar el preflight. ready=true SOLO significa recursos iniciales suficientes, no demuestra que el modelo quepa.

## Datos de entrenamiento legítimos

El dataset es JSONL privado, con al menos 30 registros para train, 10 validation y 10 test, con case_group hash por caso para prevenir filtraciones. Cada registro exige source human_reviewed_real, usage_authorized=true, privacy_reviewed=true, approved_by UUID, criterion permitido, mensajes user y assistant, referencia verificada y verificador exact o contains.

El JSONL debe ser real, revisado, anonimizado y estar expresamente autorizado para entrenar. No copiar conversaciones enteras de Messenger, datos laborales identificables o credenciales. El validador apps/backend/app/galancito_finetune_dataset.py detecta patrones comunes de identificadores, pero no reemplaza una comprobación de privacidad.

El manifest independiente requiere firma Ed25519 del hash SHA256 exacto del JSONL y debe aprobar EXPLÍCITAMENTE training_model Qwen/Qwen3.5-0.8B (no Qwen3.5-4B). Estructura: dataset_sha256, approved_by (UUID), approved_at (UTC), privacy_reviewed=true, usage_authorized=true, training_model, purpose offline_galant_finetune_qwen, signature_ed25519. La firma cubre el JSON sin signature_ed25519, serializado con sort_keys=true, ensure_ascii=false y separators coma/dos puntos. Clave privada fuera del servidor. Ejemplo en apps/backend/tests/test_ai_historical_learning.py.

Guardar approved.jsonl y approval.json en /opt/galant-cpu-lora-private con propietario 10001 y permisos 0600.

## Validar e iniciar una ronda REAL de 4 pasos

Configurar por la terminal en forma segura:

    export GALANT_OFFLINE_TRAINING_APPROVED=yes
    export GALANT_DATASET_APPROVAL_PUBLIC_KEY=<clave_publica_Ed25519_hex_64>

Validación sin entrenamiento:

    docker compose --env-file .env.preview -f docker-compose.preview.yml --profile cpu-lora run --rm --no-deps cpu-lora --dataset /private/approved.jsonl

Entrenamiento real (si preflight y dataset validan):

    docker compose --env-file .env.preview -f docker-compose.preview.yml --profile cpu-lora run --rm --no-deps cpu-lora \
      --dataset /private/approved.jsonl \
      --approval-manifest /private/approval.json \
      --output /private/runs/cpu-run-01 \
      --max-steps 4 --checkpoint-steps 2 --execute

Una ejecución permitida realiza backpropagation y actualizaciones de parámetros en la CPU, registra la huella de tensores entrenables antes y después, y guarda un checkpoint auténtico cada 2 pasos. La prueba de aceptación exige modificaciones reales; si no cambian, falla. Se guarda test reservado antes y después. NO se declara ganancia de razonamiento general automáticamente.

Para reanudar, reutilizar EXACTAMENTE el mismo dataset, manifest, output, max-steps, checkpoint-steps y max-tokens, agregando --resume. El trabajo reanuda desde el último checkpoint real y puede recalcular los pasos posteriores a ese checkpoint. Un trabajo no tiene límite de duración en reloj, pero cada ronda tiene entre 1 y 1000 pasos autorizados. No ejecutar múltiples rondas en paralelo.

## Gráficos en MAX POWER

El frontend muestra ahora una opción CPU LoRA de 0.8B y la memoria RAM del proceso medida por /proc/self/status. La API admite métricas CPU/GPU con firma HMAC por organización y consulta cada cinco segundos. La telemetría NO envía ejemplos, mensajes o parámetros.

El backend necesita la variable GALANT_FINETUNE_METRICS_SECRET en .env.preview (aleatoria, al menos 48 caracteres) y recrear solamente la API. El administrador abre MAX POWER, pulsa Vincular entrenamiento CPU/GPU y copia el token y UUID. En el host del trabajo, configurar las variables privadas GALANT_FINETUNE_TELEMETRY_TOKEN y GALANT_FINETUNE_ORG, además de la URL HTTPS completa GALANT_FINETUNE_TELEMETRY_URL.

En el comando de entrenamiento añadir:

    --telemetry-url "$GALANT_FINETUNE_TELEMETRY_URL" --telemetry-org "$GALANT_FINETUNE_ORG"

Si no se configura la conexión, el journal local training-metrics.jsonl seguirá almacenando los pasos reales y el panel NO mostrará gráficos ficticios. El journal, checkpoints y adaptadores quedan bajo /private/runs.

## Criterios de no-regresión

No activar automáticamente en producción ni ejecutar sin recursos, datos autorizados o hardware probado. El entrenado de 0.8B no sustituye el 4B y su adaptador no se promueve automáticamente. La CI verifica código, aislamiento y reglas; no constituye una ejecución real de pesos. La pérdida de validación por sí sola tampoco prueba razonamiento.

Referencias: https://huggingface.co/Qwen/Qwen3.5-0.8B y https://huggingface.co/docs/transformers/model_doc/qwen3_5 y https://huggingface.co/docs/peft/en/index
