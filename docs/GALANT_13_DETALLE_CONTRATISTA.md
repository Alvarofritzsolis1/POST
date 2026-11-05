# GALANT POST 13.0.0-rc1 — Ficha exclusiva de asistencia por contratista

## Base y alcance
- Base: `main` v12.1.0.
- Objetivo prioritario: sustituir la expansión del formulario al final de la matriz de asistencia por una **pantalla exclusiva**.
- Perfiles afectados: Administrador y Administrativo, reutilizando el componente existente.
- Sin migraciones de base de datos, eliminación de históricos ni cambios de permisos de backend.

## Navegación
- Desde el nombre del contratista, el estado semanal o «Abrir contratista» se abre una ficha que reemplaza la tabla general.
- Flecha a la izquierda: «Volver a contratistas».
- La vista conserva en memoria filtro, búsqueda, semana, obra y período del listado.
- La ruta se expresa mediante `attendance_contractor`, `attendance_site`, `attendance_period` y `attendance_week` en la URL, respetando el enrutamiento actualmente utilizado por la aplicación.
- Se integra con Historial Atrás/Adelante del navegador; los enlaces directos recuperan obra, período y selección cuando el usuario está autorizado.
- Se restaura la posición de desplazamiento al volver.

## Ficha
- Cabecera exclusiva con contratista, RUT, obra, período, estado y flecha de regreso.
- Indicadores reales calculados a partir de los datos `attendance-v81/overview` ya autorizados.
- Pestañas: **Asistencia, Trabajadores, Contratos y Finiquitos**.
- La pestaña inicial es Asistencia; utiliza el editor semanal `WeeklyAttendanceV81` ya operativo, junto a sus reglas existentes de días hábiles, plazos y registro tardío.
- Contratos/finiquitos reflejan información laboral de la obra y mantienen las autorizaciones existentes; las aprobaciones documentales continúan en el módulo laboral original.
- Alertas si existen cambios de asistencia sin guardar al cambiar de semana, pestaña, regresar o recargar la página.
- Se elimina el bloque `av92-selected` debajo de la tabla general.

## Precauciones y límites
- Se conserva el flujo existente de `ContractEntry` para registrar contratos; no se inventan nuevos endpoints.
- La clasificación CT/CE/CI se obtiene del COD de la asociación contratista-obra (backend), no de una inferencia por tipo global de empresa; si no está disponible, se omite sin inventarla.
- La regla de semanas y asistencia no se reescribe en el frontend: permanece la lógica del backend existente.
- El control de acceso permanece en backend; una URL con un ID ajeno no debe revelar datos.
- **No desplegar la rama en producción sin CI verde y revisión manual de roles/obras/datos reales.**

## QA pendiente antes de marcar versión estable
1. `npm ci && npm run build` sobre frontend.
2. `pytest` backend, Compose y workflows de QA en GitHub Actions.
3. Administrador: abrir contratista por nombre, botón y badge semanal; verificar desaparición de la matriz.
4. Administrativo: misma navegación desde obra asignada y sin acceso indebido a otra obra.
5. Volver por flecha y por navegador, verificar búsqueda/filtros/scroll y restauración del mes.
6. Recargar enlace directo; comprobar selección sin ver contratistas de otras obras.
7. Modificar asistencia y cambiar semana/pestaña/regresar: advertencia de cambios sin guardar.
8. Guardar una semana tardía y confirmar auditoría, plazos y métricas.
9. Revisar pestañas con 0, 1 y decenas de trabajadores; pantallas 360, 768 y 1440 px.
10. Confirmar que ninguna funcionalidad del listado ni evaluaciones existentes sufrió regresión.

**Estado:** Candidato de versión 13; la compilación y las pruebas deben verificarse con evidencia del commit y CI antes de fusionar/desplegar.
