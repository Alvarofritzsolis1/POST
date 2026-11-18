# GALANT 20.8.3-rc1 — Conectar IA sin entrar al VPS

## Qué se corrigió

La versión anterior impedía guardar Gemini, Groq y NVIDIA cuando faltaba
`AI_CREDENTIAL_ENCRYPTION_KEY`. El formulario exigía escribir un identificador
de modelo y mostraba costos opcionales como si fueran obligatorios.

Esta versión hace la configuración por el flujo de despliegue **seguro y respaldado**:

1. Durante `scripts/update-preview.sh`, en el VPS y **solo una vez**, se genera
   una clave de cifrado Fernet aleatoria en `/opt/galant-post/.env.preview`.
   La clave jamás aparece en logs ni se incorpora a GitHub.
2. Los despliegues siguientes **reutilizan el mismo valor**. Si ya existe
   una clave inválida o duplicada se aborta en vez de rotarla silenciosamente.
3. Los respaldos restringidos incluyen solo esa clave en `ai-key.env`
   junto a PostgreSQL; se verifican sus checksums. **Proteger esos respaldos
   igual que las claves privadas del sistema:** contienen material necesario
   para descifrar las credenciales del banco de datos.
4. El despliegue rechaza una API que no tenga el cifrado listo antes de reportar éxito.
5. La pantalla ofrece tres campos sencillos y un botón **Conectar y probar**.
   Guarda la clave cifrada, prueba realmente el servicio y lo habilita **solo**
   si la prueba es correcta. Las tarifas y el nombre son opcionales y están
   ocultos como ajustes avanzados.

## Pasos para el administrador

Una vez desplegado `20.8.3-rc1`:

1. Abre **Configuración general → Inteligencia artificial → Agregar IA**.
2. Selecciona Google Gemini, Groq o NVIDIA.
3. Selecciona un modelo del menú. El modelo debe estar habilitado en tu cuenta.
4. Abre el enlace **portal oficial del proveedor**, genera una API Key si todavía
   no la tienes, y pégala **solo en el campo de GALANT**.
5. Pulsa **Conectar y probar**. Una prueba exitosa habilita la conexión y muestra
   el estado. Si la prueba falla, se conserva el registro pero no queda habilitado.
6. Luego asigna el proveedor a **Consultas de Red de Obras** en Equipo de Galancito
   y decide si habilitas la revisión por otra IA.

No hay que copiar claves por chat ni rellenar tarifas para conectar.
El botón de prueba puede consumir cuota API y ninguna prueba certifica gratuidad.
El identificador del modelo y los permisos siguen sujetos al proveedor.

## Presets iniciales

- Google Gemini: `gemini-2.5-flash`
- Groq: `llama-3.3-70b-versatile` / `openai/gpt-oss-120b`
- NVIDIA: `deepseek-ai/deepseek-v4.1-flash`

Son **sugerencias de interfaz**, no garantías de acceso en la cuenta real.
Se puede elegir **Otro modelo** en ajustes avanzados.

## Seguridad y recuperación

- La clave maestra está en el servidor; las API Keys de los proveedores viajan
  por HTTPS y se guardan cifradas en base de datos; ninguna se devuelve al navegador.
- El valor maestro no puede regenerarse si ya existe uno válido: **no rotarlo**.
- Cuando se restaure PostgreSQL desde un respaldo, también debe recuperarse la
  **misma clave** guardada en `ai-key.env` del respaldo protegido.
- Si la clave se pierde, no es posible descifrar las credenciales almacenadas;
  habrá que reemplazarlas por nuevas.
- Las verificaciones automáticas usan claves y cuentas sintéticas. El vínculo real
  con cada proveedor debe verificarse después del despliegue.

## QA requerida

- `python3 scripts/test_ai_key_setup.py`
- `python3 scripts/test_auto_release.py`
- CI completa: backend/frontend, Compose, respaldo-restauración y navegador.
- Comprobar en el VPS que `GET /api/v1/admin/ai/bootstrap` devuelve
  `server_ready: true` para un administrador autenticado; nunca mostrar
  `AI_CREDENTIAL_ENCRYPTION_KEY` en respuestas.
