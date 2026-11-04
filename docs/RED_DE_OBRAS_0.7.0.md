# Red de Obras · GALANT POST 0.7.0

Se integra a React/TypeScript, FastAPI y PostgreSQL existentes. Comparte sesiones, organizaciones, usuarios, obras, contratistas, preferencias y control documental. El núcleo no requiere servicios externos ni un proveedor de IA.

## Operación

1. El administrador abre el menú superior, selecciona **Crear cuenta** e invita a un residente con una o varias obras. Varias personas pueden compartir una obra.
2. El residente abre el enlace, establece su contraseña e ingresa directamente a Red de Obras.
3. Publica una necesidad con partidas dinámicas, cantidades, unidades y programación. Puede guardar borradores, reordenar partidas, adjuntar archivos y modificar con motivo e historial.
4. Otro residente publica un contratista registrado en su obra, con partidas pendientes, capacidad, fecha prevista, confirmación y vigencia. Publicar no asigna trabajadores.
5. Las coincidencias explican especialidad, fechas, partidas y trabajadores libres. Registrar interés reutiliza una coordinación y su conversación, con participantes identificados.
6. La obra de origen confirma capacidad. La obra de destino propone y el administrador aprueba. Cada etapa tiene autorización y transición propias.
7. Se adjudica cada partida a una o varias empresas: por ejemplo, 60 y 40 de 100 puertas. Se puede vincular una capacidad confirmada y una coordinación aprobada.
8. Cada partida muestra contratistas, cantidades adjudicadas, saldo, ejecución, fechas y habilitación. Una adjudicación no autoriza ingreso ni ejecución.
9. El seguimiento registra avances y motivos. Una revocación conserva el historial; una modificación de cantidad puede liberar saldo sin reducir lo ejecutado. Las ampliaciones formales requieren administración.

## Permisos

| Operación | Administrador | Residente |
|---|---|---|
| Crear cuentas y modificar permisos | Sí | No |
| Crear o editar publicaciones | Organización | Obras asignadas |
| Consultar capacidad compartida | Organización | Organización |
| Consultar necesidades ajenas | Completo | Vista colaborativa limitada |
| Consultar adjudicaciones y adjuntos detallados | Organización | Obras asignadas |
| Confirmar adjudicación | Sí | Solo con autorización específica en sus obras |
| Leer mensajes y adjuntos de conversación | Como participante | Como participante con alcance vigente |
| Acceder a OCR, documentos laborales y administración | Permisos anteriores | Denegado por el servidor |

Los roles anteriores se conservan. Supervisor y analista pueden coordinar, sin permiso automático de adjudicación. Un administrador se incorpora explícitamente como coordinador a una conversación; la incorporación queda auditada.

Las organizaciones están aisladas. Las vistas compartidas no devuelven documentos laborales, información de trabajadores ni antecedentes financieros. Las escrituras y descargas verifican permisos en el backend.

## Integridad y sincronización

Las tablas `network_*` referencian las entidades existentes. Las cantidades usan `NUMERIC(14,3)`. No se relacionan contratistas por nombres escritos ni se crean bases por usuario.

Las escrituras adquieren un bloqueo transaccional de organización en PostgreSQL y las adjudicaciones bloquean además la partida. Se valida el saldo antes de confirmar, con clave de idempotencia y evento en la misma transacción. Las versiones evitan sobrescribir cambios concurrentes.

`ops_changes` conserva antes, después, usuario, motivo y fecha. No se borran adjudicaciones revocadas. El porcentaje general promedia la cobertura de las partidas, evitando sumar unidades incompatibles.

Los borradores persisten en la base compartida y solo se consultan desde su obra. El navegador no es fuente principal de datos.

## Coincidencias y capacidad

El motor normaliza tildes, espacios y mayúsculas; compara obras diferentes, especialidad, plazo, fecha prevista, tipos de partidas y trabajadores libres. Excluye borradores, publicaciones caducadas, descartadas o comprometidas y necesidades totalmente cubiertas. Expone razones y puntuación; no asigna recursos automáticamente.

Vigencia por publicación entre 1 y 90 días, con 14 días iniciales y advertencia tras siete días sin actualización. Renovar no convierte una estimación en confirmación.

