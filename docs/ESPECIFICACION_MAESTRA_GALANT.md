# GALANT — ESPECIFICACIÓN MAESTRA OPTIMIZADA PARA CODEX

## 1. TU MISIÓN

Actúa como un ingeniero de software sénior especializado en sistemas empresariales, automatización de procesos, gestión de contratistas, bases de datos y desarrollo web.

Trabajarás sobre mi repositorio GitHub **POST**, correspondiente a mi plataforma GALANT.

Tu objetivo no es simplemente agregar módulos: debes convertir GALANT en un sistema operativo para el control administrativo, contractual y documental de empresas contratistas.

El sistema debe reemplazar progresivamente mis planillas Excel, facilitar las revisiones manuales, automatizar cálculos, identificar problemas y generar reportes confiables.

**La prioridad principal es que la plataforma funcione con datos ingresados manualmente o importados desde Excel. Por ahora no dependerá de documentos PDF ni del motor OCR.**

No desarrollar pantallas de demostración que carezcan de funcionamiento real.

## 2. INSTRUCCIONES DE IMPLEMENTACIÓN

Antes de escribir código:

1. Inspecciona la estructura real del repositorio.
2. Identifica frontend, backend, base de datos y servicios existentes.
3. Revisa las convenciones y pruebas del proyecto.
4. Identifica funcionalidades reutilizables.
5. Detecta riesgos de migración y compatibilidad.
6. Define un plan por etapas, con criterios de aceptación.
7. Implementa la primera etapa funcional de extremo a extremo.
8. Continúa con las etapas siguientes cuando las verificaciones correspondientes estén superadas.

No intentes reemplazar toda la arquitectura sin una justificación técnica.

Evita crear estructuras duplicadas, sistemas paralelos o funciones incompletas.

Para cada etapa, entrega cambios verificables en el repositorio, pruebas y una explicación clara de lo implementado.

## 3. CÓMO DEBE FUNCIONAR GALANT

GALANT debe permitir el siguiente flujo operativo:

1. Seleccionar una obra.
2. Seleccionar el mes de auditoría.
3. Visualizar los contratistas asociados.
4. Consultar sus trabajadores.
5. Revisar los documentos exigibles.
6. Registrar manualmente información.
7. Comparar asistencia y cotizaciones.
8. Identificar diferencias.
9. Aprobar u observar documentos.
10. Gestionar contratos, vencimientos y tareas.
11. Actualizar automáticamente los indicadores.
12. Exportar informes.

Todo debe estar diseñado para minimizar clics y evitar la doble digitación.

La plataforma debe priorizar los registros con problemas y permitir realizar gestiones masivas.

## 4. OBRAS INDEPENDIENTES

Crear tres obras:

- Lomas Verdes.
- Brisas de Junquillar.
- Concepción.

Cada obra tendrá datos operativos independientes:

- Contratistas asociados.
- Trabajadores asignados.
- Documentación.
- Contratos y vigencias.
- Asistencia.
- Cotizaciones.
- Alertas.
- Revisiones.
- Indicadores.

Una empresa podrá pertenecer a varias obras, pero cada relación contractual y cada período documental deberán administrarse por separado.

Crear un Dashboard General con los indicadores consolidados.

## 5. CLASIFICACIÓN DE CONTRATISTAS

En mis datos actuales:

- **CT:** contratistas fijos.
- **CI:** contratistas independientes.

Conservar los demás códigos originales sin asignarles interpretaciones desconocidas.

Separar los siguientes conceptos:

**Código histórico:** CT, CI u otros.

**Naturaleza:** independiente sin trabajadores dependientes o contratista con trabajadores.

**Frecuencia:** fijo, esporádico o sin clasificar.

**Estado contractual:** activo, en proceso de baja o dado de baja.

**Actividad mensual:** con movimientos, sin movimientos o pendiente de confirmar.

Estos campos no deben confundirse.

La clasificación debe ser editable y estar respaldada por historial de cambios.

## 6. BASE DE DATOS E IMPORTACIÓN MASIVA

Crear una estructura relacional para:

