# GALANT 20.8.1-rc1 — Auditoría de infraestructura de IA y parche

## Alcance verificado
Revisión del código de GitHub en el centro IA, Galancito, retrieval y feedback, Gateway multi-proveedor, PostgreSQL, controles de acceso, Docker Compose, frontend y sus pruebas. **No es una auditoría total demostrada de cada módulo de GALANT ni una evaluación con API Keys reales.**

## Hallazgos y correcciones implementadas

1. **Modelos no conversaban entre sí.** La v20.8.0 ofrecía solamente proveedor principal y alternativa. Ahora existe una revisión explícita y opcional (apagada por defecto): proveedor principal produce la respuesta; proveedor **distinto** recibe la respuesta y contexto autorizado, devuelve únicamente un veredicto JSON `{"valid":true}` o `{"valid":false}`. Se descarta la respuesta si es rechazada o no verificable. No hay diálogo libre, autoaprendizaje ni cambios automáticos.
2. **Aislamiento de consultas y coste:** el bloqueo de inferencia local Ollama mantiene su comportamiento. Los proveedores externos usan un bloqueo transaccional por organización, no uno global para todos los usuarios, a fin de evitar que un tenant retenga a los demás. Se añade una **estimación conservadora** de tokens de entrada y salida antes de cada llamada para impedir iniciar solicitudes que previsiblemente superen la cuota configurada. El tope NO sustituye la facturación de proveedores ni ofrece límite monetario exacto.
3. **Fallos de presupuesto:** al activar el equipo en Configuración, un proveedor legacy OpenAI ya no puede saltarse la cuota del equipo, falta de verificación o fallo del segundo revisor. El modelo Ollama local, si está habilitado, conserva una ruta independiente.
4. **Datos sensibles:** se detectan formatos adicionales de teléfonos chilenos y claves comunes. Se impide consultar proveedores externos cuando **cualquier parte del contexto** —incluidos títulos y guías históricos— contenga patrones privados, aunque la pregunta inicial no los tenga. También se rechaza una **respuesta generada** si incluye patrones privados, impidiendo transferirla a la segunda IA.
5. **Conocimiento compartido:** se muestran en Configuración → IA los totales de guías aprobadas, propuestas pendientes y feedback incorrecto. No se entrenan pesos ni se transforman correcciones pendientes en hechos. Solo aprobación administrativa permite que `galancito_knowledge` sea usada en las consultas.
6. **Seguridad de contenedores:** la clave de cifrado de proveedores deja de inyectarse con su valor a los contenedores de trabajador y publicador Facebook, donde no se utiliza.
7. **Interfaz:** opción claramente identificada de segunda revisión con costo adicional, límites más explícitos y conservación de asignaciones pendientes al cambiar el período de métricas.
8. **Migración** `20.8.1_ai_collaboration` aditiva, idempotente y con `review_enabled=FALSE` de forma predeterminada. No modifica antecedentes, contratos, expedientes, mensajes ni planillas de las obras.

## Flujo efectivo

```text
Usuario autorizado → privacidad + clasificador rápido → FAQ aprobada (si coincide)
    → consentimiento IA externa → bloqueo por organización → cuota de tokens
    → proveedor principal (Gemini / Groq / NVIDIA / otro configurado)
      → alternativa verificada SOLO ante error, si la habilitaste
    → verificador distinto (opcional; salida JSON)
    → filtro de hechos no fundamentados → respuesta en Galancito
    → registro de tokens y duración SIN guardar prompts privados.
```

* No activa Facebook Messenger ni publica en una página o grupo por sí mismo.
* No se habilita procesamiento de datos personales ni subcontratistas a través de proveedores de IA externos.
* No hay memoria conversacional privada entre proveedores ni entrenamientos en los modelos externos.
* No se reciben claves reales en GitHub ni se exponen al navegador después de guardarlas.

## Uso del nuevo equipo

En **Configuración General → IA**:
1. Probar cada conexión real y dejarla Habilitada/Verificada.
2. Seleccionar una IA para **Consultas de Red de Obras**.
3. Para comprobación independiente, seleccionar **Segunda opinión / calidad** con otra IA distinta y marcar **Verificación por una segunda IA**. El modo está **desactivado** por defecto.
4. Opcionalmente activar alternativa ante error y una cuota mensual de tokens (0 indica sin límite propio). Activar el equipo solo tras comprobar costos y consentimiento.
5. Consultar las métricas: llamadas de principal, revisor, tests, tokens de entrada/salida, estimación de costo donde haya tarifas y conocimientos pendientes.
6. Para enseñar: proponer corrección desde el flujo de feedback y aprobarla en **Conocimientos**. Nunca se aprueba por IA automáticamente.

## Riesgos pendientes — no afirmar que están resueltos

- El precio por token y la cuota dependen del proveedor; pueden diferir por tokens de caché/razonamiento, uso fuera de GALANT o cambios de tarifas.
- El cálculo preventivo no es un tokenizador oficial: puede existir sobrepaso por diferencias de contabilidad o requests no exitosos facturados.
- El veredicto de la segunda IA no es garantía de verdad; aunque se le exige JSON, puede equivocarse. Se conserva el control de hechos y revisión humana.
- Las llamadas HTTP son síncronas; aunque ahora están limitadas en tiempo, requieren observación real de latencia bajo carga y recursos del VPS.
- No se ha validado con credenciales reales, cuotas comerciales ni VPS productivo.
- Integración futura: documentos/mensajes con consentimiento y políticas por tarea, auditoría de coste monetario con datos de facturación, colas durables para tareas largas y evaluaciones human-in-the-loop.

## Comprobaciones exigidas antes de publicar

```text
python -m compileall -q apps/backend/app
python -m pytest -q apps/backend/tests/test_ai_control_center.py
# Además, ejecutar TODO el pipeline de .github/workflows/ci.yml
```

No fusionar el PR hasta verificar **CI completa en verde**, respaldo/restauración, migración aditiva y configuración privada de `AI_CREDENTIAL_ENCRYPTION_KEY`. Las pruebas usan datos sintéticos y no gastan cuotas reales.
