# GALANT 19.4 — Biblioteca de cinco matrices precargadas

## Objetivo
El selector «Matrices y cargos» ya no requiere que alguien reconstruya
o suba manualmente el Excel para consultar el contenido técnico. La fuente
de referencia se incluye en el proyecto, sin datos de trabajadores ni firmas.

Fuente: `JAVIERA_ETAPA_1_PTS_CORREGIDOS.xlsx`, SHA-256
`2a6657a0f6c7d78731565ecbb59485542343629903aaf161aacfbea405da5edd`.
**Referencia documental sin aprobación preventiva automática.**

## Datos importados a la biblioteca de referencia
| Opción | Filas originales | Secciones |
|---|---:|---:|
| IRL | 25 cargos, 338 registros | Tarea, peligro, riesgo, medidas |
| PTS | 26 registros | 17 apartados D:T por registro |
| Descripción de cargos (PERFILES) | 26 registros | Perfil técnico |
| Matriz IRL optimizada (PUESTOS) | 27 registros | 4 apartados |
| Sustancias | 27 registros | 12 apartados B:M |

Se mantienen las filas originales de variantes y duplicaciones; una carga
automática no puede resolver por sí sola qué versión PTS de GASFITER es
la válida. En PUESTOS hay variantes GASFITERIA y HOJALATERIA (ALIAS).
En SUSTANCIAS hay una variante PAISAJISMO (REVISAR HDS).

El IRL corregido contiene una fila sin riesgo ni medida: fila Excel 40,
CARPINTERO. Se conserva sin completarla artificialmente.

## Integración
- `/api/v1/javiera/v194/reference-matrices?kind=IRL|PTS|PERFILES|PUESTOS|SUSTANCIAS`
  permite consultar los datos precargados sin subir otro archivo.
- El editor distingue revisiones aprobadas de **Excel original, sin aprobar**.
- Cada apartado tiene su nombre real, y el contenido puede copiarse para
  crear una nueva revisión en borrador tras confirmar el impacto.
- El IRL por cargo muestra automáticamente sus riesgos y las referencias
  de PTS, perfiles, puestos y sustancias.
- No se modifican PDF históricos ni módulos operativos.
- Se mantienen controles de acceso del administrador.
- La revisión profesional antes de habilitar un nuevo IRL/PTS sigue siendo obligatoria.

## Fuera de alcance de esta entrega
No se declara paridad de las 74 fórmulas IRL ni de las 324 fórmulas del libro.
Tampoco se afirma réplica visual 100 % fiel de sus cinco imágenes incrustadas:
estas requieren comparación PDF Excel/PDF GALANT y validación textual.
No fusionar o desplegar mientras existan pruebas fallidas.

## Pruebas
`apps/backend/tests/test_javiera_v194.py` valida recuentos, columnas,
duplicaciones, control de acceso y bloqueo de datos incompletos.
`scripts/qa_javiera_v16_browser.py` verifica las cinco opciones del selector,
contenido precargado por tipo y retorno al editor IRL.
