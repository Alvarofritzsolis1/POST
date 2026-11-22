# PROMPT MAESTRO — GALANT POST · Centro de IA y aprendizaje verificable

Versión objetivo: **20.9.19-rc1**. Repositorio: `Alvarofritzsolis1/POST`.

## Rol y objetivo

Actúa como ingeniero principal full-stack, especialista en UX SaaS, evaluación de IA y observabilidad. Mejora el módulo `/admin/ia` de POST sin cambiar permisos, datos, mensajes enviados, credenciales, políticas de privacidad ni lógica productiva de Galancito. Mantén Ollama Qwen3.5 4B como motor local compartido; usa proveedores externos únicamente conforme a la política existente. NO inventes calificaciones ni atribuyas capacidad de aprendizaje a pruebas sintéticas.

El usuario administrador necesita responder a cinco preguntas con una sola pantalla: ¿está disponible el motor?, ¿qué sucede con Messenger?, ¿qué sucede con Galancito General?, ¿qué problemas han sido observados realmente?, ¿qué mejoras están verificadas?

## Jerarquía de interfaz

1. **Resumen**: estado del motor local, número de conexiones verificadas, dos paneles diferenciados «Responder mensajes» y «Galancito General», latencia p50/p95 de solicitudes registradas, volumen, errores y hallazgos. La nota de exactitud es `null` («Sin evidencia suficiente») hasta existir una auditoría de respuestas reales.
2. **Conexiones**: conservar alta/cifrado/prueba de API, rutas, política y consumo, pero sin banners extensos, botón gigante para probar Ollama ni textos duplicados. Opciones avanzadas en desplegables.
3. **Práctica Bot**: canal, suite, categoría enfocada cuando es compatible, cantidad de casos, progreso, duración activa real, tiempo total transcurrido, respuestas correctas/incorrectas, alertas críticas. Historial y detalles en segundo plano.
4. **Aprendizaje**: al final de la configuración, diagnóstico → propuesta de corrección → evaluación A/B en casos reservados → verificación de regresiones → aprobación humana → observación en producción. No publicar correcciones de manera automática.

## Contrato de evaluación y calificaciones

- **Telemetría real**: solo registros persistidos de solicitudes, envíos, errores y tiempos. No mide exactitud factual.
- **Opinión humana**: almacenar correctamente el número de valoraciones útiles/incorrectas como indicador de feedback, nunca como precisión factual.
- **Prueba sintética**: sus notas permanecen etiquetadas como laboratorio. Jamás se incorporan a la calificación de producción.
- **Prueba con agregados reales**: respuestas sobre contadores SQL congelados de GALANT; medir fórmula y corrección, pero etiquetar «agregados operativos / laboratorio», no «conversaciones de usuarios».
- **Calificación real de calidad**: desarrollar auditoría humana trazable de una muestra representativa de conversaciones reales por canal. Requiere una referencia real, revisor, criterio, resultado, fecha, versión del modelo/prompt, recuento, límites del muestreo y permiso de acceso. Sin suficientes casos, presentar `—`; si existe evidencia, mostrar denominador y método, con intervalo de incertidumbre. Nunca mostrar 100/100 por cuatro respuestas buenas.
- **Mejoras**: solo se confirman si una prueba reservada comparable mejora y no se introducen regresiones; posteriormente comprobar comportamiento de producción. Un entrenamiento de instrucciones no equivale a fine-tuning de pesos.
- No se debe usar un LLM evaluador sin contraste/calibración con evaluaciones humanas; no mostrar niveles de confianza arbitrarios.

## Infraestructura y seguridad

- Administrador exclusivo para configuración, prácticas y resúmenes; consultas filtradas por `org_id`.
- No devolver claves, texto privado ni datos personales en indicadores agregados; no transmitir datos privados a terceros.
- El entrenamiento jamás monopoliza Ollama: mantener prioridad de Messenger, límites CPU/RAM y estado recuperable de las rondas.
- Preservar las interfaces de datos vigentes y migraciones de forma aditiva. Prohibido hacer `DROP TABLE`, introducir cambios masivos no versionados o reemplazar endpoints activos.
- Si hay cambios de metodología, registrar versión y no comparar muestras incompatibles.
- La pantalla muestra estados de carga, error, falta de datos y conectividad, además de accesibilidad por teclado y `prefers-reduced-motion`.

## Entrega y aceptación

1. Revisar `AIAdminPanel.tsx`, `AIConfiguration.tsx`, `GalancitoTraining.tsx`, APIs de configuración/entrenamiento, `AssistantRun`, worker Messenger, pruebas y permisos.
2. Implementar la interfaz de cuatro pestañas y telemetría por canal. Reducir texto sin suprimir funciones.
3. Implementar pruebas enfocadas; si una categoría aún no tiene generador verificable, bloquearla en vez de simular que funciona.
4. Validar tiempos medidos usando reloj monotónico del worker, p50/p95 por datos reales, sin incluir pruebas sintéticas como tiempo de producción.
5. Verificar permisos (admin vs residente), aislamiento de organización, errores de proveedor, datos vacíos, estados de envío y ejecución de tests.
6. Exigir `npm run build`, `pytest`, revisión de diff, checks CI, prueba de Qwen real y smoke test en VPS antes de considerar producción terminada.
7. Registrar SHA, número de versión, qué es comprobable y qué queda pendiente; no informar «100 %» sin evidencia.

**Alcance implementado:** la auditoría humana independiente ya puede revisar respuestas reales guardadas en Messenger, incluidas las anteriores al parche, y conversaciones internas guardadas voluntariamente por el propio administrador. Cada evaluación conserva criterio, versión, identificador de evidencia y revisor, sin copiar el texto de los mensajes a la tabla de notas. La calificación global permanece vacía hasta que se revisen al menos 30 casos, y después representa **únicamente esa muestra revisada**, nunca la totalidad de producción. Los errores revisados habilitan prácticas Messenger por criterio con ciclos y A/B sintéticos; cualquier mejora de laboratorio necesita confirmación posterior en nuevos chats reales.

## Investigación de referencia

- Nielsen Norman Group: divulgación progresiva — https://www.nngroup.com/articles/progressive-disclosure/
- Google SRE: latencia, tráfico, errores y saturación — https://sre.google/sre-book/monitoring-distributed-systems/
- LangSmith: evaluación online/offline — https://docs.langchain.com/langsmith/evaluation-types
- MLflow: monitoreo y feedback humano — https://www.mlflow.org/docs/latest/genai/tracing/prod-tracing/
- NIST AI RMF: evaluación representativa y métodos trazables — https://airc.nist.gov/airmf-resources/playbook/measure/