- Obras.
- Contratistas.
- Relaciones contratista-obra.
- Trabajadores.
- Asignaciones de trabajadores.
- Contratos de trabajadores.
- Relaciones contractuales de contratistas.
- Períodos.
- Requisitos documentales.
- Revisiones.
- Asistencia.
- Cotizaciones.
- Diferencias.
- Retenciones sugeridas.
- Alertas.
- Tareas.
- Bajas.
- Documentos y evidencias.
- Usuarios y auditoría.

### Carga manual

Crear formularios rápidos para registrar empresas y trabajadores.

### Carga masiva

Permitir importar Excel y CSV.

Mi Excel histórico contiene filas de contratistas, filas de trabajadores y columnas mensuales repetidas.

Debes desarrollar un importador que:

1. Identifique la estructura de la planilla.
2. Distinga empresas y trabajadores.
3. Relacione correctamente sus registros.
4. Reconozca códigos y fechas.
5. Valide RUT chilenos.
6. Detecte duplicados.
7. Muestre una vista previa.
8. Permita corregir errores.
9. Conserve los estados históricos.
10. Informe exactamente qué datos fueron importados.

Los valores históricos como OK, P y NA deberán mapearse mediante reglas confirmadas por el usuario.

No confundir una aprobación histórica registrada en Excel con una verificación respaldada por un PDF.

Crear plantillas descargables para empresas, trabajadores y registros mensuales.

No usar fórmulas Excel como única validación; toda regla importante debe verificarse también en el backend.

## 7. CONTROL DE DOCUMENTACIÓN

La auditoría inicial será **septiembre de 2026**.

Implementar estos requisitos:

1. Pago de cotizaciones.
2. F30-1.
3. Liquidación firmada.
4. Libro de asistencia.
5. Informe de portería.
6. Declaración jurada.
7. Listado de anticipos.

### Aplicabilidad

La declaración jurada corresponde a independientes, según su periodicidad y las reglas internas configuradas.

El listado de anticipos corresponde a contratistas con trabajadores dependientes, cuando resulte exigible.

Los independientes nunca deben recibir el requisito de listado de anticipos.

Los contratistas con trabajadores no deben recibir automáticamente la declaración jurada exclusiva de independientes.

Los otros cinco requisitos deberán aplicar según la situación, clasificación y reglas configuradas.

No todos los documentos son individuales: cotizaciones y F30-1 pueden tener alcance de empresa y cubrir varios trabajadores.

Cada documento deberá relacionarse correctamente con los trabajadores comprendidos.

### Estados documentales

- No exigible todavía.
- Pendiente de entrega.
- Pendiente de revisión.
- Aprobado.
- Observado.
- No aplica.

Permitir confirmar que no existieron anticipos en el período, sin generar una aprobación ficticia.

## 8. APROBACIÓN MANUAL

Crear botones visibles:

**Aprobar | Observar | Pendiente | No aplica**

Cuando apruebe un documento:

- Guardar usuario.
- Guardar fecha y hora.
- Guardar origen de la aprobación.
- Mantener historial.
- Actualizar indicadores.

No exigir PDF en esta primera etapa.

Distinguir:

- Aprobado manualmente sin respaldo digital.
- Aprobado con respaldo documental.
- Estado importado desde Excel, pendiente de validación cuando corresponda.

Permitir aprobar varios registros seleccionados, con confirmación y trazabilidad.

Cuando se cambie un dato relevante después de aprobarlo, marcar la revisión como pendiente de nueva validación.

## 9. CONTROL MANUAL DE COTIZACIONES Y ASISTENCIA

Este módulo es prioritario.

Crear una tabla editable directamente desde la interfaz.

Por trabajador, registrar:

- Obra.
- Contratista.
- Período.
- Nombre.
- RUT.
- Días de asistencia.
- Días exigibles para la comparación.
- Días declarados o pagados en cotizaciones.
- Confirmación del pago.
- Diferencia de días.
- Valor diario de retención.
- Retención sugerida.
- Estado de revisión.
- Observaciones.

### Cálculo

Diferencia faltante = MAX(0, días exigibles - días pagados).

Retención sugerida = diferencia faltante × tarifa diaria.

Tarifa inicial configurable: **$4.950 CLP por día**.

Ejemplos:

