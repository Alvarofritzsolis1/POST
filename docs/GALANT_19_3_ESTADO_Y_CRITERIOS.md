# GALANT 19.3.0-rc1 — Proyecto Javiera

## Fuente de requisitos
Prompt maestro proporcionado el 10/11/2026: migración del Excel a
HTML, automatización de diez formatos, IRL/PTS, fórmulas y PDF A4 real.
Esta rama implementa **la primera etapa funcional**. No certifica la
equivalencia completa con el Excel fuente ni la migración íntegra.

## Etapa 1 implementada
- Consulta de cargos a partir de matrices de la organización y sus revisiones aprobadas.
- Lectura estructurada de tareas IRL, peligros, riesgos y medidas preventivas.
- Selector de cargo y tabla de riesgos en el formulario documental.
- Labor nueva conservada como borrador sin inventar un riesgo; bloqueo de vista
  previa IRL/PTS y emisión heredada mientras tenga revisión preventiva pendiente.
- Tabla IRL HTML/PDF con cuatro columnas técnicas, preservando textos no
  estructurados de revisiones antiguas en una celda completa.
- Visor integrado del **PDF generado por el backend**, con apertura del mismo
  archivo para imprimir. Si cambian los datos, se descarta la vista previa anterior.
- Pruebas automáticas con matriz sintética, impresión PDF, permisos y aislamiento.

## Limitaciones explícitas
- Las marcas de labores muestran qué filas revisó el usuario; el PDF sigue
  incluyendo todos los riesgos de la matriz aprobada. No se omiten controles
  sin un proceso documentado de validación de aplicabilidad.
- Las bibliotecas PERFILES, PUESTOS y SUSTANCIAS se consultan, pero la asociación
  detallada de sustancias a tareas y la generación automática de texto de
  otros documentos aún no están completas.
- El editor global mantiene una maqueta ilustrativa solo como alternativa,
  y permite mostrar el PDF real de un expediente con diseño habilitado.
- El archivo corregido verificado contiene **21 hojas, 324 fórmulas y 26 PTS
  completos**; no confundirlo con una auditoría histórica (261 fórmulas, 3 PTS
  completos) ni con una especificación anterior (423 fórmulas).
  Los cálculos todavía NO tienen equivalencia certificada.
- La relación mediante identificadores estables a nivel de riesgo individual,
  las sugerencias de equivalencia de cargo, la aprobación preventiva por
  aplicabilidad y los diez formatos Excel migrados integralmente siguen pendientes.

## Etapas siguientes
1. Contrastar con el archivo FINAL.xlsx y verificar los cálculos hoja por hoja.
   Las matrices del archivo corregido se han analizado, pero falta validar
   la equivalencia de todas las fórmulas y la vigencia preventiva.
2. Crear selector de tareas aplicables basado en identificadores persistidos y
   controles generales obligatorios; exigir aprobación preventiva para exclusiones.
3. Conservar los diecisiete encabezados PTS originales D:T e incorporar
   una edición segura de sus contenidos, con revisión profesional por cargo.
4. Migrar las diez salidas y fórmulas verificadas, con pruebas de regresión
   en Excel y PDF. No prometer equivalencia total sin pruebas.
5. Prueba visual multi-página A4, firmas, accesibilidad y usuarios no técnicos.

## Despliegue
Rama independiente y PR en borrador. No fusionar ni desplegar en VPS mientras
no concluya CI y no se realicen las validaciones documentales y preventivas.

## Revisión directa del archivo corregido (10-11-2026)
Fuente accesible: `JAVIERA_ETAPA_1_PTS_CORREGIDOS.xlsx`, SHA-256
`2a6657a0f6c7d78731565ecbb59485542343629903aaf161aacfbea405da5edd`.
**El XLSX con datos no se agrega a GitHub.** Solo se incluyen nombres de
hojas, estructura, encabezados y resultados agregados.

- 21 hojas; la especificación inicial refería 17. Las cuatro hojas adicionales:
  `NUMEROS A LETRAS`, `CONTROL ETAPA 1`, `CAMBIOS ETAPA 1`, `FUENTES PTS`.
- `MATRIZ IRL`: 338 registros, 337 con tarea/peligro/riesgo/medida completos.
  **Fila 40, cargo CARPINTERO: riesgo y medida preventiva faltantes**.
  La importación conserva el contenido pero no debe aprobarse ese registro
  ni emitirse un IRL nuevo de ese cargo hasta su regularización.
- `MATRIZ PTS`: 26 cargos, los 26 con los 17 campos D:T completos en esta
  versión del Excel. Encabezados originales preservados en
  `javiera_pts_headers.PTS_TECHNICAL_HEADINGS`.
- `MATRIZ DESCRIPCION DE CARGO IRL`: 26 perfiles.
- `Base_Datos_Sustancias`: 27 registros de especialidad/labor.
- Fórmulas inventariadas en este archivo: **324**, sin ejecución ni prueba
  de equivalencia con el backend. Distribución: Datos Contrato 8,
  Contrato Imprimible 13, Anexo Traslado 6, Anexo extension contrato 6,
  INDUCCION PREVENCION 42, IRL 74, PTS. 40, ENTREGA PTS 6,
  Registros Entrega EPP 7, REGLAMENTO INTERNO 1, MATRIZ PTS 42,
  DECLARACION JURADA 4, MATRIZ IRL 1,
  MATRIZ DESCRIPCION DE CARGO IRL 23, NUMEROS A LETRAS 23,
  CONTROL ETAPA 1 28.

La compatibilidad con el archivo original denominado
`PROYECTO AUTOMATIZACION GESTION CONTRATISTAS FINAL.xlsx` no está
certificada. Este hallazgo corresponde únicamente al archivo corregido
identificado por su checksum, no a todas las versiones anteriores.
