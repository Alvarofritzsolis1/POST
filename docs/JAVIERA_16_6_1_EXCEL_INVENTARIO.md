# GALANT 16.6.1-rc1 — auditoría de la plantilla privada de Proyecto JAVIERA

## Evidencia del archivo entregado (9 nov 2026)

Archivo analizado localmente, no publicado en GitHub: `PROYECTO AUTOMATIZACION GESTION CONTRATISTAS FINAL(1).xlsx`.

- 17 hojas en el libro; coinciden las 10 hojas documentales declaradas en `DOC_SHEETS`.
- No se detectan macros VBA ni archivos `xl/externalLinks`.
- Aproximadamente 6,8 MB de archivo comprimido; 61,5 MB descomprimido. La hoja `MATRIZ IRL` presenta más de un millón de celdas y requiere vigilancia de memoria y tiempos de conversión.
- El contenido original de ese archivo contiene datos personales de ejemplo y no se ha subido a este repositorio ni al VPS desde esta revisión.

| Código | Hoja del Excel original |
|---|---|
| labor_contract | Contrato Imprimible |
| transfer_addendum | Anexo Traslado |
| extension_addendum | Anexo extension contrato |
| sworn_declaration | DECLARACION JURADA |
| internal_rules_receipt | REGLAMENTO INTERNO |
| ppe_delivery | Registros Entrega EPP |
| irl | IRL |
| pts | PTS. |
| pts_receipt | ENTREGA PTS |
| induction | INDUCCION PREVENCION |

## Hallazgos técnicos confirmados

1. `REGLAMENTO INTERNO!A4` contiene `TODAY()` y fórmula larga de texto; el valor cacheado puede corresponder a una fecha antigua. En un expediente se debe usar exclusivamente `event.date`.
2. `ENTREGA PTS!A23` y `F23` contienen fórmulas que traen RUT a celdas donde se esperan los nombres de los firmantes. `A24` y `F24` incluyen nacionalidad y estado civil después de la etiqueta «RUT». La corrección aplicada materializa nombre/RUT desde el expediente para ambos firmantes.
3. `REGLAMENTO INTERNO` no presenta en su contenido original un requisito de `extra.regulation_version`; no obligar a ingresarlo artificialmente en la ficha del documento Excel.
4. La versión anterior no diferenciaba suficientemente «nombre de hoja reconocido», «XLSX importado», «aprobado» y «motor PDF disponible». Se añade diagnóstico privado de diez hojas, y advertencia si un borrador Excel pudiera activar por accidente la plantilla textual alternativa.

## Funcionamiento y restricciones

- Usar `Configuración de automatización → Diseños Excel originales` para importar el archivo en el almacenamiento **privado** del servidor. La rama de GitHub **no contiene** las identidades de prueba.
- Las maquetaciones importadas siguen como **borrador**; revisión profesional y aprobación independiente son obligatorias.
- El asistente JAVIERA consume la versión aprobada con `latest_layout`. El nuevo endpoint `GET /api/v1/javiera/v166/templates/status` permite descubrir exactamente qué falta.
- Preparar un PDF no implica que haya ocurrido la firma, entrega de EPP, recepción del reglamento o inducción.
- No crear ni modificar contratistas ni trabajadores de las áreas operativas.

## Verificaciones pendientes antes de producción

1. CI backend / frontend / QA visual / Docker / respaldos.
2. Cargar el Excel privado en un entorno aislado y probar sus 10 PDF con expedientes **sintéticos**.
3. Confirmar que no sobreviven nombres, RUT o fechas de ejemplo; probar ambas firmas y la orientación/márgenes de cada PDF.
4. Examinar especialmente conversión de `MATRIZ IRL` debido al volumen descomprimido.
5. Verificar aprobación preventiva/laboral **real** antes de publicar cada plantilla.
6. Solo después de CI verde, revisión humana y copia de seguridad corresponde integrar `main` y ejecutar despliegue.

Esta tarea modifica el motor de asignación de variables, las pruebas, la presentación de estados y la versión. No acredita por sí sola que el XLSX ya se encuentre importado ni aprobado en el VPS.
