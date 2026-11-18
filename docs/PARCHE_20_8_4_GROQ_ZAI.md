# GALANT 20.8.4 — Corrección de conexiones Groq, Gemini y Z.ai

## Causa y alcance

El panel anterior ofrecía modelos predeterminados pero no sabía si una clave tenía
acceso real. Un modelo que aparece en documentación pública puede responder HTTP 404,
403 o agotar sus tokens de salida pensando sin producir texto. El panel ahora presenta
opciones verificables, recuperación guiada y errores comprensibles, sin mostrar las claves.

## Groq

- Endpoint oficial: `https://api.groq.com/openai/v1/chat/completions`.
- Listado del usuario: `GET https://api.groq.com/openai/v1/models`.
- La recuperación consulta modelos activos, descarta modelos de audio/moderación y
  comprueba como máximo tres modelos de texto mediante una solicitud real.
- Si hay un modelo que responde, la conexión anterior se conserva, se actualiza el ID
  y se habilita. No requiere copiar de nuevo la clave.
- Errores 401/403/429 no desencadenan múltiples intentos de generación.

Fuentes: https://console.groq.com/docs/api-reference y https://console.groq.com/docs/models.

## Z.ai — solo API estándar

- Endpoint: `https://api.z.ai/api/paas/v4/chat/completions`.
- Clave: **Standard API Key** de https://z.ai/manage-apikey/apikey-list.
- Modelos iniciales: `glm-4.7` (sin thinking para consulta rápida) y
  `glm-5.3-flash` (thinking forzado, requiere más tiempo y tokens).
- La recuperación automática prueba hasta dos modelos reales y conserva la conexión
  sin cambiar la clave o el endpoint.
- Se envía un presupuesto de salida más alto en pruebas de modelos de razonamiento.
- Si no hay saldo, la clave es inválida o el modelo está restringido, el panel informa
  el problema y deja la conexión desactivada.

**Importante: no se admite el Coding Plan en Galancito.** Z.ai limita ese plan
a herramientas compatibles y prohíbe compartir sus beneficios entre varios usuarios.
El plan además tiene claves y condiciones de facturación diferentes. Para GALANT
se usa únicamente la API estándar, que puede generar cargos por uso.

Fuentes oficiales:
- https://docs.z.ai/guides/overview/quick-start.md
- https://docs.z.ai/devpack/notice/api-key-management.md
- https://docs.z.ai/devpack/usage-policy.md
- https://docs.z.ai/guides/capabilities/thinking-mode.md

## Uso en GALANT

1. Entrar a Configuración General → Inteligencia artificial.
2. En una conexión Groq con error, hacer clic en **Buscar modelo compatible**.
3. Para Z.ai, pulsar **Agregar IA → Z.ai · API estándar** y pegar una Standard API Key.
4. Hacer clic en **Conectar y probar**. Si el primer modelo devuelve HTTP 400, 404
   o agota la salida sin texto, GALANT intenta la recuperación automáticamente.
5. Conectar solo el proveedor que quede **Verificado y habilitado** al agente Galancito.

Las pruebas consumen cuota real del proveedor. Las claves privadas no se comparten
con ChatGPT ni se colocan en logs; los resultados de pruebas sintéticas no garantizan
que un proveedor autorice la cuenta real.