- 25 días exigibles y 25 pagados: $0.
- 25 días exigibles y 27 pagados: $0.
- 25 días exigibles y 24 pagados: $4.950.
- 25 días exigibles y 23 pagados: $9.900.

Si existen más días pagados que exigibles, no generar una alerta negativa por esa diferencia.

Si faltan días, mostrar una observación destacada y el monto correspondiente.

### Regla fundamental

No asumir que días de asistencia y días exigibles de cotización son siempre iguales.

Permitir ajustar los días exigibles con una justificación, considerando situaciones como licencias, permisos, descansos u otras diferencias que requieran revisión.

No confundir el número de días pagados con la confirmación efectiva del pago.

Un registro puede tener días correctos, pero pago todavía no verificado.

### Retenciones

El monto calculado es una **propuesta administrativa**, no una retención aplicada automáticamente.

Crear los estados:

- Sin diferencia.
- Diferencia detectada.
- Diferencia justificada.
- Retención propuesta.
- Retención confirmada por usuario autorizado.
- Resuelto.

No descontar dinero ni modificar estados de pago automáticamente.

Permitir revisar posteriormente la procedencia del monto según contrato y reglas aplicables.

## 10. REVISIÓN DE INDEPENDIENTES

Los contratistas CI deben poder revisarse directamente, sin crear trabajadores ficticios.

Registrar la información previsional del independiente vinculada a su RUT, obra y período.

Sus reglas de pago y días exigibles deben poder configurarse separadamente de las aplicables a trabajadores dependientes.

No aplicar automáticamente la fórmula de retención por días si su régimen o documentación no permite establecer una comparación equivalente.

Mantener registro de:

- Pago verificado.
- Período.
- Días de cobertura, cuando correspondan.
- Diferencias.
- Observaciones.
- Declaración jurada.
- Estado de revisión.

## 11. INFORME GENERAL DE COTIZACIONES CT Y CI

Crear un informe exclusivo de los contratistas cuyo código sea:

- CT.
- CI.

Excluir todos los demás códigos de este informe específico.

Mostrar:

- Obra.
- Contratista.
- RUT.
- Código.
- Período.
- Trabajadores revisados, cuando corresponda.
- Días exigibles.
- Días pagados.
- Diferencias.
- Retención sugerida.
- Confirmación de pago.
- Estado.
- Responsable.
- Observaciones.

Para los CT, calcular las diferencias individualmente por trabajador y luego sumar.

No compensar días faltantes de un trabajador con días pagados de más por otro.

Para los CI, aplicar las reglas específicas de independientes.

Mostrar totales por contratista, obra y consolidado general.

Distinguir registros revisados de registros todavía sin información.

Permitir exportar Excel.

## 12. CONTRATOS Y VIGENCIAS

Implementar dos controles distintos:

**Contratos de trabajadores:** relación laboral, tipos de contrato, inicio, término, anexos y prórrogas.

**Relación contractual del contratista con la obra:** vigencia, fecha de término, actividad y proceso de baja.

Alertas configurables a 30, 15 y 7 días, y cuando exista un vencimiento confirmado.

No considerar vencido un contrato indefinido simplemente porque no tiene fecha de término.

Permitir registrar vigencias desde Excel y adjuntar documentos posteriormente.

Conservar historial.

## 13. CONTRATISTAS SIN MOVIMIENTOS

Permitir marcar a un contratista sin movimientos por obra y mes.

Registrar motivo, responsable y fecha.

No excluirlo de otras obras o períodos.

No borrar sus trabajadores ni contratos.

Excluir solamente los requisitos que efectivamente no sean exigibles durante ese período.

Si aparecen movimientos de asistencia o portería incompatibles, alertar al administrador.

Generar una tarea:

**"Revisar continuidad contractual y determinar si corresponde carta de término".**

No dar de baja ni generar cartas automáticamente por ausencia de movimientos.

## 14. BAJAS Y CARTAS DE TÉRMINO

Crear un procedimiento de baja:

1. Solicitud.
2. Revisión de antecedentes.
3. Revisión contractual.
4. Determinación de procedencia de carta.
5. Preparación.
6. Registro de envío.
7. Cierre administrativo.

Permitir marcar expresamente "No corresponde carta", con justificación.

