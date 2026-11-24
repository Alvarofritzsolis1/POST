## Qwen3.5 2B en Galancito y MAX POWER

- Galancito, Messenger, Red de Obras y MAX POWER usan un solo modelo local Qwen3.5 2B. Las evaluaciones de respuestas conservan el modelo que las generó.
- MAX POWER ajusta adaptadores LoRA del mismo modelo con base NF4 y dos CPU. La validación reservada, los checkpoints y la prioridad de Messenger forman parte del mismo flujo.

## 20.9.30-rc1 — MAX POWER de un solo botón: evaluaciones + pesos LoRA reales

- El mismo interruptor MAX POWER coordina el motor existente de pruebas Qwen3.5 4B y el entrenador neuronal Qwen3.5 0.8B. El supervisor CPU consulta el estado ON/OFF, la generación de sesión y las prioridades de Messenger mediante una API interna firmada HMAC; no accede a la base de datos, al socket Docker ni a documentos laborales.
- Nuevo servicio permanente cpu-lora-manager aislado, 1,5 CPU y 5 GiB RAM, con comprobación de salud real, respaldo/reversión en el despliegue. En reposo no descarga ni entrena modelos.
- Si hay datos reales autorizados y firmados con Ed25519, capacidad suficiente y ninguna práctica prioritaria, inicia automáticamente cuatro pasos de gradiente, checkpoints cada dos pasos y telemetría firmada al panel. Si falta algo, publica el bloqueo específico sin inventar resultados.
- OFF, cambio de sesión, presión RAM y actividad de Messenger detienen nuevos pasos con checkpoint, recuperación de rondas incompletas y salvaguarda de finalización si una llamada no cede. No se repite el mismo dataset sin nueva evidencia.
- El panel presenta por separado el estado del controlador neuronal, evaluaciones y gráficos de pesos reales. Ningún adaptador 0.8B se transfiere al 4B ni se aplica a producción automáticamente.
- Pruebas de HMAC, sesión, privacidad, autorización de dataset, estado OFF, aislamiento y límites Docker. Los tests de CI no sustituyen un piloto de gradientes en el VPS ni validan calidad general.

## 20.9.27-rc1 — MAX POWER: integridad de entrenamiento CPU y configuración automática

- Corrige el aprendizaje aparente al reanudar checkpoints: el digest de pesos LoRA se captura después de restaurar el estado del entrenador y se exigen pasos NUEVOS y cambios de tensores antes de marcar pesos entrenados.
- El evento final de entrenamiento CPU ahora aporta los SHA-256 inicial/final del adaptador y los pasos nuevos de optimización. La API rechaza afirmaciones de entrenamiento sin esa evidencia. No se confunde checkpoint cargado con gradiente calculado.
- Rechaza respuestas autorizadas truncadas y checkpoints parciales sin estado de optimizador/planificador; corrige la protección de enlaces simbólicos del directorio de salida privado.
- Preflight CPU firmado: registra RAM host, límite del contenedor, espacio libre y resultado real en MAX POWER por organización. Se presenta separado de las rondas de gradientes; no genera progreso falso.
- El despliegue seguro aprovisiona una vez en el VPS el secreto de telemetría, sin revelarlo ni reemplazar claves configuradas. La interfaz permite copiar el comando de comprobación del VPS.
- Qwen3.5 4B de Messenger no cambia, LoRA CPU 0.8B sigue apagado por defecto. No se entrenan pesos sin dataset privado real autorizado y sin capacidad comprobada; no hay promoción automática.
- Pruebas de reanudación, consistencia de gradientes, seguridad del entorno, preflight numérico y aislamiento entre organizaciones.

## 20.9.26-rc1 — MAX POWER: LoRA real con CPU del VPS actual

- Agrega ejecutor de entrenamiento neuronal por CPU para Qwen3.5-0.8B, usando únicamente el decodificador de texto oficial, con PyTorch y PEFT y actualizaciones verdaderas de parámetros LoRA. **NO** entrena ni altera el Qwen3.5-4B de producción.
- Perfil Docker opcional cpu-lora: arranque únicamente por orden explícita, 1,5 vCPU, 5 GiB RAM, sin swap, sin puerto abierto y sin acceso a DB, documentos ni Docker.sock. El despliegue normal **no lo inicia**.
- Antes de cargar pesos requiere RAM real disponible (host/cgroup), disco, dataset privado de ejemplos reales autorizado y manifest Ed25519 firmado específicamente para el 0.8B.
- Monitor de RAM durante la optimización, pausa bajo presión, checkpoints recuperables, historial JSONL seguro y comprobación de huella real de tensores LoRA modificados.
- Actualiza la telemetría por organización para distinguir CPU LoRA de GPU QLoRA, registrar RAM de proceso y mostrar gráficos interactivos medidos. No inventa puntos, cifras ni mejoras de razonamiento; un adaptador entrenado requiere evaluación independiente.
- Pruebas unitarias de preflight, límites, privacidad, recuperación, API de métricas CPU y carga de clase de texto oficial. Sin dataset firmado ni hardware comprobado la CI no puede probar gradientes en el VPS y el panel permanecerá sin mediciones.

## 20.9.25-rc1 — MAX POWER: QLoRA real con telemetría de GPU

