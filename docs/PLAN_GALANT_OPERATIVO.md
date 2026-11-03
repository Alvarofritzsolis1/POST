# GALANT operativo: plan de entrega

La [especificación maestra](ESPECIFICACION_MAESTRA_GALANT.md) es la referencia funcional. POST ya contiene autenticación, PostgreSQL, auditoría básica y un módulo OCR. La nueva gestión manual debe compartir esa organización y su base de datos; el OCR Beta se conserva.

## Estado de entrega

| Estado | Funcionalidad |
| --- | --- |
| Terminada en la rama de etapa 1 | Obras por organización, contratistas, trabajadores y asignaciones; fichas manuales; importación Excel/CSV con vista previa, corrección, mapeo histórico confirmado, guardado transaccional y plantillas. |
| Pendiente | Etapas 2–5: auditoría manual y cálculos; dashboard general; calendario, contratos y bajas; asociación de evidencias. |
| Pendiente de validación con datos reales | Ajustar el reconocimiento del Excel histórico concreto; no se recibió un ejemplar autorizado. |

La primera etapa se ha verificado con planillas sintéticas y pruebas de aislamiento, permisos, RUT y migración aditiva. Esta evidencia comprueba el flujo implementado, pero no sustituye la prueba con el Excel histórico real.

## Etapa 1 — Base operativa

**Objetivo:** crear y consultar obras, contratistas y trabajadores con datos reales, y cargarlos de forma manual o desde Excel/CSV. La auditoría inicial corresponde a septiembre de 2026.

**Aceptación:**

- Las obras Lomas Verdes, Brisas de Junquillar y Concepción existen por organización y sus relaciones son independientes.
- Una empresa puede estar en varias obras; sus trabajadores se asignan a una obra y empresa concretas. CT/CI se conservan como códigos históricos y no se mezclan con naturaleza, frecuencia ni estado contractual.
- Los formularios guardan y vuelven a mostrar datos desde la base de datos. El acceso y la escritura respetan la organización, los roles y CSRF actuales.
- Excel/CSV se analizan primero en una vista previa. Se muestran filas ambiguas, RUT inválidos, duplicados y el efecto de la importación. El usuario puede corregir filas antes de confirmar. OK/P/NA requieren un mapeo explícito y conservan su origen histórico.
- Una segunda importación del mismo archivo no crea duplicados silenciosos. Existen plantillas descargables y un resumen exacto de altas, asociaciones, filas omitidas y errores.
- Una inicialización segura agrega tablas sin eliminar datos ni modificar el OCR existente; pruebas de API/importación y compilación frontend pasan.

**Compatibilidad:** la base actual solo utiliza `Base.metadata.create_all`; eso permite agregar tablas, pero no modificar columnas existentes. Las nuevas tablas deben registrarse en `app.cli init-db` antes de publicar. No se migran datos productivos ni se ejecutan cambios destructivos. El despliegue automático configurado en CI depende de credenciales del VPS; no demuestra por sí solo que el VPS haya sido actualizado.

## Etapa 2 — Auditoría manual

Matriz de siete requisitos por obra/período con reglas de exigibilidad, estados y aprobación trazable; registro editable de asistencia y cotizaciones por trabajador e independiente, cálculo de diferencias sin compensarlas entre personas, propuesta de retención configurable e informe CT/CI exportable. Aceptación: escenarios B–E y H de la especificación, con pruebas de redondeo, aislamiento y cambios posteriores a una aprobación.

## Etapa 3 — Gestión visual

Dashboard y exportaciones basados exclusivamente en registros evaluables. Aceptación: escenario I, porcentajes ponderados sobre totales reales y ausencia de un 100 % ficticio cuando no hay datos.

## Etapa 4 — Automatización administrativa

Calendario configurable, alertas y tareas persistentes, contratos y vigencias, actividad mensual, bajas y cartas. Aceptación: escenarios F y G; ningún movimiento ausente provoca una baja ni una retención aplicada automáticamente.

## Etapa 5 — Evidencias

Archivos asociados a registros manuales e integración posterior con OCR Beta. La carga de PDF seguirá siendo opcional para operar GALANT.

## Riesgos conocidos

- No se proporcionó el Excel histórico; el importador se valida con planillas sintéticas y debe comprobarse con una copia autorizada antes de cargar datos reales.
- La semántica de OK, P y NA no está definida. El sistema debe exigir la confirmación del mapeo antes de importar esos estados.
- El modelo actual carece de un sistema de migraciones versionadas. La primera etapa solo debe agregar tablas; futuras modificaciones exigirán migraciones formales y pruebas de reversión.
