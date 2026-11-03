# Matriz de auditoría 0.5.0-rc1

La auditoría cubre el código de `main` 289616b y los cambios de esta rama. No representa una inspección de la BD real del VPS. Evidencia y límites: [entrega](ENTREGA_0.5.0.md).

| Problema | Causa técnica | Gravedad | Solución aplicada | Prueba / estado |
|---|---|---|---|---|
| Cuentas internas aisladas | `create-admin` crea un `org_id` nuevo; el nombre no determina pertenencia | Crítica | Crear cuentas desde administración en la misma organización; diagnóstico y vinculación supervisada, sin eliminar filtros | Dos clientes y dos navegadores sintéticos comparten obra/contratista/trabajador/cotizaciones; cuenta real pendiente |
| Traslado sin respaldo | `link-user` anterior vinculaba directamente organizaciones vacías | Alta | Plan por defecto, bloqueo con datos, dump validado, hash y auditoría | Prueba de plan sin cambios, falta de respaldo y datos asociados |
| Datos desactualizados | Fichas operativas solo consultaban al entrar o guardar | Alta | Refresco cada 10 s, foco, señal local y no-store; se descartan respuestas antiguas del panel | Navegador B ve cambios de A sin login nuevo |
| Permisos en interfaz insuficientes | No existía administración web de usuarios | Alta | Backend exige admin; roles enumerados; cuenta propia protegida; API vuelve a consultar usuario | Viewer y organización ajena rechazados; preferencias aisladas |
| Clasificación contradictoria | Matriz e informes inferían CT/CI a partir del código histórico; fichas usaban naturaleza | Alta | Clasificación compartida basada en naturaleza/frecuencia explícita; catálogo de importación aprobado | COD CT importado queda sin clasificar si no hay regla; independientes no admiten dependientes |
| Importador limitado a una obra | El flujo histórico recibía un único site_id y exigía RUT del empleador | Alta | Flujos especializados en el mismo centro; resolución por obra y nombre único o RUT opcional | 300 empresas en dos obras y 300 trabajadores; ambigüedad rechazada |
| Pérdida de códigos y contacto | Ficha anterior no tenía dónde guardar ID externo/especialidad/representante | Media | Extensión aditiva `contractor_details`; IDs internos independientes y datos visibles en ficha | ID externo conservado; RUT de representante validado |
| Duplicación por repetir Excel | Identidades y relaciones requieren claves distintas | Alta | Unicidad org/RUT y relación obra/persona; búsqueda de contratos por asignación/fecha; commit transaccional | Repetición de 300 empresas y 300 trabajadores conserva cantidades |
| Fechas/columnas interpretadas mal | Encabezados chilenos abreviados y columnas vacías | Alta | Alias confirmados, posiciones preservadas, parser contractual existente, errores explicados | F.INGRESO/F.TERMINO, fecha chilena y columna intermedia vacía |
| Actualizaciones importadas no revisadas | El importador histórico solo admitía completar campos por defecto | Alta | Diferencias por campo, aprobación explícita, token de contenido y huella de estado | Sin aprobación: 422; edición concurrente: 409; contenido alterado: 422 |
| Historial laboral sobrescrito | Una asignación por obra/contratista/persona no representa recontrataciones | Alta | Episodios en el `contract_register` existente; no reemplazar contratos previos; detección de solapamientos | Contrato finalizado y reingreso conservan ambos episodios |
| Promedio global engañoso | Informe anterior no exponía cobertura ni denominador individual completo | Alta | Promedio de registros individuales válidos; nulos separados; resúmenes por empresa, obra y clasificación | Empresas con 1 y 3 personas: (30+10+20)/3=20, no (30+15)/2=22,5 |
| Retención inconsistente | Valor diario solo por registro, sin catálogo temporal; CI sin diferencia calculada | Alta | Catálogo mensual auditado, valor inicial 4950 y snapshot en control; estimación por faltantes CT/CI | 30 días faltantes × 4950; vigencia diciembre 6000; excedente no retiene |
| Falta de datos confundida con incumplimiento | Ausencia de control no aparecía en el resumen de registros existentes | Alta | Filas sin información, cobertura y pendientes; pago registrado separado de confirmado | Nulos excluidos del promedio y contados aparte |
| Revisión mensual duplicada | Riesgo de crear otra matriz sin consultar `monthly_documents` | Alta | Reutilización de matriz y aprobación existentes; tabla nueva solo para revisiones por trabajador | Aprobar en nueva API se refleja en matriz anterior y recarga |
| Interfaz con OCR dominante | Historial/BETA ocupaban navegación principal | Media | Menú por funciones; OCR integrado como evidencia dentro de cotizaciones | Rutas principales abiertas por Chromium, sin entradas OCR antiguas |
| Datos privados en contexto Docker | Faltaba exclusión del contexto de build | Alta | `.dockerignore` excluye env, archivos privados, caches y Git | Docker build y revisión del contexto |
| Persistencia no demostrada | Solo compilación no prueba conservación al reiniciar | Alta | Prueba local con PostgreSQL persistente e imágenes como UID 10001 | Respuestas idénticas antes/después de reinicio de API; no demuestra recuperación del VPS |
| Inyección en exportación | Texto de usuario puede comenzar con `=`, `+`, `-` o `@` | Alta | Celdas de texto neutralizadas en nuevos reportes/observaciones | Generación y lectura XLSX; sin ejecutar fórmulas |
| Uso a gran escala | Fichas/matriz aún consultan conjuntos completos | Media | Paginación/filtros de cotizaciones desde API y eliminación de consulta de trabajadores por cada contratista en matriz | API limitada conserva total/denominador; optimización global pendiente |
| Invitaciones por correo | No existe transporte/configuración de correo | Media | Creación segura de cuentas operativa; no se presenta un botón de envío ficticio | Entrega de invitaciones pendiente |

## Archivos principales

- Backend: `admin_api.py`, `bulk_import.py`, `compliance_api.py`, `platform_models.py`; ampliaciones de `cli.py`, `security.py`, `main.py`, `ops_api.py`, `control_api.py`, `control_reports.py`, `version.py`.
- Frontend: `App.tsx`, `BulkImport.tsx`, `Settings.tsx`, `platformApi.ts`, `platform.css`; integración con `Operations.tsx`, `ControlCenter.tsx`, `MonthlyDocuments.tsx` y reutilización del visor en `DocumentAnalysis.tsx`.
- Verificación: `tests/test_platform.py`, ajuste de la clasificación explícita en `test_control_api.py`, `scripts/qa_shared_browser.py`.
- Despliegue/documentación: `.dockerignore`, cliente PostgreSQL en Dockerfile, versiones de package/lock, entrega, auditoría e instrucciones VPS.