- Integra el ejecutor de ajuste fino **real** Qwen3.5-4B en una máquina CUDA aislada. La GPU actual del VPS no está confirmada: encender MAX POWER local sigue ejecutando evaluaciones, no gradientes.
- Corrige la carga de la arquitectura oficial Qwen3.5-4B (ConditionalGeneration) y limita LoRA a capas lineales del decodificador; la torre visual queda congelada.
- Mejora checkpoints recurrentes y permite reanudar solo con dataset, aprobación y parámetros idénticos. Registra cada paso, loss, eval_loss, grad_norm, épocas y VRAM mediante callbacks reales de TRL, sin gráficos ficticios.
- Telemetría HTTPS firmada HMAC por organización, token exclusivo del administrador, API solo numérica y eventos idempotentes con almacenamiento local JSONL duradero; sin mensajes de Messenger, credenciales ni datos de trabajadores.
- Panel MAX POWER con gráficos SVG interactivos, series seleccionables y actualizaciones cada 5 s; señal estancada se muestra como desconectada. El historial general se mantiene separado de miles de pasos neuronales.
- El informe ChatGPT incorpora medidas neuronales agregadas y resultados de test reservado. Entrenamiento de pesos, ganancia de razonamiento y promoción a producción permanecen estados distintos.
- Entrenamiento neuronal no se inicia sin GPU CUDA externa, dataset privado real consentido y manifest Ed25519 válido. Los adaptadores jamás se publican automáticamente.
- Pruebas nuevas de autenticación, aislamiento entre organizaciones, idempotencia, progreso verificable, privacidad y recuperación. La CI valida el código, NO demuestra fine-tuning ejecutado en GPU.

## 20.9.24-rc1 — MAX POWER: recuperación, CPU y pruebas reales (parche aislado)

- Corrige el cuello de botella de un hilo: el controlador MAX POWER tiene solo 0,35 CPU, pero el Ollama aislado ahora recibe una cuota configurable inicial de 2 CPU y dos hilos. No altera las cuotas ni el timeout de Messenger.
- Solicitudes de laboratorio con timeout acotado según tokens previstos (máximo 360 s); se preservan los motivos sanitizados de errores HTTP y tiempos de espera, sin registros de mensajes privados.
- Evidencia real de hasta 12 obras distribuida entre obras y categorías de razonamiento, en vez de truncar a las primeras tres obras. La versión de dataset sube a 4; las comparaciones A/B siguen separadas y requieren evidencia independiente.
- La planificación inicial deja de suponer 30 segundos de p95: inicia con ocho pares y presupuesto de ronda prudente, sin limitar el tiempo total durante el que MAX POWER puede permanecer encendido.
- Una ronda interrumpida no queda bloqueada para siempre por la huella de evidencia: hasta dos nuevos intentos de ronda con espera progresiva; tras tres rondas fallidas, detiene reintentos repetitivos hasta que cambien los datos.
- Ningún cambio de pesos, promoción a producción ni mejora demostrada de razonamiento: se exigirán pruebas de laboratorio, evaluación estadística, CI y medición real en VPS antes de declarar el parche operativo.
- Pruebas de regresión nuevas: aislamiento, timeout, recuperación tras fallo, selección de obras y verificación de que Messenger no cambió.

## 20.9.22-rc1 — Histórico verificable y preparación LoRA de Qwen (parche aislado)

- Inventario histórico completo **de los registros conservados**: metadatos de ejecuciones, mensajes IA entregados, feedback, revisiones humanas y ensayos, separados por período y competencia. No lee ni almacena el texto privado de conversaciones.
- Vista de Aprendizaje con cobertura por competencia y meses, sin extrapolar una calidad que no se evaluó; aislamiento multiempresa y límite de 30 días para auditar el contenido original intactos.
- Herramienta opcional de entrenamiento LoRA real para Qwen3.5-4B, **solo en GPU aislada**, con dataset revisado y autorización explícita, filtro de datos sensibles, separación de grupos, pruebas reservadas, rechazo de regresiones y sin despliegue automático.
- Este parche NO ejecuta todavía el entrenamiento neuronal ni demuestra una ganancia de razonamiento: exige datos consentidos y una GPU externa compatible antes de entrenar.
- Pruebas de rutas administrativas, aislamiento histórico, privacidad y preparación de dataset. La PR debe pasar CI antes de cualquier fusión y requiere aprobación humana para uso de datos.

## 20.9.21-rc1 — Aprendizaje por deficiencias reales (candidato aislado)

- Diagnóstico por criterio sobre auditorías humanas reales, separando muestra y calificación global. Corrección de etiquetas de rúbricas.
- Prueba local real de Qwen3.5 4B sobre conversaciones auditadas accesibles, sin envíos a Meta, sin modelos externos y sin persistir texto del chat en la tabla de ensayos.
- Comparación humana del candidato, registro de mejoras/regresiones y propuestas pendientes solo tras dos casos reales distintos evaluados positivamente, sin regresiones observadas.
- Las guías aprobadas y exactamente coincidentes con políticas revisadas pueden alimentar el canal correspondiente; no se modifican pesos, ni se declara una mejora global automática.
- Migración aditiva, tests de trazabilidad y permisos. Requiere CI, prueba Qwen en VPS y validación posterior de respuestas de producción antes de desplegar.

## 20.9.19-rc1 — Centro de IA: datos verificables y laboratorio compacto

