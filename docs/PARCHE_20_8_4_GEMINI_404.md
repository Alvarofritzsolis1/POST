# GALANT 20.8.4-rc1 — Solución Gemini HTTP 404 sin volver a ingresar API Key

## Diagnóstico confirmado

El error `El modelo elegido no está disponible en esta cuenta (HTTP 404)` ocurre después de guardar una clave Gemini. La API rechaza el modelo `gemini-2.5-flash`, aunque la clave puede ser válida y ese modelo pueda aparecer en `models.list`. Google ha explicado que las nuevas cuentas pueden tener restricciones sobre modelos 2.5; recomienda modelos más recientes.

Fuentes oficiales / foro:
- https://ai.google.dev/api/models
- https://discuss.ai.google.dev/t/gemini-2-5-flash-models-get-returns-200-but-generatecontent-returns-404-not-found/195898

## Cambio funcional

1. Se eliminó `gemini-2.5-flash` como recomendación inicial. Los modelos sugeridos ahora son `gemini-3.8-flash` y `gemini-3.5-flash-lite`. Son solo sugerencias, no garantías de acceso.
2. Con una clave cifrada ya guardada, el administrador puede hacer clic en **Buscar modelo compatible** en la tarjeta Gemini con error.
3. GALANT consulta `GET https://generativelanguage.googleapis.com/v1beta/models` con la clave **solo en el header** `x-goog-api-key` y filtra `generateContent`, nunca muestra el secreto.
4. Prueba hasta **3** modelos Flash de bajo costo y máxima prioridad de respuesta (no selecciona automáticamente modelos Pro). Cada prueba es una solicitud real con pocos tokens; puede gastar cuota.
5. Solo si un modelo **genera texto correctamente** se actualiza el modelo guardado, estado verificado y habilitación. El modelo original, la clave y la configuración previa permanecen intactos si la recuperación falla.
6. En altas nuevas y en **Probar conexión**, un HTTP 404 Gemini dispara automáticamente el intento de recuperación. No hace falta volver a pegar la clave.
7. La conexión no se habilita cuando el modelo aún no está verificado; se conservan mediciones de intentos y se evita registrar claves o textos privados.

## Qué hace el usuario

En GALANT → **Configuración General → IA**:

- Si aparece la tarjeta Gemini en rojo, presiona **Buscar modelo compatible**.
- GALANT consultará los modelos de tu cuenta y probará un máximo de tres.
- Si alguna prueba funciona, la conexión quedará habilitada y podrás asignarla a Galancito.
- Si no hay ninguno operativo, revisa las restricciones de tu cuenta en https://aistudio.google.com/apikey. Una lista de modelos no garantiza acceso a la generación.
- No envíes API Keys por WhatsApp, chats, capturas ni GitHub.

## Validaciones

- Tests sintéticos: modelo listado pero generación 404, recuperación con otro modelo, restricción de permisos, preservación de credenciales, límite de 3 pruebas, costo y tokens de prueba, separación de organizaciones.
- CI completa: frontend TypeScript, backend Python, PostgreSQL, Docker Compose, respaldo/restauración y navegación aislada.
- **No se usan claves API reales** en CI; el acceso efectivo a Gemini requiere validación de la cuenta desde la propia plataforma tras desplegar.

## Seguridad

- No incorpora endpoints de API arbitrarios, no envía claves como parámetros de URL ni sigue redirecciones externas.
- La recuperación se autoriza solo a administradores y se limita a la organización del usuario.
- Si Google devuelve 401, 403 o 429 se detienen las pruebas adicionales.
- El menú inicial ofrece modelos nuevos, pero siempre es la llamada `generateContent` la que confirma realmente el funcionamiento.
