# GALANT POST — PROMPT MAESTRO DEFINITIVO · REVISIÓN MANUAL SIN CARGA DE ARCHIVOS
## CENTRO DE CONFIGURACIÓN GENERAL, GESTIÓN DOCUMENTAL Y CONTROL HISTÓRICO DE CONTRATISTAS

**Proyecto:** GALANT POST <br>
**Tipo de implementación:** Nueva versión integral <br>
**Prioridad:** Alta <br>
**Arquitectura:** React + FastAPI + PostgreSQL + Docker Compose <br>
**Acceso:** Exclusivo para administradores <br>
**Objetivo principal:** crear un centro de configuración general que permita administrar las exigencias documentales de todos los contratistas, controlar su cumplimiento y consultar múltiples períodos sin depender del selector mensual actual.

---

## ALCANCE VIGENTE — CONTROL Y REVISIÓN MANUAL

Por decisión del usuario, esta versión NO incorpora carga, subida ni adjunto de documentación. Tampoco incorpora OCR, importación de PDF/imágenes, lectura automática de archivos ni almacenamiento documental nuevo. Los formularios del nuevo centro no deben incluir selectores de archivo.

Las exigencias, entregas informadas, estados, observaciones, períodos y revisiones se registran manualmente y se guardan en la base compartida. Una entrega informada manualmente debe identificarse como tal y nunca presentarse como un archivo verificado. La aprobación siempre es una decisión humana auditable.

Se conservan los registros y archivos históricos existentes, con consulta cuando haya respaldo disponible. El alcance no elimina ni migra destructivamente documentos anteriores.

Para contrastar portería con trabajadores, contratos y asistencia, el ADMIN registra manualmente los accesos observados (RUT y fecha). Solo se generan observaciones a partir de esos datos; la ausencia de archivo o registro no demuestra ausencia de movimientos ni incumplimiento.

Las pruebas que antes requerían subir un documento se sustituyen por registro manual, revisión y comprobación de los indicadores. Las importaciones administrativas existentes de Excel/CSV continúan dentro de su alcance actual.

---

# 1. MISIÓN PRINCIPAL

Actúa como un equipo completo de desarrollo profesional compuesto por:

1. Arquitecto de software senior.
2. Desarrollador frontend React.
3. Desarrollador backend FastAPI.
4. Ingeniero PostgreSQL.
5. Diseñador UX/UI especializado en plataformas empresariales.
6. Especialista en seguridad y permisos.
7. Especialista en gestión documental de contratistas.
8. Ingeniero de pruebas QA.
9. Agente auditor encargado de revisar el trabajo de los demás.

La misión consiste en desarrollar un módulo administrativo centralizado que permita configurar y supervisar todo el funcionamiento documental de GALANT.

Actualmente la plataforma posee módulos operativos que deben mantenerse.

**NO quiero reconstruir GALANT desde cero.**

Quiero mejorar su infraestructura utilizando el código existente, manteniendo compatibilidad con las funcionalidades actuales y evitando pérdida de información.

El resultado debe ser una implementación real y funcional, no solamente una modificación estética.

# 2. NUEVO ACCESO A CONFIGURACIÓN GENERAL

En la parte superior de GALANT existe un acceso de Configuración.

Quiero que al seleccionarlo aparezca una opción denominada:

**Configuración General**

Esta opción debe abrir una ruta independiente.

Ruta sugerida:

`/admin/configuracion`

### Requisitos visuales

- Abrir una página completa.
- Utilizar el ancho disponible de la pantalla.
- No mostrar el contenido del módulo anterior.
- No abrir formularios debajo de las tablas.
- No usar ventanas pequeñas para configuraciones extensas.
- Incorporar botón superior izquierdo "← Volver".
- Conservar filtros y estado al regresar cuando sea posible.
- Permitir utilizar el botón atrás del navegador.
- Evitar recargas completas innecesarias.
- Mantener navegación rápida y fluida.

