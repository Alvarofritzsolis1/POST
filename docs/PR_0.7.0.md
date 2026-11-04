GALANT necesitaba coordinar requerimientos y capacidad entre obras y registrar qué contratista obtiene cada cantidad de una partida. Esta versión incorpora Red de Obras al sistema actual, con residentes limitados por obra, invitaciones, coincidencias explicables, conversación vinculada y adjudicación parcial o múltiple visible para cada partida.

La migración crea tablas nuevas y reutiliza usuarios, obras, contratistas, auditoría y matriz documental. PostgreSQL serializa adjudicaciones y administración crítica; la ejecución exige habilitación en destino. Se conservan los módulos anteriores y sus permisos.

Validación: 92 pruebas correctas; los dos casos omitidos en SQLite pasan en PostgreSQL. Compilación TypeScript/Vite, configuración Compose y recorrido de navegador con dos residentes, mensajes, adjudicación 60+40 y móvil, sin errores JavaScript ni HTTP 5xx. Reinicio local de PostgreSQL, API, frontend y proxy verificado con datos conservados. El CI incorpora el mismo recorrido sobre un stack descartable.

Preparada para revisión, sin despliegue de producción. Invitaciones con enlace manual o SMTP configurado. Detalle de operación, pruebas y actualización segura en `docs/RED_DE_OBRAS_0.7.0.md` y `docs/ENTREGA_0.7.0.md`.
