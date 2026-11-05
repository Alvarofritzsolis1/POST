# GALANT POST · Renovación visual 2026 · v12.1.0

## Alcance
Se actualiza la experiencia visual del frontend React sin modificar el esquema PostgreSQL ni contratos de API. Las siguientes mejoras están implementadas en la rama `design/galant-ux-premium-20261104`:

1. **Shell y navegación:** menú lateral agrupado por objetivo, compatible con expansión/contracción y drawer móvil existente.
2. **Encabezado:** filtros globales Obra/Período, 42 px de altura mínima de selector, ajuste responsive y accesibilidad. Se elimina el botón de importación repetido.
3. **Contratistas:** ya no aparece un segundo selector de Obra cuando existe selección global. Se conserva actualización manual y la importación del módulo.
4. **Dashboard:** tarjetas de alertas clasificadas por gravedad real del backend; enlaces de navegación a los casos, títulos y etiquetas comprensibles.
5. **Trabajadores:** tarjetas de contratos vencidos, próximos y finiquitos pendientes con señales visuales condicionadas a cantidades reales.
6. **Documentos mensuales:** distingue Aprobado, Vencido/Rechazado/Observado, Pendiente de revisión, Acción pendiente y No aplicable/No exigible. Nunca usa el estado contractual Inactivo como incumplimiento rojo.
7. **Consistencia visual:** tokens CSS, tipografía y sombras moderadas, señales con texto/color, componentes de panel y tablas, modo oscuro y compatibilidad con reducción de movimiento.
8. **Diseño responsive:** reglas específicas para 390, 760 y 1200 px; filtros adaptables, tablas sin scroll horizontal de documento.
9. **QA:** script Playwright con login sintético, verificación de una sola obra global y un solo botón Importar, capturas de siete pantallas y seis resoluciones, revisión de errores de JavaScript y respuestas 500.
10. **Integración CI:** el nuevo QA UX se ejecuta en entorno aislado; captura artefactos de screenshots, sin acceder a datos reales.

## Verificación, restricciones y advertencias
- La compilación de TypeScript/Vite y los tests backend/QA se ejecutan por GitHub Actions; consultar el resultado de la rama antes de publicar.
- El script `scripts/update-preview.sh` exige respaldo, verificación de restauración, limpieza Git y salud de la API. No realiza un reinicio ciego.
- La validación visual humana es necesaria: una compilación exitosa y capturas automáticas no sustituyen una revisión UX profesional.
- Este cambio no recalcula retenciones, modifica clasificación CT/CE/CI, altera contratos de trabajadores ni cambia permisos de residente/administrativo.
- No se han migrado todos los módulos a una biblioteca única de componentes: la unificación visual es progresiva sobre componentes existentes para minimizar regresiones.
- No se declara una revisión de contraste WCAG independiente ni una prueba de carga real del VPS.
- No debe hacerse merge ni despliegue a la instalación productiva sin revisar los artefactos de navegador y el estado final de CI.

## Pasos recomendados para revisión
1. Abrir PR #27 y comprobar que los trabajos frontend, backend, compose, QA sintético y validadores terminan correctamente.
2. Descargar el artefacto `galant-ux-2026-browser` del run QA final. Revisar las siete vistas de escritorio y seis tamaños de pantalla de Contratistas.
3. Verificar personalmente selectores de obra/período, perfil, permisos y alertas en un entorno de prueba.
4. Publicar exclusivamente el SHA exacto aceptado, utilizando el script oficial de actualización que verifica respaldo y retorno de salud.

## Referencias
- Linear, rediseño marzo 2026: https://linear.app/changelog/2026-03-12-ui-refresh
- shadcn/ui Sidebar: https://ui.shadcn.com/docs/components/radix/sidebar
- Motion: https://motion.dev/docs/react-layout-animations
- Atlassian Design System: https://atlassian.design
- WCAG 2.2: https://www.w3.org/TR/WCAG22/
