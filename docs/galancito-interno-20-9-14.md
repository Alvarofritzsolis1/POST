# GALANT 20.9.14-rc2 — Galancito Interno 360° (candidata)

## Alcance real
- Dos perfiles separados: Galancito Postulantes y Galancito Interno de solo lectura.
- Consultas internas verificables con permisos por usuario/obra: versión instalada, necesidades, urgencias, publicaciones por estado, seguimientos, contratistas activos y documentos mensuales agrupados por estado.
- Resumen de rendimiento basado en una medición puntual de los recursos del servidor cuando el usuario tiene permisos.
- Historial de sesión acotado a preguntas recientes para resolver referencias simples a obras. **No hay memoria conversacional persistente en la base de datos**.
- Informes de consulta exportables como PDF, XLSX y DOCX mediante POST autenticado. Son resúmenes verificables, no un motor libre de reportes legales.
- Conexión a búsqueda web mediante Brave Search API opcional, con consentimiento explícito del usuario por consulta. Se consultan **resúmenes públicos**, no se navega ni comprueba independientemente cada fuente.
- Práctica Bot Interno: 20 categorías, 400 casos base sintéticos, niveles, repeticiones 1–40, evaluaciones por exactitud y seguridad, y límites de 10.000 pruebas totales por ejecución.

## Configuración de búsqueda pública
La búsqueda se habilita únicamente cuando el servicio backend tiene la variable:

`GALANCITO_BRAVE_SEARCH_API_KEY=<clave-de-buscador>`

La clave es un **secreto del VPS/gestor de secretos**: no la guardes en el repositorio, en el navegador ni la envíes por chat. La búsqueda no exige conectarse a un proveedor de IA de texto. El acceso está limitado al endpoint HTTPS fijo de Brave Search, con un máximo de cinco resultados y cinco segundos por petición. El contenido de los resultados se trata como **información externa no confiable**. Sin clave, la interfaz no muestra la opción de buscar y el asistente explica que no existe búsqueda configurada.

## Práctica Bot
1. Selecciona **Interno 360°**.
2. Elige Ollama para probar la respuesta del modelo real; **Reglas locales** únicamente verifica la respuesta patrón.
3. Configura casos por ciclo y ciclos, manteniendo **casos × ciclos ≤ 10.000**.
4. Para no saturar el VPS, mantén límites de CPU, memoria, duración y concurrencia.
5. Revisa métricas globales y métricas por ciclo; compara con la misma versión de evaluación y el mismo dataset.
6. Los casos son ficticios: **no acceden a Facebook, las fichas, el VPS o la web real**.

Una ronda de simulación **no reentrena los pesos del modelo**, no convierte automáticamente sus propuestas en respuestas de producción y no sustituye pruebas reales de los módulos.

## Validación antes de despliegue
- PR en borrador mientras se ejecuta CI, pruebas de autorización y pruebas de exportación/privacidad.
- El frontend compila con TypeScript y Vite; los tests backend cubren SQLite y PostgreSQL cuando están disponibles en CI.
- No fusionar automáticamente sin un CI completo del **último commit** y QA manual autenticada (administrador y residente).
- No anunciar públicamente un porcentaje 100% sin medición de calidad conversacional real y prueba de producción.

## Pendientes explícitos del prompt maestro (NO implementados)
- Generación libre de reportes complejos con tablas y gráficos de todos los módulos.
- Flujo completo de herramientas con planificación autónoma e IA con razonamiento multi-módulo verificable.
- Memoria persistente y control de retención de conversaciones internas.
- Clasificación y análisis automatizado de todos los comentarios de Meta.
- Autoaprendizaje/fine-tuning con 40 épocas de pesos reales.
- Verificación en producción del proveedor de búsqueda web y monitorización sostenida de latencia.

## Cambios adicionales en 20.9.14-rc2
- Conversaciones internas guardadas por usuario y organización **solo con consentimiento explícito**. La opción está desactivada por defecto; el usuario puede restaurar y eliminar sus propias conversaciones. Retención de 30 días y 16 turnos recientes por conversación.
- Se rechaza el almacenamiento de datos personales detectables y de contextos críticos (fichas de candidatos, documentos, contratos y datos sensibles).
- Sugerencias de próximos pasos mediante **Ollama local** únicamente cuando el modelo ya está cargado, a petición explícita del usuario. Los datos consultados y verificados permanecen separados de la sugerencia generada.
- La nueva tabla se crea por una **migración aditiva** registrada en `migrate-db` e `init-db`; requiere el flujo habitual de respaldo verificado antes de desplegar.
- Las pruebas automatizadas verifican aislamiento, retención, borrado, filtrado y protección contra alucinaciones numéricas.

**No equivale a un agente autónomo universal ni demuestra aprendizaje de pesos o uso real de Brave sin credenciales.**
