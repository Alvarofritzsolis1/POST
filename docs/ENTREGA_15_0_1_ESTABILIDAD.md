# GALANT POST 15.0.1-rc1 — Parche de estabilidad de pestañas

**Alcance:** corrección visual del frontend. Sin migraciones de PostgreSQL, sin cambios de documentos, permisos, cálculos de asistencia, OCR ni API.

## Diagnóstico y corrección

- `App.tsx` solicitaba datos al recuperar `window.focus`, además de la actualización programada cada 10 segundos. Se elimina la solicitud duplicada de foco; el sondeo continúa cuando la pestaña está visible.
- `AdministrativeControlV92.tsx` mostraba temporalmente un párrafo de carga encima de las tarjetas en cada actualización de 30 segundos, desplazando el contenido. Ahora el mensaje solo se muestra antes de la primera carga.
- `AdminAttendanceV93.tsx` programaba actualizaciones de cartera incluso si estaba abierta una obra, donde la vista interna ya tiene su propio sondeo. Ahora solo actualiza la cartera general cuando no hay obra seleccionada y no agrega un mensaje temporal mientras ya hay datos.
- `v15-premium.css`: barras de desplazamiento finas y con espacio estable; el indicador de recarga del panel principal usa posición fija y no altera la altura de la página.

## Pruebas de regresión

Se añadió `scripts/qa_v1501_focus_stability.mjs`, ejecutado desde `npm run test:logic`.
Se conserva `npm run build` para validar TypeScript/Vite en CI.

## Verificación visual requerida antes de producción

1. En el perfil ADMIN abrir Control de asistencia > obra Concepción > noviembre de 2026.
2. Desplazarse hasta media tabla, cambiar de pestaña del navegador por 35 segundos y volver; verificar que ni `scrollY` ni la posición visual de las tarjetas cambien durante la sincronización.
3. Repetir en el consolidado de todas las obras y en el perfil de administrativa.
4. Confirmar que los cambios de datos sigan apareciendo tras el sondeo y con el botón "Actualizar".
5. Abrir ficha individual y regresar; comprobar el desplazamiento intencional al encabezado de la ficha y su restauración al listado.
6. Probar menú expandido/contraído, barra lateral y móviles, incluido navegador Edge.

**Estado:** código preparado para revisión/CI. No se ha desplegado en el VPS ni realizado la prueba de navegador sobre datos reales.
