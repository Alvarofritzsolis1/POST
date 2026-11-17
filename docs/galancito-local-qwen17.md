# GALANT 20.7.3 — Galancito local, sin cobros por mensajes

**Alcance obligatorio:** el modelo Qwen3 1.7B solo:
1. Responde mensajes nuevos de Facebook Messenger, **después del consentimiento SÍ del interesado**.
2. Actúa como **asesor de Red de Obras**, con acceso de lectura a títulos publicados de la organización y guías de oficios aprobadas.

**Fuera de alcance:** generar o publicar anuncios por IA, editar contratistas, evaluar documentación,
JAVIERA, asistencia, INE, pagos, autorizaciones, adjudicaciones y cualquier otro módulo de GALANT.
El modelo no posee herramientas ni funciones para modificar registros.

## Protección del VPS de 11 GiB de RAM y 6 CPU

| Parámetro | Configuración |
| --- | --- |
| Modelo | `qwen3:1.7b` (Ollama, descarga aprox. 1,4 GB) |
| Docker | Perfil opcional `local-ai` (apagado por defecto) |
| Memoria máxima | 3 GiB (límite estricto del contenedor) |
| CPU máxima | 1,5 núcleos (cuota) |
| Concurrencia de generación | 1 |
| Cola de espera | 2 solicitudes |
| Descarga de RAM por inactividad | 20 segundos |
| Ventana de contexto | 2048 tokens por solicitud |
| Respuesta por solicitud | Máximo 140 tokens |
| Tiempo máximo de generación | 24 segundos |
| Exposición de Ollama | Sin puerto público; solo redes privadas Docker |

**Nota:** que el contenedor tenga un límite de 3 GiB no garantiza que jamás ralentice el
VPS: puede agotar su cuota y reiniciarse, y dos procesos podrían competir por CPU.
Por eso el modelo permanece opcional y GALANT no depende de su disponibilidad.
Si falla, Messenger usa una respuesta simple de respaldo y Red de Obras usa ayuda
básica sin IA. La lentitud del modelo debe medirse con una prueba operativa real.

Referencia: https://ollama.com/library/qwen3:1.7b
y configuración oficial: https://github.com/ollama/ollama/blob/main/docs/faq.mdx

## Instalación y activación segura, solo después del despliegue de código

**NO se inicia Ollama ni se descarga el modelo al fusionar en GitHub.** Cuando
`/opt/galant-post` ya tenga el código actualizado, ejecutar manualmente:

```bash
cd /opt/galant-post
sudo python3 scripts/setup-galancito-local.py
```

El asistente:
1. Comprueba RAM disponible (mínimo 6 GiB), CPU (mínimo 4) y espacio libre (mínimo 6 GB).
2. Solicita confirmación para descargar el servicio.
3. Descarga la imagen Ollama y el modelo Qwen3 1.7B a un volumen Docker.
4. Comprueba una respuesta **desde el API interno de GALANT**, no desde Internet.
5. Guarda un respaldo privado de `.env.preview`.
6. Habilita Galancito para **Red de Obras**.
7. Pregunta por separado si habilitar también respuestas IA de Messenger.
8. Reinicia únicamente los contenedores `api` y `facebook-publisher`.

Las credenciales de Facebook existentes se conservan. **No es necesaria una
clave de OpenAI.** No activar `FACEBOOK_AI_AD_ENABLED`: Qwen3 solo conversa.

Si la instalación falla, las variables de IA no se habilitan. Si la activación
de Docker falla, el instalador intenta dejar las opciones de IA apagadas.

## Consultar recursos durante una prueba

```bash
cd /opt/galant-post
docker compose --profile local-ai --env-file .env.preview -f docker-compose.preview.yml stats --no-stream galancito-ollama
free -h
```

Para **detener Ollama sin detener GALANT**:

```bash
docker compose --profile local-ai --env-file .env.preview -f docker-compose.preview.yml stop galancito-ollama
```

Aunque se detenga Ollama, GALANT permanece disponible. Para desactivar también
la generación de respuestas automáticas en Messenger, cambiar
`FACEBOOK_AI_AUTO_REPLY_ENABLED=false` en el archivo privado de configuración
y recrear el contenedor `api` (solo con el procedimiento habitual de despliegue).

## Consentimiento y atención humana

En Messenger Galancito informa: «IA local, procesada en nuestro servidor,
sin OpenAI», solicita SÍ/NO, y solo genera si la persona responde SÍ.
Si necesita ayuda con trámites, envía un aviso a un administrador y no
pide seis documentos de golpe. Si la persona revoca el permiso, el modelo deja
de responder a ese contacto. Si un administrador contesta manualmente,
Galancito se pausa.

Las notas de voz recibidas requieren revisión humana en Meta Business Suite:
el modelo textual Qwen3 1.7B **no transcribe audio**.

## Requisitos externos pendientes

Meta debe conceder la posibilidad de usar `pages_messaging`, la suscripción
a `messages` y, según el caso, permisos adicionales y App Review para
que contacten personas fuera de los roles de prueba. Que el webhook esté
verificado no implica acceso público ya aprobado.

Las respuestas se prueban con cuentas autorizadas antes de difundir el sistema.
