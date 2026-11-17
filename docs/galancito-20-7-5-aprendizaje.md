# Galancito 20.7.5-rc1: enseñanza administrada y respuesta híbrida

La base real disponible es `b4feea3`, GALANT **20.7.3-rc1**. No se recibió una
20.7.4 verificable, por lo que las comparaciones no se atribuyen a esa versión.
Esta entrega cambia código y esquema; no acredita despliegue en el VPS.

## Qué aprende y cómo enseñarle

En **Red de Obras → Facebook → Conocimientos**, administración puede crear una
pregunta y respuesta, procedimiento, oficio con sinónimos, ejemplo, corrección,
respuesta que evitar o criterio de atención humana.

1. Escribir título, contenido y frases relacionadas. Elegir dónde puede usarse:
   asesor interno, Messenger o ambos. El valor inicial es **solo interno**.
2. Guardar. Queda **pendiente** y no participa en respuestas.
3. Revisar el contenido guardado y aprobar esa versión. Si otra persona lo
   cambió mientras se revisaba, la aprobación se rechaza con HTTP 409.
4. Consultar la frase relacionada. Las respuestas recuperadas muestran su
   referencia y versión. Una FAQ/corrección exacta y breve no necesita Ollama.
5. Corregir o desactivar cuando corresponda. Editar revoca la aprobación.
   Desactivar excluye el contenido de consultas futuras, sin borrar historial.

**Cargar 12 ejemplos iniciales** agrega material pendiente e idempotente.
Incluye «ola soy gasfite», búsqueda de pega como trabajador, empresa de pintura,
dotación de cuatro trabajadores, documentos según situación y atención humana.
Los ejemplos no son ofertas de trabajo reales ni requisitos legales.

En el chat interno, **Útil** e **Incorrecta** guardan evaluación. Administración
puede usar **Proponer corrección**: la propuesta queda pendiente en Conocimientos.
Después de aprobarla, se recupera en consultas pertinentes. Los votos por sí
solos no cambian respuestas ni autorizan conocimiento nuevo.

Esto es aprendizaje mediante recuperación local (RAG), **no modificación de
pesos**. No hay entrenamiento automático con mensajes privados, descarga de
modelos por solicitudes de usuarios ni ejecución de herramientas del negocio.

## Documentos e historial

Se importan PDF con texto, Word `.docx` y TXT UTF-8: máximo 2 MiB, 30 páginas
PDF y 24.000 caracteres extraídos. Se rechazan archivos protegidos, ilegibles,
formatos distintos y DOCX con expansión excesiva. Un escaneo necesita
transcripción; no se lanza OCR pesado desde este formulario.

Se guarda solo el texto extraído como pendiente. Los archivos originales y
documentos históricos de contratistas no se modifican. Cada revisión registra
versión, responsable, estado y fecha. El contenido se limita por organización
y canal. Las APIs administrativas exigen rol administrador y protección CSRF.

## Arquitectura y diagnóstico

Antes, el asesor llamaba al modelo incluso para saludos y enviaba hasta 26
guías, aunque no fueran pertinentes. Messenger tenía un prompt largo cuya
cola podía truncarse. `keep_alive: 20s` por petición prevalecía sobre cualquier
ajuste global de Ollama.

Ahora se resuelve así:

1. Reglas para saludos, trámites simples, intención, oficio y datos explícitos.
   Se distingue persona que busca empleo de empresa que ofrece servicios.
2. Búsqueda local de conocimientos aprobados, con índice GIN de PostgreSQL y
   búsqueda compatible con SQLite en pruebas. Se recuperan hasta tres fragmentos.
3. Inferencia local para consultas que necesitan explicación o redacción.
   La consulta actual precede al contexto; las referencias son datos sin
   autoridad para cambiar las instrucciones del asistente.

El asesor interno lee necesidades publicadas no vencidas y, para roles de
gestión autorizados, disponibilidad declarada y estados agregados de
coordinaciones, publicaciones y adjudicaciones. No consulta expedientes,
nóminas ni historiales de Messenger. No ejecuta adjudicaciones o cambios del
negocio. Los anuncios conservan su revisión y publicación actuales; crear una
necesidad no espera al modelo. La ruta local de anuncios mantiene el texto
factual existente y no introduce un proveedor de pago.

Una cerradura transaccional PostgreSQL comparte el límite de una inferencia
entre API y publicador. La saturación retorna una alternativa sin espera
ilimitada. Ollama mantiene su propia cola limitada; el webhook acepta rápido
y deja generación/envío al worker. La cola de generación tiene dos lugares,
reservados sin bloqueo mediante otra cerradura transaccional en PostgreSQL.

Antes de enviar se revalida consentimiento, pausa, apoyo humano, último mensaje
y ventana de 24 horas. Una negativa cancela solicitudes de consentimiento aún
en cola. Un fallo de generación deriva el contacto a revisión. El filtro de
salida rechaza números y URLs no proporcionados y compromisos inseguros;
no equivale a una prueba general de veracidad del lenguaje generado.

## Configuración y mediciones

Se conservaron el modelo principal Qwen3 1.7B, 2048 tokens de contexto,
140 de salida máxima, 3 GiB de límite de memoria, 1,5 CPU y una inferencia.
`think=false` se envía explícitamente. No se precarga al arrancar.

La permanencia predeterminada es ahora **2 minutos**, aplicada de forma
consistente por Compose y por cada solicitud. En la prueba tras 21 s de
inactividad, 20 s ya había descargado el modelo, mientras 2 y 5 minutos lo
conservaban. Se elige el intervalo menor de los dos que conservó carga caliente.
Con poca memoria disponible del host se solicita descarga y se evita generar.
Este control no sustituye el límite duro del contenedor.