La experiencia debe seguir el concepto de la ficha de Control de Asistencia que ya fue mejorada y funciona correctamente.

### Restricción fundamental

**Solo usuarios ADMIN pueden ver y utilizar Configuración General.**

Las administrativas conservarán su actual interfaz, que no debe rediseñarse.

Los residentes tampoco accederán a este módulo.

# 3. ESTRUCTURA DEL NUEVO CENTRO DE CONFIGURACIÓN

Crear una interfaz administrativa organizada por secciones.

### Secciones principales

**A. Vista General**

Panel con indicadores generales, alertas y resumen de cumplimiento documental de todas las obras.

**B. Configuración de Contratistas**

Permite seleccionar contratistas, administrar exigencias individuales y revisar su situación.

**C. Configuración Documental**

Catálogo completo de documentos y reglas de obligatoriedad.

**D. Configuración por Períodos**

Administración de meses, años, fechas de aplicación y vigencia de exigencias.

**E. Configuración de Obras**

Reglas específicas por obra y contratistas asociados.

**F. Alertas y Vencimientos**

Configuración de notificaciones visuales, fechas límite y estados críticos.

**G. Usuarios y Permisos**

Acceso a administración de roles y permisos existentes, sin duplicar funcionalidades.

**H. Auditoría y Trazabilidad**

Historial de modificaciones y responsables.

Cada sección debe tener navegación clara, acceso directo y rutas independientes cuando corresponda.

# 4. NUEVO CATÁLOGO GENERAL DE DOCUMENTOS

Crear un catálogo centralizado de tipos documentales.

Debe incluir al menos los siguientes:

| Documento | Nivel |
|---|---|
| F30 | Contratista |
| F30-1 | Contratista / período |
| Pago de cotizaciones previsionales | Contratista / trabajadores |
| Liquidaciones firmadas | Trabajador / período |
| Libro de asistencia | Contratista / trabajadores |
| **Informe de Portería** | **Contratista / obra / período** |
| Contrato de trabajo | Trabajador |
| Anexos de contrato | Trabajador |
| Finiquito | Trabajador |
| Declaración jurada | Independiente |
| Certificado de afiliación a mutualidad | Según configuración |
| Certificado de accidentabilidad | Según configuración |
| Certificado de siniestralidad | Según configuración |
| Otros documentos personalizados | Configurable |

Las exigencias legales u operativas de cada documento deben poder configurarse sin asumir que todos corresponden automáticamente a todas las categorías.

### Propiedades configurables

- Nombre documental.
- Descripción.
- Categoría.
- Nivel de exigencia.
- Frecuencia.
- Obligatoriedad.
- Fecha límite.
- Vigencia.
- Tipos de contratista aplicables.
- Obras aplicables.
- Período inicial.
- Período final opcional.
- Condiciones especiales.

El administrador debe poder agregar documentos nuevos sin modificar manualmente el código.

No permitir duplicaciones de documentos por diferencias de escritura o formato.

# 5. INFORME DE PORTERÍA: DOCUMENTO OBLIGATORIO PARA TODOS

## REQUERIMIENTO CRÍTICO DE ESTA VERSIÓN

El **INFORME DE PORTERÍA** debe incorporarse como documento obligatorio predeterminado para todos los contratistas.

Aplica a:

- CT: contratistas fijos.
- CE: contratistas esporádicos.
- CI: contratistas independientes.

Debe incluir las obras:

- Brisas de Junquillar.
- Lomas Verdes.
- Concepción.
- Todas las demás obras existentes o que se creen posteriormente.

No debe excluirse automáticamente por el tipo de contratista.

### 5.1 Configuración predeterminada

**Documento:** Informe de Portería.

**Frecuencia:** mensual.

**Obligatoriedad:** sí, todas las categorías.

**Nivel:** contratista por obra y período.

**Período inicial:** configurable por ADMIN.

**Fecha límite:** configurable.

