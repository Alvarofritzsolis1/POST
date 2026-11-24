# GALANT 20.9.39-rc1 — Conversación natural y coordinación

## Causas y alcance
- Respuestas deterministas de intake y CRM reproducían literalmente frases robóticas.
- Las rutas Messenger y Práctica omitían el modelo aun cuando estaba disponible.
- Contacto voluntario ausente del cierre, evaluación de contacto dependiente de extracción, recuperación de conocimiento limitada.
- Se conserva el consentimiento, privacidad, traspaso humano, límites de cola y prohibición de prometer contratación.

## Implementación
- 20 ejemplos contextualizados disponibles como material de referencia acotado del código, no como respuesta fija ni aprobación de datos por organización.
- 8 familias sintéticas nuevas del laboratorio LoRA (320 variantes nominales), más escenarios de conversación completa en Práctica Bot.
- Modelo configurado con validación semántica de pregunta, fallback local y estado de contacto sin exponer números.
- Backend y frontend versionados; no cambia las tablas ni solicita documentos personales.

## Validación obligatoria
1. CI completa y pruebas anteriores; verificar que las nuevas frases no rompan la interpretación de respuestas cortas.
2. Ejecutar conversación de anuncio de trabajo hasta contacto, rechazo y teléfono/correo existentes, también con caída del modelo y cola ocupada.
3. Revisar integración con MAX POWER 20.9.38-rc2 (PR #184); resolver los tres archivos de versión si esa rama cambia main.
4. Comparar A/B con Qwen 4B real, fuente de respuestas, tasa de fallos, precisión de ficha, p50/p95 y casos reservados.
5. Importar y aprobar referencias administrativas si se desea que aparezcan en el catálogo de conocimiento de cada organización. Las referencias didácticas del release están disponibles sin esa operación.
6. No afirmar que se entrenaron pesos, que mejoró la latencia o que el VPS se actualizó sin ejecución y pruebas verificables.

Estado: candidato de release, no desplegado.
