# Actualización futura de GALANT POST 0.6.0-rc1 en VPS

Este borrador local no está publicado. Los comandos siguientes sirven cuando exista un commit aprobado y accesible desde el repositorio del VPS. No sustituir el SHA por un nombre mutable de rama.

1. Con el checkout limpio, verificar `.env.preview`, estado de los servicios y espacio suficiente para un respaldo PostgreSQL más documentos. Conservar una copia externa del respaldo.
2. Revisar el commit completo y su diff. Ejecutar `sudo bash scripts/update-preview.sh SHA_COMPLETO_DE_40_CARACTERES` en `/opt/galant-post`. El script exige root, respaldo `pg_dump` más `preview-storage`, validación de SHA256 y restauración aislada antes de construir y activar las imágenes. Ejecuta la migración aditiva en un contenedor temporal antes de cambiar la API en servicio y aborta si falla.
3. Comprobar `curl -fsS http://127.0.0.1:18512/api/v1/health`. Debe informar `version: 0.6.0-rc1` y `commit: <SHA desplegado>`. Revisar `sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps` y los logs de API/worker sin imprimir datos personales. Verificar acceso a PDF históricos y nuevos, conteos de organizaciones, usuarios, contratistas, trabajadores y contratos; reiniciar los servicios de QA y contrastar los mismos IDs y SHA de documentos.
4. Dos usuarios de la misma organización deben ver las mismas personas y cambios. Una cuenta externa no debe consultar esas fichas; un revisor documental puede revisar un finiquito sin editar contratos. Probar una planilla autorizada en vista previa antes de confirmar.
5. En **Control de asistencia**, elegir obra y mes, comprobar la base de contratistas activos y ajustar inclusión/exclusión con motivo. Crear una cuenta «Administrativa (asistencia)», marcar firmas de una semana ya terminada, adjuntar PDF/imagen o escribir una nota detallada y completar. Comprobar quién la ingresó y cuándo, revisión conforme/observada por supervisor, balance con días pagados y alerta roja de otras semanas atrasadas. Confirmar que un independiente no genere alerta automática y que excluir una empresa no borre sus semanas previas. La semana 5 de febrero de 28 días debe indicar «No aplica». Descargar la planilla Excel de cinco hojas. El plazo está en `attendance_due_days` dentro de Configuración → Catálogos; por defecto son dos días tras cada semana.
6. En Configuración → Recuperación de clasificaciones, generar vista previa. El actualizador registra el respaldo verificado y su SHA256. Revisar cada evidencia, conflicto y nombre sospechoso; confirmar solo las filas verificables y corregir manualmente las ambiguas. Exportar o conservar el informe devuelto antes de otra reconciliación. Un respaldo nuevo posterior puede registrarse **solo después** de ejecutar `scripts/backup-preview.sh` y `scripts/verify-restore-preview.sh`:

```bash
cd /opt/galant-post
sudo bash scripts/backup-preview.sh
sudo bash scripts/verify-restore-preview.sh /RUTA/DEL/BACKUP
sha256sum /RUTA/DEL/BACKUP/postgres.dump
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api \
  python -m app.cli register-verified-backup --verified-backup-sha256 SHA256_DEL_DUMP
```

El respaldo registrado solo habilita la reconciliación durante 24 horas; no sustituye conservar el dump y los documentos. Si una actualización falla, el script vuelve al checkout previo y reconstruye sus contenedores. Las tablas nuevas son aditivas. No ejecutar `down -v`, borrar `preview-storage` ni restaurar sobre datos activos sin revisar qué operaciones ocurrieron tras el respaldo.
