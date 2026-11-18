# GALANT — NVIDIA DeepSeek (parche de integración)
## Objetivo
Ofrecer DeepSeek de NVIDIA como una conexión seleccionable en Configuración General > Inteligencia artificial, sin publicar claves ni exigir GPU local.

## Endpoint oficial
- Proveedor: NVIDIA Build.
- URL: `https://integrate.api.nvidia.com/v1/chat/completions`.
- Modelo recomendado: `deepseek-ai/deepseek-v4.1-flash`.
- Alternativa DeepSeek: `deepseek-ai/deepseek-v4-flash`.
- API key individual del proveedor, guardada cifrada por la organización en la base de datos.

## Uso
1. Generar la API key en https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash .
2. Ingresar a **Configuración General > IA > Agregar IA** en GALANT.
3. Elegir NVIDIA, seleccionar DeepSeek V4.1 Flash, pegar la clave **solamente** en el formulario autenticado de GALANT, y pulsar **Conectar y probar**.
4. Si la conexión aparece **Verificada y habilitada**, ir a **Equipo de IA**, asignarla a **Red de Obras** o **Messenger**, habilitar la orquestación y guardar.
5. Confirmar con una consulta real de Galancito que se registre el uso; para Messenger siguen siendo necesarios los permisos y parámetros independientes de Meta.

## Criterios de seguridad y verificaciones
- La clave jamás debe escribirse en GitHub, logs, capturas o el chat.
- En NVIDIA DeepSeek las pruebas usan `temperature=1.0`, `top_p=0.95` y hasta 512 tokens de salida.
- La recuperación solo considera modelos **DeepSeek** si esa era la elección inicial, y no cambia silenciosamente a Nemotron.
- No se marca una conexión como verificada si solo aparece en el catálogo; se realiza una llamada real.
- Los usuarios autenticados usan las rutas configuradas para su organización, sin duplicar la clave en cada cuenta.
- NVIDIA puede aplicar límites de cuota, disponibilidad y costos. No se prometen llamadas ilimitadas ni gratuidad garantizada.
- Las pruebas automatizadas usan respuestas sintéticas: **no verifican el acceso real de la cuenta del usuario**.
- Este parche de GitHub no configura la API key ni despliega por sí solo en el VPS.

## Referencias oficiales
- https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash
- https://docs.api.nvidia.com/nim/reference/nvidia-deepseek-v4_1-flash-infer
