# GALANT 20.9.7-rc1 — Publicaciones y comentarios de Facebook

## Qué incorpora
- Interfaz GALANT compacta y adaptable: filtros, búsqueda, orden por comentarios, revisión, detalle y enlace.
- Datos del post realmente confirmados por Meta: texto, comentarios, reacciones, compartidos. Un guion significa métrica no disponible, **no cero visitas**.
- Sincronización limitada (máximo 150 comentarios por publicación), con nombre **solo si Meta entrega** el campo del autor. Ningún dato se inventa.
- Respuesta pública, ocultar/restaurar comentarios y editar texto, todo sujeto a permisos de la página.
- Respuesta privada **una sola vez** por comentario, solo si Meta entrega can_reply_privately y el comentario tiene menos de 7 días.
- El identificador público del autor de un comentario NO se confunde con el PSID de Messenger. Si Meta confirma recipient_id y luego la persona responde por Messenger, aparece "Abrir chat" en el comentario asociado.
- Cola durable, confirmación real de estado, bloqueo de envíos inciertos, recuperación prudente después de reiniciar.
- Solicitud de eliminación por el publicador existente, con confirmación de Meta y desactivación de futuras sincronizaciones de la necesidad.

## Permisos identificados
pages_show_list, business_management, pages_messaging, pages_read_engagement,
pages_manage_metadata, pages_read_user_content, pages_manage_posts,
pages_manage_engagement.

**No se usa read_insights** ni se atribuyen visitas/alcance a las reacciones. La disponibilidad de comentarios, nombres, respuestas privadas y eliminación depende de permisos efectivos en el token de página, tareas MODERATE/MESSAGING/CREATE_CONTENT y acceso avanzado si la cuenta es externa a la app.

## Arquitectura de seguridad
- FACEBOOK_PAGE_TOKEN se usa solo dentro de facebook-publisher; la API de GALANT no lo necesita ni lo devuelve.
- El backend filtra por organización, página, post y comentario. Solo administradores pueden consultar/modificar.
- El proceso de publicaciones tiene un hilo dedicado para no bloquear Messenger/Galancito.
- Se aceptan exclusivamente IDs numéricos de Meta, no URLs externas como recurso del Graph API.
- La respuesta privada conserva estado pending/sent/failed/uncertain y no se vuelve a enviar automáticamente después de un resultado incierto.
- Solo se asocia una conversación existente cuando hay PSID confirmado por Meta y respuesta entrante; no se infiere identidad por nombre.
- Operaciones documentadas en auditoría por administrador; no se publican tokens en logs ni respuestas.

## Pasos de actualización
1. Validar CI, pruebas unitarias y compilación frontend.
2. Migrar base de datos con python -m app.cli migrate-db dentro del backend o el flujo de despliegue ya utilizado. Migración aditiva 20.9.7_facebook_publications; **no borra** mensajes ni datos históricos.
3. Desplegar backend, frontend y facebook-publisher desde el mismo commit. La migración debe ocurrir antes de iniciar el nuevo worker.
4. Verificar página y token en el diagnóstico GALANT. Abrir una publicación confirmada y pulsar **Sincronizar**.
5. Con una cuenta de prueba autorizada para la app, publicar un comentario. Verificar nombre cuando Meta lo permita; responder públicamente y confirmar el job.
6. Con una cuenta externa (si el acceso avanzado está aprobado), probar **una sola** invitación privada, responderle desde Messenger y comprobar "Abrir chat".
7. Verificar edición, moderación y eliminación en una publicación creada para pruebas. **Nunca** usar un anuncio real para la primera eliminación.
8. Validar los permisos de MODERATE/MESSAGING/CREATE_CONTENT y los rechazos de Meta antes de declarar el módulo plenamente operativo.

## Límites deliberados
- No se inician conversaciones arbitrarias ni se envían mensajes de seguimiento fuera de la ventana de Meta.
- Las publicaciones listadas son las que GALANT tiene enlazadas a necesidades de Red de Obras; no se importa indiscriminadamente el muro entero.
- Los 150 comentarios más recientes disponibles se consultan en un máximo de tres páginas. Si hay más, se recomienda completar la revisión en Facebook.
- El token, scopes reales, app review y autorización de cuentas externas requieren comprobación en producción; **el código solo no prueba que Meta haya aceptado envíos reales**.
- No afirmar que el despliegue está terminado hasta comprobar versión y SHA en /api/v1/health y una interacción real.

## Pruebas
pytest -q apps/backend/tests/test_facebook_publications.py desde un entorno con el paquete backend importable.
npm run build dentro de apps/frontend.
No se hacen solicitudes reales a Meta en tests; se reemplazan por resultados sintéticos.
