# Despliegue GALANT 20.0.0-rc1 — 12 de noviembre de 2026

El VPS terminó el despliegue el 12 de noviembre a las 08:30:48 de America/Santiago (11:30:48 UTC). Sirve el commit `a393a073e27849bf65e42a505f0e775bd9b77d60` integrado mediante [PR 61](https://github.com/Alvarofritzsolis1/POST/pull/61).

## Evidencia del despliegue

[Ejecución correcta del despliegue](https://github.com/Alvarofritzsolis1/POST/actions/runs/43208581355).

- Respaldo completo PostgreSQL y archivos privados: `/opt/galant-post-backups/20261112T112744Z`.
- Restauración aislada correcta antes de actualizar; cinco archivos documentales asociados contrastados con sus huellas.
- Migración aditiva `20.0.0_excel_master_workspace` completada sin eliminar tablas ni datos anteriores.
- API y proxy: `status=ok`, versión `20.0.0-rc1`, commit exacto esperado.
- Portada y dos recursos compilados del frontend disponibles.
- Almacenamiento privado con lectura y escritura; rutas privadas bloqueadas para acceso anónimo.
- Calc privado recalculó una referencia entre hojas y exportó exclusivamente la hoja seleccionada. Conversión sintética observada: 490,47 ms. No representa un percentil ni una prueba sostenida del VPS.

[CI de integración aprobada](https://github.com/Alvarofritzsolis1/POST/actions/runs/43207879920): 462 pruebas de backend aprobadas, dos escenarios SQLite omitidos y 23 pruebas de lógica frontend aprobadas. Se completaron los recorridos de navegador, persistencia tras reinicio, restauración aislada, permisos y PDF con datos sintéticos. El flujo de despliegue repitió la CI sobre el commit integrado antes de acceder al VPS.

## Maestro e inicialización

El adjunto original se transfirió cifrado con AES-256-GCM y RSA-OAEP; nunca se publicó su contenido ni la clave privada en GitHub. Se comprobó su SHA256 antes de importar:

`4f063b135d5e9c0d7f9806b57d1cd340bd2ecac78fed77345ffa7ccabbead292`

La inicialización se limitó a la única organización que tenía expedientes de Javiera. La segunda organización quedó fuera de la operación. El original se conserva privado y de solo lectura. Se creó la revisión limpia mediante el mismo mecanismo de la API, manteniendo los 18 recursos gráficos originales. La base derivada tiene 34 hojas y 395 fórmulas.

La operación interna completó y comprobó:

- Cero expedientes, emisiones e historial activos en el nuevo espacio de trabajo.
- Cero formatos publicados y fallback documental anterior deshabilitado para esa organización.
- Respaldo verificado del reinicio y archivo reversible de los registros anteriores del espacio.
- Igualdad de los conteos de obras, empresas, trabajadores, asignaciones y usuarios antes y después.
- Conservación de los registros y originales históricos, incluidos los del flujo documental anterior, para retención y rollback.

El envoltorio de la inicialización falló al leer su recibo porque una advertencia de la biblioteca PDF precedió al JSON, después de que el proceso interno terminara correctamente y confirmara sus comprobaciones. No se repitió la importación ni el reinicio. La [comprobación manual posterior](https://github.com/Alvarofritzsolis1/POST/actions/runs/43209533013) terminó correctamente y confirmó un espacio Excel nativo donde antes había cero, manteniendo dos organizaciones y tres administradores.

## Límites y pendientes

CARPINTERO sigue bloqueado por datos preventivos incompletos en la fila 40. La inducción no se publica por el recorte del original. ONLYOFFICE y la equivalencia completa con una impresión patrón de Microsoft Excel siguen pendientes. No se registraron firmas ni aprobaciones profesionales.

Los PDF completos de contrato e IRL PINTOR/GASFITER y su caché se probaron con este adjunto en QA. En el VPS se verificó la conversión sintética indicada arriba. La comprobación ampliada de esos PDF completos sobre el maestro recién importado y la retirada final del directorio temporal cifrado de transferencia no se completaron al quedar inaccesible la consola del entorno de trabajo. Ese directorio temporal es privado de root; el maestro y el original oficiales ya están en el almacenamiento privado de la aplicación.

No se habilitó automatización de verificación en cada push. La revisión automática rechazó esa ampliación. La comprobación posterior se ejecutó manualmente tras demostrar que su código solo realiza consultas SELECT.
