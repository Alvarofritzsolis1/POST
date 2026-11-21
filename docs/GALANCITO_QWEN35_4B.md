# Galancito — Qwen3.5 4B local (candidata reversible)

Cambio de inferencia, no de datos. El modelo oficial cuantizado es `qwen3.5:4b-q4_K_M` (aprox. 3,3 GB de descarga). Se conserva Qwen3 1.7B en el volumen original. No hay migraciones SQL, cambios de esquema, borrados de conversaciones, fichas, memorias, guías, correcciones ni credenciales. Las rondas históricas y el motor de entrenamiento aislado permanecen en 1.7B hasta validar un cambio independiente; no se trasladan pesos entre arquitecturas.

## Antes de activar
- Revisar y aprobar CI de esta rama, integrar con la versión desplegada y publicar el código mediante el procedimiento seguro del repositorio. La candidata 20.9.11-rc1 incrementa la versión de los tres manifiestos; la publicación del código no activa automáticamente el modelo sin QA real.
- Ejecutar el respaldo y la verificación de restauración establecidos en docs/DESPLIEGUE_VPS_UN_CLIC.md; incluir configuración privada y volúmenes de modelos. No eliminar originales.
- Comprobar `free -h`, `df -h`, `docker stats --no-stream` y `docker compose --profile training --env-file .env.preview -f docker-compose.preview.yml ps`. Para el ensayo reservar 5 GiB al contenedor Ollama, dejar al menos 2 GiB de memoria disponible para el resto tras cargar el modelo y disponer de al menos 8 GiB libres de disco. No iniciar entrenamiento simultáneo; esperar a que la ronda termine y detener únicamente los servicios de entrenamiento si es necesario, sin eliminar volúmenes. Si no se cumple, no activar.
- Guardar una copia privada (modo 600) de .env.preview. Mantener todas las banderas y datos actuales. El modelo anterior sigue siendo el predeterminado si no se define la nueva variable.

## Prueba previa sin cambiar el motor activo
Desde /opt/galant-post, una vez desplegado el código:
```bash
sudo docker compose --profile local-ai --env-file .env.preview -f docker-compose.preview.yml exec -T galancito-ollama ollama pull qwen3.5:4b-q4_K_M
sudo docker compose --profile local-ai --env-file .env.preview -f docker-compose.preview.yml exec -T galancito-ollama ollama list
```
La descarga no sustituye el modelo anterior. Para probar inferencia, ajustar primero GALANCITO_OLLAMA_MEM_LIMIT=5g y GALANCITO_OLLAMA_CPUS=2 en .env.preview y recrear exclusivamente galancito-ollama con `up -d --no-deps galancito-ollama` (ventana de mantenimiento). No cambiar todavía GALANCITO_LOCAL_MODEL. Enviar pruebas sintéticas al API privado de Ollama desde el contenedor api con el modelo nuevo explícito, think=false, num_ctx=2048, num_predict=140 y num_thread=2. Comparar con el original, medir p50/p95, tiempos de carga, RAM y calidad, no enviar mensajes reales. Verificar que no hay OOM ni presión de memoria y que GALANT responde normalmente. Si falla, restaurar el env y recrear solo Ollama.

## Activación asistida (recomendada)
Con el código candidato ya desplegado, ejecutar primero `sudo python3 scripts/upgrade-galancito-qwen35.py` desde `/opt/galant-post`. Es un preflight de solo lectura. Si aprueba, realizar la evaluación comparativa descrita arriba y, solo si es satisfactoria, ejecutar `sudo python3 scripts/upgrade-galancito-qwen35.py --activate` en una ventana de mantenimiento. El instalador exige 7 GiB libres inicialmente, verifica respaldo y restauración aislada, conserva los modelos, prueba el nuevo motor antes y después de cambiar la configuración y revierte el archivo de entorno si falla. No deja iniciada una ronda de entrenamiento concurrente ni transmite mensajes a Facebook. No ejecutar simultáneamente otro despliegue o cambio de configuración. Si no hay RAM suficiente, conservar la versión anterior.

## Activación manual posterior a la prueba satisfactoria
Editar las variables existentes (sin duplicarlas) en .env.preview privado:
```dotenv
GALANCITO_LOCAL_MODEL=qwen3.5:4b-q4_K_M
GALANCITO_OLLAMA_MEM_LIMIT=5g
GALANCITO_OLLAMA_CPUS=2
GALANCITO_NUM_THREAD=2
GALANCITO_TIMEOUT_SECONDS=45
GALANCITO_AI_PROVIDER=ollama
FACEBOOK_AI_PROVIDER=ollama
GALANCITO_LOCAL_AI_ENABLED=true
```
Mantener GALANCITO_AI_ENABLED y FACEBOOK_AI_ENABLED en su valor operativo autorizado. La rama evita seleccionar el equipo externo para Messenger/Red de Obras cuando el candidato está elegido; conserva credenciales y reglas de consentimiento. Los contactos que solo autorizaron otro proveedor no deben recibir inferencias sin el consentimiento correspondiente.
```bash
sudo docker compose --profile local-ai --env-file .env.preview -f docker-compose.preview.yml up -d --no-deps galancito-ollama api worker facebook-publisher
```
Verificar salud, ficha, mensajes, clasificación, modismos, varios oficios, continuidad y memoria; comparar contra el original con casos anonimizados. No declarar calidad superior hasta medir. El timeout de 45 s es un techo de prueba, no una promesa de respuesta.

## Vuelta atrás
Restaurar los valores originales desde la copia privada (no sobrescribir cambios ajenos posteriores); volver GALANCITO_LOCAL_MODEL a qwen3:1.7b y recrear los mismos servicios. No ejecutar down -v, volume rm, ollama rm ni reiniciar la base de datos. Si el código candidato falla, usar además el rollback del despliegue seguro. No restaurar una BD antigua solo para revertir el modelo: se perderían cambios posteriores.

## Estado
Candidata sin despliegue ni pruebas reales en VPS. Las pruebas automatizadas añadidas verifican el modelo seleccionado, endpoint privado, no selección de equipo externo en Messenger y conservación del motor de entrenamiento. Pendiente ejecución de CI, prueba local, revisión de etiquetas de UI y validación real de calidad/recursos antes de activar.

La activación conserva también la configuración privada y el servicio Calc de Proyecto Javiera; no recrea el API sin el overlay de Javiera si está presente.

## Corrección 20.9.11-rc2 — prueba de Qwen3.5 4B en VPS

El primer intento de activación falló después de respaldar/restaurar y antes de seleccionar el modelo. La comprobación anterior exigía respuestas literales («GALANT» y «gasfit») y limitaba a 45 s también la primera carga del modelo CPU. Eso podía generar falsos negativos. Se sustituyó por pruebas sintéticas con respuesta no vacía, dos ventanas diferenciadas (carga en frío 180 s y respuesta caliente 45 s), registro de duración y tokens, y códigos seguros `SMOKE_ERROR` para distinguir HTTP, tiempo de espera, respuesta inválida y lentitud. La activación continúa bloqueada si no supera ambas etapas o falta memoria. La configuración original y los datos permanecen intactos ante fallo. La reparación del código no descarga ni activa automáticamente el modelo: ejecutar el instalador solo tras constatar el despliegue y detener entrenamiento si no hay rondas activas.

No ampliar de forma automática el timeout operativo si la respuesta caliente no pasa la prueba: un modelo demasiado lento para Messenger debe quedarse desactivado hasta revisar recursos.