Variables: `GALANCITO_KEEP_ALIVE` (`20s`, `2m`, `5m`), `GALANCITO_NUM_PREDICT`
(40–140), `GALANCITO_NUM_CTX` (1024–4096), `GALANCITO_NUM_THREAD` (1–4),
`GALANCITO_TIMEOUT_SECONDS` (1–24) y `GALANCITO_MEMORY_RESERVE_MB`.
Si el VPS ya define permanencia, ese valor sigue prevaleciendo; revisar su
archivo de entorno al activar. No se incrementó la cuota de CPU.

El benchmark compara tres modelos instalados en un Ollama **aislado**, sin
descargas automáticas: Qwen3 1.7B, Qwen3 0.6B y Granite 3.3 2B. Registra
tiempos de carga, lectura del prompt, generación, tokens, motivos de término,
expiraciones, RAM de cgroup y consumo CPU. La matriz incluye 40, 60, 80 y
140 tokens; 1 y 2 hilos; tres consultas simultáneas y permanencia tras 21 s.

El modelo de 0.6B respondió rápido, pero en la muestra repitió una instrucción
y confundió algunas preguntas. Granite truncó respuestas y generó orientación
inadecuada. Se conserva 1.7B. Cuarenta tokens truncaron una respuesta; se
conserva el máximo anterior y se ofrecen parámetros para evaluar en el VPS.

Las mediciones de este entorno no certifican la meta de 35% en producción.
Las muestras con expiración a 24 s son censuradas: no representan respuestas
generadas completas. Los tiempos de cola de Ollama no se infieren como si
fueran independientes; transporte es un residuo con esa limitación documentada.

En **Rendimiento** se muestran hasta 500 consultas de las últimas 24 horas,
promedio, mediana, p95, rutas, errores de generación y etapas disponibles.
No se guardan preguntas o respuestas en la tabla de métricas. CPU real se mide
desde Docker en el benchmark, no se presenta una cuota como consumo medido.

## Reproducción y validación

```bash
PYTHONPATH=apps/backend python -m pytest -q \
  apps/backend/tests/test_galancito_learning.py \
  apps/backend/tests/test_galancito.py \
  apps/backend/tests/test_galancito_local.py \
  apps/backend/tests/test_facebook_crm.py \
  apps/backend/tests/test_facebook_onboarding.py

python scripts/evaluate_galancito.py --output work/galancito-evaluation.json
python scripts/benchmark_galancito.py --url http://galancito-ollama:11434 \
  --container NOMBRE_CONTENEDOR_QA --output work/galancito-benchmark.json --idle
python scripts/benchmark_galancito.py --url http://galancito-ollama:11434 \
  --container NOMBRE_CONTENEDOR_QA --output work/galancito-final.json --compare-only
```

Ejecutar el benchmark en QA con el mismo hardware/límites, sin conversaciones
reales y con los modelos ya instalados. No expone un puerto de producción.
Para PostgreSQL, definir `TEST_DATABASE_URL` contra una base desechable: las
pruebas crean y eliminan únicamente esquemas de ensayo de nombre aleatorio.

Hay **64 casos de comprensión determinista** y pruebas de aprobación,
versiones, edición, desactivación, privacidad, aislamiento, permisos, subida de
documentos, consentimiento, revocación durante inferencia, memoria, concurrencia
y fallos. Esos 64 casos no equivalen a 64 evaluaciones de calidad generativa.
La calidad generativa se inspecciona separadamente en las respuestas del benchmark.

Las capturas y el resultado de navegador acreditan: crear → aprobar → consultar
con referencia → proponer corrección pendiente → ver historial → desactivar →
comprobar exclusión; también rendimiento y móvil sin desbordamiento.

## Activación y reversión del VPS

1. Revisar el PR y el CI del commit exacto. Confirmar espacio, memoria disponible
   y la configuración real. No asumir que el VPS tiene este hardware de QA.
2. Con la autorización operativa y acceso al servidor, usar el actualizador
   existente: `sudo bash scripts/update-preview.sh SHA_COMPLETO`. El script
   exige checkout limpio, hace respaldo, verifica restauración y ejecuta las
   migraciones con SHA256 del respaldo antes de levantar los servicios.
3. Verificar el registro `20.7.5_galancito_learning` y las tablas nuevas
   `galancito_knowledge`, `galancito_knowledge_versions`, `galancito_runs`.
   Son aditivas; no requieren borrar o alterar datos históricos.
4. Confirmar `/api/v1/version` y `/api/v1/health`, versión y commit del servidor,
   consentimiento, permisos de Meta, una consulta rápida y una consulta generada.
   Revisar el comportamiento tras 21 s sin actividad y el uso real de recursos.
5. Si Ollama no estaba instalado, el instalador local existente realiza su
   preflight y prueba con autorización de descarga; esta versión no lo instala
   ni activa por sí sola. Aprobar únicamente conocimientos revisados.
6. Ante fallos, pausar automatización y volver al SHA anterior con el mecanismo
   de actualización existente. Conservar las tablas nuevas: la versión anterior
   puede ignorarlas. No ejecutar un borrado de esquema ni restaurar encima de
   datos recientes sin un procedimiento de recuperación autorizado.

El actualizador conserva su reversión automática ante errores de salud. Esta
sesión no tiene evidencia de respaldo/restauración ni commit del VPS y, por
tanto, **no declara la versión desplegada**.
