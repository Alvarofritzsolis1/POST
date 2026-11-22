# GALANT 20.9.15 — Auditoría de rutas antiguas y rendimiento de Qwen3.5 4B

## Hallazgos confirmados en el código

| Área | Hallazgo | Acción en esta rama |
| --- | --- | --- |
| Galancito General | Preguntas explicativas acababan entrando a consultas de obras, aunque no pedían datos | Se clasifican las consultas de orientación para que utilicen directamente Ollama 4B |
| Indicadores internos | Una consulta de publicaciones/seguimiento ejecutaba cinco consultas SQL agregadas, aunque solo necesitaba una | `_counts(..., include={...})` consulta solo el indicador solicitado; los panoramas completos mantienen todos los indicadores |
| Chat antiguo de Red de Obras | Algunas preguntas deterministas invocaban sincronización de proveedores y leían indicadores antes de responder | Salida temprana para saludos, orientación fija y casos restringidos, con registro de auditoría |
| Chat frontend | La decisión de API dependía de que la petición de estado hubiera terminado y de un control manual | El servidor decide automáticamente con política de organización, complejidad y privacidad |
| Red de Obras antiguo | La ruta heredada podía generar un prompt con indicadores internos antes de llamar a API | Los proveedores externos reciben solo preguntas públicas complejas, sin métricas, fichas ni títulos internos |
| Interfaz anterior | Quedaban estilos para pestañas de dos chats, y estados de un formulario de corrección no mostrado | Se eliminaron clases sin uso en el componente actual y estados inactivos |
| Inferencia Ollama | La actualización conservaba el modelo caliente solo dos minutos | La activación segura de 4B configura cinco minutos; el control de RAM sigue vigente |
| Observabilidad | El chat general no guardaba el desglose de tiempos de Ollama | Se guardan métricas técnicas de duración/tokens sin almacenar el texto de la pregunta |

## Arquitectura de respuesta

1. Saludo, seguridad o caso determinista: respuesta local inmediata.
2. Estado, obras, documentos, versión y publicaciones: herramientas verificadas con permisos por organización y obra; no se mandan registros a API.
3. Orientación habitual: Qwen3.5 4B local, sin cambiar silenciosamente al modelo 1.7B.
4. Análisis público de varios factores: API de organización previamente autorizada, con cuota y privacidad; si no está disponible, intenta 4B.
5. Casos sintéticos de Práctica Bot: evaluación controlada sin reentrenamiento de pesos y sin autorizar consultas a producción.

## Código que NO se debe borrar por parecer antiguo

- Migraciones históricas de bases de datos: necesarias para actualización/recuperación.
- Canal y lógica de Messenger: independiente del chat interno; evita mezclar conversaciones privadas.
- `area=red_obras` y `area=interno` de la API: contratos heredados; removerlos exige verificar primero todos los clientes.
- Modelo 1.7B y datasets históricos: necesarios para prácticas antiguas reproducibles, aunque el chat general nuevo exija 4B.
- Tests, fixtures, versiones previas y scripts de respaldo: no influyen en la latencia de las peticiones normales, y eliminarlos reduce trazabilidad.

## Calidad pendiente de verificar antes de fusionar

- CI completa (backend y frontend) y regresiones de rol, privacidad, métricas y modelos.
- Pruebas autenticadas en VPS de latencia caliente/fría, RAM, CPU, varias conversaciones y entrenamiento simultáneo.
- Instalación y prueba real de Qwen3.5 4B; editar GitHub no activa el modelo ni cambia el VPS.
- Comparación de p50/p95 de latencia, `load_ms`, `prompt_ms`, `generation_ms`, `db_ms`, RAM libre y tasa de respuesta correcta.
- Perfilado del hardware para establecer si `5m`, el límite de CPU y los hilos ofrecen mejor desempeño sin presionar otros servicios.

No es correcto afirmar mejora porcentual o «100 %» sin el ensayo del VPS. Las optimizaciones anteriores eliminan trabajo innecesario en rutas concretas y añaden pruebas específicas; las ganancias exactas de tiempo dependerán de la carga real.
