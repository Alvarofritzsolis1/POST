# GALANT 19.0.0-rc1 — Estado comprobable de la migración documental

## Alcance implementado
- Diez **diseños HTML/CSS A4**: contrato de trabajo, anexos de traslado y prórroga, declaración jurada, EPP, PTS, recepción PTS, IRL, Reglamento Interno e Inducción.
- Los primeros tres tenían plantillas nativas piloto. Los otros siete se incorporan con **la cláusula original publicada en la base de la organización**, sin inventar contratos ni reducir textos extensos a letra minúscula.
- PTS e IRL requieren matrices aprobadas del cargo. EPP requiere listado de elementos; PTS recibido requiere versión. La declaración de empresa usa la firma del representante, no firma ficticia de trabajador.
- El admin edita en «Configuración → Plantillas y cláusulas» y completa datos y observaciones en el expediente. En modo piloto puede habilitar la *vista previa A4* de su propia revisión, con auditoría, **sin publicarla como una revisión profesional**.
- Si hay un borrador más reciente no habilitado, la vista previa se bloquea para evitar imprimir una versión antigua.
- El sistema Excel anterior permanece operativamente disponible. Los nuevos PDF son **vistas previas**; imprimir no registra firma, recepción o capacitación, y el nuevo motor no modifica trabajadores o contratistas operativos.

## Paridad e integridad del Excel
El archivo privado auditado conserva **33 hojas y 423 fórmulas**. En una comparación local entre:
- PROYECTO_JAVIERA_FORMATOS_PROFESIONALES.xlsx
- PROYECTO_JAVIERA_FORMATOS_IMPRESION_CORREGIDA.xlsx

se verificó:
- 423/423 fórmulas en ambos.
- Cero diferencias de expresiones de fórmulas, atributos OOXML y referencias por celda.
- Cero diferencias de los valores caché almacenados.
- 33/33 hojas con nombres y orden idénticos.
- Los formularios incluyen fórmulas compartidas; se comparan sus atributos y referencias OOXML.
- Hash SHA256 del catálogo de fórmulas: b206c63d49142d9544441bc6e664e07ff77151a51637bc4f7ff0af35c3630a1a.

**Límite crítico:** este resultado es una prueba de **conservación de fórmulas**, NO de que las 423 expresiones ya hayan sido traducidas y calculadas por el backend. Para aprobar equivalencia dinámica es necesario introducir datos de prueba equivalentes en Excel y backend, con múltiples escenarios, e inspeccionar las salidas. Nunca declarar que está terminada esa traducción sin evidencia.

Herramienta de auditoría privada y reproducible:
\`python scripts/qa_javiera_formula_parity.py original.xlsx candidato.xlsx --min-formulas 423 --report auditoria.json\`

No almacenar nombres, RUT, fórmulas originales, hojas con valores ni PDF con datos reales en GitHub.

## UX revisada
1. Elegir empresa nueva/existente y documentos mediante casillas.
2. Completar una sola vez los datos compartidos.
3. Cambiar campos específicos, EPP, temario de inducción y observaciones opcionales.
4. Elegir **Vista previa A4** en la pantalla «Revisión e impresión».
5. Si falta una cláusula oficial, **Editar formato original** conduce al editor de textos y revisiones.
6. En piloto, habilitar la vista previa administrativa del texto ya revisado. Esto no es aprobación profesional.
7. Comparar con «Vista previa Excel» si es necesario. No emitir documentos nativos definitivos sin aceptación funcional.

## Requisitos de pruebas
- Diez diseños imprimibles y salvaguarda sin texto fuente (bloqueo), sin inventar contenidos.
- RUT, nombre, fecha, cargo y obra reflejados correctamente sin fuga interorganización.
- Documento empresarial sin trabajador ficticio.
- Matrices IRL/PTS verificadas y por cargo.
- A4 en todas las páginas; encabezados, firma, textos largos, no imágenes comprimidas.
- HTML escapado; sin URLs externas activas ni HTML arbitrario en plantillas.
- El motor no modifica identidades/estados operativos.
- Regresiones frontend, backend, restauración, navegación y permisos.
- Revisión humana del texto y PDF de los diez documentos frente al Excel original antes de activar emisión nativa.

## Acciones aún pendientes
- Certificar visualmente cada PDF final contra el original (incluido contenido de imágenes, IRL y PTS).
- Traducir/contrastar cálculos dinámicos que realmente intervengan en los documentos; la equivalencia de 423 fórmulas **en el backend no está demostrada**.
- Completar la ejecución y aprobación de la CI del commit final.
- Fusión de PR y despliegue controlado al VPS: **no efectuados**.

## Evaluación de calidad
Arquitectura, diseño editorial, especialista Excel, ingeniería PDF, revisión laboral, prevención y QA deben aceptar evidencia independiente. **No afirmar 95/100** ni validación profesional de contenido sin los informes y firmas pertinentes.