Al vincular capacidad confirmada, se revisan fechas y trabajadores comprometidos. Los conflictos requieren confirmación expresa y motivo cuando existen otras cuadrillas. Una adjudicación directa sin capacidad publicada no constituye reserva de una cuadrilla.

## Habilitación documental

La comprobación consulta la matriz documental original y los controles laborales por **contratista, obra de destino y período**. Requiere asociación activa y requisitos aplicables aprobados. OCR no acredita cumplimiento por sí solo.

Puede registrarse una adjudicación con habilitación pendiente. Pasar a habilitada, en ejecución o finalizada se rechaza cuando falta documentación en destino. La habilitación de otra obra no se hereda. El ingreso físico permanece bajo el proceso original de GALANT.

## Mensajes, calendario y avisos

Publicaciones e indicadores se actualizan aproximadamente cada siete segundos; mensajes cada cuatro, con la pestaña visible. La revisión temporal de alertas se ejecuta cada treinta segundos durante el uso. No genera avisos en segundo plano cuando nadie utiliza el portal.

Los mensajes incluyen participantes, obras, fecha/hora en America/Santiago, historial paginado y lectura acumulativa. Las preferencias controlan notificaciones y las claves de evento impiden repetirlas.

El calendario permite mes, semana, filtros y detalle. La reprogramación se realiza desde formularios autorizados y conserva motivo. El CSV identifica contratistas, cantidades, saldo, ejecución, responsable y habilitación, respeta obras y neutraliza fórmulas introducidas en textos.

## Archivos privados

PDF, JPG y PNG se guardan en `DOCUMENT_DIR/<organización>/network`, dentro del volumen persistente. Cada descarga verifica alcance y participantes. Se valida formato, tamaño y resolución; se rechazan formularios PDF, JavaScript, lanzadores y archivos incrustados. La entrega usa descarga, `nosniff` y CSP sandbox. No se exponen archivos laborales mediante este repositorio.

## Invitaciones y recuperación

PostgreSQL almacena solo SHA-256 de tokens criptográficos. Invitaciones: 48 horas; recuperación: una hora. Un enlace nuevo invalida anteriores y establecer contraseña revoca sesiones. Argon2 y mínimo doce caracteres; nunca se guardan contraseñas en texto plano.

Sin correo configurado, el administrador recibe el enlace para compartirlo por su canal autorizado. La interfaz indica si el envío realmente ocurrió. Para envío y recuperación automática, configurar:

```dotenv
PUBLIC_URL=https://dominio-de-galant.example
SMTP_HOST=servidor-de-correo.example
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=acceso@dominio-de-galant.example
```

SMTP exige STARTTLS y validación de certificados. La recuperación devuelve una respuesta genérica. Suspender o cambiar rol, obras o autorización de adjudicación revoca sesiones; reactivar no restaura cookies anteriores. No se permite suspender o degradar la propia cuenta administrativa.

## Actualización segura

`app/migrations/v0_7_0.py` crea tablas e índices nuevos. No elimina ni cambia filas o columnas históricas. `app.cli migrate-db` aplica idempotentemente 0.6 y 0.7 y registra versiones.

Para una instalación existente, usar `scripts/update-preview.sh`: respaldo PostgreSQL/archivos, restauración aislada verificada, migración y reconstrucción. La migración debe preceder al inicio de la nueva API porque la autenticación consulta la extensión de sesiones. Se conserva el procedimiento de rollback.

`python -m app.cli init-db` se mantiene para instalaciones nuevas o inicialización controlada; no sustituye el respaldo requerido para actualizar datos existentes.

Comprobar `/api/v1/health` y `/api/v1/version`: versión `0.7.0` y SHA desplegado. Verificar administrador, residente, publicación, 60+40 y bloqueo por documentación pendiente. Esta entrega no despliega producción.

## Código y pruebas

- Backend: `network_models.py`, `network_schemas.py`, `network_service.py`, `network_accounts.py`, `network_api.py`, `network_files.py`.
- Frontend: `Network.tsx`, `NetworkForms.tsx`, `NetworkAccounts.tsx`, `NetworkUI.tsx`, `networkApi.ts`, `network.css`.
- Integración: `main.py`, `security.py`, `admin_api.py`, `cli.py`, `App.tsx`, `DocumentAnalysis.tsx`.
- Verificación: `tests/test_network.py`, suite histórica y `scripts/qa_network_browser.py`.