- Nuevo **Resumen** de IA con canales separados «Responder mensajes» y «Galancito General»: recuentos de interacciones reales, mediana, latencia p95, señales de error y feedback realmente registrado. Se informa explícitamente el límite de 2.000 registros por canal y período.
- La nota de exactitud /100 se mantiene **sin calcular** mientras no exista una auditoría representativa y trazable de respuestas reales. Un comentario útil no equivale a precisión; las pruebas sintéticas y las pruebas con agregados de la base de datos se presentan por separado.
- Navegación independiente y compacta: Resumen, Conexiones, Práctica Bot y Aprendizaje. Las opciones técnicas de proveedores y límites se conservan sin ocupar la portada.
- Práctica Bot con tiempo activo acumulado, tiempo transcurrido y selección por categoría para escenarios **sintéticos** de Galancito General. La suite sobre agregados operativos permanece sin categoría enfocada por ser una metodología distinta.
- La exportación del laboratorio diferencia datos operativos de simulaciones. Se amplían pruebas de permisos, procedencia de puntuaciones y aislamiento de categoría.
- Auditoría de Messenger con **mensajes reales entregados**, incluidos registros anteriores al parche: muestra contexto reciente, revisión humana con seis criterios y almacenamiento sin transcribir el chat. El sistema no atribuye duraciones ficticias a interacciones históricas. El chat interno solo se audita cuando el propio administrador tiene historial privado guardado y autorizado.
- Calificación verificable por muestra auditada: 30 conversaciones revisadas como umbral mínimo, recuento y criterios individuales, con advertencia de sesgo de selección y sin extrapolar a toda producción. Los hallazgos reales activan prácticas Messenger focalizadas.
- **Épocas especializadas Messenger:** escenarios ficticios variables separados de conversaciones privadas, propuestas fijas de mejora de instrucciones tras errores, y ensayo A/B con los mismos casos reservados y semillas comparables. Muestra ganancias y regresiones únicamente como prueba sintética; no entrena pesos ni aprueba automáticamente nuevas instrucciones en producción.
- **Pendiente de validación:** CI, prueba contra Ollama real y smoke test en VPS. Se requieren conversaciones nuevas y revisiones comparables para demostrar mejoras de producción. Este parche no se despliega automáticamente.

## 20.9.16-rc1 — Parche: aprendizaje medido con datos reales de GALANT

- **Práctica Bot · Datos reales:** crea escenarios cuantitativos a partir de agregados reales de obras autorizadas en PostgreSQL, sin entregar fichas, nombres de contratistas o mensajes personales al modelo.
- **Qwen3.5 4B:** realiza inferencias reales con razonamiento interno activado cuando corresponde; no se muestra razonamiento privado ni se recurre a respuestas predefinidas como evidencia de aprendizaje.
- **Ciclos A/B:** primera referencia, correcciones supervisadas y prueba con los mismos casos reservados sin/con instrucciones, usando semillas comparables. Informa casos recuperados, regresiones, exactitud y latencia.
- **Transferencia controlada:** las reglas generales solo llegan al chat con aprobación administrativa y mejora medida sin regresiones en la prueba reservada. No entrena los pesos de Qwen ni promete fine-tuning.
- **Protección operativa:** conserva el orden de prioridad del chat y Messenger sobre la práctica, respetando el bloqueo de inferencias compartido y los límites de recursos.
- **Alcance:** la interfaz del chat permanece intacta; los cambios corresponden al módulo Práctica Bot y al razonamiento fundamentado de Galancito General.
- **Validación:** la evidencia de integración del parche y una ejecución de Qwen real en VPS deben revisarse antes de instalar en producción.

## 20.9.14-rc1 — Red de Obras: contacto, fichas y chat en el requerimiento

- Resúmenes profesionales legibles, sin repetir etiquetas ni declarar confirmada una fecha relativa.
- Afinidad de oficio/dotación/disponibilidad con porcentajes fijos, sin 100% cuando faltan pruebas.
- Teléfono y correo voluntarios visibles con estado pendiente; captura de correos explícitos en Messenger mediante migración aditiva.
- Chat integrado dentro de la ficha para residentes autorizados: lectura del historial, respuesta manual y estados reales de cola/envío.
- El contacto se ofrece solo durante una coordinación real, sin exigir datos personales para postular; no se divulgan correos a modelos de IA.
- Validaciones por obra, ventana estándar de Messenger y controles para evitar mensajes duplicados.

## 20.9.13-rc1 — Red de Obras: fichas y seguimiento por requerimiento

- Vista completa con candidatos y ficha interactiva, consulta de Messenger, capacidades compartidas y comentarios públicos.
- Seguimiento por candidato y solicitud con etapa, observaciones, próxima gestión, concurrencia y auditoría.
- Comparaciones explicadas, datos faltantes, avisos de discrepancias de oficio, filtros y roles por obra.
- Migración aditiva; no cambia adjudicaciones ni envía mensajes automáticos.

## 20.9.10-rc3 — Conversación natural y evaluación de Galancito

- Galancito pregunta en palabras, reconoce presentaciones y oficios declarados, y conserva la cuadrilla cuando la persona corrige solo su comuna.
- El laboratorio señala opciones numeradas y muestra las fallas por turno. El botón **Exportar resultados a ChatGPT** descarga un informe JSON con métricas y ejemplos.

## 20.9.10-rc2 — Inicio automático del laboratorio Galancito
- Activa el trabajador y Ollama de entrenamiento en la instalación y actualización del VPS.
- Descarga Qwen en segundo plano cuando una ronda lo necesita y conserva la cola durante la preparación.
- Verifica la actividad del trabajador en el despliegue y muestra un estado claro cuando se desconecta.

## 20.9.10-rc1 — Laboratorio Galancito Evolution
- Rondas sintéticas reproducibles con métricas por turno, programación nocturna de Chile y avance persistente en PostgreSQL.
- Trabajador de activación opcional que prioriza Messenger, con Ollama propio y presupuestos para conexiones externas.
- Exportación JSON y Markdown con la clave `GALANT PRACTICA`, comparación de rondas y correcciones aprobadas con historial y reversión.
- El informe indica el origen de las respuestas, los turnos procesados y el alcance de la estimación de naturalidad.
- Verificación local opcional de nombres y oficios, con comparación sobre la misma ronda base.

## 20.8.4-rc1 — Messenger automático y bandeja simplificada
- Webhook en tiempo real y recuperación de respaldo automática cada 75 segundos (inicio tras 15 segundos), con espera creciente ante errores o límites de Meta. No requiere botón para uso normal.
- Estado compacto «Vigente» cuando la página está verificada y Messenger habilitado; diagnóstico técnico y recuperaciones puntuales ocultos tras menú. Eliminación de avisos verdes redundantes.
- Chat principal de dos columnas sin recortes; ficha inteligente opcional, herramientas compactas, mensajes con desplazamiento y respuestas rápidas desplegables.
- Enter envía, Shift+Enter crea nueva línea; estado de cola por mensaje, sin aviso global que sugiera falsamente entrega confirmada.
- Lista de contactos con vista previa del último mensaje, para distinguir contactos sin nombre; sugerencias de nombre expresamente declarado con confirmación humana y seguimiento actualizado cuando llegan mensajes.
- Pruebas de cadencia automática, retroceso frente a errores Meta y lectura eficiente del último mensaje; conserva consentimiento de IA, permisos y límites de Messenger.

