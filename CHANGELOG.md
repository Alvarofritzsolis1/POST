# Historial de cambios

## 0.6.0-rc1 — candidata local, pendiente de revisión y despliegue

- Importación especializada de contratistas con `NATURALEZA` y `FRECUENCIA` independientes de `COD`; archivos anteriores siguen admitidos y sus celdas vacías no borran clasificaciones válidas. CI se interpreta como independiente; CT no presupone trabajadores ni frecuencia.
- Reconciliación administrativa de clasificaciones con procedencia por evento, vista previa firmada, conflictos visibles, corrección manual y respaldo verificable obligatorio. No se atribuyen valores sin evidencia.
- Registro de trabajadores por obra y empresa con filtros, paginación y ficha individual. Contratos con fecha pactada separada del término efectivo, anexos, PDF y auditoría; finiquitos con causal, ratificación, entrega y revisión manual.
- Semáforo de riesgos contractuales, finiquitos, cotizaciones y documentos exigibles, con centro de alertas en Inicio y acceso a los registros. Los hallazgos de pago requieren documento y revisión; una modificación posterior invalida la conclusión.
- Control de asistencia por obra, contratista y trabajador: cinco ventanas de siete días (semana 5: días 29 al fin de mes), firmas diarias, borrador/cierre/revisión semanal, respaldo, autor y fechas, alerta por semanas vencidas y balance mensual con días pagados. Exclusión o reincorporación mensual sin borrar evidencia.
- Rol de administrativa para ingreso semanal; administrador y supervisor pueden revisar. Se mantienen administrador, supervisor, revisor documental, consulta y `analyst` para cuentas anteriores. Revisores documentales no pueden modificar trabajadores ni contratistas.
- Migración aditiva versionada `0.6.0-rc1`, prueba de respaldo/restauración obligatoria en el actualizador Docker, versión y SHA del commit servidos por la API.

## 0.5.0-rc1

- Organización compartida, administración de cuentas, importaciones especializadas y controles mensuales.
