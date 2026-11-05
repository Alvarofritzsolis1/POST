# GALANT POST 13.1.0-rc1 — Configuración General

Fecha: 5 de noviembre de 2026. Candidata preparada para revisión; no desplegada al VPS.

Código verificado: `b4b9cdc94e06a771871cdde685d711691b9dedf6`.

## Alcance implementado

El administrador abre **Configuración → Configuración General** en `/admin/configuracion`. El centro ocupa una página independiente, conserva el contexto en la URL y admite Volver y el historial del navegador. Las administrativas y residentes conservan sus espacios actuales y reciben denegación tanto en la URL directa como en las APIs administrativas.

El centro utiliza la misma organización, contratistas, obras, trabajadores y revisiones de los módulos existentes. Incluye ocho secciones: vista general, contratistas, catálogo documental, períodos, obras, alertas, acceso a los usuarios existentes y auditoría. La ficha `/admin/configuracion/contratistas/:id` separa resumen, documentos, trabajadores, configuración, historia y auditoría.

**No se incorporó carga de documentación.** Se retiraron los controles de subida de la documentación mensual. La entrega informada, la revisión y las observaciones se registran manualmente. Los originales históricos se conservan y pueden consultarse; una revisión no oculta ni reemplaza el archivo recibido. La funcionalidad OCR anterior y las importaciones administrativas de Excel/CSV permanecen en sus módulos existentes.

- Catálogo inicial de quince tipos documentales y creación de nuevos tipos con nombre normalizado único. Incluye F30, F30-1, cotizaciones, liquidaciones, asistencia, Portería, contratos, anexos, finiquitos, declaración jurada y certificados de mutualidad, accidentabilidad y siniestralidad.
- Reglas generales, por categoría CT/CE/CI, por obra, individuales y excepciones temporales. Las reglas guardan vigencia, frecuencia, plazo, motivo, versión y procedencia. Restaurar la herencia utiliza una nueva revisión de la regla; no borra la anterior.
- Vista previa y confirmación para reglas masivas y para cambiar el período inicial de Portería. El servidor vincula la confirmación al usuario, organización, propuesta, revisión y destinatarios. Si cambia el impacto, exige una nueva vista previa.
- Portería mensual obligatoria por defecto para CT, CE y CI de todas las obras actuales y futuras, desde el período configurado. Las exclusiones son individuales, temporales y justificadas; una plantilla de categoría no puede excluirlo silenciosamente.
- Selección de mes, meses manuales, rango, trimestre, semestre, año y períodos disponibles. Cada consulta admite hasta sesenta meses y un máximo de 200.000 obligaciones personales; se debe acotar la consulta si supera ese límite.
- Cumplimiento ponderado por obligaciones aprobadas/exigibles. El porcentaje de entrega es independiente; exenciones justificadas y ausencia de obligaciones no generan un 100% ficticio.
- Estados manuales aprobado, entregado pendiente de revisión, no entregado, incompleto, rechazado, fuera de plazo, no aplica, exento y sin movimientos. Los últimos tres requieren justificación; la ausencia de archivo no demuestra ausencia de actividad.
- Obligaciones de nivel trabajador evaluadas por asignación individual, reutilizando revisiones laborales existentes. Las tablas operativas agregan estos resultados y remiten a la ficha para revisar cada persona.
- Registro manual de accesos de Portería, contraste con trabajadores, contratos y asistencia, y observaciones que requieren revisión. No se interpreta un dato ausente como una infracción demostrada.
- Alertas de documentación pendiente, incompleta, rechazada o próxima a vencer; contratos próximos a terminar, finiquitos registrados pendientes y diferencias de Portería. Incluye paginación de alertas.
- Auditoría con responsable por nombre, motivo, antes/después y filtros. La matriz, fichas, indicadores y reportes existentes utilizan el evaluador compartido para los períodos configurados.

## Conservación histórica y migración

Migración `13.1.0_documentary_configuration`, registrada en `app.cli.migrate` y repetible sin borrar los registros previos. Agrega cinco tablas:

| Tabla | Contenido |
|---|---|
| `configuration_settings` | Inicio de configuración y umbrales de alertas |
| `configuration_document_types` | Catálogo normalizado por organización |
| `configuration_rules` | Revisiones inmutables de reglas y activación de Portería |
| `configuration_gate_movements` | Accesos transcritos manualmente |
| `configuration_obligation_snapshots` | Obligaciones observadas por contratista y período |

Las instantáneas conservan categoría, sujetos, exigibilidad, plazos y procedencia al consultar un período. Los períodos históricos mantienen esa información aunque después cambien la categoría o la actividad de un trabajador. Las revisiones humanas siguen disponibles para corrección explícita; una corrección retroactiva de reglas requiere vista previa, confirmación y auditoría y actualiza únicamente las obligaciones afectadas. Los períodos anteriores sin evidencia ni calendario mantienen el criterio de evaluabilidad anterior. No se reconstruye información histórica que nunca fue registrada.

