# GALANT 20.1.0-rc1 · Javiera

Candidata local, sin despliegue al VPS. Cambios sobre React/FastAPI y el maestro OOXML existentes; no requiere nuevas tablas ni otra plataforma de alojamiento.

## Recorrido

1. Entrar por **Contratista nuevo** o **Contratista existente**, con el mismo recorrido para ambas clases de empresa. La relación de los expedientes históricos se conserva al recuperarlos.
2. Seleccionar documentos con tarjetas y casillas. Los diez documentos permanecen visibles: contrato, traslado, prórroga, declaración jurada, reglamento, EPP, IRL, PTS, recepción de PTS e inducción. Hay búsqueda y selección de todos, laborales o prevención.
3. En modo individual, completar los campos requeridos por los documentos elegidos y guardar la ficha. En modo masivo, seleccionar expedientes guardados de la empresa y obra; cada expediente conserva sus propios antecedentes.
4. Generar la selección. Cada resultado indica éxito o la causa del bloqueo; los documentos válidos permanecen disponibles aunque falle otro. Descargar los PDF individualmente o juntos en ZIP.

El lote permite hasta 20 expedientes y 10 documentos por expediente. El ZIP admite hasta 200 PDF y 100 MB sin comprimir, con un manifiesto de versiones y hashes. La emisión conserva las comprobaciones del servidor y la deduplicación existentes. No inventa datos faltantes ni permite emitir formatos sin los requisitos aplicables.

## Excel descargado

Se reprodujo un defecto de serialización: ElementTree elimina declaraciones de espacios de nombres referidas solo en valores de atributos como `mc:Ignorable`. El XML resultante puede conservar `x14ac xr` sin declarar esos prefijos, aunque el ZIP sea válido. Microsoft Excel utiliza estas declaraciones.

- Al escribir partes OOXML modificadas, se conservan los alias originales sin modificar el registro global de namespaces.
- Al descargar o editar una revisión antigua, se recuperan las declaraciones desde su original inmutable. La descarga no sobrescribe el archivo histórico; incluye el hash de los bytes exportados.
- Se conserva el contenido de dibujos y recursos gráficos. Se copia `ZipInfo` al empaquetar, evitando modificar los offsets del ZIP de origen durante su lectura.
- Se rechazan caracteres de control que producirían XML inválido. Las nuevas propiedades de cálculo y alineación respetan el orden de elementos de OOXML.

El Excel original recibido se comprobó por SHA256: `4f063b135d5e9c0d7f9806b57d1cd340bd2ecac78fed77345ffa7ccabbead292`. Tiene 33 hojas, 384 fórmulas y 18 recursos gráficos, de los cuales 17 son EMF. Se verificaron la importación privada, edición y descarga HTTP conservando los gráficos y las declaraciones Microsoft. La copia compatible entregada conserva sus 33 hojas y 384 fórmulas; el maestro de la aplicación añade la hoja de contexto y los vínculos documentales. Falta la apertura manual en Microsoft Excel de Windows.

## Editor web

Mantiene la cuadrícula privada del proyecto y agrega pegado TSV desde Excel/Calc, con saltos de línea y comillas; hasta 500 celdas por pegado. Rechaza el bloque entero si atraviesa fórmulas o celdas combinadas protegidas. Se incorpora al historial como una sola operación de deshacer/rehacer.

Incluye negrita, cursiva, tamaño de letra, fondo y alineación, con previsualización local. El estilo se clona por celda para no cambiar otras celdas. También agrega búsqueda por coordenada, Ctrl/Cmd+S y protección de contenido pendiente en la barra de fórmulas. El guardado sigue creando revisiones y conserva el control de concurrencia.

No se integra ONLYOFFICE ni se presenta la cuadrícula como sustituto completo de Excel: aún no reproduce todos los dibujos, gráficos y funciones de escritorio.

## Revisión adicional de estabilidad

- Las fichas recuperadas comparan solo sus campos editables normalizados, con orden de claves estable. Completar valores opcionales ausentes no crea cambios ficticios. La empresa, obra, trabajador y contratista principal forman parte de esa comparación.
- Los datos personales y beneficios de un trabajador se vacían al elegir otro. Se limpian también los motivos de revisión y reemisión de la ficha anterior.
- Los botones de escritura adquieren un bloqueo antes del primer `await`; durante una operación se avisa antes de recargar y se bloquea el cambio de módulo por la navegación de GALANT.
- El guardado de expedientes actualiza la revisión mediante comparación atómica en la base. Dos conexiones que leen la misma revisión producen un guardado y un HTTP 409; una prueba con conexiones independientes comprueba que no se pierde la revisión ganadora.
- La importación prepara y valida el libro completo antes de activar revisiones. El original y el maestro limpio se guardan en una transacción. Un fallo de la segunda escritura revierte la base y elimina los archivos incompletos, conservando la revisión activa anterior.
- El editor mantiene la cuadrícula al pulsar otra vez el documento activo o volver de versiones. Deshacer actualiza también la barra de contenido. Si falla la lectura de otra hoja, se bloquea la edición y aparece un botón de reintento.
- Un conflicto al guardar Excel conserva los cambios locales y permite descargarlos en JSON antes de descartarlos para abrir la revisión actual. El JSON es una copia de recuperación; no se afirma que exista importación automática de esa copia.
- Se rechazan XML mal formado, partes duplicadas o ausentes, estilos inválidos, números no finitos, textos demasiado extensos y ediciones bajo una celda combinada. Una revisión acumula hasta 500 celdas para que pueda guardarse dentro del límite del servidor.
- En modo masivo, los indicadores se refieren a los expedientes seleccionados. No se muestran como si fueran errores del lote los datos que falten en una ficha individual vacía.

