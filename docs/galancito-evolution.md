# Galancito Evolution

Acceso para administradores en **Configuración → Inteligencia artificial → Entrenamiento de Galancito**. El laboratorio practica con conversaciones sintéticas y guarda las rondas en PostgreSQL. El trabajador es un servicio independiente. El navegador solo consulta el estado.

## Activación en un entorno de prueba

Usa el procedimiento de respaldos y restauración de GALANT para una base existente. La migración aditiva `20.9.10_galancito_training` crea tres tablas de laboratorio. En una base de pruebas vacía, el comando habitual `app.cli init-db` crea el esquema completo. En una base restaurada, utiliza `app.cli migrate-db --verified-backup-sha256` con el hash del respaldo verificado.

Ejemplo con un proyecto Compose, un archivo de entorno y un almacenamiento propios de QA.

```sh
docker compose --project-name galant-evolution-qa --env-file .env.qa \
  -f docker-compose.preview.yml -f docker-compose.qa.yml \
  --profile training up -d --build

docker compose --project-name galant-evolution-qa --env-file .env.qa \
  -f docker-compose.preview.yml -f docker-compose.qa.yml \
  exec -e OLLAMA_HOST=http://127.0.0.1:11434 galancito-training-ollama ollama pull qwen3:1.7b
```

El perfil `training` incluye el trabajador y un Ollama privado independiente, con un modelo y una solicitud concurrente. El Ollama de Messenger conserva su propia cola. El trabajador aplica límites de CPU y RAM, mide la reserva de RAM disponible y cede ante una cola reciente de Messenger. El modo de reglas locales funciona sin el modelo descargado. La concurrencia automática está limitada a cuatro casos con reglas y un caso con proveedores de modelos. El límite de RAM configurable en el panel se refiere al trabajador. El proceso de Ollama tiene un límite independiente de 3 GB.

Las conexiones externas se seleccionan explícitamente, requieren verificación y tarifas, y reciben solo casos sintéticos. Estas rondas excluyen conocimientos y alias propios de la organización. Los presupuestos se comprueban antes de la llamada con una reserva conservadora. Las respuestas con uso informado se agregan al consumo existente de GALANT. Las llamadas sin medición mantienen la reserva de la ronda. El costo mostrado depende de las tarifas registradas y del uso informado por el proveedor. El presupuesto mensual de GALANT se consulta antes de las solicitudes externas.

## Rondas y revisión

- **Referencia** usa diez conversaciones de referencia y variaciones reproducibles para el resto del objetivo. **Práctica** admite una semilla propia. **Prueba reservada** usa una partición independiente, oculta diálogos y excluye respuestas exactas aprobadas para evitar contaminar la evaluación.
- **Entrenamiento nocturno** guarda la hora de inicio y fin de la ventana civil de Chile. El trabajador admite hasta 10.000 casos por ronda. Pausar conserva los casos terminados y la tanda en curso puede guardar su punto de avance. Detener invalida la reserva del trabajador y descarta cualquier caso todavía sin guardar. Una llamada ya iniciada puede completar su consumo.
- **Ver errores** muestra la ficha esperada por turno y las diferencias detectadas. El informe calcula exactitud sobre los campos presentes y clasifica alertas críticas por separado. Las métricas provienen de los casos ejecutados y distinguen las respuestas por origen. La naturalidad es una estimación sobre los turnos revisados por un modelo evaluador. Con evaluación por reglas, esa métrica aparece como «Sin revisión IA». La puntuación global pondera las competencias que sí se midieron. También se puede seleccionar un modelo distinto para ampliar las propuestas de corrección sujetas a revisión. El conjunto reservado y el volumen de muestra condicionan cualquier conclusión sobre mejoras.
- **Exportar para ChatGPT** descarga Markdown y JSON. En ChatGPT, escribe **GALANT PRACTICA** y adjunta ambos archivos. Solicita patrones, fallas críticas, propuestas y pruebas de regresión. El informe identifica la ronda, el sistema, la versión de instrucciones, el dataset y el comparativo con la última ronda del mismo conjunto y método de evaluación.
- **Aplicar correcciones aprobadas** importa un arreglo de entradas revisadas. Cada entrada apunta a un caso fallido de la ronda elegida y a un turno sintético. La exportación de la ronda ofrece los identificadores. La revisión de cambios de lógica de fichas se hace en código y con pruebas de regresión. El laboratorio puede aplicar respuestas exactas aprobadas y recuperar instrucciones revisadas para Ollama.
- **Reevaluar conjunto** repite el mismo dataset con el conocimiento aprobado vigente y compara el resultado. **Restaurar** crea una versión nueva a partir de una versión previa, o desactiva las correcciones actuales. Las versiones históricas de las rondas se conservan. Los candidatos se mantienen en el laboratorio hasta una revisión de despliegue por separado.

Ejemplo para una ronda que detectó una falla en el primer turno de `referencia-01`.

```json
[
  {
    "case_id": "referencia-01",
    "turn": 1,
    "reply": "Hola, Pedro. ¿Qué oficio tienes?",
    "instruction": "Usa el nombre cuando la persona lo declare explícitamente."
  }
]
```

Cada organización puede exportar sus ejemplos sintéticos aprobados como JSONL de entrenamiento, validación y prueba. La separación es estable por texto, de modo que una frase duplicada queda en una sola partición. Con pocos ejemplos, una partición puede estar vacía. El ajuste LoRA o QLoRA requiere validar GPU, VRAM, dependencias y tamaño del dataset antes de ejecutar un entrenamiento real. Las simulaciones miden desempeño y las correcciones versionan conocimiento. LoRA o QLoRA ajusta parámetros en una ejecución aparte.

El detalle de casos se retiene durante 30 días y los informes agregados durante 180 días. Los identificadores de conexión, el contenido de los conocimientos de la organización y los resultados con datos reservados quedan fuera de la exportación de revisión.

## Metas de calidad

Mide el desempeño en el conjunto reservado con una muestra suficiente. Las metas iniciales son 95% de exactitud en campos presentes, 90% de cumplimiento de los criterios conversacionales, menos de 3% de preguntas que vuelven a pedir un dato entregado, sobre el total de preguntas y cero fallas críticas detectadas. Fija el presupuesto de latencia a partir de las mediciones del VPS y verifica las regresiones de Messenger antes de promover una versión.

## Pruebas

```sh
cd apps/backend
python -m pytest -q tests/test_galancito_training.py
```

Define `TEST_DATABASE_URL` apuntando a un PostgreSQL desechable para ejecutar la misma aceptación con el motor del VPS. Desde `apps/frontend`, ejecuta `npm run build` y `npm run test:logic`. Antes de promover una candidata, verifica la reserva real en el VPS durante una ronda larga, la restauración de la base y la operación de Messenger.
