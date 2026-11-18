# GALANT 20.8.0-rc1 — Centro de IA multi-proveedor

## Qué queda disponible
- Configuración General → Inteligencia artificial (solo administradores).
- Crear varias conexiones, incluso más de una por proveedor. Presets: Gemini, Groq, NVIDIA, OpenAI, Mistral, OpenRouter.
- Introducir API Key y modelo exacto, verificar conectividad, pausar o desvincular.
- Cifrado Fernet de credenciales en la base de datos. Nunca se devuelven al frontend ni se imprimen en logs.
- Registro de tokens de entrada y salida informado por API, errores, duración y costo estimado si el administrador indica tarifas USD / millón de tokens. Sin tarifa configurada, el costo NO se conoce.
- Asignar funciones a modelos mediante reglas de enrutamiento, opcionalmente intentar otro proveedor ante error; límites de latencia.
- En la **primera etapa**, el enrutamiento multi-proveedor está **conectado al chat de Galancito de Red de Obras**. Las otras funciones visibles (anuncios, clasificación, seguimiento y segunda opinión) quedan preparadas como asignaciones, pero **todavía no ejecutan solicitudes automáticas**. No hay entrenamiento autónomo entre proveedores.
- Las guías y correcciones compartidas siguen siendo las aprobadas manualmente en Conocimientos; no se mezclan chats privados.

## Paso 1 — Clave de cifrado privada (una sola vez)
En el VPS, generar una clave aleatoria Fernet (nunca pegarla en chats, capturas, commits ni comentarios):
```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```
Si el host no tiene cryptography, generar la clave con el Python del contenedor ya reconstruido:
```bash
docker compose -f docker-compose.preview.yml run --rm --no-deps api python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```
Guardar como **AI_CREDENTIAL_ENCRYPTION_KEY** en el archivo privado de variables del despliegue, por ejemplo en el mismo `.env.preview` ya usado para ese entorno. La variable se inyecta solo en servicios backend y nunca en el frontend.

**Advertencia:** conservar un respaldo protegido de esta clave. Si se pierde o cambia, las API Keys existentes no podrán descifrarse y deben ser reemplazadas. No usar APP_SECRET como clave Fernet ni publicar el valor en GitHub.

## Paso 2 — Desplegar
Antes de desplegar, aprobar y fusionar el PR, verificar copia/restauración de base de datos e incluir la migración aditiva `20.8.0_ai_control_center` usando el flujo de migraciones de GALANT. El despliegue no está incluido en este PR ni debe considerarse realizado automáticamente.

Recrear el contenedor de API tras definir la variable de entorno. El nuevo menú mostrará si el servidor puede recibir credenciales.

## Paso 3 — Agregar las tres IA existentes
Abrir **Configuración General → Inteligencia artificial → Agregar IA**.

| Proveedor | Obtener API Key | Modelo |
|---|---|---|
| Gemini | https://aistudio.google.com/apikey | Pegar ID de modelo válido de AI Studio |
| Groq | https://console.groq.com/keys | Pegar ID de modelo activo de Groq |
| NVIDIA | https://build.nvidia.com/settings/api-keys | `deepseek-ai/deepseek-v4.1-flash` si está disponible para la cuenta |

Por cada una: elegir proveedor, nombre, modelo exacto y clave secreta; guardar; **Probar conexión**. El test hace una solicitud real, que puede usar cuota y tokens.

Opcional: introducir precios reales de entrada/salida por millón de tokens para estimar consumo. No suponer que una API es gratuita por el hecho de admitir pruebas.

## Paso 4 — Repartir tareas
En **Equipo de Galancito**, asignar una IA para **Consultas de Red de Obras**; activar la conexión y luego **Activar equipo IA**. El chat Galancito de Red de Obras solo usará la IA externa si la persona autoriza explícitamente el procesamiento externo. Si es una pregunta trivial o ya existe una guía aprobada, sigue respondiendo localmente.

La opción de alternativa recurre secuencialmente a otro proveedor habilitado, sin multiplicar consultas en paralelo. El límite mensual deja de iniciar consultas nuevas **cuando se ha alcanzado el valor registrado**; no es un bloqueo anticipado exacto ni sustituye los límites de facturación de cada proveedor.

## Verificación y seguridad
1. Usuario administrativo no entra al centro: HTTP 403.
2. Credenciales cifradas y no presentes en respuestas JSON.
3. Conexiones separadas por organización y no modificables entre organizaciones.
4. Conexión desconectada conserva métricas sin conservar la API Key.
5. Las rutas y dominios externos provienen de una lista cerrada en `ai_gateway.py` y no del usuario.
6. Las mediciones solo incluyen llamadas cursadas por GALANT, no el uso fuera de la plataforma.
7. Los errores de los proveedores no exponen cuerpos HTTP, tokens ni mensajes enviados.
8. Pruebas unitarias en `test_ai_control_center.py`.

## Próxima integración
Con autorización y pruebas independientes, conectar gradualmente las asignaciones ya configurables a redacción de anuncios, clasificación, seguimiento CRM y control de calidad. Ningún flujo que publique en Facebook, contacte personas, adjudique o modifique registros debe activarse automáticamente por el solo hecho de añadir una API Key.
