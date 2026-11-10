# GALANT 19.3.0-rc1 — Proyecto Javiera

## Fuente de requisitos
Prompt maestro proporcionado el 10/11/2026: migración de 17 hojas Excel a
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
- El editor global de plantillas mantiene una maqueta HTML ilustrativa.
  El PDF auténtico está disponible al completar el expediente.
- La auditoría histórica encontró 261 fórmulas, 26 PTS (3 completos) y 17 hojas.
  Una especificación posterior menciona 423 fórmulas. No hay paridad
  certificada hasta cotejar el Excel definitivo, hoja por hoja.
- La relación mediante identificadores estables a nivel de riesgo individual,
  las sugerencias de equivalencia de cargo, la aprobación preventiva por
  aplicabilidad y los diez formatos Excel migrados integralmente siguen pendientes.

## Etapas siguientes
1. Validar estructura real de MATRIZ IRL, MATRIZ PTS, Hoja1 y descripciones
   de cargo frente a los archivos fuente autorizados. No derivar contenidos
   preventivos de un Excel de auditoría o fórmulas cacheadas.
2. Crear selector de tareas aplicables basado en identificadores persistidos y
   controles generales obligatorios; exigir aprobación preventiva para exclusiones.
3. Completar los diecisiete apartados de PTS por cargo según encabezados
   originales, conservando borradores de los 23 incompletos.
4. Migrar las diez salidas y fórmulas verificadas, con pruebas de regresión
   en Excel y PDF. No prometer equivalencia total sin pruebas.
5. Prueba visual multi-página A4, firmas, accesibilidad y usuarios no técnicos.

## Despliegue
Rama independiente y PR en borrador. No fusionar ni desplegar en VPS mientras
no concluya CI y no se realicen las validaciones documentales y preventivas.
