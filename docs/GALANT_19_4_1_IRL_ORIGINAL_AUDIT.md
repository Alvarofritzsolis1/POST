# GALANT 19.4.1-rc1 — Integridad IRL por cargo (candidata, NO desplegar)

**Estado:** parche de integridad y consulta, pendiente de paridad total con el Excel original.
Esta rama se propone como PR *draft* para que no llegue automáticamente al VPS.
El formato nativo IRL actual **no cumple todavía** la equivalencia completa requerida.

## Fuente inspeccionada

Archivo entregado en esta conversación: `PROYECTO AUTOMATIZACION GESTION CONTRATISTAS FINAL(3).xlsx`.
SHA-256: `bf5d466879f80cd67583447baabf752278d616fd700d439ff3374c591ddc5ed9`.
Según auditoría local OOXML contiene 17 hojas, 74 fórmulas IRL y cinco imágenes
incrustadas con antecedentes y reglas preventivas. Es distinto del catálogo de
referencia previamente corregido en el repositorio, que ya incluye el perfil
de SOLDADOR. **No reemplazar datos corregidos por el original defectuoso.**
El XLSX privado no se publica ni debe cargarse en el repositorio.

## Implementado en esta candidata

- Auditoría determinista de Tarea/Peligro/Riesgo/Medidas unidas por `excel_row`;
  no se elige una medida preventiva por índice independiente.
- Las 13 entradas de un bloque de cargo se conservan; GASFITER tiene 26 y se
  documenta su duplicidad sin fusionar los dos bloques.
- Se exponen las filas incompletas (CARPINTERO, fila 40) antes de aprobación.
- Los vínculos PERFILES, PUESTOS, SUSTANCIAS y PTS muestran fuente exacta
  (`source_sheet`, `source_row`, `source_cargo`) y aviso de variaciones.
- La selección de la primera matriz para cargos con dos referencias se
  suprime: requiere seleccionar, corregir y aprobar una variante.
- PAISAJISTA / PAISAJISMO es solo propuesta para revisión, nunca
  asociación química automática.
- Interfaz administrativa: paneles desplegables por cargo, sección del
  perfil, condiciones laborales, sustancias/HDS y avisos comprensibles.
- Tests de regresión sobre duplicados, bloque de 13, ausencia de sustancias
  y piezas originales no migradas.
- No se modifica módulo de trabajadores, contratos, asistencia, acceso al
  VPS ni estado de aprobación histórica.

## Incompleto y explícitamente bloqueado como «paridad 100 %»

1. Los cinco bloques gráficos originales aún no están transcritos
   íntegramente a HTML editable, verificados línea a línea ni incorporados
   al PDF nativo. La nueva interfaz los identifica como pendientes.
2. No se ha demostrado equivalencia de las 74 fórmulas de IRL con una batería
   de pares entrada/salida Excel–HTML: reportar como **no certificada**.
3. No existe aprobación preventiva de los cambios para TODOS los cargos.
   Especialmente revisar los perfiles del Excel original desplazados desde B8.
4. Falta cotejo visual página por página (A4, márgenes, casillas,
   tablas, firmas y saltos), y pruebas de impresión desde navegador real.
5. No se ha validado en el VPS ni en un entorno con datos reales. No publicar.

## Pruebas de aceptación antes de habilitar producción

- [ ] Backend: `python -m pytest -q` y pruebas focalizadas de Javiera en verde.
- [ ] Frontend: `npm ci && npm run build && npm run test:logic`.
- [ ] Los 25 cargos se verifican con labores, peligros y medidas idénticas
      para cada fila sin introducir otros cargos.
- [ ] Las 74 fórmulas se mapean, se prueban y se documenta cada equivalencia.
- [ ] Los cinco bloques se transcriben a HTML editable, se validan por
      prevención y se comparan en impresión A4 con el Excel original.
- [ ] Revisar y resolver duplicado GASFITER, perfil/descripción y sustancias.
- [ ] Verificar que generar IRL no crea trabajador/contratista ni altera
      asistencia, otros documentos o datos de organizaciones ajenas.
- [ ] Validación de respaldo, healthcheck, rollback y revisión final del PR.

## Despliegue

**No usar comandos de despliegue ni fusionar esta candidata todavía.**
La actualización automática existe al fusionar en `main` versiones
coherentes en `version.py`, `package.json` y `package-lock.json`, por
lo que un merge prematuro activaría el pipeline de despliegue.
Solo utilizar el mecanismo existente de CI/CD cuando estén todas las
pruebas y las revisiones preventivas aprobadas.

## Referencias legales (sujetas a revisión profesional)

- D.S. 44, art. 15: https://www.bcn.cl/leychile/navegar?i=1205298
- D.S. 57 (sustancias y etiquetas): https://www.bcn.cl/leychile/navegar?idNorma=1155752