## 20.8.2-rc1 — Messenger: recuperación de conversaciones externas
- Recuperación de mensajes entrantes cuando Meta no entregó o GALANT no procesó el webhook; botón de recuperación y sondeo de respaldo de bajo consumo.
- Solo API oficial de conversaciones y mensajes, con token privado en facebook-publisher; no se crean respuestas automáticas retrospectivas ni se cambian fichas confirmadas.
- Deduplicación por página y mensaje, bloqueo transaccional con el webhook, registro de errores seguro y pruebas sintéticas para cuentas externas.
- La recuperación requiere credenciales vigentes y permisos autorizados por Meta; el código no puede eludir la revisión de aplicaciones ni renovar credenciales revocadas.

## 20.7.7-rc1 — Respuesta rápida a saludos y espera acotada
- Espera del chat de hasta 10 segundos en la interfaz, con alternativa segura; inferencia local acotada a 8 segundos incluso con configuración heredada de 24.
- Cinco ejemplos adicionales de trato respetuoso, orientación y atención humana, pendientes de aprobación.
- Messenger revisa trabajos nuevos cada segundo cuando está inactivo; elimina la espera fija anterior de 20 segundos.
- Intervalo configurable con FACEBOOK_WORKER_POLL_SECONDS, entre 0,1 y 5 segundos; conserva apagado controlado y prioridades.
- El chat interno resuelve saludos antes de consultar conocimientos, guías e indicadores; mantiene autenticación y métricas sin contenido privado.
- No cambia modelos, límites de CPU/RAM, consentimiento ni permisos de publicación. Las solicitudes externas y trabajos ya en ejecución pueden añadir latencia.

## 20.7.6-rc1 — Facebook Red de Obras: publicación y seguimiento
- Diagnóstico de errores Graph API con código y subcódigo de Meta, sin exponer tokens ni mensajes privados.
- Centro Facebook con listado de publicaciones, estados reales de la cola y enlaces de posts confirmados.
- Se restaura la verificación manual de la página desde el mismo Centro Facebook.
- Corrección del falso «sin sincronizar» para publicaciones ya confirmadas.
- No se publican anuncios antiguos automáticamente; los reintentos de resultados inciertos se bloquean para evitar duplicados.
- Despliegue supeditado a CI, aprobación y configuración privada de Meta en el VPS.

## 20.7.5-rc1 — Galancito: conocimientos aprobados y respuesta híbrida
- Centro de conocimientos con aprobación explícita, historial, importación de PDF/DOCX/TXT y desactivación inmediata.
- Doce ejemplos pendientes y correcciones administrables; recuperación local por organización y canal, sin reentrenar pesos ni incorporar chats automáticamente.
- Comprensión de expresiones chilenas, oficios y datos explícitos; consultas frecuentes sin cargar Ollama.
- Prompts breves, referencias pertinentes y datos vigentes de Red de Obras; métricas sin texto privado y benchmark reproducible.
- Permanencia configurable con valor inicial de 2 minutos tras comparar 20 s, 2 y 5 min; se conservan Qwen3 1.7B y límites de 3 GiB/1,5 CPU.
- Límite compartido de inferencia y cola acotada; revalidación de consentimiento y atención humana antes de enviar.
- 64 casos sintéticos de comprensión y pruebas del ciclo de aprendizaje, aislamiento, privacidad y degradación; migración aditiva.
- Integrada con 20.7.4-rc1: conserva anuncios locales y seguimiento. Las mediciones iniciales usan 20.7.3 como referencia; el despliegue requiere verificar el commit del VPS.

## 20.7.4-rc1 — Galancito: anuncios, seguimiento y categorización de Red de Obras
- Galancito local Qwen3 1.7B redacta introducciones para anuncios de las necesidades registradas, preservando literalmente obra, oficio, dotación, fechas y partidas. Solo genera borradores administrados y no publica ni adjudica por sí mismo.
- Red de Obras muestra al administrador un tablero de interesados por oficio, prioridad de atención, etapa, obra, necesidades y seguimiento vencido.
- Clasificación automática conservadora: oficio registrado tiene prioridad, los mensajes solo se analizan cuando el interesado dio consentimiento; categorías sugeridas nunca reemplazan el registro confirmado.
- Ficha de Facebook incorpora fecha y nota de próximo seguimiento, guardadas con responsable administrativo.
- Botón de análisis de Galancito por contacto que genera sugerencias locales, sujeto a consentimiento y sin cambios de estado.
- Asesor de Red de Obras con contexto resumido de necesidades, capacidades, coordinaciones y adjudicaciones de la organización, sin información privada de otras áreas.
- Los controles no conceden autorización de ingreso, validación documental ni decisiones de contratación. La prioridad es de *atención operativa*, no nota de idoneidad personal.

## 20.7.3-rc1 — Galancito local gratuito: solo Messenger + Red de Obras
- Qwen3 1.7B (Ollama), modelo privado de aproximadamente 1,4 GB de descarga; sin API de pago.
- Un único contenedor opcional con máximo 3 GB de RAM, 1,5 CPU, una inferencia simultánea, cola corta y descarga de memoria tras 20 s de inactividad.
- No publica ningún puerto de Ollama ni cambia permisos o información de contratistas, nóminas, documentos, pagos, IRL ni INE.
- En Messenger, presenta consentimiento específico para procesamiento de IA local antes de generar respuestas; derivación humana si faltan datos o falla el modelo.
- En la plataforma, Galancito se presenta exclusivamente dentro de Red de Obras y consulta solo títulos de necesidades publicadas y guías de oficios aprobadas.
- Instalación manual protegida de Ollama, prueba de respuesta y activación opcional de Messenger; jamás se inicia el modelo durante el despliegue.
- Respuestas sin conexión: orientación básica local y mensajes de respaldo, sin bloquear el resto de GALANT.

