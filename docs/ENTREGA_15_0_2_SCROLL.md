# GALANT POST 15.0.2-rc1 — Corrección de parpadeo y salto visual

## Incidencia reproducible

En la vista de Contratistas, `Operations.tsx` activaba `loading` en cada actualización de 10 segundos y el JSX sustituía **toda la tabla** por una línea temporal «Cargando contratistas…». El documento quedaba más corto, el navegador recortaba `scrollY` y, al recuperar la tabla, el usuario veía un salto brusco. Además, el navegador podía restaurar automáticamente una posición antigua en una recarga y la navegación global reutilizaba la posición anterior al cambiar de módulo.

## Cambios

- `Operations.tsx`: mantener la tabla existente durante actualizaciones; mostrar la carga principal solo cuando aún no hay contratistas visibles. Se conserva el sondeo de 10 segundos y el refresco manual. Se retira la actualización redundante al recuperar el foco; se evita sondear pestañas ocultas.
- `App.tsx`: resolver el módulo inicial desde la ruta y el historial del navegador, para evitar mostrar brevemente Inicio si se estaba en otro módulo. Cambiar de módulo pone el scroll arriba de forma síncrona, antes de cambiar el contenido. Mantener la restauración especial al salir de la ficha individual de un contratista. La obra seleccionada se conserva en `sessionStorage` (incluso la opción «Todas las obras») para que al recargar no desaparezca la tabla por cambio a otra obra.
- `index.html` y `main.tsx`: desactivar la restauración automática global del scroll del navegador y fijar el inicio de una nueva carga en la cabecera. No altera el desplazamiento del menú lateral.
- Versiones de API, frontend y package-lock sincronizadas en `15.0.2-rc1`.

## Pruebas

- `npm run test:logic` incorpora `scripts/qa_v1502_scroll_flicker.mjs`.
- La QA en Chromium `scripts/qa_v1502_scroll_browser.py` sobre instancia sintética verifica que la tabla no desaparezca durante el refresco manual, el retorno de pestaña y la actualización de 10 segundos, así como el inicio arriba tras una recarga.
- Las pruebas comprueban que cambiar de módulo inicia arriba y que se puede regresar a una ficha sin perder el listado.

## Seguridad y despliegue

Este cambio no altera PostgreSQL, las obligaciones documentales, la asistencia, los cálculos, los roles, la API ni los archivos privados. La instalación vigente del VPS no se modifica mientras el parche esté en una rama. Se requiere CI aprobado y luego despliegue seguro mediante `scripts/update-preview.sh` apuntando al SHA de merge, con respaldo y restauración probada.

## Verificación con datos reales posterior

Entrar en Contratistas de Concepción, noviembre de 2026; desplazarse hacia los registros con estado «Activo»; dejar transcurrir al menos 10 segundos, cambiar y regresar a la pestaña, y utilizar «Actualizar». La tabla, la posición vertical y el menú deben permanecer estables. Comprobar además las rutas de fichas, asistencia y usuarios administrativos.