## Verificación ejecutada

Todos los datos utilizados fueron sintéticos. No se accedió a la base ni a los archivos laborales del VPS.

| Comprobación | Resultado |
|---|---|
| Suite completa con PostgreSQL 16 y Tesseract español/inglés | 159 aprobadas, 2 omitidas y 3 aserciones antiguas de versiones de migración detectadas |
| Tres aserciones de migración actualizadas y repetidas | 3 aprobadas; conservan la comprobación de usuarios, obras y datos previos |
| Aceptación final del centro y concurrencia PostgreSQL, tras la última corrección histórica | 28 aprobadas |
| Resultado consolidado de los 164 casos de backend | 162 aprobados; 2 omitidos por escenarios concurrentes exclusivos de PostgreSQL en la variante SQLite |
| Compilación TypeScript y producción Vite | Correcta |
| Chromium real → Vite → FastAPI → PostgreSQL | Correcto: entrada desde Configuración, catálogo, regla individual con vista previa/confirmación, revisión incompleta persistente tras recarga, tres períodos, Volver/atrás y denegación de ambos perfiles no ADMIN |
| Navegador a 390, 768 y 1440 píxeles | Sin desplazamiento horizontal de página; sin selectores de archivo; tabla de evolución adaptada a móvil |
| Concurrencia PostgreSQL | Una vista previa se confirma una sola vez; dos revisiones reutilizan un único registro lógico y conservan ambas acciones en auditoría |

La compilación conserva el aviso de tamaño del paquete principal de la aplicación existente. Configuración General se carga en un paquete separado. La dependencia de pruebas de FastAPI emite un aviso de deprecación de TestClient; no impide la ejecución.

Las revisiones independientes de arquitectura, gestión documental, frontend, backend, seguridad y QA detectaron y permitieron corregir la conservación de originales, los denominadores históricos, la exclusión por frecuencia de Portería y la compatibilidad de revisiones laborales. El agente principal completó las instantáneas históricas y verificó la entrega final.

Comandos reproducibles desde el repositorio, con dependencias instaladas y una base PostgreSQL **exclusivamente de pruebas**:

```bash
cd apps/backend
TEST_DATABASE_URL="$GALANT_TEST_DATABASE_URL" pytest -q
cd ../frontend
npm ci
npm run build
```

La prueba de navegador `scripts/qa_configuration_browser.py` acepta únicamente localhost y requiere `GALANT_QA_URL`, `GALANT_QA_EMAIL` y `GALANT_QA_PASSWORD` de la instancia sintética. Las capturas se guardaron en el directorio de trabajo de QA, fuera de los datos productivos.

## Archivos principales

- Backend: `configuration_models.py`, `configuration_service.py`, `configuration_api.py` y `migrations/v13_1_0.py`; registro en `main.py` y `cli.py`.
- Integración: `control_api.py`, `compliance_api.py` y `control_reports.py`.
- Frontend: `GeneralConfiguration.tsx`, `configurationApi.ts`, `configuration.css`; navegación en `App.tsx` y `Settings.tsx`, reutilización de `NetworkAccounts.tsx` y documentación mensual manual en `MonthlyDocuments.tsx`.
- Pruebas: `test_configuration.py`, `test_configuration_postgres.py` y `qa_configuration_browser.py`.
- Prompt ajustado: [PROMPT_CONFIGURACION_GENERAL_SIN_CARGAS.md](PROMPT_CONFIGURACION_GENERAL_SIN_CARGAS.md).

## Actualización del VPS existente

Estos comandos se prepararon para el checkout `/opt/galant-post`, `.env.preview`, `docker-compose.preview.yml` y el puerto privado 18512 documentados en el repositorio. **No se ejecutaron en el VPS.**

```bash
cd /opt/galant-post
sudo git fetch --no-tags origin codex/configuracion-general-sin-cargas
sudo bash scripts/update-preview.sh b4b9cdc94e06a771871cdde685d711691b9dedf6
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps
curl -fsS http://127.0.0.1:18512/api/v1/health
```

El actualizador existente verifica el checkout, respalda PostgreSQL y documentos, ensaya la restauración aislada, construye desde el SHA exacto, detiene escritores, ejecuta la migración versionada y comprueba versión y commit antes de finalizar. Mantiene los volúmenes y el archivo de configuración existente.

Tras actualizar, comprobar `version: 13.1.0-rc1` y el SHA indicado en `/api/v1/health`. Abrir `/admin/configuracion` mediante el acceso privado habitual, verificar las tres categorías y un cambio con dos administradores, y comprobar que administrativa y residente siguen en sus espacios. No ampliar a datos reales hasta verificar en ese entorno el respaldo, la migración y los resultados de la revisión.

## Pendiente real

Revisión del PR y actualización validada del VPS con su base y respaldos reales. La candidata no se publicó como producción, no se alteró la instalación activa y no se afirmó validación externa de documentos o pagos.
