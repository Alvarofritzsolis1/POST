# GALANT 20.3.2-rc1 — Configuración unificada

## Cambios

- Centro con categorías de Mi cuenta, Usuarios y permisos, Obras, Reglas operativas, Exigencias documentales y Automatizaciones.
- Se elimina la pantalla de tres columnas y el botón duplicado para entrar a Configuración General.
- Navegación Volver por contexto y regreso desde las vistas avanzadas al centro.
- Diseño de usuarios adaptable sin desplazamiento horizontal en escritorio.
- Editor visual de estados, clasificaciones y plazos de importación; conserva las causales y tipos de contrato actuales.
- Registro de retenciones por mes y protección contra vigencias duplicadas.
- Prueba de navegador actualizada.

## Límites y seguridad

No se modifican las migraciones, bases de datos, expedientes ni requisitos documentales. Se reutilizan las vistas existentes para documentación avanzada y automatizaciones. Los códigos TH/TM/F no se confunden con categorías CT/CI/ESP. La edición de obras existentes y la asignación de permisos por obra requieren soporte específico del backend y no se simulan.

## Validación necesaria

1. Instalar dependencias e iniciar npm run build y npm run test:logic desde apps/frontend.
2. Completar las pruebas backend y de integración de GitHub Actions.
3. En navegador, comprobar entrada, navegación y regreso, edición visual y guardado de catálogos, flujo de usuarios y diseño responsive.
4. Validar nueva vigencia en QA, rechazo de duplicados, permisos y conservación de información histórica.
5. Solo después de CI aprobada, fusionar y verificar la versión publicada en API, frontend y logs de despliegue.

El parche queda como candidato hasta que existan evidencias de CI y VPS. No implica por sí solo publicación a producción.