## Validación

| Comprobación | Resultado | Evidencia |
|---|---|---|
| Suite general backend en host | 439 aprobadas, 35 omitidas | `PYTHONPATH=apps/backend .venv/bin/python -m pytest apps/backend/tests -q` |
| Regresión documental con Calc real | 76 aprobadas, ninguna omitida | Contenedor de QA aislado con LibreOffice, código montado en solo lectura; `test_javiera_excel_layout.py`, `test_javiera_workbook.py`, `test_javiera_201.py`, `test_javiera_full_workflow.py` |
| Lógica frontend | 26 aprobadas | `npm run test:logic` |
| TypeScript y compilación Vite | Aprobados | `npm run build`; permanece un aviso de tamaño de bundle, sin errores de compilación |
| Navegador → API → datos → PDF/ZIP | Aprobado | Dos expedientes sintéticos, un documento válido y otro bloqueado por persona; PDF reales dentro del ZIP |
| Editor → API → revisión → XLSX | Aprobado | Pegado, deshacer/rehacer, formato, guardado y reapertura del archivo descargado con openpyxl |
| Fallos y concurrencia | Aprobados | Importación interrumpida sin cambios parciales; dos guardados simultáneos; conflicto HTTP 409 con descarga de cambios locales; error HTTP 503 al abrir hoja seguido de reintento |
| Cambios de contexto | Aprobados | Recuperar una ficha incompleta sin falso aviso de cambios, cambiar trabajador, reabrir documento activo y cambiar de pestaña |
| Pegados y móvil | Aprobados | Rechazo atómico de pegado sobre combinaciones; ancho de 390 px sin desbordamiento global; sin errores JavaScript |

Los recuentos de backend y del contenedor cubren pruebas solapadas y **no deben sumarse como pruebas distintas**. Las 13 pruebas de conversión omitidas en el host sí se ejecutaron con éxito en el contenedor. Persisten otras omisiones por recursos/condiciones de prueba no disponibles. Esta sesión no prueba Microsoft Excel de Windows ni el VPS. El original sí se utilizó para generar los diez tipos documentales con datos sintéticos y el cargo PINTOR, y se verificó la importación/edición/descarga mediante una prueba privada adicional aprobada. No se afirma cobertura completa de todos los cargos.

## Comprobación del Excel recibido

Los diez documentos se generaron con el original y datos de prueba: contrato (2 páginas), traslado (1), prórroga (1), declaración jurada (1), reglamento (1), EPP (1), IRL PINTOR (6), PTS (4), recepción PTS (1) e inducción (11). La inducción conserva 11 imágenes y su papel original, sin recortar encabezados.

Se corrigió el salto de impresión anterior a la fila 468 de la evaluación de inducción. El encabezado original queda completo en la página 11; no se borraron elementos ni se redujo la escala para esconder el defecto. Se comprueba la estructura de ese formulario antes de aplicar el ajuste. EPP reconoce zapatos/botines de seguridad como calzado de seguridad y sigue rechazando tipos ambiguos de guantes.

**Antecedente pendiente del propio archivo:** `MATRIZ IRL`, fila 40, cargo CARPINTERO, tiene vacíos los campos E (riesgo) y F (medida). Su emisión permanece bloqueada hasta completar y revisar esos antecedentes. Los campos no se rellenaron con riesgos o medidas inventados.

El Excel compatible que se entrega mantiene los datos de entrada y las 384 fórmulas del original. No es el maestro vacío de la aplicación ni contiene nombres de las pruebas. Los PDF de QA se generaron por separado con identidades sintéticas y no se incorporan como documentos laborales reales.

## Actualización

Backend, frontend y lockfile se identifican como 20.1.0-rc1. Se conserva el procedimiento del repositorio para respaldar, verificar restauración y desplegar al VPS. No ejecutar reinicios de datos ni importar/reemplazar maestros reales como parte automática de esta corrección. No se modificaron datos de producción.