## 20.7.2-rc1 — Conexión simplificada de Galancito a Meta Messenger
- Instalador interactivo de una sola ejecución en el VPS: `sudo python3 scripts/setup-galancito-messenger.py`.
- Genera token webhook privado, identifica automáticamente la organización, verifica el token de página ante Meta, configura solo los servicios afectados y confirma el callback HTTPS.
- Registra por Graph API la suscripción al campo `messages` y activa la conexión de la página sin introducir el token de verificación manualmente.
- Mantiene copias privadas y ediciones atómicas de `.env.preview`; no imprime secretos.
- Ofrece activar difusión automática de necesidades seleccionadas y respuestas IA con confirmación expresa y clave privada.
- Respeta los permisos de Meta y App Review; no los elude ni afirma éxito sin confirmación.
- Pruebas unitarias sin credenciales externas para evitar fuga de secretos y modificaciones accidentales.

## 20.7.1-rc1 — Galancito: nombre único, orientación y respuestas automáticas controladas
- Galancito aparece en GALANT y Red de Obras como asistente de orientación de solo lectura; no crea registros, no habilita contratistas ni adjudica.
- La IA interna es opcional y requiere aceptación del usuario en la propia interfaz, con credenciales y salida HTTPS separadas.
- Galancito de Messenger presenta el uso de IA de OpenAI, pregunta por consentimiento explícito SÍ/NO y solamente envía mensajes a IA externa tras aceptación.
- Permite pausa por contacto; los mensajes manuales del administrador detienen las respuestas automáticas para evitar duplicaciones.
- Guías simples para maestros con fallas de escritura, antecedentes incompletos y solicitudes de orientación humana.
- Mensajes de Facebook se actualizan sin borrar formularios de ficha sin guardar.
- Protecciones: límite de respuestas, ventana de Messenger, cola idempotente, aislamiento por organización, webhook firmado, sin solicitud de documentos personales en chat.
- La activación en producción queda sujeta a permisos de Meta, configuración privada y validación completa.

## 20.7.0-rc1 — Facebook: bandeja de contactos, IA para maestros y guías por especialidad
- La pestaña Facebook es una bandeja de conversación, anuncios pendientes y guías de oficios; no un segundo formulario para publicar.
- Webhooks de Messenger firmados, control de duplicados, respuestas por cola y conexión privada al token de página.
- Asistente de lenguaje simple: comprende mensajes con errores y pide una sola cosa a la vez. Puede registrar audio para atención humana; no lo transcribe todavía.
- Guías editables por especialidad para orientar requisitos documentales sin inventarlos. IA externa opcional y condicionada a consentimiento.
- Identificación de coincidencias por especialidad, dotación y disponibilidad, siempre con revisión humana.
- Nuevas tablas y migración aditiva; no altera contratistas históricos ni adjudicaciones.
- Despliegue protegido por permisos de Meta, configuración privada, CI, pruebas de navegador y respaldo verificado.

## 20.6.0-rc1 — Red de Obras: formulario ampliado y publicación simple
- El formulario ocupa hasta el 94 % de la pantalla; clic fuera no cierra y el cierre con cambios solicita confirmación.
- Publicación rápida con una fecha visible, resumen breve, dotación y partidas opcionales.
- Preferencia de Facebook por requerimiento (activada inicialmente en el formulario y desmarcable). Los datos previos NO se publican retroactivamente.
- Navegación simplificada; acceso al historial de coincidencias, mensajes, adjudicaciones y calendario desde Seguimiento.
- Cambios en rama de revisión hasta superar CI, migración con respaldo verificado y pruebas de integración.

## 20.4.0-rc1 — Red de Obras: difusión en Facebook Pages (no desplegada)

- Publicación automática de requerimientos nuevos en una página empresarial autorizada con Graph API v27.
- Cola transaccional, seguimiento por requerimiento, actualización, eliminación y control de duplicados.
- Procesador Docker aislado con token únicamente en el backend y configuración desactivada por defecto.
- Publicación externa limitada a datos de convocatoria; no revela documentos ni descripciones internas.
- Pruebas sintéticas de éxito, edición, cancelación y estado indeterminado.
- **Pendiente**: CI, respaldo/migración de pruebas, token NUEVO de página en el VPS y validación real antes de fusionar o desplegar.
- No publica en grupos de terceros mediante API de Meta. Ver docs/facebook-red-de-obras.md.

## 20.0.0-rc1 — Javiera / candidata Excel

- Maestro XLSX privado con original verificado, revisión limpia, edición de celdas/cláusulas, historial y concurrencia.
- Recálculo real Calc, matrices Excel sin segunda fuente editable, exportación por hoja y caché privado.
- Correcciones verificables de vínculos IRL, declaración, fechas y datos fijos de ejemplo; conservación de 17 EMF.
- Reinicio documental exclusivo de Javiera, respaldado y reversible; sin borrar datos operativos de otros módulos.
- Candidata no desplegada. Pendientes: datos preventivos incompletos, inducción recortada, editor completo y validación del VPS. Ver `docs/ENTREGA_20_0_0_JAVIERA.md`.

# Historial de cambios

## 18.0.0-rc1 — Proyecto JAVIERA: Excel corregido y PDF A4 con preflight

