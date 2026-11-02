# Evaluación OCR GALANT POST

Prioridad: comprobar evidencia documental del pago previsional, no presumir impago por ilegibilidad ni exigir que cuadren todas las bases numéricas.

Motores:
1. PyMuPDF para extracción nativa, coordenadas y rasterizado cuando corresponda.
2. Tesseract OCR spa+eng con orientación y mejora de contraste solo si aporta valor.
3. RapidOCR + ONNX Runtime como segunda opinión local y opt-in, sujeto a benchmarks de español y pequeños dígitos. El contenedor de prueba no lo instala por defecto para limitar RAM.
4. API Document AI externa: futura, opcional y condicionada a privacidad/costo/consentimiento.

Referencias de implementación:
- https://pymupdf.readthedocs.io/en/latest/page.html
- https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/install/
- https://github.com/tesseract-ocr/tesseract

Evaluar 30 o más documentos reales autorizados sin publicar datos personales en GitHub:
- Previred AFP, Fonasa, Isapre y Seguro Social, trabajadores independientes y F30-1;
- PDF digital, escaneado, girado, borroso, híbrido y multipágina;
- etiquetas manuales: período de remuneraciones, empleador, RUT, folio, estado pago, página y organismo.

Métricas: CER, recall RUT, precisión por período/folio/estado, falsos positivos de pago acreditado, abstenciones, p50 y p95 tiempo, consumo de RAM. No desplegar si hay falsos positivos de pago en corpus de aceptación ni pruebas de backups/seguridad pendientes. Cero fallas en datos observados no garantiza 100% universal. Siempre permitir revisión humana.
