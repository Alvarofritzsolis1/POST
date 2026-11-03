# Arquitectura POST

Sistema nuevo sin Streamlit. React/Vite en navegador -> Caddy privado -> FastAPI -> PostgreSQL. La gestión manual usa tablas operativas dentro de la misma organización. En paralelo, el worker OCR independiente procesa archivos hacia JSON privado, interpretación, evidencias y resultado estructurado.

Componentes con responsabilidades:
- Interfaz: selector de obra, fichas de contratistas y trabajadores, importación con vista previa, y módulo OCR Beta. Nunca ejecuta OCR en el navegador.
- API: credenciales, control organizacional, CSRF, validación de RUT y de archivos, importación transaccional, publicación de resultados y trazabilidad.
- Modelo operativo: obras y períodos, contratistas globales a una organización, relación contratista-obra con código histórico, frecuencia y estado contractual, trabajadores y asignaciones a obra/contratista. Los cambios se registran en `ops_changes`; las marcas importadas permanecen identificadas como históricas y pendientes de validación.
- Worker: archivo original -> diagnóstico por página -> texto nativo/OCR selectivo -> JSON completo por página -> interpretador documental -> base de datos. La reinterpretación verifica SHA-256, versión del motor, configuración e idioma OCR efectivo antes de reutilizar el JSON.
- PostgreSQL: documentos, organizaciones, registros de auditoría y datos operativos; sesiones representadas por JWT.
- Almacenamiento privado: volumen de archivos y JSON OCR no expuesto al proxy. Un endpoint autenticado y limitado por organización permite descargar la extracción de un documento completado.
- Excel: se genera a partir de campos estructurados y controles por página; no exporta texto OCR bruto como resultado validado ni inventa asociaciones entre RUT y trabajadores.
- Infraestructura: Docker Compose en puerto 18512 de loopback del VPS, sin dominio ni servicios antiguos.

Las lecturas de confianza de Tesseract no son probabilidades calibradas de que un pago sea auténtico.

Límites para producción:
- No hay Alembic/migraciones versionadas: `init-db` crea las tablas operativas nuevas y las obras iniciales sin alterar tablas de OCR. Las futuras modificaciones de columnas requerirán migraciones formales.
- La revocación central de sesiones, bloqueo distribuido y análisis antimalware están pendientes.
- No hay verificación de transacciones oficiales ante Previred/AFP/DT.
- La detección de tablas y RUT de varios trabajadores en formatos Previred variados aún no está validada.
- No operar con documentos laborales reales hasta evaluar seguridad, control de acceso, retención, backups y HTTPS.
