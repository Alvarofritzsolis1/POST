# GALANT POST — v0.3.0

Plataforma GALANT para gestión manual de contratistas y trabajadores, con importación Excel/CSV y un módulo OCR Beta separado. Frontend React + TypeScript, backend FastAPI y PostgreSQL. **No usa Streamlit ni importa código anterior.**

> ESTADO: Versión de evaluación. La etapa 1 permite organizar datos operativos; la matriz documental y los cálculos previsionales aún no están disponibles. Ningún resultado OCR confirma una transacción ante Previred, DT, AFP o una institución bancaria.

## Base operativa (etapa 1)

- Obras Lomas Verdes, Brisas de Junquillar y Concepción, creadas por organización con período inicial septiembre de 2026. Una empresa puede asociarse a varias obras; su código histórico, frecuencia y estado contractual se conservan por obra.
- Fichas editables de contratistas y trabajadores, asignaciones por obra, búsqueda, validación de RUT e historial de modificaciones.
- Importación Excel/CSV con vista previa, corrección de filas, detección de errores y duplicados, confirmación de la interpretación de OK/P/NA, resumen de resultados y plantillas descargables. Los estados históricos conservan origen y quedan pendientes de validación; no equivalen a una aprobación documental.
- FastAPI autenticada con cookies HttpOnly, CSRF, roles, Argon2 y separación de organizaciones.

## Revisión OCR — Beta

- Interfaz de carga, historial, bandeja de revisión y visor. La versión visible se consulta al backend desplegado.
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

## Pendiente

La matriz documental, aprobaciones, comparación de asistencia y cotizaciones, informe CT/CI, dashboard INE y calendario pertenecen a las etapas 2–4. No se ha recibido la planilla Excel histórica para validar el reconocimiento de sus columnas; pruebe primero una copia autorizada en vista previa. El esquema actual permite agregar tablas con `init-db`, pero todavía no dispone de migraciones versionadas. También faltan backup/restore probado, antivirus documental, políticas de retención y HTTPS. Un caso privado de 14 páginas corrigió la orientación OCR, pero no demuestra precisión general de pagos.

Consulta [especificación maestra](docs/ESPECIFICACION_MAESTRA_GALANT.md), [plan por etapas](docs/PLAN_GALANT_OPERATIVO.md), docs/ARQUITECTURA.md, docs/AUDITORIA_0.2.0.md, docs/OCR_EVALUACION.md y docs/VPS.md.