**Estado inicial:** según la situación documental real, sin presumir que existe una entrega.

### 5.2 Funcionalidades requeridas

El administrador debe poder:

- Consultar el Informe de Portería de cualquier contratista.
- Revisar si fue entregado.
- Consultar el registro manual y, si existe, su respaldo histórico.
- Aprobarlo.
- Rechazarlo.
- Marcarlo como incompleto.
- Registrar observaciones.
- Identificar el período al cual corresponde.
- Consultar su historial.
- Evaluar diferencias con los trabajadores registrados.
- Determinar si existe documentación pendiente.

### 5.3 Comparación con trabajadores y asistencia

El sistema debe permitir contrastar el Informe de Portería con:

1. Trabajadores registrados en GALANT.
2. Fechas de ingreso y término contractual.
3. Registros de asistencia.
4. Información documental del contratista.
5. Movimientos de trabajadores informados.
6. Contratos vigentes.

Ejemplo:

El Informe de Portería indica que un trabajador ingresó a la obra en octubre, pero no aparece registrado en la ficha del contratista.

La plataforma deberá generar una alerta:

**Ingreso detectado sin registro de trabajador asociado.**

Otro ejemplo:

El trabajador registra acceso a obra, pero no presenta firma correspondiente en el libro de asistencia.

Mostrar:

**Posible diferencia entre portería y asistencia — requiere revisión.**

No declarar automáticamente que existe un incumplimiento definitivo si falta información para comprobarlo.

### 5.4 Estados documentales

El Informe de Portería utilizará los mismos estados del sistema:

- Aprobado.
- Entregado y pendiente de revisión.
- No entregado.
- Incompleto.
- Rechazado.
- Fuera de plazo.
- No aplica por excepción autorizada.
- Sin movimientos debidamente registrado.

### 5.5 Situaciones sin movimientos

Si un contratista no tuvo actividad durante un período, el administrador debe poder registrar una excepción por ausencia de movimientos.

Esta condición debe tener respaldo y trazabilidad.

No suponer automáticamente que no tuvo movimientos solamente porque no existe un archivo.

### 5.6 Integración completa

El Informe de Portería debe aparecer en:

- Configuración General.
- Catálogo documental.
- Ficha individual del contratista.
- Documentación mensual.
- Configuración masiva.
- Progreso de revisión.
- Indicadores de cumplimiento.
- Alertas.
- Historial documental.
- Reportes por obra.
- Reportes multiperíodo.

**No basta con agregar el documento a una lista. Debe formar parte de todo el proceso documental real.**

# 6. CONFIGURACIÓN DOCUMENTAL POR CONTRATISTA

Esta es la función principal del nuevo centro administrativo.

Necesito seleccionar cualquier contratista y decidir exactamente qué documentos debe presentar.

Ejemplo:

**Contratista:** CONSTRUCTORA EJEMPLO SPA <br>
**Obra:** Brisas de Junquillar <br>
**Categoría:** CT

| Documento | Obligatorio | Frecuencia |
|---|---|---|
| F30 | Sí | Mensual |
| F30-1 | Sí | Mensual |
| Cotizaciones | Sí | Mensual |
| Liquidaciones firmadas | Sí | Mensual |
| Libro de asistencia | Sí | Según regla |
| Informe de Portería | Sí | Mensual |
| Contratos laborales | Sí | Por trabajador |
| Finiquitos | Según corresponda | Por término |
| Declaración jurada | No | No aplica |

### Funciones necesarias

1. Agregar nuevas exigencias.
2. Eliminar obligaciones futuras cuando corresponda.
3. Cambiar obligatoriedad.
4. Modificar fechas límite.
5. Configurar frecuencia.
6. Aplicar reglas temporales.
7. Registrar excepciones.
8. Agregar observaciones.
9. Consultar requisitos anteriores.
10. Restaurar la configuración general.

El Informe de Portería debe permanecer como obligación general predeterminada para CT, CE y CI.

