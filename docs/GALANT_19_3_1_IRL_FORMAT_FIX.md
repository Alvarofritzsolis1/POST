# GALANT 19.3.1 — Corrección de hoja IRL vacía

## Incidencia reproducida
Al seleccionar «INFORMACIÓN DE RIESGOS LABORALES (IRL)» en el
Editor visual, la hoja aparecía blanca. El endpoint
`/api/v1/javiera/v19/editor/irl` entrega solo el fragmento HTML
complementario. Si el fragmento es inexistente, retorna `html=""`,
aunque los apartados fijos y la tabla de riesgos IRL están definidos
en `javiera_native_templates/base.html` y `irl.html`.

**No era correcto presentar el fragmento HTML vacío como el formato entero.**
El backend continúa generando el PDF IRL desde la plantilla fija y
una matriz aprobada para el cargo de un expediente.

## Solución implementada
- El menú IRL ahora presenta por defecto una hoja de referencia con
  cabecera, identificación empresa/trabajador/obra/cargo, cuadro de
  riesgos reales y espacios de firma.
- Se consultan los cargos y riesgos aprobados mediante la API de
  GALANT 19.3, siempre filtrada por organización y permisos de admin.
- Las filas sin campos técnicos completos se señalan; la vista
  no inventa riesgos ni crea matrices.
- Botón directo a «Matrices y cargos» para editar los riesgos mediante
  revisión versionada y control preventivo.
- El editor HTML complementario sigue disponible, pero aparece solo
  al pulsar «Editar texto complementario del IRL (opcional)».
- La maqueta HTML vacía deja de presentarse como PDF del IRL; el PDF
  A4 auténtico se muestra al seleccionar un expediente guardado.
- El formato de referencia en pantalla **no es un PDF emitido**, no
  reemplaza la comprobación real de A4, y sus textos «Dato del
  expediente» no se imprimen como valores reales.
- El generador y las matrices históricas no cambian; no se escriben
  datos operativos de trabajadores.

## Prueba de aceptación
`scripts/qa_javiera_v16_browser.py` verifica la navegación:
1. Abrir editor, seleccionar «Información de Riesgos Laborales».
2. Confirmar que hay estructura y cabeceras de cinco columnas.
3. Confirmar acceso «Abrir Matrices y cargos».
4. Confirmar que el HTML opcional no crea una hoja vacía principal.
5. Volver a recepción de reglamento y conservar su editor funcional.

## Pendiente
- Auditoría final de 324 fórmulas del Excel corregido; no afirmar
  equivalencia de fórmulas al 100 %.
- Validación preventiva del riesgo incompleto en
  `MATRIZ IRL` fila 40 del libro corregido.
- Pruebas visuales y aprobaciones responsables de los PDF reales antes
  de usar un documento con fines laborales.
- La migración íntegra de diez formatos no forma parte de este parche.

No fusionar ni desplegar antes de CI verde.
