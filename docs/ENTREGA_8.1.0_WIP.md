# GALANT POST v8.1.0 — Rama de trabajo NO DESPLEGABLE

**Estado: implementación parcial, PR borrador.** No sustituye la v8.0 ni habilita despliegue del VPS.

## Implementado en la fase inicial

- Tres roles seleccionables: `admin`, `administrative`, `resident`.
- Perfil Administrativo con pantalla independiente: Asistencia semanal y Contratos de Trabajo sin PDF.
- Permisos de API y asignación de obras para Administrativo; protección contra acceso cruzado por obra.
- Opciones de cuenta y ediciones limitadas a tres perfiles, con identificación de cuentas históricas que requieren reasignación.
- Buscador compacto de contratistas por nombre/RUT en lugar de tarjetas laterales.
- Contratos laborales iniciales sin archivos, con validación backend de obra autorizada.
- Historial visible de asistencia por nombre de usuario registrado, nunca correo.
- Vista de Administrativo sin campos de días pagados ni balance financiero.
- Registros atrasados permiten entrada mediante motivo y conservan el primer cierre.

## Imprescindible ANTES de publicar

1. La API histórica usa bloques 1–7, 8–14, 15–21, 22–28 y 29–31: **no hay calendario lunes–domingo real todavía**. Diseñar migración histórica aditiva que preserve cada fecha firmada, permitir 4–6 segmentos y probar cruces de meses.
2. Implementar evaluación mensual por administrativo/obligaciones exigibles, puntualidad, nota configurable 1,0–7,0, revisión y auditoría inmutable. No confundir registros ingresados con obligaciones asignadas.
3. Refactorizar infraestructura, consultas, índices, paginación, control de concurrencia, trazabilidad de sesiones, respaldos y QA con métricas reales.
4. Resolver migración de cuentas con roles anteriores sin pérdida de datos. Mientras tengan roles antiguos el acceso devuelve 403 hasta su reasignación por un admin.
5. Actualizar pruebas antiguas de asistencia que esperan carga de PDF y cinco semanas fijas, y pruebas antiguas de permisos que esperan otros roles. Ejecutar backend y frontend CI y pruebas de acceso cruzado y de contrato.
6. Inspeccionar versión real en VPS y ejecutar un respaldo y ensayo de restauración antes de cualquier migración; no alterar producción desde esta rama.
7. Validar y eventualmente publicar v8.1 con autorización expresa; recién entonces cambiar la versión visible.

## Especificación vinculante

Ver [issue #15](https://github.com/Alvarofritzsolis1/POST/issues/15), que reúne el PROMPT REY completo y las prioridades. Mantener este PR como **borrador**, nunca fusionarlo o desplegarlo por la mera existencia de commits.