- Copia de Excel 18 con 22 hojas, 381 fórmulas y 250 combinaciones preservadas y alturas/alineación de documentos extensos revisadas; fichero privado descargable desde el chat, no incrustado en GitHub.
- Impresión A4 por cada una de las 10 hojas, áreas de impresión acotadas, márgenes seguros y varias páginas cuando corresponda.
- Recuperación controlada de contenido ligeramente desplazado en PDF sin desactivar las validaciones de recortes.
- Biblioteca con preflight técnico de fórmulas, cantidad de páginas, áreas y texto dentro de A4.
- Pruebas automatizadas de las 10 configuraciones, contenido parcialmente fuera de margen, permisos y ausencia de aprobación automática.
- Conserva sistema documental independiente y aprobación por responsables.
- Ver `docs/GALANT_18_JAVIERA_PRINT_PREFLIGHT.md` para alcance, limitaciones y pasos posteriores.

## 17.0.0-rc1 — Biblioteca inteligente JAVIERA y revisión documental delimitada

- Nuevo inicio de Proyecto JAVIERA con diez documentos precatalogados, un único importador de Excel privado, detección de cargas repetidas, vistas previas y acciones claras.
- Excel preparado por el usuario se importa sin copiar su información privada a GitHub. Todas las plantillas nacen como borradores para modificar y aprobar una sola vez.
- Nuevo perfil `doc_reviewer` con acceso exclusivamente a revisión documental por especialidad; firma de acta y publicación en un paso validado, manteniendo la separación del autor.
- Sin cambios operativos en módulos de Trabajadores, Contratistas, Asistencia o Leyes Sociales.
- Pruebas de seguridad, aislamiento, idempotencia y UX; ver [guía de implantación](docs/JAVIERA_17_BIBLIOTECA_INTELIGENTE.md).
- Es versión candidata: requiere revisión y CI en verde y cargar/aprobar el XLSX en el servidor privado antes de emitir sus PDF.

## 16.6.1-rc1 — JAVIERA: vinculación y diagnóstico de plantillas Excel (candidata)

- Corrección de las firmas en Entrega PTS: nombres y RUT de representante y trabajador desde la ficha documental, en vez de nacionalidad o estado civil.
- Fecha efectiva `event.date` sustituye el valor histórico calculado por `TODAY()` en constancias del Excel.
- Biblioteca diagnóstica: hoja reconocida, plantilla importada, aprobación, almacenamiento privado y motor LibreOffice; mensajes de bloqueo con acción de configuración.
- Reglamento Interno: no exigir una versión que no se imprime en el diseño Excel original.
- Pruebas sintéticas y auditoría estructural del archivo original, conservando identidades y XLSX fuera del repositorio.
- No se considera una certificación de plantillas publicadas ni despliegue en VPS hasta CI y revisión profesional.

## 16.6.0-rc1 — JAVIERA independiente y generación múltiple (candidata)

- Expedientes, empresas y personas documentales independientes; el asistente no da de alta ni modifica trabajadores y contratistas operativos.
- Asistente por pasos y selección múltiple de las diez plantillas, información compartida y documentos específicos.
- API independiente, generación parcial por lotes, PDF combinado e historial de emisión con originales inmutables.
- Migración aditiva; sin cambios ni bajas en documentos históricos.
- Requiere CI, aprobación humana de plantillas y verificación de impresión en VPS antes de considerar producción lista.


## 16.5.0-rc1 — JAVIERA documental simplificado desde Excel (candidata)

- Asistente centrado en elegir uno de los diez documentos; campos rotulados según el Excel y separados entre documentación laboral y prevención.
- Alta de empleador y trabajador desde la misma ficha; se pueden completar RUT pendientes sin salir del asistente.
- Equivalencias explícitas de labores y cargos compatibles con matrices históricas aprobadas, manteniendo sus revisiones.
- Vista previa, apertura para imprimir y descarga diferenciadas. El PDF se abre en el visor; reemitir una corrección requiere motivo y conserva el PDF anterior.
- Aislamiento ante respuestas tardías al cambiar empresa, obra o trabajador; expediente de empresa separado del individual y bloqueo de cambios de contexto en el servidor.
- Corrección de sueldo en palabras y de un rechazo erróneo al coincidir el sueldo vigente con el ejemplo de la plantilla.
- Regresiones de backend y Chromium con ficha incompleta, emisión, impresión, descarga, reemisión, inmutabilidad y cambio de contexto. Sin migraciones ni cambios en datos de producción.

## 15.0.5-rc1 — Despliegue automático seguro tras aprobación de versión

- Se activa el flujo automático en GitHub Actions solo para commits integrados en `main` que aumenten la versión de backend, frontend y lockfile de forma coherente.
- Un cambio de documentación o código que no incremente versión no dispara despliegue.
- Cada versión nueva vuelve a superar backend, frontend, pruebas Docker, restauración aislada y QA visual antes de desplegar.
- Se reutilizan las credenciales SSH ya comprobadas `VPS_SSH_KEY` y `VPS_KNOWN_HOSTS` en el entorno `GALANT-VPS`.
- El despliegue comprueba el commit exacto y la punta de `main`; crea respaldo de PostgreSQL y documentos, prueba restauración, migra y comprueba estado y commit. Rollback de contenedores si falla.
- El botón manual permanece disponible; se excluyen PR, ramas, tareas programadas y eventos de CI como disparadores automáticos.
- Se añaden pruebas con commits Git sintéticos para impedir versiones incompletas, descendentes o no aprobadas.
- **Activación:** al fusionar esta versión en `main`, GitHub Actions inicia la primera publicación automática solo si las pruebas terminan correctamente.


## 15.0.4-rc1 — Firma de autor en portada (candidata)

- La pantalla pública de acceso muestra «Creado por Álvaro Fritz» en su franja inferior, con un acento dorado discreto integrado al diseño premium existente.
- En pantallas móviles, la autoría aparece bajo el aviso de acceso restringido, sin mostrar el panel decorativo oculto.
- No se modifican autenticación, permisos, datos de contratistas ni esquema de base de datos.
- Nueva prueba visual en Chromium para cuatro resoluciones y comprobación de desbordes horizontales.
- API, frontend y lockfile sincronizados a GALANT 15.0.4-rc1. El VPS se actualiza únicamente desde GitHub Actions con el botón manual.