Cualquier exención excepcional debe requerir autorización administrativa, motivo y registro de auditoría.

No permitir que una configuración por categoría lo excluya silenciosamente.

# 7. CONFIGURACIÓN POR CATEGORÍA

GALANT trabaja con tres categorías de contratistas:

- CT: fijo.
- CE: esporádico.
- CI: independiente.

Crear plantillas documentales configurables.

Por ejemplo, una plantilla CI puede contener declaración jurada y otros documentos aplicables, mientras una plantilla CT incorpora documentación empresarial y laboral.

Las plantillas deben poder modificarse.

### Jerarquía de configuración

1. Reglas generales.
2. Reglas por categoría.
3. Reglas por obra.
4. Reglas individuales del contratista.
5. Excepciones temporales.

Mostrar siempre qué regla se está aplicando y desde dónde proviene.

Evitar conflictos entre configuraciones.

# 8. CONFIGURACIÓN POR PERÍODOS

Actualmente GALANT tiene un selector de mes general en la parte superior.

Ese selector puede permanecer para las operaciones habituales.

Sin embargo, la Configuración General debe permitir administrar distintos períodos sin depender de ese selector.

### Nueva funcionalidad

Configurar una exigencia documental indicando:

- Desde qué mes.
- Desde qué año.
- Hasta qué período.
- Si continúa indefinidamente.
- Si aplica solo un mes.
- Si aplica a períodos futuros.

Ejemplo:

**Documento:** F30-1.

**Inicio:** septiembre de 2026.

**Fin:** sin fecha.

Resultado:

Se exige desde septiembre y durante los períodos siguientes.

Otro ejemplo:

**Documento:** certificado especial.

**Inicio:** octubre de 2026.

**Fin:** diciembre de 2026.

Resultado:

Solamente se exige durante esos meses.

### Reglas históricas

No alterar automáticamente el cumplimiento de meses anteriores cuando cambie una exigencia actual.

Las correcciones retroactivas deben requerir una acción específica, vista previa del impacto y registro de auditoría.

Las obligaciones históricas deben ser reproducibles con las reglas que estaban vigentes en cada período.

# 9. NUEVO SISTEMA MULTIPERÍODO

## CAMBIO FUNDAMENTAL DE GALANT

Necesito consultar el progreso documental de varios meses simultáneamente.

Actualmente resulta engorroso porque hay que cambiar manualmente el mes superior.

Quiero solucionar esa limitación.

### Nuevo selector

Agregar opciones:

- Un mes.
- Varios meses seleccionados manualmente.
- Rango de meses.
- Trimestre.
- Semestre.
- Año completo.
- Todos los períodos disponibles.

Ejemplo:

Seleccionar septiembre, octubre y noviembre de 2026.

Mostrar inmediatamente el cumplimiento acumulado del contratista.

### Tabla de ejemplo

| Mes | Exigidos | Aprobados | Pendientes | Cumplimiento |
|---|---:|---:|---:|---:|
| Septiembre | 10 | 10 | 0 | 100% |
| Octubre | 10 | 7 | 3 | 70% |
| Noviembre | 12 | 6 | 6 | 50% |

Los valores deben calcularse utilizando los documentos reales registrados.

### Indicadores

- Porcentaje acumulado.
- Documentos aprobados.
- Documentos sin entregar.
- Documentos incompletos.
- Documentos rechazados.
- Pendientes de revisión.
- Documentos atrasados.
- Evolución del cumplimiento.
- Comparación entre meses.

No promediar directamente porcentajes si los meses poseen cantidades distintas de obligaciones.

Calcular:

**Cumplimiento = obligaciones aprobadas / obligaciones exigibles × 100.**

Distinguir porcentaje de entrega y porcentaje de aprobación.

Los documentos no aplicables o exentos no forman parte del denominador.

Cuando no existan obligaciones exigibles, mostrar "Sin obligaciones aplicables".

# 10. FICHA INTEGRAL DEL CONTRATISTA

