# Entrega GALANT POST 0.7.0 · Red de Obras

Implementación del prompt maestro en `Alvarofritzsolis1/POST`, conservando React, FastAPI, PostgreSQL, Docker y los módulos anteriores. No se desplegó producción ni se utilizaron datos reales.

## Resultado funcional

- Administrador: menú superior, invitaciones, usuarios, roles, suspensión, obras asignadas y autorización específica de adjudicación.
- Residente: ingreso directo a Red de Obras, creación y edición en sus obras, consulta colaborativa limitada y bloqueo de los demás módulos en el servidor.
- Requerimientos y capacidad: partidas dinámicas sin límite de tres, borradores persistentes, archivos privados, fechas, estados, caducidad y renovación.
- Coincidencias: algoritmo determinístico con razones y capacidad libre; estados de confirmación separados de publicación y adjudicación.
- Coordinación: etapas, aprobación, conversación única, participantes, archivos, lectura, mensajes y notificaciones entre usuarios.
- Adjudicación por partida: empresas distintas, distribución parcial, saldos, ampliaciones, reprogramación, ejecución, revocación y auditoría. La cantidad ejecutada no se confunde con la adjudicada.
- Integración documental: consulta por contratista y obra de destino; ejecución bloqueada cuando falta habilitación.
- Interfaz: indicadores calculados con datos de la base, filtros, gráficos, tarjetas, lista, Kanban, calendario mensual/semanal y CSV por obra. Paneles, menús y movimiento reducido accesibles.

## Verificación ejecutada

| Comprobación | Resultado |
|---|---|
| Suite completa del backend, incluida regresión histórica | **92 correctas, 2 omitidas intencionalmente** |
| Dos casos de concurrencia en SQLite | Omitidos porque requieren bloqueo real de PostgreSQL |
| Esos mismos dos casos en PostgreSQL 16 | Correctos: no sobreasignación y no pérdida del último administrador |
| Migración aditiva e idempotente, conservación de cuentas y obras | Correcta en SQLite y PostgreSQL |
| Compilación TypeScript y Vite de producción | Correcta |
| Ruff, compilación Python y configuración Docker Compose | Correctas |
| Navegador: administrador crea dos residentes mediante invitaciones | Correcto |
| Navegador: tres partidas, capacidad compartida y coincidencia | Correcto |
| Navegador: intercambio de mensajes entre dos residentes | Correcto |
| Navegador: 60 + 40 adjudicadas a dos empresas | **100 adjudicadas, 0 pendientes, 0 ejecutadas** |
| Navegador: escritorio, móvil 390 px y calendario semanal | Correctos; sin desbordamiento horizontal de la página |
| Errores JavaScript y respuestas HTTP 5xx durante el recorrido | **0** |
| Reinicio de PostgreSQL, API, frontend y proxy | **Correcto: cuentas, requerimiento, capacidad, mensajes y adjudicaciones conservados; acceso por navegador verificado nuevamente** |

La suite muestra una advertencia de deprecación de Starlette sobre su cliente de pruebas HTTP. No produjo fallos; no se presenta como error de la aplicación.

La verificación usa datos sintéticos en bases aisladas. Se construyeron imágenes Docker del backend y frontend. Tras agotar el almacenamiento temporal al reconstruir, se recuperaron cachés y se verificó el código final y la compilación de producción montados en solo lectura dentro de esos contenedores, con PostgreSQL y volumen privado persistentes. No equivale a un despliegue de la instalación real.

## Reproducir las pruebas

Desde `apps/backend`, con dependencias de `requirements-dev.txt` y PostgreSQL descartable:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USUARIO:CLAVE@127.0.0.1:5432/BD_PRUEBA python -m pytest -q
```

Cada caso de Red de Obras en PostgreSQL usa su propio esquema de ensayo. No ejecutar este comando contra una base real.

Desde `apps/frontend`:

```bash
npm ci
npm run build
```

Con un stack local descartable, un administrador sintético y Playwright/Chromium:

```bash
export GALANT_NETWORK_QA_EMAIL=correo-del-administrador-de-qa
export GALANT_NETWORK_QA_PASSWORD=contraseña-del-administrador-de-qa
python scripts/qa_network_browser.py --url http://127.0.0.1:18612 --output work/red-de-obras-qa
# Después de reiniciar exclusivamente ese stack de ensayo:
python scripts/qa_network_browser.py --url http://127.0.0.1:18612 --output work/red-de-obras-qa --verify-only
```

El script rechaza hosts distintos de localhost/127.0.0.1. Crea usuarios y contratistas sintéticos. No se incluye ninguna contraseña real. GitHub Actions incorpora el recorrido y publica su reporte y capturas como artefacto de QA.

## Preparación de la actualización

Revisar la migración `0.7.0`, preparar el respaldo y verificar su restauración con los scripts existentes. La nueva API requiere las tablas de la migración antes de iniciar. La aplicación conserva sus controles anteriores de despliegue y rollback.

Para envío de invitaciones y recuperación automática por correo se requiere SMTP. Sin él, la cuenta se crea y el administrador comparte el enlace de un solo uso desde el panel. Las alertas temporales se revisan mientras se utiliza el portal; no se añadió un servicio autónomo de notificaciones en segundo plano.

La guía operativa, permisos, estados, modelo de persistencia y configuración están en [RED_DE_OBRAS_0.7.0.md](RED_DE_OBRAS_0.7.0.md).
