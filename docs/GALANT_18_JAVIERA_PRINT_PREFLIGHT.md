# GALANT 18.0.0-rc1 — Corrección Excel, impresión A4 y preflight documental

## Origen y entrega del Excel corregido

Se usó `GALANT_JAVIERA_10_PLANTILLAS_EDITABLES.xlsx`, copia previamente preparada a partir de los documentos originales proporcionados por el usuario. Se generó fuera del repositorio el archivo `GALANT_JAVIERA_18_10_PLANTILLAS_CORREGIDAS.xlsx` (aproximadamente 408 KB).

Comparación estructural comprobada antes/después:
- 22 hojas conservadas.
- 381 fórmulas conservadas.
- 250 rangos combinados conservados.
- Ajustes acotados de alto de filas, ajuste de texto y alineación en documentos extensos; sin modificar cláusulas jurídicas ni matrices preventivas.
- Las 10 hojas imprimibles conservan su contenido y dependencia de `Datos Contrato`.
- Los valores que parezcan identidades, remuneraciones u otros datos personales no se cargan a GitHub; el Excel se importará exclusivamente por la interfaz privada de GALANT 18.

El Excel corregido puede contener **marcadores de demostración o datos pendientes de completar**: **no es un documento laboral ni preventivo aprobado**.

## Cambios principales en el generador

- `DOCUMENT_PRINT_AREAS` define región de impresión específica por hoja.
- Durante `excel_document` el archivo de salida de una sola hoja recibe área de impresión, A4, márgenes seguros, ancho de una página y tantas páginas de alto como requiera el contenido.
- `normalize_pdf_a4` intenta recuperar desplazamientos leves arriba/izquierda, conservando validación y rechazando desplazamientos exagerados. No se permite recortar datos para ocultar errores.
- Endpoint `GET /api/v1/javiera/v18/print-profiles`: inventario de las diez configuraciones técnicas.
- Endpoint `POST /api/v1/javiera/v18/layouts/{layout_id}/check`: genera vista previa sintética con el motor real de PDF y comprueba fórmulas detectadas, número de páginas y textos fuera del lienzo. **No aprueba ni emite documentos**.
- Biblioteca de GALANT incluye un botón de validación técnica por plantilla. Los estados finales siguen sujetos a revisión profesional de una cuenta distinta al autor.

## Rangos de impresión previstos

| Documento | Hoja Excel | Rango |
|---|---|---|
| Contrato de trabajo | Contrato Imprimible | A1:C36 |
| Anexo traslado | Anexo Traslado | A1:C19 |
| Anexo extensión | Anexo extension contrato | A1:I9 |
| Declaración jurada | DECLARACION JURADA | A1:A16 |
| Recepción Reglamento Interno | REGLAMENTO INTERNO | A1:G12 |
| Entrega EPP | Registros Entrega EPP | A1:E30 |
| IRL | IRL | A1:D178 |
| PTS | PTS. | A1:G190 |
| Entrega PTS | ENTREGA PTS | A1:I24 |
| Inducción Prevención | INDUCCION PREVENCION | A1:D474 |

Se prueban los rangos y no se fuerza una página única: documentos largos deben conservar páginas suficientes.

## Perspectivas de validación independientes

1. **Excel**: inventario de hojas, fórmulas, celdas combinadas y relaciones originales.
2. **PDF e impresión**: geometría A4, texto completo y márgenes.
3. **Laboral**: original preservado, cambios técnicos únicamente; cláusulas requieren revisión humana.
4. **Prevención**: matrices IRL/PTS y constancias requieren responsable autorizado.
5. **Seguridad**: organización, permisos, documentos privados y ninguna modificación operativa.
6. **QA**: tests unitarios, integración y navegador real.
7. **UX**: nueva acción «Validar fórmulas y PDF» antes de enviar a aprobación.

No se afirma que se hayan ejecutado siete agentes externos autónomos. Los puntos son responsabilidades de control cubiertas mediante las pruebas indicadas y revisiones humanas pendientes.

## Limitaciones que deben validarse en el VPS

- Aunque el Excel corregido conserva fórmulas y combinaciones, su importación no garantiza por sí sola que todas las fórmulas estén recalculadas o todas las plantillas aprobadas.
- El servidor puede tener una versión distinta de LibreOffice o fuentes. Hay que probar las diez hojas con el XLSX privado efectivamente importado.
- Un PDF correcto técnicamente no acredita firma, recepción de Reglamento Interno, entrega EPP o capacitación.
- La revisión laboral y preventiva debe examinar cada versión editada.
- Se requieren CI, backup/restauración, navegador, 10 PDF y confirmación de salud del VPS **antes de fusionar o desplegar**.

## Cómo instalar el archivo correcto después de aprobar la versión

1. Descarga la copia Excel 18 desde esta conversación, revísala en Excel y verifica los datos.
2. En GALANT 18 → Proyecto Javiera → Biblioteca inteligente, importa el archivo desde tu computador.
3. Espera la identificación de las 10 hojas y consulta los estados.
4. Utiliza «Validar fórmulas y PDF» para cada documento.
5. Envía las plantillas a revisión profesional y apruébalas con una cuenta autorizada independiente.
6. Solo después utiliza las plantillas publicadas para generar los documentos laborales/preventivos.

## Entrega técnica

- Rama: `feat/galant-18-excel-pdf-preflight-20261109`
- Versión: `18.0.0-rc1`
- Archivo de código: `apps/backend/app/javiera_excel.py`
- API: `apps/backend/app/javiera_v18_api.py`
- UI: `apps/frontend/src/JavieraV17.tsx`
- Tests: `test_javiera_excel_layout.py`, `test_javiera_v18.py`
