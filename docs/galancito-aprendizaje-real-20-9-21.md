# GALANT · 20.9.21-rc1 · Aprendizaje dirigido por fallas reales

Este parche no entrena pesos de Qwen y no declara que una mejora haya sido
demostrada en producción. Resuelve una brecha previa: feedback real del chat
se registraba, pero no existía un circuito verificable hacia una corrección
que pudiera utilizarse posteriormente en la respuesta.

## Qué implementa

1. **Diagnóstico humano trazable:** \`/admin/ai/real-learning/plan\` separa por
   canal, criterio y ventana temporal. Indica tamaño de muestra, errores, prioridad
   y estado de evidencia. Sin revisiones reales: sin nota y sin mejora inventada.
2. **Práctica de Qwen sobre una conversación real:** el administrador audita
   la respuesta entregada, marca una dimensión fallida y solicita una prueba
   local con Qwen3.5 4B. El modelo recibe el historial disponible y una corrección
   general delimitada. No se envía ninguna respuesta a Meta y no se llama a
   proveedores externos. Se compara con la respuesta original de producción.
3. **Evaluación humana vinculada:** el administrador indica «mejoró», «igual»
   o «empeoró». Se guardan únicamente identificadores, criterio, modelo,
   duración y veredicto: nunca texto de mensajes ni respuesta candidata.
4. **Propuesta de guía:** exige dos fallas humanas de ese criterio y dos
   pruebas de conversaciones distintas evaluadas como mejores, sin regresiones
   en el período. Aún así crea una propuesta **pendiente** que el administrador
   debe aprobar en Conocimientos. El texto permitido es una regla genérica
   y fija: no incluye conversaciones, nombres ni propuestas libres del modelo.
5. **Uso controlado:** una guía aprobada coincidente con la lista de políticas
   entra al prompt del canal correspondiente. Ediciones desactivan su aprobación;
   nada se aplica si el criterio no ha sido validado por el sistema de guías.
6. **UX:** los criterios están etiquetados con las claves correctas del backend,
   se ven cifras de la muestra aunque todavía no haya 30 auditorías, la interfaz
   describe la causa y permite lanzar una reproducción real desde la auditoría.

## Interpretación rigurosa

- Una reproducción real no es una comparación A/B aleatorizada y cegada;
  el veredicto humano puede tener sesgo. Las dos comparaciones exigidas solo
  habilitan una **propuesta supervisada**, no acreditan mejora general.
- Los 20 aprendizajes predeterminados son guías, no épocas ni fine-tuning.
- Los ensayos sintéticos existentes sirven para regresión complementaria,
  nunca para aumentar una nota de producción.
- Solo una nueva evaluación posterior al despliegue, idealmente con casos
  reservados y métricas por versión, puede acreditar mejora real generalizada.
- Las prácticas sobre chats con datos privados son rechazadas.
- Un VPS sin Qwen3.5 4B activo devuelve 409; no se simula inferencia.
- No se toca el módulo documental ni el envío de Meta fuera de añadir
  instrucciones preaprobadas en el momento de generación.

## Validar antes de desplegar

Ejecutar pruebas de backend, el build del frontend y pruebas de regresión de
Messenger. Verificar permisos por organización, protección CSRF, migración
aditiva \`20.9.21_real_defect_learning\`, casos que no tengan contexto accesible
y ausencia de texto de chats en registros de práctica. Después del despliegue,
hacer pruebas de Qwen real sobre conversaciones auditadas y comparar nuevas
respuestas de producción; no anunciar «100 %» sin esa verificación.

Fuentes de metodología:
- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://www.anthropic.com/research/demystifying-evals-for-ai-agents
- https://dspy.ai/current/tutorials/gepa_ai_program/
