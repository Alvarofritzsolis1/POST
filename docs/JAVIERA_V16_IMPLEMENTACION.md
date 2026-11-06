# GALANT 16.0.1-rc1 — JAVIERA: conservación de documentos y validación por especialistas

**Estado: implementación en rama de desarrollo, PR #40 en borrador. NO desplegada ni aprobada para producción.**

## 1. Origen

- Repositorio real GALANT React/FastAPI/PostgreSQL: \`Alvarofritzsolis1/POST\`.
- Rama: \`feat/galant-v16-proyecto-javiera-20261106\`.
- Base instalada antes de v16: \`15.0.5-rc1\`.
- Especificación funcional: Proyecto JAVIERA V3.
- Entradas: Contratistas y Subcontratos; áreas documentales: Zona Subcontratos y Prevención de Riesgos.
- Ruta del módulo: \`/proyecto-javiera\`. Ruta del panel: \`/configuracion/automatizacion\`.

## 2. Documentos originales

El módulo reconoce los **10 documentos individuales** del Excel corregido:

| Documento GALANT | Hoja original XLSX | Revisión |
|---|---|---|
| Contrato de trabajo | Contrato Imprimible | Laboral |
| Anexo de traslado | Anexo Traslado | Laboral |
| Declaración jurada | DECLARACION JURADA | Laboral |
| Prórroga contrato | Anexo extension contrato | Laboral |
| Recepción reglamento interno | REGLAMENTO INTERNO | Prevención |
| Entrega EPP | Registros Entrega EPP | Prevención |
| IRL | IRL | Prevención |
| PTS | PTS. | Prevención |
| Recepción PTS | ENTREGA PTS | Prevención |
| Inducción | INDUCCION PREVENCION | Prevención |

Las matrices técnicas PTS, IRL, perfiles y sustancias se importan de las hojas correspondientes, como **borradores privados** que deben revisarse.

### Fidelidad de diseño (no equivalencia píxel por píxel garantizada)

- \`javiera_excel.py\` preserva el OOXML original de la hoja: estilos, imágenes/media, rellenos, bordes, celdas combinadas y rangos/ajustes de impresión.
- Se genera **un libro temporal con una sola hoja imprimible** para evitar que LibreOffice exporte accidentalmente todas las demás hojas.
- Se eliminan fórmulas dinámicas de la hoja final de impresión, sustituyéndolas por valores del expediente. Las variables de texto personal, cargo y fecha se procesan antes del PDF. El libro original permanece privado e intacto.
- \`libreoffice-calc\` convierte a PDF en carpeta temporal; \`PyMuPDF\` valida el resultado, páginas y vista previa.
- El contenido final no debe contener valores personales del ejemplo del XLSX: \`source_leaks\` bloquea la emisión al encontrar coincidencias detectables con el origen.
- Conservación no significa perfección universal. Fuentes del sistema, imágenes WMF/VML y ajustes propios de Excel pueden renderizar distinto en LibreOffice. Se requiere comparación visual de las 10 piezas.

### Correcciones específicas sobre el Excel base

1. Anexo de extensión: la nueva fecha se obtiene del expediente, debe ser posterior al término previo, y se inserta en el bloque y en la celda de control de la prórroga.
2. Declaración jurada: no permite un trabajador asignado; exige período, representante, domicilio, empresa mandante **real** y declaración explícita del responsable. Evita el nombre de empresa mandante fijo en el ejemplo original.
3. EPP: las cantidades pre-llenadas en las ocho filas se limpian; solo se imprimen elementos cuya entrega se registró expresamente. Elementos ambiguos no se aceptan.
4. PTS: se inyectan las 17 secciones de la matriz aprobada correspondiente al cargo; no copia un procedimiento de otro cargo.
5. IRL: utiliza matriz de riesgo del cargo y contenido aprobado de puestos/perfiles/sustancias cuando exista.
6. RUT y fechas: las fechas de ingreso/emisión/prórroga y datos del empleador y trabajador se obtienen del expediente; se bloquean RUT inválidos y fechas contradictorias.
7. Jornada: se incluye control del máximo semanal ordinario general vigente a noviembre de 2026, sin sustituir el juicio sobre regímenes y excepciones aplicables.

## 3. Configuración de automatización

Desde el encabezado de GALANT, perfil administrador:

- **Plantillas y cláusulas:** editar texto completo, variables, campos, condicionales declarativos, encabezado, pie, márgenes, tipografía básica.
- **Matrices PTS/IRL:** importar el Excel, revisar cada sección y registrar versiones. No se publica automáticamente.
- **Diseños Excel originales:** subir XLSX corregido privado, elegir documento, revisar las celdas por página, corregir textos y copiar un estilo preexistente, ajustar altura de fila, visualizar PDF y guardar como nueva versión.
- **Revisiones y aprobaciones:** seleccionar documento y especialidad, completar lista de verificación y acta, publicar solo si existe designación vigente y revisor diferente del autor.

Una corrección posterior crea versión nueva; PDF emitidos anteriormente no se sobrescriben.

## 4. Validación humana laboral y preventiva

\`javiera_review.py\` añade:

- Designación de revisor por organización y especialidad (laboral o prevención), registrada por **otro administrador**.
- Evaluación con lista de verificación (identidad/empleador, cláusulas, remuneraciones, jornada, períodos, etc. en laboral; riesgos/controles, puesto, sustancias, EPP, información y procedimientos en prevención).
- Acta con resultado aprobado/observado, datos del revisor, comentarios sustantivos y referencia normativa.
- La aprobación requiere que **todos** los controles estén marcados conformes y un comentario fundamentado; una persona no puede revisar su propio borrador.
- Publicación de revisiones de plantillas estructuradas, PTS/IRL y maquetaciones XLSX bloqueada por API sin acta aprobatoria de la especialidad correspondiente.
- La aplicación registra la revisión; **no certifica** que los documentos cumplan realmente la ley. Esa determinación corresponde al responsable jurídico/laboral o de prevención acreditado que revise los originales y el trabajo real.

Referencias que deberá revisar el profesional: Código del Trabajo chileno, arts. 9 y 10; D.S. 44 sobre gestión preventiva y obligaciones de información.

## 5. Flujo correcto para probar (sin tocar producción)

1. Verificar en PR #40 todas las pruebas de GitHub Actions: backend, frontend, compilación, Docker, backup/restore aislado y smoke QA.
2. En copia aislada del VPS, hacer respaldo consistente de PostgreSQL y directorio privado \`/data/private\`, y verificar restauración.
3. Aplicar migraciones aditivas \`16.0.0\` y \`16.0.1_excel_pdf_reviews\` mediante CLI ya existente.
4. Entrar con administrador a **Configuración de automatización → Diseños Excel originales** y cargar \`JAVIERA_ETAPA_1_PTS_CORREGIDOS.xlsx\` desde el ordenador (NO adjuntarlo a GitHub).
5. Importar también las matrices PTS e IRL desde **Matrices PTS / IRL**. Los responsables deben revisar calidad técnica/cargo y aprobar las versiones.
6. Revisar una a una las diez hojas y generar sus diez **vistas previas** con datos sintéticos; comprobar texto, saltos de página, logos, tablas, campos variables, ausencia de datos de ejemplo y firma en blanco. Corregir desde editor si es necesario.
7. Designar formalmente revisores laboral y prevención; esos revisores deberán comprobar sustantivamente contenido y riesgos reales, registrar actas e indicar cambios. Solo entonces publicar.
8. Crear expedientes con datos **sintéticos** de empresa/trabajador y comprobar los cuatro escenarios (nuevo/existente), 10 PDFs, históricos, restricciones y no emisión con faltantes.
9. Recién después de todo ello, considerar la aprobación de PR, un respaldo/restauración completo de producción y el despliegue seguro por workflow.

## 6. Pruebas automatizadas

- \`apps/backend/tests/test_javiera_v16.py\`: 10 tipos, elegibilidad, RUT, cargo, PTS/IRL y vista previa PDF, no confundir generación con entrega o firma.
- \`apps/backend/tests/test_javiera_excel_layout.py\`: generación de un Excel sintético con 10 hojas, estilos/bordes, combinación y área de impresión, sustitución de identidades, 17 secciones PTS, impresión PDF Calc real, fecha de prórroga, declaración jurada, EPP sin marcación ficticia.
- \`.github/workflows/ci.yml\`: instala LibreOffice en CI para no omitir silenciosamente prueba real de conversión.
- Nuevas migraciones aditivas y pruebas históricas de PostgreSQL para garantizar que no se destruye información previa.

**No equivale aún a la ejecución de los 70 criterios de aceptación del prompt V3**, ni constituye revisión técnica/legal humana de las plantillas reales. La validación de la maquetación real requiere ensayar **las diez vistas previas del Excel proporcionado** en entorno privado.

## 7. Límites importantes

- El editor visual permite editar celdas y copiar formatos existentes, pero no es Excel ni un editor de imágenes/celdas combinadas de amplitud ilimitada. Para cambiar logotipo, dibujos o estructura compleja, el administrador puede modificar su XLSX de origen e importarlo como nueva versión.
- El documento **no se firma** automáticamente. Firmas, recepción de PTS, EPP y asistencia real a inducción deben tener evidencias verificables. Un PDF emitido es un documento sin firma hasta que ésta exista.
- Las plantillas originales dependen de la funcionalidad de impresión de LibreOffice; debe verificarse la equivalencia razonable con el Excel en cada documento.
- Datos personales se mantienen en servidor privado; no se suben al repositorio público.
- La versión de JAVIERA es actualmente **solo para administradores**, preservando el acceso restringido de los residentes y administrativos de GALANT.

## 8. VPS y liberación

**NO ejecutar los comandos de despliegue en producción en esta etapa.** Este PR permanece en borrador y \`main\` conserva la versión productiva anterior. El procedimiento de actualización y rollback está documentado en:

- \`docs/INSTALACION_VPS_CADA_VERSION.md\`
- \`docs/DESPLIEGUE_VPS_UN_CLIC.md\`
- \`docs/ACTUALIZACION_SEGURA_VPS.md\`

Cuando las pruebas y revisiones estén completas, publicar una versión estable y seguir el flujo de despliegue seguro con comprobación de salud y respaldo.