No confundir una baja de obra con la eliminación de una empresa de la base general.

Conservar todos los antecedentes.

## 15. CALENDARIO DE PROCESOS

El sistema debe distinguir:

- Mes al que corresponde el documento.
- Fecha de inicio de solicitud.
- Fecha límite interna.
- Fecha de generación de alertas.

Ejemplo:

Cotizaciones de octubre de 2026.

Inicio de solicitud interna: **10 de noviembre de 2026**.

Antes de esa fecha, no debe marcarse como documentación atrasada por el solo hecho de no estar entregada.

Desde esa fecha, el sistema activará la solicitud correspondiente.

La fecha deberá poder modificarse desde la interfaz.

Permitir programar cada tipo de documento por mes y obra.

Los procesos automáticos deberán ejecutarse sin necesidad de mantener abierto el navegador.

No inventar fechas para requisitos que todavía no tienen una regla configurada.

## 16. DASHBOARD Y GRÁFICOS

Crear un panel principal inspirado en los indicadores INE de mi Excel.

Indicadores:

- CT.
- CI.
- Esporádicos.
- Contratistas activos.
- Sin movimientos.
- Dados de baja.
- Total de trabajadores.
- Contratos vigentes.
- Contratos próximos a vencer.
- Cumplimiento documental.
- Avance de revisión.
- Diferencias de cotizaciones.
- Retenciones sugeridas.
- Cartas pendientes.
- Actividades por resolver.

Gráficos:

- Cumplimiento de las tres obras.
- Evolución mensual.
- Avance de auditoría.
- Distribución de contratistas.
- Estados documentales.
- Contratos por vencer.
- Diferencias de cotizaciones.
- Retenciones propuestas por obra.

### Reglas de cálculo

Cumplimiento = requisitos aprobados / requisitos exigibles.

Avance = requisitos con revisión concluida / requisitos exigibles.

Las aprobaciones históricas importadas deben quedar identificadas por su origen.

No considerar como incumplimiento un requisito aún no exigible.

No mostrar 100% cuando no existen datos evaluables.

El consolidado deberá calcularse sobre la suma real de requisitos de las obras, no promediando porcentajes sin ponderación.

Evitar contar dos veces empresas que tienen varias asignaciones.

## 17. CENTRO DE ALERTAS Y TAREAS

Crear un panel que responda:

**¿Qué tengo pendiente de gestionar hoy?**

Mostrar prioritariamente:

- Cotizaciones con diferencias.
- Pagos pendientes de verificar.
- Documentos pendientes de aprobación.
- Contratos próximos a vencer.
- Contratos vencidos.
- Contratistas sin movimientos.
- Cartas de término pendientes.
- Procesos documentales que se activan.
- Auditorías pendientes.

Cada alerta tendrá responsable, prioridad, fecha, estado y observaciones.

Permitir registrar la acción realizada y cerrar la tarea cuando esté resuelta.

## 18. DOCUMENTACIÓN Y OCR

Preparar desde ahora la arquitectura para guardar archivos PDF, Excel y otros respaldos autorizados.

Sin embargo, **no exigir carga documental para utilizar la plataforma**.

Conservar el módulo existente:

**Revisión OCR — Beta**

No rehacerlo durante este desarrollo.

El funcionamiento manual de GALANT debe ser independiente del OCR.

Posteriormente, el motor OCR podrá alimentar las mismas estructuras de datos utilizadas por la revisión manual, sin reemplazar las decisiones del usuario.

## 19. EXPERIENCIA DE USUARIO

Diseñar GALANT para una persona que necesita revisar numerosos contratistas y trabajadores diariamente.

Priorizar:

- Tablas editables tipo Excel.
- Guardado confiable.
- Filtros rápidos.
- Búsqueda por RUT y nombre.
- Aprobación con un clic cuando corresponda.
- Edición y revisión masiva.
- Indicadores siempre visibles.
- Alertas claras.
- Navegación entre trabajadores.
- Exportación rápida.
- Formularios simples.

No abrir múltiples pantallas para realizar operaciones sencillas.

El sistema debe ofrecer vistas generales y permitir acceder al detalle sin perder el contexto de obra y período.

