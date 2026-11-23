# GALANT 20.9.21-rc1 · Aprendizaje guiado por errores reales (candidato, sin desplegar)

**Estado:** Pull request en borrador. No se afirma que Qwen haya cambiado sus
pesos, mejorado globalmente ni que el VPS haya superado pruebas reales.
No fusionar ni desplegar sin CI completo, QA de Ollama local y rollback preparado.

## Qué funciona en código

1. **Diagnóstico**: auditoría humana de conversaciones auténticas accesibles y
   resultados por criterio, canal, tamaño de muestra y prioridad. Las fallas de
   reglas, recuperación y modelo se diferencian como hipótesis, no causa probada.
   Se registran contadores de contexto y truncamiento sin almacenar texto de chat.
2. **Práctica focalizada**: el motor selecciona, sin azar, el siguiente error
   humano elegible (`/next`) o permite elegir uno (`/cases`). Rechaza datos
   sensibles detectados, requiere Qwen 3.5 4B local y un modelo de origen
   verificado para habilitar futuras propuestas. No hace inferencia externa.
3. **Comparación pareada**: para una conversación auditada se ejecutan dos
   inferencias locales bajo el mismo contexto, modelo, semilla y parámetros:
   Qwen base y Qwen con una instrucción candidata de lista permitida.
   Se muestra además la respuesta de producción como referencia separada.
   Si ambas salidas coinciden o un filtro de seguridad rechaza alguna, no
   se contabiliza éxito. El tiempo incluye ambas inferencias.
4. **Dos estrategias distintas por criterio**, sin producción de ejemplos
   ficticios. No se prueban variantes con regresiones ya observadas; el
   sistema no prueba ilimitadamente el mismo caso.
5. **Revisión humana estricta**: para contar «mejor», la persona debe afirmar
   expresamente que el defecto auditado quedó resuelto y que la seguridad
   sigue intacta. Una nota mejor pero todavía incorrecta no cuenta.
6. **Ensayos recuperables**: solo se guarda estado, variante, procedencia,
   duración, comprobante efímero y veredicto. Si se pierde la pestaña, se
   puede cancelar el ensayo no evaluado y repetir; no se puede calificar
   una candidata cuyo texto ya no está a la vista.
7. **Separación práctica/reserva**: una variante necesita dos casos
   de práctica favorables y cuatro casos distintos de evaluación reservada
   favorables, sin regresiones observadas y con procedencia de Qwen verificable,
   para proponer una guía genérica **pendiente**. No se mezcla una misma
   conversación entre práctica y reserva.
8. **Transferencia controlada**: solo una guía aprobada por administración,
   con contenido en lista permitida y un evento auditado de propuesta,
   puede integrarse a las instrucciones del canal pertinente.
9. **UX**: vista por competencia, casos previos auditados, práctica focalizada
   automática, dos estrategias, comparación triple y estado de aprobación.
   La biblioteca de guías temáticas no se denomina «entrenamiento de pesos».

## Límites explícitos

- La reproducción utiliza historial accesible y puede no incluir todas las
  condiciones exactas de la ejecución original: permisos, ficha, herramientas,
  estado temporal o sistema de reglas. La telemetría revela parte de la ruta,
  pero **no identifica causalidad automáticamente**.
- Las cuatro evaluaciones reservadas son casos distintos, pero no constituyen
  por sí mismas un ensayo aleatorizado, cegado o una muestra representativa.
  Requieren nueva validación posterior al despliegue.
- Son revisiones humanas supervisadas, no aprendizaje por gradientes, DPO,
  fine-tuning ni una implementación completa de DSPy/GEPA.
- El filtro de privacidad por expresiones regulares no garantiza detección
  universal de datos personales. El acceso a reproducción debe mantenerse
  limitado a administradores y al entorno local privado.
- Las prácticas comparten la capacidad limitada de inferencia con producción;
  cada ensayo usa dos generaciones y se aborta si el motor está ocupado.
- Sin conversaciones auditadas suficientes, la pantalla debe informar
  «sin evidencia», nunca fabricar porcentajes o declarar «100%».

## Puertas de validación obligatorias

1. CI del último commit del PR: Python y migraciones, frontend, Messenger,
   protección multiempresa, respaldos y regresiones.
2. Evaluación manual real de Qwen en un VPS o QA aislada con recursos y
   privacidad adecuados; confirmar respuesta del modelo vía telemetría.
3. Pruebas con carga concurrente y confirmación de que Messenger mantiene
   prioridad y sus límites de latencia y memoria.
4. Verificar que la reproducción de errores reales relacionados con reglas
   se derive a diagnóstico de código y no declare corregido el modelo.
5. Comprobar que no se guardan textos privados en la tabla de prácticas, que
   la aprobación deja traza y que se puede cancelar/repetir ensayos perdidos.
6. Aprobación administrativa con despliegue gradual, observación en nuevas
   conversaciones reales y reversión si aparece degradación.

Fuentes:
- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://www.anthropic.com/research/demystifying-evals-for-ai-agents
- https://dspy.ai/current/tutorials/gepa_ai_program/