Al seleccionar un contratista desde la Configuración General, debe abrirse una página independiente.

Ruta sugerida:

`/admin/configuracion/contratistas/:id`

### Diseño de encabezado

Mostrar:

- Nombre del contratista.
- RUT.
- Obra.
- Categoría.
- Estado.
- Cumplimiento general.
- Última revisión.
- Alertas principales.
- Botón superior izquierdo para volver.

### Pestañas internas

**Resumen**

Situación general e indicadores.

**Documentación**

Todos los documentos exigidos, su estado y períodos.

**Trabajadores**

Trabajadores asociados y contratos.

**Configuración**

Requisitos documentales individuales.

**Historial**

Evolución del cumplimiento.

**Auditoría**

Cambios y responsables.

No colocar toda esta información en un único formulario extenso.

Usar pestañas o rutas internas y conservar el contexto al navegar.

Incluir filtros, buscador y paginación para grandes cantidades de información.

# 11. REVISIÓN DOCUMENTAL Y ESTADOS

Unificar los estados utilizados en la plataforma.

### Estados mínimos

1. Aprobado.
2. Entregado, pendiente de revisión.
3. No entregado.
4. Entregado incompleto.
5. Rechazado.
6. Vencido o fuera de plazo.
7. No aplica.
8. Exento.
9. Sin movimientos.

### Regla importante

Un documento informado manualmente con información incompleta no puede figurar como "No entregado".

Ejemplo:

Un contratista presenta comprobantes de cotizaciones previsionales, pero pagó menos de lo correspondiente.

Resultado:

**Documento entregado — Incompleto — Diferencia detectada.**

Si existe una diferencia monetaria validada, mostrarla y permitir registrar la retención correspondiente.

El registro manual de una entrega no equivale a su aprobación.

Conservar:

- Fecha de registro de la entrega informada.
- Fecha de revisión.
- Nombre del revisor.
- Observaciones.
- Resultado.
- Referencia de respaldo y documentación histórica existente, cuando corresponda.
- Historial.

# 12. TABLERO GENERAL DE CUMPLIMIENTO

Crear un dashboard exclusivo para administradores.

### Indicadores principales

- Contratistas activos.
- Contratistas inactivos.
- Cantidad de CT.
- Cantidad de CE.
- Cantidad de CI.
- Contratistas al día.
- Contratistas con incumplimientos.
- Documentos exigibles.
- Documentos aprobados.
- Documentos pendientes.
- Documentos incompletos.
- Documentos vencidos.
- Informes de Portería pendientes.
- Cumplimiento por obra.
- Evolución histórica.

### Filtros

Permitir filtrar por:

- Obra.
- Contratista.
- Categoría.
- Estado.
- Mes.
- Rango de períodos.
- Año.

### Semáforo

**Verde:** obligaciones aprobadas.

**Amarillo:** pendientes de revisión o próximas a vencer.

**Rojo:** incumplimientos, documentos rechazados o vencidos.

**Gris:** sin información suficiente, no aplica o sin movimientos.

No utilizar solamente colores: mostrar también texto descriptivo e iconos.

# 13. CONFIGURACIÓN DOCUMENTAL MASIVA

Quiero modificar requisitos para muchos contratistas simultáneamente.

Ejemplos:

- Exigir un documento a todos los CT.
- Agregar un certificado a todos los contratistas de una obra.
- Configurar el Informe de Portería para todos los contratistas existentes.
- Cambiar fechas límite.
- Aplicar obligaciones desde un mes determinado.
- Crear reglas diferentes para contratistas independientes.

### Flujo

1. Elegir contratistas o grupo.
2. Elegir documento.
3. Definir obligatoriedad.
4. Definir período de aplicación.
5. Mostrar vista previa.
6. Identificar conflictos.
7. Confirmar cambios.
8. Guardar en base de datos.
9. Registrar trazabilidad.
10. Actualizar indicadores.

