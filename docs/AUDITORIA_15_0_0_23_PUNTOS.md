# GALANT 15.0.0-rc1 · Auditoría de aceptación del prompt maestro (23 apartados)

**Fuente:** Prompt Maestro GALANT Premium UX enviado por el usuario.
**Versión base:** 13.1.0-rc1 (`b91052939b21e286334a0e5d5cde2dece9460675`).
**Rama auditada:** `feat/galant-15-premium-ux-20261105`.
**PR:** https://github.com/Alvarofritzsolis1/POST/pull/32.
**Alcance de la evaluación:** código del PR, revisión de rutas y APIs, pruebas automáticas de GitHub Actions, sin acceso a la base productiva.
**Definición:** Cumple en código = existe y se verifica con los medios disponibles. Parcial = funciona una parte pero no cubre todo el prompt. Requiere validación = necesita evidencia adicional de usuarios o entorno real. No equivale a una aprobación de producción.

| N.º | Requisito | Evidencia verificable | Dictamen |
|---|---|---|---|
| 1 | Misión y experiencia premium | Capa premium, ficha, dashboard y navegación sin recrear backend | Parcial: falta validación con usuarios |
| 2 | Auditoría del proyecto | Comparación contra main 13.1, árbol, APIs, control de cambios, PR aislado | Cumple en código |
| 3 | Sistema de diseño unificado | `v15-premium.css`, tokens, tablas, estados, responsive, foco | Parcial: no todos los módulos utilizan componentes React comunes |
| 4 | Navegación global | Sidebar plegable heredado, buscador real de módulos, selector global, historial | Parcial: búsqueda es solo de módulos; no global de registros |
| 5 | Ficha del contratista | Pantalla completa, botón Volver, cabecera única, KPI y pestañas | Cumple en código y QA |
| 6 | Documentación | Tabla, mes, búsqueda, filtro, revisión manual, observaciones, prioridades, periodos | Cumple en flujo esencial; faltan pruebas manuales exhaustivas |
| 7 | Configuración General | Ocho secciones 13.1 conservadas, Portería, reglas históricas, nuevo estilo | Parcial: adaptación visual transversal, no rediseño funcional completo |
| 8 | Contratistas | Búsqueda, estado, COD, cumplimiento, pendientes y paginación de 25 | Parcial: falta ordenamiento por todas las columnas y filtros avanzados |
| 9 | Trabajadores | Fichas y formularios existentes conservados, historial humanizado | Parcial: falta revisión de todas las combinaciones contractuales |
| 10 | Asistencia | Flujo semanal vigente preservado, nueva entrada desde contratista | Cumple en código; QA de navegación y reglas existente |
| 11 | Red de Obras | Portal conservado, pruebas sintéticas de publicaciones y adjudicaciones | Cumple en alcance conservado |
| 12 | Carga masiva | Vista previa/validación servidor, confirmación, 7 etapas visuales e historial legible | Parcial: las etapas no son 7 pantallas independientes |
| 13 | Dashboard | 5 indicadores conectados a API y secundarios plegables, alertas existentes | Parcial: pendiente evaluación de jerarquía visual final |
| 14 | Estados y semáforos | `documentUX.ts`, excluidos correctos, porcentaje ponderado, pruebas unitarias | Cumple en código y pruebas |
| 15 | Seguridad y roles | Rutas admin/admon/residente preservadas; backend aplica autorización | Parcial: no equivale a una auditoría de penetración |
| 16 | Navegación y rendimiento | Estado de período global, URL del detalle, filtros/página, lazy previo | Parcial: faltan mediciones comparativas reales |
| 17 | Responsive y accesibilidad | Tests Playwright 390/768/1024/1366/1440/1920, foco de mayor contraste | Parcial: falta auditoría manual completa WCAG 2.2 AA |
| 18 | Agentes especializados | CI, validadores independientes v9.1 y v12, revisión manual de código | Parcial: no existen siete agentes autónomos verificables |
| 19 | Pruebas obligatorias | `pytest`, TypeScript/Vite, Node semántico, CI Docker, QA browser, respaldos | Requiere confirmar CI del commit final y revisar capturas |
| 20 | Estrategia por fases | Código incremental y documentación en PR separado; sin despliegue | Cumple como proceso, continúa validación |
| 21 | Control de versiones y VPS | Frontend/API 15.0.0-rc1, rama aislada, VPS intacto, sin migración DB | Cumple en gestión de versión |
| 22 | Entregables | PR, changelog, documento, QA y capturas en artifacts de CI | Parcial: capturas no inspeccionadas manualmente |
| 23 | Calidad definitiva | Checklist y pruebas automáticas; sin datos reales del VPS | No aprobado todavía para producción |

## Protecciones verificadas por diseño
- Ninguna migración de esquema ni actualización productiva.
- Se reutiliza el evaluador de exigibilidad de 13.1; no se crea motor paralelo.
- Sin nuevas cargas documentales en Configuración General.
- Los perfiles administrativo y residente conservan su interfaz especializada.
- El informe de Portería mantiene su política existente para CT/CE/CI.
- Las cifras no evaluables se muestran como tales, no como 100% de cumplimiento.
- El historial muestra responsables por nombre, sin JSON ni identificadores técnicos en la UI.

## Pruebas añadidas en 15
- `scripts/qa_v15_document_states.mjs`: requisitos no exigibles, estados críticos, múltiples trabajadores, cálculos ponderados, sin datos.
- `scripts/qa_v1010_browser.py`: cabecera única, dos indicadores, contrato, finiquito, asistencia, filtros, período y actor de auditoría.
- `scripts/qa_ux_2026_browser.py`: 11 secciones, navegación rápida, seis resoluciones, capturas de ficha documental y ausencia de overflow.
- CI ejecuta `npm run test:logic` y pruebas Python/QA existentes.

## Gates pendientes de 10/10 real
1. CI del commit final completamente en verde y revisión de capturas artefactadas.
2. Prueba de usabilidad con al menos un administrador, una administrativa y un residente sobre tareas reales (tiempo, errores y comprensión).
3. Auditoría WCAG 2.2 AA con teclado, lector de pantalla, zoom, contraste de todos los componentes y estados.
4. Medición previa/posterior de carga, interacción y memoria, sin declarar rendimiento no medido.
5. Prueba de permisos por organización, autorizaciones de recursos y casos de acceso directo con usuario no autorizado.
6. Revisión exhaustiva de importaciones, periodos históricos, retenciones y documentos inusuales con datos sintéticos representativos.
7. Revisión y aprobación de las fases de rediseño aún parciales (react components compartidos, filtros avanzados, vistas de importación, búsqueda de registros).

**Decisión:** No fusionar ni desplegar mientras estén pendientes los gates de producción. Una suite en verde respalda el código probado, pero no demuestra un 10/10 de usabilidad.
