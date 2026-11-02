# Evaluación OCR GALANT POST v0.2.0

El objetivo es identificar documentos previsionales y conservar evidencia verificable. Una coincidencia OCR no confirma por sí sola un pago ni la autenticidad de un certificado.

## Reproducción del fallo aportado

Se analizó localmente un PDF privado autorizado de 14 páginas, sin texto digital y con las páginas rasterizadas de lado. El documento original no se incorpora al repositorio ni se transmite a servicios externos. Se usó PyMuPDF, Tesseract 5.5, `tessdata_fast` español/inglés, 180 DPI y el mismo equipo para ambas ejecuciones.

| Medida | Código inicial | v0.2.0 |
| --- | ---: | ---: |
| Tiempo total del primer análisis | 112,52 s | 60,96 s |
| Tipo detectado | desconocido | cotizaciones |
| Período detectado | ninguno | 2026-09 |
| Estado documental | Documento incorrecto | Pendiente de revisión |
| Palabras conservadas en JSON | máximo 150 por página | 4.841 en total |
| Segundo análisis del mismo archivo | repetir OCR | 0,020 s desde caché |

La causa raíz comprobada fue una inversión del giro: el campo `rotate` de Tesseract expresa grados horarios y `Pillow.rotate()` recibe grados antihorarios. Las 14 páginas requerían el mismo giro correctivo. La v0.2.0 conserva 30.019 caracteres de texto y todas las palabras con sus coordenadas; la interfaz solo muestra un extracto. Siete páginas contienen una señal textual de declaración sin pago, por lo que el estado conservador es revisión. La interpretación actual también se abstiene ante filas de trabajadores sin asociación verificada. El benchmark final registró 162,01 s de CPU sumando Python y procesos Tesseract, y un pico de 188 MB del proceso Python sin sumar memoria simultánea de Tesseract. La ejecución inicial usó otro arnés de medición, por lo que no se infiere una variación de RAM o CPU entre versiones. Esta prueba demuestra una corrección de clasificación para este archivo, no precisión universal ni validez oficial de los pagos.

## Motores contrastados

En cuatro páginas del mismo archivo se ejecutó RapidOCR con sus modelos ONNX locales, usando la imagen ya girada. Tardó 5,74, 8,19, 6,98 y 2,54 s para las páginas 1, 4, 8 y 13. La RAM máxima observada en el proceso fue 893 MB. Tesseract tardó 5,03, 13,00, 6,41 y 3,16 s en esas páginas, incluyendo su diagnóstico de orientación y el segundo intento selectivo. Las puntuaciones de confianza de ambos motores no están calibradas entre sí: no se pueden comparar como probabilidades. RapidOCR recuperó más texto aparente en la página 4, pero no hay transcripción corregida que permita afirmar que sea más exacto. Con un límite de 950 MB para el worker, activarlo de forma general tendría poco margen de memoria. Permanece opcional y desactivado.

| Alternativa | Uso posible | Decisión actual |
| --- | --- | --- |
| PyMuPDF + Tesseract | Texto digital, OCR local español/inglés, coordenadas | Motor principal: probado en el caso real y compatible con el worker actual. |
| RapidOCR / PaddleOCR | Detección y reconocimiento ONNX/Paddle, posible segunda lectura de tablas | RapidOCR probado parcialmente; activación pendiente de verdad de referencia y memoria del VPS. PaddleOCR completo aún sin ensayo reproducible. |
| docTR y EasyOCR | Detectores y reconocedores basados en redes neuronales | No medidos en este VPS ni en corpus previsional; su pila de modelos añade RAM y mantenimiento. |
| Surya | OCR y análisis de disposición y tablas | Candidato para ensayos tabulares si el corpus demuestra fallos de estructura y el VPS admite el modelo. |
| OCR con transformadores y modelos multimodales | Lectura de diseños complejos y rescate de regiones ambiguas | Sin prueba de exactitud, coste ni trazabilidad de cada campo; no se incorporan a decisiones automáticas. |
| Azure AI Document Intelligence y Google Document AI | Servicios opcionales de extracción y tablas | No usados: requieren evaluación de privacidad, residencia de datos, consentimiento, conectividad y coste. |

No se calculó CER, exactitud de tablas ni precisión de montos: falta una transcripción de referencia por página, fila y campo. La media de confianza OCR, el número de caracteres y el tiempo no sustituyen esas métricas. El próximo experimento debe reunir al menos 30 comprobantes y F30-1 autorizados, etiquetar período, tipo, estado, RUT, folio, montos y filas, y dividir el corpus por institución y calidad. Cada motor deberá usar el mismo rasterizado, hardware, presupuesto de tiempo y criterios de abstención. Se medirán CER, precisión y recobrado por campo, falsos positivos de pago, p50/p95 de latencia y RAM/CPU del proceso completo.

Para reproducir las métricas sin publicar contenido: `python scripts/benchmark_ocr.py --file /ruta/autorizada/documento.pdf --declared cotizaciones`. El comando solo imprime métricas y elimina su copia temporal con la extracción JSON al finalizar. Para un caso sintético, omitir `--file`.

Referencias de implementación: [PyMuPDF](https://pymupdf.readthedocs.io/), [Tesseract](https://github.com/tesseract-ocr/tesseract), [RapidOCR](https://github.com/RapidAI/RapidOCR), [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [docTR](https://github.com/mindee/doctr), [Surya](https://github.com/datalab-to/surya), [EasyOCR](https://github.com/JaidedAI/EasyOCR).
