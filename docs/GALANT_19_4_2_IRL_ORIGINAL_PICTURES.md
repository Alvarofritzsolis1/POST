# GALANT 19.4.2-rc1 — IRL original con fotografías automáticas

## Error real de la 19.4.1

El editor anterior mostraba una **tabla genérica de cinco columnas** con números de
registro en lugar de las **cuatro columnas** de la hoja original de Excel. La
vista estructural no incluía las fotografías de reglamentos generales, ni
la descripción, condiciones ni sustancias en su orden documental.

## Flujo nuevo

1. Ingresar a **Proyecto Javiera → Documentos → IRL**.
2. Si la plantilla original **no está importada** en la organización, la vista
   muestra un control **Seleccionar Excel original (.xlsx)**. Este archivo se
   guarda **únicamente en el almacenamiento privado de la organización** mediante
   el importador de formatos ya existente. No se sube a GitHub ni a servicios de IA.
3. GALANT extrae las imágenes **desde la propia hoja IRL** siguiendo las
   referencias OOXML. Conserva sus píxeles, orden y anclaje. No se pide subir
   manualmente las cinco imágenes.
4. El editor muestra cabecera original, perfil y condiciones del cargo,
   tabla de cuatro columnas, 12 campos de sustancias/HDS, cinco imágenes,
   obligaciones, declaración y firma.
5. Al elaborar la **vista PDF nativa desde un expediente**, se vinculan empresa,
   obra, trabajador, RUT, fecha y cargo, con matrices **aprobadas** de la misma
   organización. No se copian datos de identidad de la hoja de ejemplo.
6. Si el Excel original está importado, la ruta de PDF utiliza
   **LibreOffice a partir del propio XLSX conservado**, no `fitz.Story`.
   Esto respeta las imágenes, encabezados, bordes y saltos del documento fuente
   y evita pérdidas de texto observadas en la conversión HTML → PDF.
7. Las vistas HTML son editables y orientativas; la impresión conserva el
   documento original. Los demás PDF mantienen sus motores actuales.

## Seguridad y criterios de revisión

- Cada consulta requiere rol administrador y la organización propietaria del
  Excel. El documento no modifica trabajadores, contratistas ni asistencia.
- Los perfiles y las sustancias no se rellenan utilizando datos de otro cargo.
  Matrices aprobadas y versiones históricas permanecen intactas.
- Se impiden imágenes externas, referencias no válidas y cargas excesivas.
- No se permite convertir una imagen de normas generales en texto editable
  por suposición: **las imágenes se preservan idénticas, no se transcriben**.
  Una futura migración textual requerirá cotejo humano con la fuente.
- **Todavía no se acredita paridad píxel a píxel ni equivalencia de las
  74 fórmulas originales.** El objetivo de fidelidad completa requiere
  revisión preventiva, pruebas de los 25 cargos y cotejo de páginas.
- Esta versión sigue en PR borrador. No fusionar o desplegar hasta revisarla.

## Pruebas técnicas

- Extracción OOXML de cinco imágenes, orden y procedencia.
- Ausencia de datos del trabajador de ejemplo en la API de imágenes.
- PDF A4 desde XLSX privado, con cinco PNG embebidos, contenido por cargo y ninguna identidad de ejemplo.
- Declaración, nombre y RUT del trabajador en el **mismo folio**.
- Pruebas de regresión de backend, frontend, 10 formatos, navegador y respaldo.
- CI: ver ejecución y resultados del PR #57.

## Verificación antes de declarar el IRL idéntico

- Comparar visualmente, hoja por hoja, tamaños y bordes con el Excel privado.
- Comprobar texto fijo completo, encabezados repetidos y los cinco bloques.
- Confirmar que 25 cargos presentan sus riesgos/condiciones/sustancias correctas,
  incluidas excepciones sin sustancias, y que no se usan las 12/13 filas erróneas.
- Revisión profesional de perfiles, contenidos preventivos y HDS.
- Probar las fórmulas del IRL, una a una, frente al Excel de referencia.
