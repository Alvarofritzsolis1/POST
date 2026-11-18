# GALANT — NVIDIA Nemotron 3.5 Lightning (configuración segura en VPS)

## Modelo
- Proveedor: NVIDIA Build
- Modelo: `nvidia/nemotron-3.5-lightning-30b-a3b`
- Endpoint: `https://integrate.api.nvidia.com/v1/chat/completions`
- Sin GPU en VPS; generación remota en NVIDIA.
- Modo rápido: `chat_template_kwargs.enable_thinking=false`; para razonamiento profundo habilitar en una futura configuración separada.

## Pasos de instalación (luego de integrar este PR a main)

Estos comandos son para el servidor de vista previa del repositorio POST, instalado en `/opt/galant-post`.
No ejecutar si la instalación activa usa otra ruta o un Compose diferente.

```bash
cd /opt/galant-post
git status --short
git pull --ff-only origin main
sudo python3 scripts/ensure-ai-key.py .env.preview
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml config --quiet
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml up -d --build api worker frontend proxy
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.ai_nvidia_setup
```

El último comando pide la API Key *en pantalla oculta*, realiza una llamada real al modelo y **solo entonces** guarda la clave cifrada, marca verificada la conexión y asigna `red_obras` a Lightning para esa organización.

Si hay varias organizaciones, usar:
```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.ai_nvidia_setup --admin-email ADMIN@DOMINIO.CL
```

No pegar claves en archivos fuente, Github, capturas ni chats. No rotar `AI_CREDENTIAL_ENCRYPTION_KEY` si ya existen credenciales cifradas.

## Comportamiento
- Red de Obras/galancito usa conexión compartida por organización, no por usuario.
- Messenger mantiene la ruta y las opciones ya configuradas; no se activan respuestas automáticas ni otros permisos de Meta.
- Una cuenta nueva sin límite de tokens recibe un tope mensual local inicial de 100.000 tokens. Límites existentes se conservan y pueden ajustarse en el panel.
- No se realiza la escritura si la prueba externa falla. No se expone la clave ni en la respuesta ni en los logs del programa.
- Las pruebas sintéticas de CI no sustituyen la prueba real con la clave del administrador.

## Diagnóstico
- HTTP 401: clave incorrecta; 403: acceso restringido; 404: modelo no habilitado; 410: retirado; 429: cuota agotada.
- `docker compose ... ps` comprueba contenedores; `docker compose ... logs --tail 40 api` comprueba excepciones sin mostrar secretos.
- La cuenta y el catálogo de NVIDIA pueden variar; `Free Endpoint` no significa uso gratuito e ilimitado.

Referencias:
- https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-5-lightning-30b-a3b-infer
- https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html
