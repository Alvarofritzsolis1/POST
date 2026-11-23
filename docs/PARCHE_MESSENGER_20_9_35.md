# GALANT 20.9.35-rc1 — Parche Messenger natural sin colisión

## Historial de versiones y solución del conflicto
- `20.9.33-rc1` ya fue fusionado a `main` mediante PR #164: MAX POWER activo + simulador de Messenger.
- `20.9.34-rc1` está reservado en el PR #166: resumen editorial Facebook.
- Esta corrección corresponde a `20.9.35-rc1` y se reconstruye sobre `main` (PR #164), preservando ambos cambios de Messenger y MAX POWER.

## Fallos demostrados en las pruebas del parche anterior
- Uno de los 40 escenarios rechazaba la frase «Este chat utiliza IA» porque su expectativa solicitaba explícitamente «asistente de IA». Se conserva la descripción transparente sin autopresentarse como Galancito.
- La conversación de seguimiento de una pregunta compleja pierde continuidad si se sustituye el permiso pendiente por una pregunta de ficha. Se preserva el flujo anterior: la consulta compleja sigue pendiente de permiso y los detalles aportados se retienen para la respuesta posterior.
- La rama anterior no podía fusionarse porque #164 había modificado los mismos archivos en `main`.

## Cambios respecto a main
1. El enrutamiento nuevo de aviso/publicación del PR #164 se preserva: comprueba avisos publicados sin inventar obras ni apropiarse del oficio del aviso como dato del postulante.
2. Consultas generales muy breves pueden responderse localmente sin mandar al usuario a autorizaciones innecesarias. Las preguntas sobre información no comprobada siguen con controles de privacidad, consentimiento y derivación.
3. Se elimina la autopresentación «Soy Galancito» de los prompts Messenger y de las salidas generadas. Si preguntan explícitamente quién responde, el servicio explica que utiliza un asistente de IA, sin suplantar a una persona.
4. Las respuestas válidas con dos preguntas o números de opción no pierden su explicación; se simplifican a una pregunta, manteniendo prohibiciones de divulgar datos y prometer contrataciones.
5. Un postulante que solo busca empleo no recibe preguntas de organización de cuadrillas propias de contratistas.
6. La recuperación de Inbox usa el mismo enrutamiento de avisos que el webhook firmado, con respuestas locales si son suficientes.
7. Se simplifican los fallbacks genéricos, sin interferir con los controles de escalamiento.

## Comprobaciones antes de fusionar
- Suite completa y regresión focalizada de Messenger y simulador
- Los 40 casos de conversación, incluido `38-identidad_ia`
- Mensajes encadenados: pregunta compleja, dato adicional, consentimiento, respuesta con historial
- Inicio de conversación: «Vi una postulación de trabajo»
- No pérdida de respuestas por filtros de opciones y preguntas
- Compatibilidad con consentimientos enviados antes del cambio
- Diferencias y versión exacta de frontend, lockfile, backend
- Prueba con Meta real únicamente después de fusionar y verificar el VPS

## Alcance / riesgo
El parche no cambia la configuración LoRA ni los pesos Qwen, el simulador de Messenger, el panel MAX POWER, la base documental ni los permisos de administración. Los consentimientos y solicitudes de revisión humana siguen vigentes. La suite automática no prueba por sí sola respuestas desde el Messenger público.

No activar el despliegue automático hasta revisar que el PR #166 se haya fusionado o que `20.9.35-rc1` continúe siendo el siguiente número de publicación apropiado.