## 20. PRUEBAS DE ACEPTACIÓN

Para comprobar que el proyecto funciona, crear pruebas sobre estos escenarios:

**Escenario A: importación masiva**

Importar empresas y trabajadores desde un Excel de estructura histórica, conservando relaciones, RUT y estados.

**Escenario B: cálculo correcto**

Trabajador con 25 días exigibles, 23 pagados y tarifa de $4.950.

Resultado esperado: 2 días faltantes y $9.900 de retención sugerida.

**Escenario C: días pagados en exceso**

25 exigibles y 27 pagados.

Resultado: $0 de retención por diferencia de días.

**Escenario D: informe CT y CI**

Crear registros CT, CI y otro código.

El informe específico debe incluir exclusivamente CT y CI.

**Escenario E: aprobación**

Aprobar manualmente un requisito sin PDF.

El sistema debe conservar usuario, fecha, origen manual y estado aprobado.

**Escenario F: contratista sin movimientos**

Marcar una empresa sin movimientos en septiembre.

Debe excluir únicamente los requisitos no exigibles de septiembre, mantener su historial y generar una tarea de revisión de continuidad contractual.

**Escenario G: calendario**

Antes del 10 de noviembre de 2026, las cotizaciones de octubre no deben marcarse atrasadas por no haber sido entregadas.

Desde la fecha configurada, debe activarse la solicitud.

**Escenario H: separación de obras**

Una actualización documental en Concepción no debe cambiar los registros de Lomas Verdes ni Brisas de Junquillar.

**Escenario I: dashboard**

Los indicadores deben coincidir con las cifras obtenidas directamente desde la base de datos.

**Escenario J: seguridad y conservación**

La información existente y el módulo OCR Beta deben continuar operativos.

## 21. ENTREGABLES

Implementa por etapas, pero cada etapa debe quedar operativa y verificable.

Para cada etapa:

1. Modifica el código necesario.
2. Ejecuta las migraciones apropiadas en un entorno seguro.
3. Agrega pruebas.
4. Ejecuta las verificaciones disponibles.
5. Corrige los errores.
6. Documenta los cambios.
7. Prepara un Pull Request cuando corresponda.
8. Explica cómo comprobar que funciona.

Mantén una lista de funcionalidades terminadas, pendientes y bloqueadas.

No declares funciones implementadas cuando solamente hayas creado una interfaz.

No modifiques datos productivos ni despliegues cambios destructivos sin autorización.

## 22. ORDEN DE PRIORIDAD

**Primera etapa — Base operativa:**
Obras, contratistas, trabajadores, importación Excel y estructura persistente.

**Segunda etapa — Auditoría manual:**
Matriz documental, aprobaciones manuales, cotizaciones, asistencia, cálculos e informe CT/CI.

**Tercera etapa — Gestión visual:**
Dashboard INE, gráficos, indicadores y exportaciones.

**Cuarta etapa — Automatización administrativa:**
Calendario, alertas, contratos, vigencias, movimientos, bajas y cartas.

**Quinta etapa — Gestión documental futura:**
Carga de archivos, asociación de evidencias e integración posterior con OCR Beta.

Las primeras dos etapas son prioritarias porque resuelven el trabajo diario que actualmente realizo mediante Excel.

# RESULTADO ESPERADO

Quiero ingresar a GALANT y saber:

- Qué contratistas tengo en cada obra.
- Cuáles son fijos, independientes o esporádicos.
- Qué trabajadores pertenecen a cada empresa.
- Qué documentación corresponde revisar.
- Qué registros ya están aprobados.
- Qué días de cotizaciones están mal declarados.
- Cuánto corresponde proponer como retención.
- Qué contratos están por vencer.
- Qué empresas no tuvieron movimientos.
- Qué gestiones administrativas tengo pendientes.
- Cuánto ha avanzado cada obra.

**El éxito del desarrollo no se medirá por la cantidad de pantallas creadas, sino por la capacidad de administrar datos reales, hacer cálculos correctos, conservar el historial y reducir el trabajo manual.**

Comienza inspeccionando el repositorio y ejecutando la primera etapa con pruebas verificables. Conserva este documento como especificación de referencia para las etapas siguientes.