No ejecutar cambios masivos irreversibles sin confirmación.

# 14. ALERTAS DOCUMENTALES

Crear un sistema configurable de alertas.

Debe detectar:

- Documentos no entregados.
- Documentos incompletos.
- Documentación vencida.
- Obligaciones próximas al vencimiento.
- Contratos laborales próximos a terminar.
- Finiquitos pendientes.
- Informe de Portería pendiente.
- Diferencias entre portería y asistencia.
- Trabajadores ingresados sin registro correspondiente.
- Contratistas con incumplimientos reiterados.

Cada alerta debe indicar:

- Contratista.
- Obra.
- Período.
- Documento.
- Motivo.
- Prioridad.
- Acción recomendada.

Evitar alertas duplicadas.

Permitir configurar umbrales y fechas límite desde el panel administrativo.

# 15. PERMISOS Y CONSERVACIÓN DE LA INTERFAZ ACTUAL

## REGLA OBLIGATORIA

Este nuevo centro de configuración es exclusivamente para ADMIN.

**Las administrativas deben conservar el formato que ya tienen actualmente.**

No rediseñar su módulo operativo.

No modificar negativamente:

- Control de Asistencia.
- Registro semanal.
- Selección de contratistas.
- Registro de trabajadores.
- Control de contratos.
- Registro de finiquitos.
- Trazabilidad de sus actividades.

Las administrativas deben seguir utilizando las mismas pantallas y flujos.

Los cambios de exigencias documentales efectuados por ADMIN deben reflejarse correctamente en las consultas correspondientes, pero sin entregar permisos nuevos.

### Seguridad

Implementar:

- Protección frontend.
- Protección backend.
- Validación de roles por endpoint.
- Control de acceso por obra cuando corresponda.
- Auditoría de modificaciones.
- Verificación de permisos de lectura y escritura.

No confiar únicamente en que un botón esté oculto.

# 16. AUDITORÍA Y TRAZABILIDAD

Cada modificación deberá quedar registrada.

Campos mínimos:

- Nombre del usuario.
- Identificador interno.
- Fecha.
- Hora.
- Acción.
- Contratista afectado.
- Obra.
- Documento.
- Período.
- Valor anterior.
- Valor nuevo.
- Motivo de modificación.

### Importante

En las pantallas debe mostrarse el **nombre del responsable**, no su correo electrónico ni códigos internos.

Ejemplo:

"Configuración modificada por Juan Pérez — 05/11/2026".

Conservar historial incluso cuando una exigencia sea desactivada.

Permitir filtrar los eventos por usuario, contratista, obra y período.

# 17. ARQUITECTURA E INFRAESTRUCTURA

Respetar la arquitectura actual:

- React.
- FastAPI.
- PostgreSQL.
- Docker Compose.
- Infraestructura de despliegue existente.

Revisar primero los componentes y modelos implementados.

No duplicar servicios, rutas ni tablas innecesariamente.

### Entidades que deben existir o adaptarse

- Tipos documentales.
- Plantillas documentales.
- Reglas documentales.
- Vigencia de reglas.
- Excepciones.
- Obligaciones por período.
- Entregas informadas y registradas manualmente.
- Revisiones.
- Estados.
- Auditoría.
- Configuración de alertas.

### Reglas técnicas

1. Utilizar migraciones versionadas.
2. Preservar datos existentes.
3. Evitar obligaciones duplicadas.
4. Usar transacciones.
5. Implementar índices apropiados.
6. Optimizar consultas multiperíodo.
7. Mantener consistencia entre frontend y backend.
8. Evitar cálculos distintos para un mismo indicador.
9. No almacenar estados críticos únicamente en frontend.
10. No afectar la base compartida entre usuarios.

La nueva configuración debe utilizar la misma fuente de datos central que los demás módulos.

# 18. DISEÑO PREMIUM Y EXPERIENCIA DE USUARIO

Quiero que la nueva Configuración General tenga apariencia de plataforma empresarial profesional.

