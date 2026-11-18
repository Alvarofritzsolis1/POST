# GALANT — NVIDIA Nemotron 3.5 Lightning para TODOS los usuarios

Una única credencial NVIDIA, introducida de forma privada en el VPS, sirve a **todas las organizaciones y usuarios autorizados de GALANT**, actuales y futuros. No se pide correo, no se crea una API Key por cuenta y no se comparten datos entre organizaciones.

## Modelo y arquitectura
- Proveedor: NVIDIA Build; modelo: `nvidia/nemotron-3.5-lightning-30b-a3b`.
- Inferencia remota: `https://integrate.api.nvidia.com/v1/chat/completions`.
- La clave se guarda cifrada una sola vez en `ai_global_credentials` y se vincula a registros separados `ai_connections` por organización. Solo el backend accede a las credenciales.
- Las rutas y el consumo se contabilizan por organización, sin cruzar datos de obras ni mensajes.
- Los usuarios futuros de organizaciones existentes comparten su ruta. Las nuevas organizaciones reciben la ruta automáticamente al crear el administrador o acceder a Galancito/Configuración IA.
- Por seguridad, las consultas externas de Galancito siguen requiriendo consentimiento `allow_external_ai` por mensaje; no se habilitan mensajes automáticos de Facebook.
- Tope local inicial de 100.000 tokens por organización, ajustable en Centro de IA. NVIDIA aplica sus propios límites y puede cobrar.

## Despliegue para el VPS de GALANT POST (solo tras merge y CI)
Primero verificar que `/opt/galant-post` es el proyecto activo, respaldar PostgreSQL y documentos privados y verificar restauración; nunca usar `docker compose down -v`.

```bash
cd /opt/galant-post
git status --short
git pull --ff-only origin main
sudo python3 scripts/ensure-ai-key.py .env.preview
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml config --quiet
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml up -d --build api worker frontend proxy
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli init-db
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.ai_nvidia_setup
```

El último comando **solo pide la clave NVIDIA** de forma oculta. Primero prueba una generación real; después la registra cifrada y habilita a todas las organizaciones. Muestra el número conectado, no nombres ni credenciales. Si falla, no deja cambios parciales.

Verificar después entrando con una cuenta de residente o administrativa a Galancito. Los usuarios no administradores no tienen acceso al panel de claves y mantienen sus permisos habituales.

## Diagnóstico
- 401: credencial rechazada; 403: sin permisos; 404: modelo no disponible; 410: modelo retirado; 429: límite o cuota.
- No declarar la conexión correcta hasta que responda el endpoint real.
- Si existe otro modelo asignado al agente de Red de Obras, la instalación global cambia esa ruta a Lightning. No borra conexiones anteriores ni cambia Messenger.
- Si una organización había configurado un revisor distinto, su revisión se conserva salvo que existiera un conflicto de modelo; revisarlo desde Configuración IA.
- Este procedimiento no despliega el parche por sí solo. CI y una prueba real con la clave son necesarios.

Documentación de despliegue existente: `docs/DESPLIEGUE_VPS_UN_CLIC.md`.
