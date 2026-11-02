# Programa de pruebas: noviembre de 2026 a octubre de 2027

La acción `GALANT POST - CI` ejecuta pruebas de backend (incluida deduplicación concurrente con PostgreSQL), frontend y configuración Compose cada lunes a las 09:00 UTC, además de cada push y PR, una vez que esta versión llegue a la rama principal de GitHub. Esa programación es una infraestructura de seguimiento; no equivale a haber completado un año de pruebas. Los documentos reales autorizados permanecen fuera de GitHub y no se incorporan a Actions sin un almacenamiento privado y controles de acceso aprobados.

| Meses | Trabajo y criterio verificable |
| --- | --- |
| 1–2 | Etiquetar un corpus privado de al menos 30 documentos de cotizaciones y F30-1, con PDF digital, escaneado, girado, borroso y mixto. Medir CER, período, folio, estado, RUT, filas, p50/p95 de tiempo y RAM/CPU. Fijar umbrales de aceptación desde esa línea base. |
| 3–4 | Incorporar regresiones de cada fallo reproducido y comparar Tesseract, RapidOCR y un candidato de tablas sobre el mismo corpus. Activar segundo motor solo para regiones donde mejore la métrica de campo sin superar el presupuesto del VPS. |
| 5–6 | Probar carga concurrente, límites de recursos, recuperación de workers, caché dañada, archivos duplicados y restauración de backup. Registrar tiempos y errores por lote. |
| 7–8 | Revisar seguridad, aislamiento por organización, retención y eliminación de archivos y JSON, manejo de fórmulas en Excel y acceso al visor. Repetir pruebas de backup y restauración. |
| 9–10 | Ensayar formatos nuevos por institución, precisión de tablas y asociación empresa/trabajador; revisar falsos positivos y abstenciones con evaluadores humanos. |
| 11–12 | Congelar corpus de aceptación, ejecutar regresión completa en el VPS de prueba y publicar informe con comparación respecto a meses 1–2. Decidir promoción o nueva iteración según resultados y reversión ensayada. |

El caso privado inicial de 14 páginas fija una referencia puntual: 60,96 s de OCR en este entorno y 0,020 s de reinterpretación desde JSON. No sirve para extrapolar p95 ni CER. Hasta contar con etiquetas, el control de pago se mantiene conservador y la meta de cero falsos positivos se evalúa solo sobre ejemplos cuya verdad haya sido verificada. Cada informe mensual debe registrar versión, commit, corpus y permisos, hardware, idioma OCR, métricas por documento, fallos nuevos, regresiones y decisión tomada.
