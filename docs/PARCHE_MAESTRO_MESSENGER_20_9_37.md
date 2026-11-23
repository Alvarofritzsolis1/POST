# GALANT 20.9.37-rc1 — PARCHE MAESTRO DE AYUDA SIMPLE EN MESSENGER

## Objetivo
Ayudar de verdad a trabajadores y pequeños contratistas con poca experiencia digital. Evitar exigir enlaces, nombres de obra, capturas, formularios o conocimientos técnicos. Responder con vocabulario chileno sencillo, sin infantilizar, sin presentaciones reiteradas como «Galancito» y sin inventar vacantes, sueldos, adjudicaciones ni datos personales.

## Incidente real: cadena ignorada
1. Persona: «Vi una postulación de trabajo».
2. GALANT: «¿Qué aviso viste? Con el nombre de la obra o el link…».
3. Persona: «DE GASFITER».
4. GALANT: «Con ese dato aún no ubico el aviso. ¿Tienes el link…?».

Causa en código: \`facebook_worksite_reply.application_reply\` solamente buscaba coincidencia literal por título/obra/URL. Ante un dato de oficio, ignoraba \`trade_terms()\` y terminaba exigiendo enlace. La máquina confundía «oficio del aviso» con «experiencia del usuario» si se omitían las protecciones de memoria.

## Nuevas decisiones conversacionales
- «Vi un aviso» -> «¿De qué trabajo era el aviso?».
- «De gasfiter» -> «Ah, era un aviso de gasfitería. ¿Buscas trabajo para ti o quieres ofrecer tus servicios?».
- «Yo solo» -> «¿Trabajas en gasfitería?». Es una pregunta de confirmación; NO guarda como profesión el oficio que apareció en el aviso.
- «Sí» a esa pregunta -> recién entonces registra Gasfitería como oficio declarado; pregunta por comuna.
- «No», «No me acuerdo», «no tengo link», «no sé usar Facebook», «nose», «gafiter», «mi equipo», «no entiendo», etc. -> respuestas contextuales que no repiten requisitos técnicos.
- Cuando una publicación vigente y confirmada coincide en GALANT, se puede mencionar su nombre y obra, SIN exigir un clic ni afirmar que hay una contratación garantizada.
- Si existen múltiples avisos similares, no se asume cuál es el correcto; se pide una pista sencilla, mientras se continúa la orientación laboral.
- Una consulta nueva no vinculada al aviso (por ejemplo, sueldo o documentación) vuelve a su ruta correcta.

## Humanización y traspaso
Dos motivos de derivación humana: **solicitud expresa** de la persona o **incapacidad objetiva** del sistema para confirmar una respuesta/situación que requiere intervención. La función común \`flag_for_human\` registra el motivo, alerta a administración y activa simultáneamente \`needs_support=true\` y \`ai_paused=true\`.

Una derivación emite un mensaje breve de confirmación; se permite enviar solo ese mensaje aunque la IA ya haya quedado pausada. Otras respuestas automáticas en cola son canceladas, sin descartar las redactadas por un operador.

La ficha de Messenger muestra el motivo y un botón **«Volver a respuestas por IA»**. Al pulsarlo por un administrador:
- Se limpian juntos ambos estados (\`needs_support=false\` y \`ai_paused=false\`).
- Se conserva todo el historial y el estado real de consentimiento.
- No se autoriza IA externa en nombre del contacto. Si la persona rechazó IA, el botón está deshabilitado y se explica que ella debe autorizarla nuevamente.
- La IA reanudada responde a **nuevos mensajes**, nunca reenvía retroactivamente una respuesta que fue cancelada.

## Seguridad
Conservar control de firma del webhook, aislamiento por organización, aprobaciones de documentación, consentimiento del proveedor, privacidad de datos y ventana 24 h de Meta. No se modifica MAX POWER, pesos LoRA, modelos Qwen, base de datos documental ni infraestructura.
La causa de una falla se registra como motivo de atención humana; no se promete a la persona que un empleo está disponible cuando el sistema no puede confirmarlo.

## Validación exigida
- Frases y modismos reales, errores ortográficos, ausencia de enlaces, no saber usar Facebook, roles de cuadrilla vs postulante, datos citados de un aviso vs declaraciones personales.
- Secuencia Messenger webhook firmado -> cola -> worker -> estado de ficha.
- Dos disparadores de derivación humana, acuse único posterior a la pausa, cancelación de pendientes y reactivación sin alterar consentimientos.
- Probar en simulador y con contactos de prueba en Meta, sin exponer mensajes de terceros.
- Las pruebas de CI son simuladas y **no** demuestran que Messenger real haya entregado el mensaje. Verificar producción tras merge/deploy.

## Versionado
Creado sobre GALANT 20.9.35-rc1 de \`main\`. La versión editorial 20.9.36-rc1 está en PR #166; este parche usa 20.9.37-rc1. Si la base cambia antes del merge, actualizar el parche sin sobrescribir otras versiones y volver a correr CI. Despliegue solo con el control automático de incremento de versión y pruebas completas satisfactorias.
