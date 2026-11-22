# GALANT 20.9.15-rc1 — Galancito General

## Un solo chat
El administrador ve un único widget Galancito para toda la plataforma. La página
independiente de residentes usa el mismo componente. Las pestañas antiguas
«Red de Obras»/«Interno 360°» se eliminaron. Las consultas anteriores a
`area=red_obras` o `area=interno` siguen aceptándose en la API para no romper
integraciones existentes. El bot Messenger de candidatos sigue independiente:
su función no es el chat interno empresarial.

## Enrutamiento
- Saludos sencillos: respuesta rápida local, sin consumir modelo.
- Estados, cifras, documentos, publicación, obras y versión: exclusivamente
  consultas autorizadas a GALANT y respuestas basadas en datos comprobados.
- Consejos y preguntas generales: Qwen3.5 4B (`qwen3.5:4b-q4_K_M`).
  **No existe degradación automática a Qwen1.7B**. Si el 4B no está preparado,
  el chat devuelve una explicación de respaldo, no inventa datos.
- Consultas genéricas de análisis realmente complejo: Galancito detecta la
  complejidad del texto automáticamente. Si la organización ya tiene activa
  una conexión `red_obras` aprobada, llama a esa API sin pedir al usuario
  que seleccione manualmente el proveedor en cada mensaje. Respeta permisos,
  cuota y revisión; ante fallos vuelve al Qwen 4B, si está operativo.
  Consultas sencillas, aunque contengan «analiza» o «compara», usan el
  modelo local y no consumen API externa.
- **Nunca** se envían a API externa títulos internos de obras, nombres de
  contratistas, fichas, RUT, correos ni documentos. Las respuestas de modelos
  externos no prueban que se hayan consultado sistemas internos.
- El enrutamiento automático no activa proveedores deshabilitados ni autoriza
  nuevas credenciales, cuotas o permisos. La conexión se habilita previamente
  desde Configuración IA por un administrador; luego cada pregunta se clasifica
  sin controles manuales en el chat. El servidor vuelve a aplicar la política.
- Búsqueda pública en internet es un control distinto y explícito, que
  requiere `GALANCITO_BRAVE_SEARCH_API_KEY` configurada en el servidor.

## Activar 4B en el VPS con seguridad
Hay un procedimiento ya existente `scripts/upgrade-galancito-qwen35.py`.
No basta con fusionar la versión: comprueba el modelo instalado, memoria
disponible y configuración. El procedimiento exige un respaldo previo,
mínimo 7 GiB de RAM disponible, suficiente espacio en disco y detener
el entrenamiento antes de cambiar el motor.

Desde el directorio del proyecto del VPS, con credenciales de administración
del servidor y un mantenimiento autorizado:

```bash
python3 scripts/upgrade-galancito-qwen35.py
# Revisar que los controles previos pasaron y que hay copia de seguridad.
python3 scripts/upgrade-galancito-qwen35.py --activate
```

La ejecución con `--activate` puede reconstruir servicios y **no** debe
ejecutarse durante la atención a candidatos o una ronda en curso. El
procedimiento conserva configuración anterior y ejecuta pruebas sintéticas
de respuesta y latencia; si falla, revise el rollback. No publique claves
en capturas, chat ni GitHub.

Una vez activo, desde administración abre **Galancito > Probar respuesta**.
La prueba responde desde Ollama con una pregunta ficticia, sin usar datos
de producción. Si la prueba falla, el estado «Configurado» no equivale
a «operativo».

## Práctica Bot específica
El perfil «Galancito General» usa el identificador interno `interno` para
preservar evaluaciones anteriores. Conserva 20 categorías/400 casos
sintéticos y permite 1–40 ciclos con máximo 10.000 evaluaciones por ronda.
Por defecto elige `ollama`, que exige el 4B activado; la alternativa
`guided` verifica reglas sin IA y nunca se debe interpretar como
mejora real del modelo. La práctica tampoco modifica los pesos de Qwen.

Mantener pausas, prioridad para Messenger y límites de recursos; no
ejecutar 40 ciclos en horario de máxima carga.

## Validación para liberar
1. CI de frontend, backend, seguridad y 400 casos sintéticos.
2. QA con administrador y residente y acceso a documentos restringidos.
3. Prueba real de modelo 4B en el VPS (saludo, consulta factual y consulta
   compleja) y de API solo cuando la conexión autorizada existe.
4. Medición de latencia y memoria durante tráfico normal y práctica.
5. Verificación de versión desplegada, respaldo y rollback.

**Límites:** no es un agente universal de escritura, no garantiza informes
de todos los módulos y no dispone de aprendizaje autónomo de pesos.
