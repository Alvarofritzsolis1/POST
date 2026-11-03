# GALANT POST — cuentas compartidas y documentación mensual

> Actualización 0.5.0-rc1: `link-user` ahora muestra un plan sin aplicar cambios. Para una vinculación vacía exige `--apply --backup` y respaldo validado. Ver [procedimiento vigente](VPS_0.5.0.md). La revisión manual sin PDF ya existe en el centro de control; las restricciones del módulo inicial descritas más abajo son antecedentes históricos.

## Diagnóstico comprobado en el código

El comando `create-admin` crea una nueva fila de `organizations` y asigna al administrador un `org_id` propio. Los endpoints de contratistas y archivos aplican correctamente `org_id` para aislar empresas distintas. **No eliminar los filtros por organización:** el arreglo consiste en asignar colaboradores internos al mismo `org_id` de su empresa.

Hasta esta intervención, los documentos OCR no tenían una relación con contratista/obra/mes. La tabla adicional `monthly_documents` guarda esa asociación y el estado de revisión humana sin alterar los PDF ni su resultado OCR.

## Seguridad antes de desplegar

1. Confirmar que se está trabajando en `/opt/galant-post` y que `.env.preview` existe allí (no en `/root`).
2. Respaldar PostgreSQL y el directorio `preview-storage`. Verificar que pueden recuperarse.
3. Revisar el PR y sus pruebas. No fusionar ni activar despliegue automático antes de comprobarlos.
4. Actualizar el código y ejecutar `sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -m app.cli init-db`. El comando crea las tablas faltantes, no borra datos.
5. Comprobar `/api/v1/health`, acceso a contratistas y documentación de un período con dos usuarios.

No usar `docker compose down -v` ni mover manualmente los `org_id` en PostgreSQL.

## Agregar usuario a la misma empresa

Desde `/opt/galant-post`:

```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-user --email NUEVO@EMPRESA.CL --admin-email ADMIN_ORIGINAL@EMPRESA.CL --role analyst
```

El comando solicita la contraseña del nuevo usuario sin mostrarla. Roles admitidos: `admin`, `analyst`, `viewer`.

Si la cuenta **ya existe y fue creada con `create-admin` por error**, se puede vincular solamente si no tiene datos operativos propios y es la única cuenta de su organización:

```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli link-user --email CUENTA_EXISTENTE@EMPRESA.CL --admin-email ADMIN_ORIGINAL@EMPRESA.CL --role analyst
```

Este último comando no borra ni mezcla datos. Si la organización de origen contiene contratistas, documentos, modificaciones o usuarios adicionales, cancela la operación e informa que hace falta una migración supervisada. Cerrar sesión e ingresar de nuevo para actualizar el token de organización.

## Documentos de un mes

Abrir **Contratistas**, seleccionar obra y contratista. En **Documentación mensual**, elegir mes, subir un archivo o asociar un documento OCR previamente cargado. El PDF original permanece en su almacenamiento privado y el registro en PostgreSQL conserva contratista, obra, mes, tipo de documento, revisión, notas y usuarios responsables.

Estados: pendiente, aprobado, observado, rechazado o no aplica. Los documentos sin PDF solo permiten la excepción **No aplica**; aprobar requiere evidencia adjunta. Los registros anteriores no se asignan automáticamente porque un mismo nombre de archivo podría corresponder a otra empresa o mes.

El módulo es una primera versión de vinculación y revisión: **no sustituye aún una matriz normativa completa**, el cálculo de retenciones ni la acreditación externa del pago.

## Prueba mínima de aceptación

- Cuenta A crea contratista y carga cotizaciones del mes.
- Cuenta B de la misma organización visualiza el contratista, el mes y el mismo archivo.
- Cuenta B registra aprobación u observación. Cuenta A ve ese resultado.
- Una cuenta con rol viewer consulta, pero no modifica.
- Una cuenta de otra organización no tiene acceso a esos registros.
- Reiniciar contenedores sin borrar volúmenes y verificar que la información permanece.
- Validar que los PDF antiguos del OCR se puedan asociar manualmente sin perder su contenido.