## 15.0.3-rc1 — Carga de trabajadores con COD y alertas (candidata)

- Formato de Excel obligatorio de seis columnas: contratista, trabajador, RUT, ingreso, término y COD.
- Selección de obra, fechas «INDEFINIDO» o DD-MM-AAAA, códigos TH/TM/F con validación estricta.
- Actualización de COD desde Trabajadores y Alertas contractuales; F queda inactivo operativamente sin generar un finiquito firmado.
- Alertas de vencimiento con umbrales 30/15/7 días visibles por obra para ADMIN y ADMINISTRATIVA.
- Contratos y documentos históricos permanecen intactos; importación de empresas continúa con once columnas.
- Nueva cobertura de pruebas y código de versión sincronizado; el VPS no se modifica automáticamente.


## 15.0.0-rc1 — GALANT Premium UX (candidata)

- Nueva capa visual compartida: navegación azul marino, tarjetas y tablas más legibles.
- Ficha administrativa de contratista inicia en Documentación y elimina su cabecera duplicada.
- Indicador ponderado de obligaciones aprobadas/exigibles y panel de prioridades del período.
- Cambiar período en Documentación actualiza indicadores; revisar actualiza el resumen superior.
- Acciones documentales agrupadas y observaciones visibles, sin eliminar los respaldos históricos.
- Sin requisitos ficticios cuando la matriz documental está vacía.
- Contratistas ordenados alfabéticamente.
- Se conservan los permisos y flujos de Asistencia, Red de Obras y Configuración General 13.1.
- No requiere migraciones ni nuevos endpoints. **Pendiente verificación CI y QA real.**


## 12.1.0 — Renovación UX/UI premium (rama de validación)

- Corrige el recorte de controles de obra/período en el encabezado, con alineación y dimensiones accesibles.
- Elimina selector de obra y botón de importación redundantes en Contratistas.
- Organiza la navegación por módulos y conserva el comportamiento retráctil y móvil.
- Presenta indicadores de alerta y prioridad desde datos reales de backend, sin equiparar Activo/Inactivo con cumplimiento.
- Rediseña el tratamiento visual de estados documentales: aprobado, observado/rechazado/vencido, pendiente de revisión, pendiente de configuración y no aplicable/no exigible.
- Refuerza los avisos de contratos vencidos y finiquitos pendientes con cantidades reales.
- Añade tokens de diseño, responsive, modo oscuro, foco accesible, movimiento reducido y microinteracciones discretas en los módulos.
- Incorpora pruebas Playwright en entorno QA aislado para seis resoluciones, siete secciones, controles únicos, navegación y capturas de pantalla.
- No altera esquemas PostgreSQL, API, reglas de negocio, retenciones, OCR ni permisos.
- Requiere comprobar los resultados finales de CI y revisión visual antes de integrar o publicar. Consultar docs/GALANT_UX_12_1.md.



## 12.0.0-rc1 — Auditoría de fallos ocultos (candidata)

- Corrige bypass de COD=CI en altas laborales y contratos nuevos; rechaza reclasificación incompatible con trabajadores activos.
- El endpoint mensual ya no admite nuevas vinculaciones exigibles para inactivos en período actual/futuro, preservando históricos.
- Elimina falsas alertas de clasificación de CI y corrige la clasificación por obra en opciones laborales.
- Añade pruebas dirigidas y auditorías estáticas de seguridad/dependencias, con resultados verificables en GitHub Actions.
- No se incorporan nuevas funcionalidades ni modificaciones estéticas.

## 10.10.0-rc1 — Activos e inactivos y resiliencia de fichas (candidata)

- Filtros y semáforos de estado; ficha de contratistas con trabajadores, documentación e historial.
- Corrección de detalles anidados que podían provocar pantalla blanca; aislamiento de errores React.
- Inactivos sin nuevas obligaciones documentales ni de asistencia en período vigente/futuro; históricos preservados.
- Pruebas de datos multiobra y no exigibilidad. Estado: pendiente de CI y QA de navegación.

## 10.9.0-rc1 — Importación especializada de contratistas por obra (candidata)

- Plantilla estricta de 11 columnas, sin NATURALEZA ni FRECUENCIA.
- Clasificación CT / CE / CI y estado ACTIVO / INACTIVO independientes por obra, sin asignación mediante catálogos ambiguos.
- Vista previa y actualización segura de registros previamente importados; conserva relaciones y auditoría.
- Corrección de listados, filtros, controles documentales y reglas de independientes usando COD por obra.
- Validaciones y pruebas de importación repetida, encabezados, estados y registros multiobra.
- **Estado:** rama y PR; sujeto a CI, QA y aprobación antes del VPS.

## 9.3.0-rc1 — Control de Asistencia compartido y supervisión de todas las obras (candidata)

- El administrador utiliza el mismo panel de asistencia, contratos, finiquitos y dotación que la administrativa: desaparece la obligación de buscar cada contratista por separado.
- Vista global «Todas las obras» con contratistas activos, revisiones exigibles iniciadas, completadas, pendientes y vencidas; acceso a cada obra con un clic.
- Matriz mensual interactiva (4/5 semanas laborales reales), con semáforos, semanas futuras no penalizadas y distinción de completado fuera de plazo.
- Nombre de la persona responsable asignada y de quien realizó cada revisión, sin confundir asignación con ejecución.
- Acceso directo a la asistencia y trabajadores desde cada casilla semanal del contratista; el administrador conserva su vista de balance de días.
- Datos compartidos y refresco del panel ante actividad de otras sesiones; reutiliza los endpoints y tablas existentes.
- `GET /api/v1/attendance-v81/portfolio` reservado al perfil administrador; la administrativa solo consulta sus obras.
- Pruebas de consolidado, límites de permisos y trazabilidad. Sin migraciones ni alteración de las firmas históricas de fin de semana.
- **Estado:** cambio en rama/PR, pendiente de CI y QA real antes de integración o despliegue.


