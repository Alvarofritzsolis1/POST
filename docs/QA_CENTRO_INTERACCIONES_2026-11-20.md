# GALANT · Centro de Interacciones de Facebook — control de calidad

> Estado: **BORRADOR. NO desplegar ni fusionar a producción** hasta completar todos los criterios, incluidos los verificados con la Página Meta real.

## Alcance implementado

- Pestaña propia «Interacciones» en el Centro de Facebook, manteniendo «Publicaciones», «Conversaciones» y «Seguimiento» existentes.
- Bandeja ligera y accesible: filtros, búsqueda, autor y fotografía exclusivamente cuando Meta las entrega, iniciales sin suplantación cuando no las entrega.
- Lectura reciente de comentarios + respuestas del hilo, webhooks ya existentes, refresco periódico acotado; consultas en orden inverso cuando Graph API lo permite.
- Clasificación preliminar local (interesado, consulta, positivo, negativo, spam, ambiguo, atención humana) con corrección manual persistente y botón explícito para análisis con Galancito.
- Respuestas públicas manuales; respuesta privada **solo si Meta habilita la opción**. La sugerencia IA no publica mensajes; editor con borrador preservado hasta confirmación real del worker.
- Moderación manual de Me gusta, ocultar, restaurar y eliminar. No se presenta una operación en cola como éxito; entrega desconocida nunca se reintenta sin verificación.
- Trazabilidad con operador, fecha, tipo de acción, estado, mensaje y clasificación; notas de seguimiento.
- Fichas de información **declarada** (oficios y equipo), enlaces a necesidades vigentes por oficio explícito, identidad de Messenger únicamente si hay PSID legítimo y respuesta entrante.
- Actividad repetida de un autor solo cuando coincide **exactamente el identificador de Meta** y la Página; nunca se agrupa por nombre/fotografía.
- Corrección del acceso global: «Configuración de automatización» visible exclusivamente en Proyecto JAVIERA.
- Diseño responsive y pruebas reales de Chromium, que verifican posicionamiento de controles dentro de 390 px y ausencia de publicaciones automáticas durante QA.

## Salvaguardas

1. **Modo manual predeterminado**. No se habilita el envío automático por llegar un comentario público.
2. Para mensajes privados se exige elegibilidad de Meta, plazo y una sola invitación; nunca se toma un ID de comentarista público por el PSID de Messenger.
3. Las eliminaciones tienen confirmación humana y requieren éxito de Meta antes de actualizar estado.
4. Los datos de autor se muestran solo si Meta los provee; no se recogen imágenes desde scraping.
5. El servidor comprueba permisos administrativos y organización. El token de Página nunca llega al navegador.
6. El clasificador diferencia rechazo, preguntas y críticas de un interés real; no hace juicios sobre la persona ni promete empleo.
7. Los fallos o resultados inciertos conservan el borrador y generan un estado visible.

## Validaciones técnicas obligatorias

- [ ] CI completo de backend (incluye todas las pruebas históricas, sin regresiones).
- [ ] CI frontend TypeScript y Vite.
- [ ] Pruebas focalizadas de Facebook (SQLite y PostgreSQL; Meta simulado).
- [ ] Chromium de escritorio y móvil con comentarios sintéticos, sin envíos reales.
- [ ] Revisión visual de las capturas generadas.
- [ ] Revisión de permisos y acceso avanzado de la Página Meta real.
- [ ] Publicar, ocultar, restaurar, eliminar, reaccionar y respuesta privada en Página Meta real con autorización apropiada, comparando registros y estados.
- [ ] Verificar webhook real y recuperación de eventos faltantes tras desconexión.
- [ ] Revisar compatibilidad de datos personales con políticas de Meta y normas aplicables.
- [ ] Prueba aislada de despliegue/retorno a versión anterior con respaldo verificado.

**No confundir pruebas sintéticas completas con aceptación en producción.** Las operaciones reales requieren la autorización y configuración de la Página que no se proporciona en GitHub Actions.

## Despliegue

No crear despliegue desde esta rama sin aprobación de QA y verificación Meta real.
Aplicar migraciones aditivas únicamente con respaldo comprobado, probar en entorno aislado y conservar procedimiento de reversión. Nunca acceder al token desde el navegador.

## Pendiente por diseño

El modo automático y las respuestas masivas no se habilitan: primero deben definirse condiciones de elegibilidad, límites antiabuso, política de aprobación humana y pruebas con la cuenta Meta real. El modo de respuestas actuales es **manual y supervisado por persona**. No informar al usuario de que la automatización total está disponible.
