# GALANT 16.5.0-rc1 · JAVIERA — Diagnóstico y rediseño centrado en el Excel

**Estado:** cambio de implementación en PR #42 (borrador), sin instalación en VPS. No se aprueba producción ni validez legal sin evidencia.

## Problemas reales detectados en la versión anterior
La captura del usuario mostraba los diez documentos al lado de un formulario universal extenso. Pedía sueldo, vigencia contractual y datos bancarios incluso al preparar IRL/PTS/EPP/inducción. Para empresas nuevas obligaba a seleccionar entidades de GALANT y crear trabajador en pasos separados; la lista era extensa, los campos adicionales se veían como `representative_name` y no había una acción evidente de «Imprimir».

## Fuente de verdad: Excel corregido
Se revisó `JAVIERA_ETAPA_1_PTS_CORREGIDOS.xlsx` en el entorno privado. Su hoja `Datos Contrato` contiene:
- Empresa / empleador (C5:C14): razón social, RUT, representante y RUT, teléfono, domicilio, comuna, ciudad, correo y rubro.
- Trabajador (C17:C26): nombre, RUT, nacionalidad, nacimiento, estado civil, domicilio, comuna, ciudad, correo y teléfono.
- Parámetros (C29:C40): labor, ubicación de faena, jornada, sueldo, sueldo en palabras, frecuencia de pago, cuenta bancaria, inicio, término, AFP, previsión de salud y fecha de firma.
- Traslado / declaraciones (C43:C45): destinos, locomoción y mes de referencia.
- Dependencia documental: cargo/rubro canónico para los PTS (17 secciones), IRL por cargo y recepción, sin mezclar empresas.

**Los valores de nombre, RUT, sueldo y otros que venían escritos en la plantilla son ejemplos; nunca se heredan de otra empresa o trabajador.** El origen de datos se prioriza así: registro existente de GALANT; historial del mismo empleador/obra/trabajador; dato ingresado por la persona; solo después formatos genéricos sin datos personales.

## Nuevo recorrido de usuario
1. Seleccionar **Contratistas** o **Subcontratos**.
2. Seleccionar **Prevención de Riesgos** o **Zona Subcontratos**.
3. Elegir el documento (4 laborales + 6 preventivos), antes de rellenar.
4. Obra; **Empresa nueva** (nombre/RUT escrito ahí) o **Ya existe en GALANT** (selección de registro). Para Subcontratos se pide la principal, sin reemplazar al empleador directo.
5. Trabajador nuevo o existente, únicamente si corresponde; **declaración de ausencia de trabajadores** es de la empresa, no del individuo.
6. Introducir una sola «Labor / especialidad»: equivalencias explícitas Pintura/Pintor, Carpintería/Carpintero, Gasfitería/Gasfiter y otras. Si no hay equivalencia real, no se asigna preventivamente un cargo por similitud.
7. El asistente muestra solo campos relevantes del documento. IRL/PTS no muestra sueldo, jornada, cuenta bancaria ni fechas de término. Los contratos sí muestran el vínculo laboral dependiente/independiente.
8. La lista de documentos muestra avance de antecedentes sin duplicar llamadas; el documento seleccionado muestra validación real, faltantes con acciones para enfocar el campo y botones **Guardar ficha · Vista previa · Imprimir PDF · Descargar PDF**.
9. Si la plantilla Excel es un borrador, un administrador puede **Ver borrador Excel** con marca de agua; emitir requiere documento y matrices aprobadas.

## Revisión por cinco perspectivas (revisión interna, no herramientas Claude)
| Perspectiva | Defecto de v16 identificado | Corrección / verificación en v16.5 |
|---|---|---|
| UX y accesibilidad | Formulario universal; etiquetas técnicas; no se entiende qué imprimir | Flujo por documento, etiquetas iguales a la hoja Excel, botones directos, diseño adaptable, QA Chromium |
| Datos y backend | Validación de sueldo/contrato bloqueaba prevención; alta dependía de registros previos | Validación solo por campos del documento, creación desde JAVIERA usando API de GALANT y recuperaciones de igual organización/obra |
| Especialidad y matrices | «PINTURA» no coincidía con PTS «PINTOR» | Equivalencias explícitas y catálogo de matrices; nunca emparejamiento difuso |
| Seguridad documental | Cambiar empresa/trabajador podía dejar campos de otra entidad | Limpieza al cambiar contexto, control parent-id misma obra, historial segregado y aprobación obligatoria |
| QA y despliegue | Pruebas antiguas no comprobaban el recorrido de usuario ni aceptaban versión 16.5 | Prueba Chromium empresa+trabajador nuevos, los 2 grupos, campos independientes, impresión bloqueada sin aprobación y móvil; pruebas backend de validaciones y cargos |

## Lo que NO se considera finalizado
- La corrección gráfica no equivale a que los 10 PDF reales hayan sido aprobados jurídicamente o por prevención.
- El libro privado debe importarse a cada organización, compararse visualmente y sus borradores deben pasar revisión de un segundo administrador habilitado.
- La vista previa de un borrador NO permite usarlo como firma, entrega EPP ni inducción realizada.
- La edición completa WYSIWYG y la ejecución exhaustiva de los 70 criterios del prompt V3 permanecen separadas de esta revisión de usabilidad.
- La versión 16.5.0-rc1 no se fusiona ni despliega en producción hasta tener CI verde y aprobación del usuario.

## Invariantes verificables
- Elegibilidad de IRL/PTS sin campos de contrato, con RUT/cargo válidos y matriz aprobada.
- Ninguna emisión por plantilla o matriz pendiente.
- No se registra automáticamente entrega, firma ni inducción.
- Contratista principal distinto del empleador directo y vinculado a la misma obra.
- Corrección de un documento no cambia los PDF emitidos antes.
- No se incluyen nombres/RUT/sueldos reales del Excel dentro de GitHub.
