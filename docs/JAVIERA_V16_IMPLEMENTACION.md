# GALANT 16.0.0-rc1 · Proyecto JAVIERA

**Estado:** candidato de integración; PR #40 en borrador; **NO desplegado** ni aprobado para producción.

## Origen y alcance
- Repositorio operativo: `Alvarofritzsolis1/POST` (no el repositorio Streamlit anterior).
- Base: GALANT 15.0.5-rc1 React/FastAPI/PostgreSQL.
- Especificación: Proyecto JAVIERA V3, contratistas y subcontratos, actuales y antiguos.
- Las áreas son `Zona Subcontratos` y `Prevención de Riesgos`. Se modelan diez piezas: contrato, traslado, declaración, prórroga, reglamento, EPP, IRL, PTS, recepción PTS e inducción.
- Navegación `/proyecto-javiera`; botón global administrador `Configuración de automatización` en `/configuracion/automatizacion`.

## Funcionalidad incluida en esta rama
- Selección de obra, empresa, empleador directo, trabajador y cargo desde datos GALANT; creación de empresas/trabajadores por los endpoints existentes; vínculo opcional con empresa contratista principal.
- Formularios reactivos y elegibilidad del servidor con faltantes, RUT chileno, eventos, tipo de vínculo, contratos y matrices preventivas.
- Configuración por plantilla: texto integral, variables `{{worker.name}}`, campos personalizados `extra.*`, reglas de eventos y vínculos, encabezado/pie, letra y margen del PDF. Edición de matrices en versiones.
- Aprobación de plantillas y matrices por un segundo administrador (autor no se aprueba a sí mismo), registro de auditoría.
- PDF individual A4 privado; vista previa con advertencia; cada emisión conserva hash SHA-256, instantánea de datos y versión de plantilla, sin inventar firmas, entregas ni inducciones.
- Carga de documentos históricos para revisión posterior; estado histórico nunca se infiere automáticamente como vigente.
- Subida **privada** del Excel corregido desde Configuración: extrae matrices PTS, IRL, perfiles, condiciones y sustancias como borradores sujetos a revisión.
- Migración aditiva v16 para seis tablas nuevas, sin borrar ni modificar tablas de GALANT.

## Cómo iniciar en entorno privado de pruebas
1. Revisar **PR #40** y esperar CI verde: `https://github.com/Alvarofritzsolis1/POST/pull/40`.
2. Crear respaldo consistente de la base + almacenamiento `/data/private`, y comprobar la restauración en un entorno aislado.
3. En una **copia aislada** de GALANT, ejecutar el comando existente `python -m app.cli init-db` / migración verificada según `docs/INSTALACION_VPS_CADA_VERSION.md`. Esto registra nuevas tablas; no migrar antes de probar el backup.
4. Acceder como administrador, abrir Configuración de automatización, cargar `JAVIERA_ETAPA_1_PTS_CORREGIDOS.xlsx` desde el computador **sin subirlo al repositorio público**.
5. Revisar cada matriz importada; otro administrador la aprobará tras validar los riesgos reales por obra.
6. Redactar/revisar/publicar las plantillas exactas de documentos, sus condiciones y variables. No se publican textos legales genéricos de forma automática.
7. Seleccionar empresa, trabajador, obra, evento y datos. Ver las tarjetas documentales y generar PDF cuando los requisitos y aprobaciones estén superados.

## Pruebas y limitaciones
- Pruebas unitarias nuevas: `apps/backend/tests/test_javiera_v16.py` (cargos, RUT, 10 documentos, independencia/contrato, IRL vs PTS, PDF vista previa, tokens seguros e histórico).
- Los flujos API integrados y navegador/impresión requieren pruebas contra PostgreSQL y datos **sintéticos**, así como validación legal y preventiva antes del despliegue.
- La importación identifica contenido de matriz; **no reproduce automáticamente la maquetación original** de las 17 hojas Excel ni genera de inmediato todos sus documentos.
- Los PDF actuales son composición A4 basada en texto y controles de presentación simples; quedan pendientes formatos ricos (tablas anidadas, membretes complejos, firmas digitales reales) para alcanzar fidelidad al Excel.
- Todos los perfiles de acceso de JAVIERA son **solo administrador** en esta versión candidata. El responsable de prevención y el revisor jurídico deben realizar una aprobación competente por procedimiento.
- No existe acreditación automática de firma, recepción, entrega EPP, inducción ni verificación de pagos.
- El editor aún no es WYSIWYG; se configura mediante campos y texto/variables. Una futura iteración puede mejorar formato visual, siempre conservando controles de publicación.
- No fusionar ni desplegar sin CI completo, respaldo verificado, pruebas visuales PDF y validación de los procedimientos.

## Código VPS

**No ejecutar actualización en producción todavía.** La rama está en PR borrador, `main` permanece en la versión actual. El procedimiento seguro de despliegue sigue en:
- `docs/INSTALACION_VPS_CADA_VERSION.md`
- `docs/DESPLIEGUE_VPS_UN_CLIC.md`
- `docs/ACTUALIZACION_SEGURA_VPS.md`

Los comandos finales de PowerShell/SSH para producción solo deben utilizarse tras completar y aprobar estas comprobaciones, manteniendo respaldo y rollback.
