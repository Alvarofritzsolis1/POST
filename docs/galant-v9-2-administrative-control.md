# GALANT POST v9.2.0-rc1 — Control laboral de obra

## Alcance

La vista administrativa muestra los contratistas activos de su obra sin escribir un nombre en el buscador. En la misma pantalla muestra el cumplimiento semanal, la dotación vigente, las alertas contractuales y los finiquitos pendientes, y permite abrir el registro de asistencia de un contratista con un clic.

Se añadieron las pestañas **Asistencia semanal**, **Contratos de trabajo**, **Finiquitos**, **Dotación vigente** y **Mi rendimiento**. La consulta de trabajadores es histórica por fecha; los estados del documento de finiquito son el estado registrado actualmente. La condición contractual "vencido" exige verificación humana: por sí sola no confirma término laboral.

## Arquitectura y datos

- `GET /api/v1/attendance-v81/overview?site_id=<id>&period=AAAA-MM&as_of=AAAA-MM-DD` (as_of opcional): lectura acotada a obra, resumen semanal y estado contractual/documental por trabajador.
- `GET /api/v1/attendance-v81/my-evaluation?period=AAAA-MM`: únicamente la evaluación personal del administrativo autenticado; no cambia la aprobación/cierre que realiza el administrador.
- Reutiliza `ContractorWorksite`, `WorkerAssignment`, `ContractRegister`, `WorkerTermination`, `CalendarWeek` y `CalendarDuty`. No crea tablas paralelas ni cambia el esquema.
- Respeta la lista de obras asignadas mediante `_scope` y nunca ofrece datos financieros de cotizaciones a la administrativa.
- Mantiene la numeración interna de semanas y conserva la evidencia histórica de sábado/domingo; solo lunes a viernes generan obligaciones nuevas.
- Las revisiones tardías quedan reflejadas como tales; el estado "completado tarde" no se confunde con "pendiente vencido".
- Recepción y validación de finiquitos siguen restringidas a revisores documentales en los endpoints existentes de `/labor`. El módulo administrativo los puede consultar y detectar pendientes; no se conceden permisos peligrosos de aprobación automática.

## Revisión previa obligatoria

1. Confirmar que el CI de GitHub ejecutó correctamente el build de React/TypeScript, tests de backend y Compose.
2. Verificar en QA Concepción, Lomas Verdes y Brisas de Junquillar con datos autorizados y una cuenta administrativa restringida a cada obra.
3. Probar visualmente 3 y 100 contratistas, filtros, selección de semana y trabajadores, contratos indefinidos/vencidos, finiquitos pendientes, semanas de 4/5 días y domingos no exigibles.
4. Comprobar trazabilidad por nombre, estados sin pérdida de firmas y cálculo de evaluación sin penalizar semanas futuras.
5. Ejecutar respaldo verificable antes de cualquier actualización del VPS. No desplegar si falla la validación.

## Actualización segura del VPS (solamente tras merge y CI aprobada)

La instalación conocida utiliza `/opt/galant-post` y `docker-compose.preview.yml` con `.env.preview`. El actualizador del repositorio ya incluye respaldo con prueba de restauración, migración controlada y rollback del código si el despliegue falla.

Desde la sesión SSH en el VPS:

```bash
cd /opt/galant-post
git fetch origin main
TARGET_SHA="$(git rev-parse origin/main)"
echo "Actualización propuesta: $TARGET_SHA"
bash scripts/update-preview.sh "$TARGET_SHA"
docker compose --env-file .env.preview -f docker-compose.preview.yml ps
docker compose --env-file .env.preview -f docker-compose.preview.yml exec -T api python -c 'from app.version import VERSION; print(VERSION)'
```

**No ejecutar** el actualizador apuntando a una rama en revisión. Confirmar el SHA fusionado en `main` y que no hay modificaciones locales pendientes. Si la instalación usa otro compose/env, revisarlo antes.

Después comprobar desde la URL real de la plataforma:

- `/api/v1/version` responde `9.2.0-rc1` y SHA esperado.
- `/api/v1/health` responde `status=ok`.
- El frontend muestra `v9.2.0-rc1`; probar sesión nueva o recarga sin caché.
- Las firmas históricas de sábados y domingos siguen intactas, aunque esos días no generen nuevas obligaciones.

## Pendientes para iteración posterior

- Esta primera entrega conserva las operaciones delicadas de finiquito y término en el módulo principal protegido: su revisión documental no se delega automáticamente a administrativas.
- La actualización entre sesiones está respaldada por la base de datos compartida; el panel dispone de refresco manual. Notificaciones en tiempo real se pueden integrar por separado.
