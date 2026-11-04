# GALANT POST v8.0.0 — Entrega candidata

## Alcance implementado

- **Visibilidad compartida:** el inicio y el listado de requerimientos muestran por defecto todas las publicaciones visibles de la organización. Los borradores de otras obras siguen siendo privados. El filtro «Solo mis obras» es voluntario y se aplica también a los indicadores.
- **Procedencia:** la API devuelve el `site_id` y el nombre desde la publicación persistida; una edición no puede cambiar la obra de origen, aunque la realice un administrador. Para publicar en otra obra corresponde crear un nuevo requerimiento.
- **Edición por autor:** los residentes pueden escribir solamente sobre las publicaciones que crearon y que pertenecen a una obra asignada. Los administradores conservan sus facultades existentes.
- **Historial legible:** los eventos operativos son presentados en español con nombres, fechas, valores anteriores/nuevos y motivos. El JSON de `OpsChange` no se entrega en el endpoint de historia; continúa persistido para auditoría. Los campos mostrados se obtienen mediante lista de permitidos.
- **Interfaz:** cinco indicadores compactos, publicaciones visibles antes de los gráficos, panel de trazabilidad y bloqueo visual de obra para residentes con una sola asignación.
- **Versionado:** API y frontend utilizan la versión 8.0.0, que deberá comprobarse tras desplegar mediante `/api/v1/version` y el SHA de compilación.

## Seguridad

Las consultas compartidas tienen alcance de **organización**, no global entre empresas. Los borradores, adjuntos, documentación laboral y mensajes conservan los controles existentes. La vista de detalle de un requerimiento externo continúa limitada y no incluye la descripción privada ni adjudicaciones confidenciales de otra obra. La capacidad y la adjudicación no se transfieren automáticamente.

## Validación requerida

1. Confirmar que `python -m pytest -q` pasa tanto en SQLite como en PostgreSQL de prueba.
2. Confirmar `npm ci && npm run build` y que no hay errores en consola.
3. Probar con residentes sintéticos de Junquillar, Lomas Verdes y Concepción: publicación de cada obra y visualización cruzada sin cambio de origen.
4. Verificar que un residente no puede editar publicaciones ajenas ni alterar `site_id` vía API.
5. Verificar la línea de tiempo con eventos antiguos, creaciones, modificaciones y adjudicaciones.
6. Revisar el dashboard en escritorio, tablet y móvil.
7. Mantener las pruebas de OCR, control documental, trabajadores, anticipos y exportaciones.
8. Antes de fusionar o desplegar, preparar y verificar un respaldo recuperable del VPS, conforme a `docs/ACTUALIZACION_SEGURA_VPS.md`.

## Límites explícitos

Esta entrega corrige de forma prioritaria la Red de Obras y la interacción básica de sus residentes. **No constituye una reescritura de todos los módulos de GALANT, una auditoría anual ni evidencia de despliegue en producción.** No se han ejecutado pruebas sobre datos laborales reales.

Si la CI falla, mantener la PR como borrador y corregir antes de integrarla.
