# Arquitectura POST

Sistema nuevo sin Streamlit. React/Vite en navegador -> Caddy privado -> FastAPI -> PostgreSQL -> worker OCR independiente -> JSON de extracción privado -> interpretación -> evidencias y resultado estructurado.

Componentes con responsabilidades:
- Interfaz: carga, navegación, informes y visor autenticado. Nunca ejecuta OCR.
- API: credenciales, validación de archivos, control organizacional, publicación de resultado y trazabilidad.
- Worker: archivo original -> diagnóstico por página -> texto nativo/OCR selectivo -> JSON completo por página -> interpretador documental -> base de datos. La reinterpretación verifica SHA-256, versión del motor, configuración e idioma OCR efectivo antes de reutilizar el JSON.
- PostgreSQL: documentos, sesiones representadas por JWT, organizaciones y registros de auditoría.
- Almacenamiento privado: volumen de archivos y JSON OCR no expuesto al proxy. Un endpoint autenticado y limitado por organización permite descargar la extracción de un documento completado.
- Excel: se genera a partir de campos estructurados y controles por página; no exporta texto OCR bruto como resultado validado ni inventa asociaciones entre RUT y trabajadores.
- Infraestructura: Docker Compose en puerto 18512 de loopback del VPS, sin dominio ni servicios antiguos.

Las lecturas de confianza de Tesseract no son probabilidades calibradas de que un pago sea auténtico.

Limites para producción:
- No hay Alembic/migraciones: init-db solamente crea tablas nuevas.
- La revocación central de sesiones, bloqueo distribuido y análisis antimalware están pendientes.
- No hay verificación de transacciones oficiales ante Previred/AFP/DT.
- La detección de tablas y RUT de varios trabajadores en formatos Previred variados aún no está validada.
- No operar con documentos laborales reales hasta evaluar seguridad, control de acceso, retención, backups y HTTPS.
