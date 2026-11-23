# MAX POWER → ChatGPT: archivo de diagnóstico de GALANT

## Propósito

MAX POWER guarda resultados y sesiones en PostgreSQL. El módulo crea un archivo JSON descargable para que su administrador comparta evidencia de mejora con ChatGPT y solicite revisar código de POST.

## Pasos desde GALANT

1. Abrir Inteligencia artificial → MAX POWER.
2. Encender MAX POWER y dejarlo experimentar, con los límites del VPS.
3. Presionar **Descargar informe**. Funciona encendido o después de apagar.
4. Se descarga un archivo galant-max-power-chatgpt-[fecha].json.
5. Adjuntar el archivo en un chat de ChatGPT y solicitar:

> Analiza este informe real de MAX POWER. Identifica falencias, evalúa si las mejoras están verificadas, revisa el código del repositorio POST y crea un parche aislado con pruebas. No inventes aumentos de rendimiento ni declares cambios de pesos si no están medidos.

6. ChatGPT podrá analizar el archivo aportado y, si tiene conectado GitHub con permisos, investigar o modificar POST mediante un PR. Descargar un informe no modifica ni despliega código.

## Contrato de API

GET /api/v1/admin/ai/max-power/export

Requiere autenticación y rol administrador. Filtra toda la información por organización. No cambia el estado del aprendizaje. Entrega JSON como archivo adjunto con cabeceras no-store y nosniff.

## Contenido

- Versión, commit y rutas de código.
- Hora de exportación UTC y fecha del primer encendido.
- Segundos de actividad acumulados y número de experimentos.
- Resultados por competencia cuando la evidencia está disponible.
- Histórico de mediciones numéricas, latencia y regresiones.
- Causas clasificadas de bloqueos o experimentos sin mejora.
- Pruebas de Messenger expresadas solamente en señales objetivas, no conversaciones.
- Integridad SHA-256 de un JSON canónico sin su clave integrity.
- Objetivos sugeridos de análisis, sin autorizar cambios por sí solos.

## Privacidad

Excluye nombres, textos de conversación, correos, teléfonos, RUT, documentos, identificadores de personas, claves API y prompts internos. Solo se exportan claves conocidas y tipos de valores permitidos. Sin envío automático a ChatGPT. Las estadísticas internas de GALANT también son información corporativa: compartir solo con destinatarios autorizados.

## Límites y confiabilidad

El exportador incluye un máximo de 4.000 eventos y 4.000 pruebas de Messenger, y registra el total histórico y si hay elementos omitidos. Los contadores globales de sesiones se mantienen aunque se apague.

Una mejora de laboratorio no acredita por sí sola que Galancito sea más inteligente en producción ni que se hayan entrenado sus pesos. Cuando no hay muestras suficientes, el archivo indica ausencia de nota.

ChatGPT puede analizar el archivo que el usuario adjunte en la conversación actual; el informe no crea una conexión automática o en segundo plano con ChatGPT.

## Fuentes

- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-2.ipd.pdf
- https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/