## 9.2.0-rc1 — Centro laboral administrativo (candidata de revisión)

- Nuevo panel por obra con todos los contratistas activos sin buscar previamente, filtros, semáforos semanales y acceso directo a los trabajadores.
- Pestañas: asistencia semanal, contratos de trabajo, finiquitos, dotación vigente y rendimiento administrativo personal.
- Endpoint de lectura `/attendance-v81/overview` con seguridad por obra, estados laborales vigentes/históricos por fecha, contratos próximos a vencer, finiquitos y semanas de asistencia; no expone los días pagados a la administrativa.
- Reutiliza el registro de asistencia v8.1/v9.1: sin renumerar semanas, modificar firmas antiguas ni generar obligaciones sábado/domingo.
- Vista personal de evaluación mensual sin acceso a la evaluación de otras cuentas.
- Reutiliza tablas y relaciones existentes; **sin migraciones destructivas ni cambios de esquema**.
- El registro de contratos mantiene las rutas autorizadas; la validación y recepción de finiquitos permanecen en el flujo de permisos documentales vigente.
- **Estado:** versión propuesta en rama/PR. Requiere CI, revisión, respaldo verificado y despliegue aprobado. No está desplegada por crear este cambio.


## 8.0.0 — Red de Obras: vista global y experiencia de trazabilidad (candidata)

- Vista inicial de requerimientos y métricas compartida entre todas las obras de la misma organización; filtro «Solo mis obras» opcional, desactivado al ingresar.
- Origen de obra obtenido de los datos de la publicación; bloqueo de cambios de obra en requerimientos existentes.
- Edición de publicaciones limitada a su autor para residentes, incluso si otro residente pertenece a la misma obra.
- Historial de auditoría presentado como eventos en español, con campos permitidos y nombres reales de obra y contratista; se conserva el JSON original solo en el registro interno.
- Diseño de Red de Obras más compacto: cinco indicadores principales, requerimientos antes de gráficos, línea de tiempo visual y formularios de obra bloqueada cuando corresponde.
- Pruebas nuevas de visibilidad entre obras, integridad del origen, autorización de edición e historial seguro.
- No introduce migraciones destructivas ni modifica las reglas documentales, OCR o de pago.
- **Estado:** cambios en rama de revisión. Requiere CI, prueba QA, respaldo y aprobación antes de fusionar o desplegar.

## 0.7.0 — Red de Obras, preparada para revisión

- Portal integrado con requerimientos, partidas dinámicas, borradores y capacidad compartida. Tarjetas, lista, Kanban, calendario mensual/semanal, filtros e indicadores calculados con datos persistentes.
- Rol residente con varias obras asignadas, bloqueo de módulos administrativos en el servidor y vistas colaborativas limitadas. Se conservan los perfiles anteriores.
- Menú superior con creación de cuentas, invitaciones seguras, administración, perfil y notificaciones; suspensión y revocación de sesiones ante cambios críticos.
- Coincidencias explicables por especialidad, fechas, partidas y capacidad libre; vigencia, renovación y distinción entre estimación y confirmación.
- Coordinación formal, conversación única, participantes autorizados, adjuntos, lectura e historial. Actualización automática entre sesiones.
- Adjudicación individual, parcial y a varios contratistas por partida. Saldo separado de ejecución, bloqueos PostgreSQL, idempotencia, ampliaciones, modificaciones, revocaciones y trazabilidad.
- Habilitación documental en la obra de destino, exportación CSV por obra y migración exclusivamente aditiva `0.7.0`.
- Pruebas de integración SQLite/PostgreSQL y recorrido reproducible de navegador con dos residentes.

## 0.6.0-rc1 — candidata local, pendiente de revisión y despliegue

- Importación especializada de contratistas con `NATURALEZA` y `FRECUENCIA` independientes de `COD`; archivos anteriores siguen admitidos y sus celdas vacías no borran clasificaciones válidas. CI se interpreta como independiente; CT no presupone trabajadores ni frecuencia.
- Reconciliación administrativa de clasificaciones con procedencia por evento, vista previa firmada, conflictos visibles, corrección manual y respaldo verificable obligatorio. No se atribuyen valores sin evidencia.
- Registro de trabajadores por obra y empresa con filtros, paginación y ficha individual. Contratos con fecha pactada separada del término efectivo, anexos, PDF y auditoría; finiquitos con causal, ratificación, entrega y revisión manual.
- Semáforo de riesgos contractuales, finiquitos, cotizaciones y documentos exigibles, con centro de alertas en Inicio y acceso a los registros. Los hallazgos de pago requieren documento y revisión; una modificación posterior invalida la conclusión.
- Control de asistencia por obra, contratista y trabajador: cinco ventanas de siete días (semana 5: días 29 al fin de mes), firmas diarias, borrador/cierre/revisión semanal, respaldo, autor y fechas, alerta por semanas vencidas y balance mensual con días pagados. Exclusión o reincorporación mensual sin borrar evidencia.
- Rol de administrativa para ingreso semanal; administrador y supervisor pueden revisar. Se mantienen administrador, supervisor, revisor documental, consulta y `analyst` para cuentas anteriores. Revisores documentales no pueden modificar trabajadores ni contratistas.
- Migración aditiva versionada `0.6.0-rc1`, prueba de respaldo/restauración obligatoria en el actualizador Docker, versión y SHA del commit servidos por la API.

## 0.5.0-rc1

- Organización compartida, administración de cuentas, importaciones especializadas y controles mensuales.
