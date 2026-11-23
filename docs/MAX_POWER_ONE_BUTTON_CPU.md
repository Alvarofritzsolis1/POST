# GALANT MAX POWER 20.9.31 — Un botón para práctica y LoRA CPU

## Qué sucede cuando enciendes MAX POWER

1. El controlador continúa evaluando respuestas reales de Galancito en Qwen3.5 4B y Messenger.
2. Un supervisor CPU aislado consulta automáticamente el encendido de MAX POWER, mediante firma HMAC y control de generación de sesión. No tiene acceso a Postgres, documentos laborales ni al socket Docker.
3. Si Messenger o una práctica están ocupados, el entrenamiento espera o se pausa. Solo una carga intensiva de IA se ejecuta a la vez en las seis CPU.
4. Mide RAM disponible del VPS, RAM del contenedor y disco. Publica el preflight real por organización y no lo cuenta como aprendizaje.
5. Comprueba si existe un dataset firmado y consentido. Si falta, muestra «Falta un conjunto real autorizado y firmado», sin empezar gradientes ni inventar indicadores.
6. Cuando todo está autorizado y el servidor tiene capacidad, inicia automáticamente una ronda inicial de cuatro pasos de LoRA sobre Qwen3.5 0.8B. Guarda checkpoints cada dos pasos y reporta pérdida, RAM y pasos reales cada cinco segundos.
7. Al apagar MAX POWER, el proceso deja de autorizar pasos y guarda el checkpoint del último paso confirmado. Una llamada de Qwen en curso puede tardar en terminar; si el proceso no se detiene, se termina conservando el checkpoint anterior.
8. Al volver a encender, reanuda únicamente desde checkpoints íntegros del mismo dataset y manifest. No suma pasos antiguos como aprendizaje nuevo.
9. Después de cuatro pasos, el adaptador candidato espera evaluación independiente; no se repite indefinidamente el mismo dataset ni se instala en producción.

## Auditoría de requisitos y estados (20.9.31)

MAX POWER muestra ahora cuál es el requisito exacto pendiente. Al encenderlo, distingue entre:

- **Falta la clave pública Ed25519:** aún no existe una identidad de firma de datasets confiable configurada en el servidor. Esto NO autoriza a inventar una clave privada o a firmar conversaciones automáticamente.
- **Faltan ejemplos reales autorizados:** no existe el archivo privado por organización `approved.jsonl`. No se extraen mensajes de Messenger sin permiso.
- **Falta el manifiesto firmado:** existe el conjunto de ejemplos, pero falta la autorización criptográfica `approval.json` para ese hash SHA256 y modelo 0.8B.
- **Permisos inseguros:** los archivos deben ser de lectura/escritura solo para UID 10001 (0600); no se relajan permisos en automático.
- **Datos rechazados:** la firma, el contenido, el formato, la revisión de privacidad o el número de ejemplos no son válidos. No se usará ese conjunto.
- **RAM insuficiente o entrenamiento en espera:** se conservan las reservas para Messenger, se dan turnos a las organizaciones activas y se muestran mediciones, sin falsear progreso.

Los estados de error y de espera no constituyen entrenamientos. Los pesos solo se consideran entrenados si se recibieron eventos firmados con pasos nuevos y dos huellas distintas del adaptador. Los pasos LoRA 0.8B no cambian los pesos del 4B de Messenger.

Para habilitar gradientes reales falta **una autorización verificable del dueño de los datos**, más un conjunto privado anonimizado revisado y firmado por el responsable. MAX POWER no puede sustituir esa autorización con ejemplos artificiales o con el hecho de estar encendido.

## Única preparación imprescindible: datos reales autorizados

No es posible demostrar consentimiento ni crear una firma Ed25519 automáticamente. Para evitar entrenar con información laboral privada, cada organización necesita una autorización explícita una sola vez.

El supervisor busca en el VPS:

    /opt/galant-cpu-lora-private/UUID_ORGANIZACION/
        approved.jsonl
        approval.json
        runs/

Los archivos JSONL y manifiesto deben estar separados, con propietario UID 10001 y permisos 0600, en un directorio con permisos 0700. El formato requiere al menos 30 ejemplos de entrenamiento, 10 de validación y 10 de prueba reservada, todos reales, aprobados, revisados y anonimizados. El manifest Ed25519 autentica SHA256 del JSONL y modelo exacto Qwen/Qwen3.5-0.8B.

Configura la clave pública del firmante una vez en .env.preview:

    GALANT_DATASET_APPROVAL_PUBLIC_KEY=<64 caracteres hex de clave Ed25519 pública>

Nunca ingreses la clave privada en GALANT ni copies conversaciones o datos identificables de contratistas sin consentimiento. La configuración automática no firma ni autoriza datos por sí sola.

Con esos elementos presentes, el botón ya controla automáticamente el entrenamiento y no es necesario ejecutar comandos Docker para iniciarlo.

## Seguridad y límites

El contenedor cpu-lora-manager permanece encendido pero con uso mínimo de recursos en reposo. Su entrenamiento puede usar hasta 1,5 CPU y 5 GiB RAM, sin swap; no tiene acceso directo a la base de datos ni a Messenger.

Qwen3.5 4B permanece en producción. Solo se actualizan los pesos del adaptador LoRA del modelo 0.8B, que NO es compatible directamente con el 4B. Un resultado de CI no demuestra una mejora de razonamiento; se requieren gradientes reales, evaluación reservada y pruebas de regresión.

Los gráficos se basan exclusivamente en métricas reales firmadas. Si el VPS no admite entrenamiento o no existen datos autorizados, se muestra el motivo exacto sin resultados ficticios.

## Diagnóstico técnico

    cd /opt/galant-post
    docker compose --env-file .env.preview -f docker-compose.preview.yml ps max-power-controller cpu-lora-manager
    docker compose --env-file .env.preview -f docker-compose.preview.yml logs --tail 50 cpu-lora-manager
    docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c "from app.version import VERSION,SOURCE_COMMIT; print(VERSION,SOURCE_COMMIT)"

No ejecutar docker compose down -v ni --remove-orphans para esta operación; checkpoints, datos autorizados y volúmenes se conservan.

Referencias: https://huggingface.co/docs/transformers/en/trainer_callbacks ; https://docs.docker.com/compose/how-tos/startup-order