No quiero un diseño genérico.

### Características

- Menú lateral interno elegante.
- Espaciado adecuado.
- Tarjetas informativas.
- Tablas modernas.
- Buscadores rápidos.
- Indicadores visuales.
- Filtros claros.
- Selector multiperíodo intuitivo.
- Animaciones discretas.
- Transiciones suaves.
- Mensajes de confirmación.
- Estados de carga.
- Estados vacíos.
- Mensajes de error claros.
- Componentes responsivos.

La interfaz debe ser fácil de utilizar cuando existan cientos de contratistas y varios años de registros.

Evitar desplazamientos horizontales innecesarios.

Los botones deben ejecutar acciones reales.

Los formularios deben validar información.

Los cambios deben persistir luego de recargar la página.

# 19. EQUIPO DE AGENTES DE VERIFICACIÓN

Quiero una metodología de revisión mediante agentes especializados o roles de validación independientes.

### Agente 1 — Arquitectura

Revisa la estructura del proyecto y compatibilidad con la infraestructura actual.

### Agente 2 — Backend

Verifica reglas de negocio, endpoints, permisos y persistencia.

### Agente 3 — Frontend

Revisa navegación, experiencia de usuario y diseño.

### Agente 4 — Gestión documental

Comprueba que los documentos se soliciten correctamente según contratista, obra y período.

Debe verificar específicamente que el Informe de Portería aparezca para CT, CE y CI.

### Agente 5 — Seguridad

Comprueba que solamente ADMIN pueda modificar configuraciones.

### Agente 6 — QA

Ejecuta pruebas funcionales y de regresión.

### Agente 7 — Auditor final

Revisa los resultados de todos los agentes y detecta problemas pendientes.

Si el entorno de desarrollo no dispone de agentes paralelos reales, ejecutar estas revisiones de forma secuencial y documentada. No simular verificaciones que no se hayan realizado.

# 20. PRUEBAS AUTOMATIZADAS OBLIGATORIAS

Implementar pruebas unitarias, de integración y de interfaz donde corresponda.

### Prueba 1: Navegación

Abrir Configuración General desde el menú superior.

Verificar que utiliza toda la pantalla y que el botón Volver funciona.

### Prueba 2: Permisos

Comprobar que ADMIN puede acceder y que administrativas y residentes no pueden acceder ni mediante URL directa ni mediante llamadas API.

### Prueba 3: Configuración individual

Modificar una obligación documental de un contratista.

Recargar la aplicación y verificar que los cambios permanecen.

### Prueba 4: Configuración masiva

Aplicar una nueva exigencia a un grupo de contratistas.

Verificar resultados en todos los registros afectados.

### Prueba 5: Informe de Portería

Comprobar que el documento está configurado para:

- Todos los CT.
- Todos los CE.
- Todos los CI.
- Todas las obras.

Verificar también que se aplique correctamente desde el período configurado.

### Prueba 6: Revisión de Portería

Registrar manualmente la entrega informada de un Informe de Portería, revisarlo, marcarlo como aprobado y comprobar su efecto en los indicadores, sin adjuntar archivos.

### Prueba 7: Diferencias

Registrar manualmente los accesos observados de portería y contrastarlos con trabajadores registrados, contratos y asistencia.

Verificar la generación de observaciones sin producir incumplimientos falsos.

### Prueba 8: Multiperíodo

Seleccionar tres meses y comprobar que el sistema muestra correctamente el cumplimiento acumulado.

### Prueba 9: Historia documental

Modificar las exigencias de un período futuro y comprobar que los resultados históricos anteriores permanecen intactos.

### Prueba 10: Interfaz administrativa

Comprobar que las administrativas mantienen su formato y pueden continuar trabajando normalmente.

### Prueba 11: Persistencia

Reiniciar frontend y backend y verificar que los datos de configuración y revisiones permanecen.

### Prueba 12: Multiusuario

