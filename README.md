# GALANT POST — Enterprise Document Intelligence

Software documental chileno construido de cero en el repositorio POST. Frontend React + TypeScript, backend FastAPI y PostgreSQL, OCR nativo y escaneado con Tesseract. **No usa Streamlit ni importa código anterior.**

> ESTADO: Base inicial en pruebas. NO usar documentos laborales reales ni publicar como producción. Ningún resultado es confirmación oficial ante Previred, DT, AFP o institución bancaria.

## Funciones implementadas

- Interfaz original: login, dashboard, carga drag-and-drop, módulos cotizaciones / F30-1 / independientes, historial, bandeja de revisión y visor del documento.
- FastAPI autenticada con cookies HttpOnly, CSRF, roles, Argon2 y separación de organizaciones.
- Carga privada de PDF / imágenes con límites, inspección de firma PDF y deduplicación SHA256.
- Cola persistente PostgreSQL y worker OCR que registra resultados y errores.
- PyMuPDF para texto seleccionable y páginas mixtas, Tesseract para escaneos con orientación y contraste selectivo.
- RapidOCR opcional (no habilitado por defecto): debe evaluarse con documentos de prueba y RAM adecuada.
- Reglas de evidencia de pago basadas en período, comprobante, estado y folio, en contexto de la misma página; nunca declarar verificación externa.
- Evidencia por página, confianza OCR orientativa, RUT válidos, reportes CSV y reprocesamiento.

## Despliegue aislado en Contabo

En Ubuntu 24.04 con Docker Compose v2 y Git instalados:

    git clone https://github.com/Alvarofritzsolis1/POST.git /opt/galant-post
    cd /opt/galant-post
    sudo bash scripts/install-preview.sh

Antes de fusionar la nueva rama a main, usar:

    git clone -b feat/galant-ocr-enterprise-20261102 https://github.com/Alvarofritzsolis1/POST.git /opt/galant-post

Crear administrador mediante contraseña introducida en el VPS:

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email ADMIN@EMPRESA.CL

En el equipo Windows, abrir PowerShell (NO ejecutar el siguiente comando dentro del VPS):

    ssh -N -L 18512:127.0.0.1:18512 root@89.117.144.140

Entrar por http://127.0.0.1:18512 desde Windows.

Esta modalidad no modifica GALANT anterior, Nginx, DNS, 80/443 ni SSH. Publicación en Internet con HTTPS se decidirá solo después de seguridad y validación. POST utiliza 127.0.0.1:18512 privado.

## Pruebas

En apps/backend, instalar requirements-dev.txt, Tesseract español/inglés y ejecutar pytest -q. En apps/frontend ejecutar npm install y npm run build. GitHub Actions contiene las verificaciones.

## Limitaciones no resueltas

Esta versión inicial NO demuestra superar al OCR antiguo en documentos reales. Faltan parser tabular por institución y trabajador, benchmark de 30+ comprobantes reales autorizados, antivirus documental, políticas de retención, migraciones formales, backup/restore probado, rate limiting distribuido, pruebas de seguridad y HTTPS. El archivo no debe considerarse aprobado en pagos solo por señales OCR.

Consulta docs/ARQUITECTURA.md, docs/OCR_EVALUACION.md y docs/VPS.md.
