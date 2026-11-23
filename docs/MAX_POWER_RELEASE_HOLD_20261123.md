# MAX POWER — BLOQUEO DE PUBLICACIÓN POR EVIDENCIA PENDIENTE

Estado: **NO APROBADO PARA PUBLICACIÓN** (2026-11-23).

El botón MAX POWER **no está validado de extremo a extremo** aunque el controlador y el supervisor estén saludables.

Criterios obligatorios antes de liberar:
1. Al pulsar ON, comprobar sesión y heartbeat en API y base de datos.
2. Verificar 100 ejemplos sintéticos, hash, partición, privacidad y procedencia sin fingir autorizaciones.
3. Ejecutar evaluación aislada Qwen 4B con métricas de respuestas, independientemente de la configuración de producción de Messenger.
4. Ejecutar LoRA CPU Qwen 0.8B en recursos reales y registrar optimizador con pasos positivos, hashes de pesos distintos y checkpoint persistente.
5. Demostrar OFF, reanudación, protección de Messenger y manejo de errores sin perder resultados.
6. Demostrar mejoras y regresiones en holdout independiente. El LoRA 0.8B no mejora automáticamente los pesos Qwen 4B de Messenger.
7. Confirmar SHA en VPS, servicios saludables, evidencias y actividad de la base de datos, no solo GitHub Actions en verde.

Un estado healthy o pasar pruebas unitarias sin descargar pesos NO demuestran entrenamiento neuronal exitoso.
Este commit no cambia versión. La publicación futura requiere los resultados de todos estos puntos.