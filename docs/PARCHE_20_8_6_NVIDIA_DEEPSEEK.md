# GALANT — NVIDIA DeepSeek (parche de integración)
## Objetivo
Ofrecer DeepSeek de NVIDIA como una conexión seleccionable en Configuración General > Inteligencia artificial, sin publicar claves ni exigir GPU local.

## Endpoint oficial
- Proveedor: NVIDIA Build.
- URL: `https://integrate.api.nvidia.com/v1/chat/completions`.
- Modelo recomendado: `deepseek-ai/deepseek-v4-flash` (verificar disponibilidad real con tu clave).
- Alternativa DeepSeek: `deepseek-ai/deepseek-v4-flash-0731` (solo si aparece en el catálogo de NVIDIA y funciona la prueba).
- API key individual del proveedor, guardada cifrada por la organización en la base de datos.

## Uso
1. Generar la API key en https://build.nvidia.com/deepseek-ai/deepseek-v4-flash .
2. Ingresar a **Configuración General > IA > Agregar IA** en GALANT.
3. Elegir NVIDIA, seleccionar DeepSeek V4 Flash, pegar la clave **solamente** en el formulario autenticado de GALANT, y pulsar **Conectar y probar**.
4. Si la conexión aparece **Verificada y habilitada**, ir a **Equipo de IA**, asignarla a **Red de Obras** o **Messenger**, habilitar la orquestación y guardar.
5. Confirmar con una consulta real de Galancito que se registre el uso; para Messenger siguen siendo necesarios los permisos y parámetros independientes de Meta.

## Criterios de seguridad y verificaciones
- La clave jamás debe escribirse en GitHub, logs, capturas o el chat.
- En NVIDIA DeepSeek las pruebas usan `temperature=1.0`, `top_p=0.95` y hasta 512 tokens de salida; V4 Flash usa `reasoning_effort=none` para mejorar la velocidad de consultas cortas.
- El modelo `deepseek-ai/deepseek-v4.1-flash` fue retirado por NVIDIA el **16 de noviembre de 2026** según respuesta real HTTP 410 recibida desde el VPS del usuario. No elegirlo como opción predeterminada.
- La recuperación considera modelos **DeepSeek** vigentes en el catálogo si esa era la elección inicial, y no cambia silenciosamente a Nemotron. En HTTP 410 el panel ofrece recuperación, pero ningún modelo se declara operativo sin prueba real.
- No se marca una conexión como verificada si solo aparece en el catálogo; se realiza una llamada real.
- Los usuarios autenticados usan las rutas configuradas para su organización, sin duplicar la clave en cada cuenta.
- NVIDIA puede aplicar límites de cuota, disponibilidad y costos. No se prometen llamadas ilimitadas ni gratuidad garantizada.
- Las pruebas automatizadas usan respuestas sintéticas: **no verifican el acceso real de la cuenta del usuario**.
- Este parche de GitHub no configura la API key ni despliega por sí solo en el VPS.

## Referencias oficiales
- https://build.nvidia.com/deepseek-ai/deepseek-v4-flash
- https://docs.api.nvidia.com/nim/reference/deepseek-ai-deepseek-v4-flash-infer