Modificar una regla con ADMIN y comprobar que la fuente de datos es compartida, sin que otro administrador visualice información desactualizada permanentemente.

### Prueba 13: Datos existentes

Verificar que los documentos anteriores, contratistas, trabajadores y revisiones no desaparezcan después de las migraciones.

### Prueba 14: Períodos sin movimientos

Verificar que una obligación se excluya del indicador solamente cuando exista una justificación válida y auditable.

### Prueba 15: Regresión integral

Ejecutar pruebas de los módulos existentes, especialmente:

- Contratistas.
- Trabajadores.
- Control de Asistencia.
- Documentación mensual.
- Gestión de usuarios.
- Red de Obras.
- Carga masiva.

# 21. CRITERIOS DE ACEPTACIÓN

No considerar terminada esta implementación hasta verificar que:

- El nuevo centro funciona sin cargar ni adjuntar documentación.
- Existe una ruta independiente de Configuración General.
- Solo ADMIN puede acceder.
- El botón superior izquierdo permite regresar.
- Se pueden configurar documentos por contratista.
- Se pueden definir las obligaciones desde un período determinado.
- El Informe de Portería es obligatorio por defecto para CT, CE y CI.
- Los requisitos se aplican correctamente a todas las obras.
- Se pueden revisar varios meses simultáneamente.
- Los indicadores se calculan con datos reales.
- Existe trazabilidad de modificaciones.
- Las configuraciones se guardan en PostgreSQL.
- Se conservan los registros históricos.
- La interfaz administrativa actual sigue funcionando.
- Se ejecutaron las pruebas y se reportaron sus resultados.

# 22. ENTREGA Y PUBLICACIÓN DE LA NUEVA VERSIÓN

Antes de modificar código:

1. Revisar el estado actual del repositorio.
2. Identificar componentes existentes reutilizables.
3. Identificar las migraciones necesarias.
4. Preparar un plan breve de implementación.

Después:

1. Implementar backend.
2. Implementar frontend.
3. Integrar los módulos existentes.
4. Ejecutar migraciones y pruebas.
5. Corregir errores detectados.
6. Verificar permisos.
7. Revisar rendimiento.
8. Preparar una nueva versión siguiendo el versionado real del proyecto.
9. Incorporar el número de versión visible en GALANT.
10. Preparar instrucciones exactas de actualización del VPS.

No inventar una versión nueva si no se verificó la versión actual.

No realizar despliegues destructivos ni eliminar volúmenes de PostgreSQL.

No incluir `docker compose down -v` ni comandos equivalentes.

Entregar al finalizar:

- Resumen de cambios implementados.
- Archivos principales modificados.
- Migraciones realizadas.
- Pruebas ejecutadas y resultados reales.
- Problemas pendientes.
- Versión resultante.
- Commit o referencia correspondiente.
- Comandos de despliegue adaptados a la configuración existente del VPS.

Si una función no pudo implementarse o probarse, declararlo expresamente.

---

# 23. OBJETIVO FINAL

GALANT debe transformarse en una plataforma donde el administrador pueda controlar centralizadamente las obligaciones documentales de todos los contratistas.

Debe ser posible:

**Seleccionar un contratista → ver su situación → revisar varios meses → detectar incumplimientos → modificar sus exigencias documentales → definir desde cuándo se aplican → guardar cambios → mantener trazabilidad.**

Todo desde una interfaz ordenada, rápida y profesional.

El Informe de Portería debe estar integrado al sistema documental completo, con obligatoriedad general predeterminada para CT, CE y CI.

La plataforma debe conservar el trabajo realizado anteriormente, especialmente los módulos administrativos que ya funcionan correctamente.

**PRIORIDAD ABSOLUTA: funcionamiento real, integración completa, seguridad, conservación de datos y ausencia de regresiones.**

Implementar esta nueva versión de GALANT sobre el proyecto existente y verificar de manera rigurosa cada función antes de darla por finalizada.
