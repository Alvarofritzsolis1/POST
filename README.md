# GALANT POST — v0.2.0

Software documental chileno construido de cero en el repositorio POST. Frontend React + TypeScript, backend FastAPI y PostgreSQL, OCR nativo y escaneado con Tesseract. **No usa Streamlit ni importa código anterior.**

> ESTADO: Versión local de evaluación. No desplegar como producción sin validar seguridad, datos y reversión. Ningún resultado confirma una transacción ante Previred, DT, AFP o una institución bancaria.

## Funciones implementadas

- Interfaz: login, dashboard, carga, módulos cotizaciones y F30-1, historial, bandeja de revisión y visor del documento. La versión visible se consulta al backend desplegado.
- FastAPI autenticada con cookies HttpOnly, CSRF, roles, Argon2 y separación de organizaciones.
- Carga privada de PDF / imágenes con límites, inspección de firma PDF y deduplicación SHA256.
- Cola persistente PostgreSQL y worker OCR que registra resultados y errores.
- PyMuPDF para texto seleccionable y páginas mixtas, Tesseract para escaneos con orientación corregida y contraste selectivo.
- Extracción completa por página en JSON privado con coordenadas, líneas identificables y diagnóstico. La reinterpretación reutiliza el JSON si no cambiaron el archivo, el motor y el idioma disponible.
- RapidOCR opcional, desactivado por defecto por su consumo de memoria observado.
- Reglas de evidencia de pago basadas en período, comprobante, estado y folio, en contexto de la misma página; nunca declarar verificación externa.
- Evidencia por página, confianza OCR orientativa, RUT válidos, exportación Excel de campos interpretados y reinterpretación sin repetir OCR.

## Despliegue aislado en Contabo

En Ubuntu 24.04 con Docker Compose v2 y Git instalados:

    git clone https://github.com/Alvarofritzsolis1/POST.git /opt/galant-post
    cd /opt/galant-post
    sudo bash scripts/install-preview.sh

Crear administrador mediante contraseña introducida en el VPS:

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email ADMIN@EMPRESA.CL

En el equipo Windows, abrir PowerShell (NO ejecutar el siguiente comando dentro del VPS):

    ssh -N -L 18512:127.0.0.1:18512 root@89.117.144.140

Entrar por http://127.0.0.1:18512 desde Windows.

Esta modalidad no modifica GALANT anterior, Nginx, DNS, 80/443 ni SSH. Publicación en Internet con HTTPS se decidirá solo después de seguridad y validación. POST utiliza 127.0.0.1:18512 privado.

## Pruebas

En apps/backend, instalar requirements-dev.txt, Tesseract español/inglés y ejecutar pytest -q. En apps/frontend ejecutar npm ci y npm run build. Para comparar OCR inicial y reinterpretación, ejecutar `python scripts/benchmark_ocr.py` o añadir `--file` con una ruta autorizada. El benchmark copia el documento a un directorio temporal privado y solo imprime métricas. GitHub Actions contiene verificaciones semanales una vez que el flujo esté en la rama principal.

## Limitaciones no resueltas

Un caso privado de 14 páginas reproduce y confirma la corrección de la orientación, pero no constituye una medición general de precisión. Faltan transcripciones de referencia, parser tabular por institución y trabajador, corpus amplio autorizado, antivirus documental, políticas de retención, migraciones formales, backup/restore probado, rate limiting distribuido, pruebas de seguridad y HTTPS. El archivo no debe considerarse aprobado en pagos solo por señales OCR.

Consulta docs/ARQUITECTURA.md, docs/AUDITORIA_0.2.0.md, docs/OCR_EVALUACION.md, docs/CAMBIOS_0.2.0.md, docs/PLAN_PRUEBAS_12_MESES.md y docs/VPS.md.
