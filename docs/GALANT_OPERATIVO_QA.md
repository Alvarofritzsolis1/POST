# GALANT — Estado de requisitos, pruebas y despliegue seguro

## Fuente de verdad
La especificación de aceptación es el documento de 22 secciones compartido por el responsable del proyecto el 03-11-2026. Este PR prioriza el control operativo manual; OCR Beta permanece separado.

## Matriz de cumplimiento verificable

| Requisito | Implementación incluida en PR #6 | Limitación / pendiente |
| --- | --- | --- |
| Obras independientes + consolidado | Sí: tres obras, asignaciones separadas y dashboard agregado | Validación con datos del VPS |
| Excel/CSV histórico de empresas y trabajadores | Existía en etapa 1, con preview, mapeo y pruebas | Probar Excel real autorizado; contratos y anexos ahora tienen importador separado |
| Códigos CT/CI, frecuencia y naturaleza | Se conservan como campos distintos | Códigos históricos distintos no se interpretan automáticamente |
| Matriz de siete documentos | Sí: regla por naturaleza, override de exigibilidad, estados por obra/mes | Matriz legal aplicable debe validarla empresa |
| Aprobación sin PDF y masiva | Sí: POST /control/reviews y /reviews/bulk, historial de usuario | No significa que el pago esté acreditado externamente |
| Control de asistencia y cotizaciones | Sí: registro manual por trabajador; días exigibles, pagados y asistencia independientes | No conecta automáticamente documentos reales de PREVIRED |
| Cálculos | Sí: MAX(0, exigibles - pagados) × tarifa configurable, por trabajador | La procedencia legal de cualquier retención queda sujeta a revisión humana |
| Independiente CI sin empleado ficticio | Sí, se registra como sujeto independiente y no aplica retención por días | Normativa específica y reglas de cobertura requieren validación |
| Excel CT y CI | Sí, informe exclusivo por código y totales sin compensar faltantes | Contratos y otros códigos quedan excluidos deliberadamente |
| Sin movimientos y continuidad | Sí: período/obra, motivo, tarea, sin baja ni carta automática | Movimientos de portería no se contrastan automáticamente hasta tener datos |
| Contratos y prórrogas | Sí: registros con fechas, edición API, alertas 30/15/7 | Importador con vista previa, edición y control de duplicados implementado; validar planilla histórica real |
| Calendario mensual | Sí: fecha solicitud, vencimiento, alerta opcional y worker autónomo | Requiere proceso worker en ejecución; no se programan fechas ficticias |
| Bajas y cartas | Sí: etapas, decisión explícita y motivo | No crea ni envía automáticamente carta |
| Dashboard INE básico | Sí: indicadores CT, CI, esporádicos, obra y consolidado ponderado | Gráficos mensuales, estados, vencimientos y retenciones incorporados; probar volumen real |
| Alertas y tareas | Sí: tareas manuales, continuidad y alertas de pagos y contratos | Automatización avanzada por documento y correo pendiente |
| Archivos OCR Beta | Conservados; PDF optativo | Los documentos previos requieren asociación manual con la ficha y el mes |
| Seguridad multiusuario | Por org_id, permisos y pruebas sintéticas | Probar dos cuentas reales de la misma organización en VPS |
| Despliegue y backup | Backup + restauración PostgreSQL y PDFs SHA256 en Docker aislado, comprobados con prueba sintética; actualización detiene ante error | Falta ejecutar la restauración de ensayo en el VPS real y validar usuario/volumen/permisos |
| 24 horas de estabilidad | Script 24h con reutilización de cookies (evita bloqueo por logins) preparado | **No ejecutado**; el tiempo no debe presentarse como probado |

## Aprobación de la implantación

No fusionar ni desplegar mientras exista alguna prueba de CI fallida. La aprobación debe incluir:

1. Respaldo del estado previo con `scripts/backup-preview.sh`, directorio seguro fuera del repositorio y verificación de integridad.
2. Ensayo de restauración con `scripts/verify-restore-preview.sh` en PostgreSQL Docker sin red, contrastando SHA256 de archivos; el script de despliegue lo exige automáticamente.
3. Confirmar cuál rama y entorno usa el VPS, que `.env.preview` está en `/opt/galant-post` y que los cinco servicios son los correctos.
4. Ejecutar la migración aditiva `python -m app.cli init-db` una vez instalado el código nuevo.
5. Verificar con usuarios A y B del mismo `org_id`: ambos consultan el mismo contratista, siete requisitos, pago manual, aprobación y tareas.
6. Verificar usuario viewer (solo lectura) y usuario de otra organización (sin acceso).
7. Verificar obra A ≠ obra B, incluidos períodos y bajas.
8. Confirmar exportación Excel CT/CI, dato sin evaluar y periodo sin fecha de solicitud.
9. Reiniciar servicios **sin borrar volúmenes**, comprobar persistencia con datos sintéticos.
10. Ejecutar el ensayo de resistencia durante 86.400 segundos, guardar evidencia y no etiquetarlo como aprobado antes de terminar.\n11. Solo entonces autorizar la fusión y el despliegue; conservar la posibilidad de rollback.

**Nunca ejecutar** `docker compose down -v`, `docker volume prune`, `DROP DATABASE` ni `git reset --hard` sobre el VPS de datos.

## Ensayo de 24 horas

`scripts/soak_24h.py` comprueba durante 86.400 segundos que las cuentas autorizadas comparten el mismo `org_id`, las mismas obras y la misma matriz mensual, consulta el estado de salud y almacena un reporte sin nombres ni RUT.

Necesita `GALANT_SOAK_EMAIL_A`, `GALANT_SOAK_PASSWORD_A`, `GALANT_SOAK_EMAIL_B`, `GALANT_SOAK_PASSWORD_B`, dos cuentas sintéticas en la misma organización y un destino HTTPS privado o un túnel SSH a 127.0.0.1.

Ejemplo de invocación después de preparar las variables de entorno de manera segura:

```bash
python3 scripts/soak_24h.py --url https://STAGING-AUTORIZADO --period 2026-09 --duration-seconds 86400 --interval-seconds 60 --output /ruta-privada/soak-24h-summary.json
```

Criterio: muestras positivas, cero errores de salud, sin desincronización, sin filtración entre cuentas. Comprobar además logs, uso de CPU/RAM y persistencia tras reinicio controlado. La prueba de 24 horas **no se puede sustituir por una corrida de pytest o un build exitoso**. No se ha ejecutado desde este chat.

## Diagnóstico multiusuario ya identificado

El comando `create-admin` abre una organización diferente. La forma correcta de sumar colaboradores es `create-user --admin-email ADMIN_ORIGINAL`. Cuentas antiguas de organizaciones sin registros pueden usar `link-user`; organizaciones con datos requieren migración administrada, nunca asociación silenciosa.

## Resultado real de esta entrega

Las funcionalidades descritas como "sí" existen en código. Solo se deben considerar **validadas** después de que el CI de la rama actual pase y se repitan los escenarios de aceptación en un entorno de ensayo. No se altera producción mediante este Pull Request en borrador.
