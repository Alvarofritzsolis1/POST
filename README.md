# GALANT POST — v0.4.0-rc1

Plataforma GALANT para gestión manual de contratistas y trabajadores, con importación Excel/CSV y un módulo OCR Beta separado. Frontend React + TypeScript, backend FastAPI y PostgreSQL. **No usa Streamlit ni importa código anterior.**

> ESTADO: **versión candidata de evaluación**. Se incorporó un Centro de Control Operativo manual con matriz de siete requisitos, asistencia/cotizaciones, retenciones propuestas y reportes CT/CI. Requiere validación del PR, respaldos y pruebas de VPS antes de integrarse/desplegarse. Ningún resultado OCR confirma una transacción ante Previred, DT, AFP o una institución bancaria.

## Base operativa (etapa 1)

- Obras Lomas Verdes, Brisas de Junquillar y Concepción, creadas por organización con período inicial septiembre de 2026. Una empresa puede asociarse a varias obras; su código histórico, frecuencia y estado contractual se conservan por obra.
- Fichas editables de contratistas y trabajadores, asignaciones por obra, búsqueda, validación de RUT e historial de modificaciones.
- Importación Excel/CSV con vista previa, corrección de filas, detección de errores y duplicados, confirmación de la interpretación de OK/P/NA, resumen de resultados y plantillas descargables. Los estados históricos conservan origen y quedan pendientes de validación; no equivalen a una aprobación documental.
- FastAPI autenticada con cookies HttpOnly, CSRF, roles, Argon2 y separación de organizaciones.

## Centro de Control Operativo — v0.4.0-rc1

La navegación inicial ahora abre **Centro de control**: tres obras y un consolidado general, selección de mes auditado, matrices por contratista y períodos, revisión manual individual o masiva **sin PDF**, registro de asistencia, días exigibles y días cotizados, cálculo de diferencias y retención administrativa sugerida desde $4.950 por día, control de independientes sin trabajador ficticio, exportaciones Excel CT/CI, calendario de solicitud, contratos y tareas, bajas administrativas y dashboard ponderado. Ninguna decisión de pago, baja o carta se ejecuta automáticamente.

La matriz muestra siete requisitos: cotizaciones, F30-1, liquidaciones firmadas, asistencia, portería, declaración jurada y listado de anticipos. Su exigibilidad depende de la naturaleza del contratista o de la configuración manual; no se exige listado de anticipos a independientes. Sin fechas de exigibilidad ni datos evaluables, el sistema no muestra incumplimiento ficticio ni 100% de cumplimiento.

**Limitaciones conocidas:** el importador histórico de contratos/anexos ya está implementado con vista previa y reglas de conflicto, y el dashboard incluye curvas mensuales, vencimientos, estados y retenciones. Falta validar la interpretación legal aplicable, probar un Excel real autorizado, respaldar/restaurar el VPS real y completar una prueba de 24 horas. Estas verificaciones **no se han ejecutado en producción**. Consulta [matriz de aceptación y QA](docs/GALANT_OPERATIVO_QA.md).

Para crear las tablas aditivas, usa `python -m app.cli init-db` únicamente después de respaldar y verificar el entorno. `scripts/backup-preview.sh` crea copias de PostgreSQL y de documentos privados con comprobaciones de integridad; `scripts/verify-restore-preview.sh` comprueba un ensayo de restauración aislado y SHA256 de cada documento registrado. El procedimiento de actualización exige ambos controles antes de recrear contenedores; `scripts/soak_24h.py` prepara una prueba sintética de consistencia entre dos usuarios durante 24 horas, sin ejecutarse automáticamente. **El autodespliegue desde CI requiere ahora `VPS_AUTODEPLOY=true` explícito.**

## Usuarios compartidos y documentación mensual

**Por qué se separaban los usuarios:** el comando `create-admin` crea una organización nueva. Si las cuentas pertenecen a organizaciones distintas, sus contratistas y sus PDF quedan correctamente aislados. No se deben eliminar los filtros por organización.

Para agregar un colaborador a la **misma organización** del administrador original:

```bash
cd /opt/galant-post
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-user --email NUEVO@EMPRESA.CL --admin-email ADMIN_ORIGINAL@EMPRESA.CL --role analyst
```

Para una cuenta creada antes con `create-admin` por equivocación, si su organización **no contiene datos operativos**, se puede vincular sin cambiar la contraseña:

```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli link-user --email CUENTA_EXISTENTE@EMPRESA.CL --admin-email ADMIN_ORIGINAL@EMPRESA.CL --role analyst
```

El comando **rechaza** una cuenta que ya tenga contratistas, documentos, importaciones operativas u otros usuarios en su organización de origen: primero se requiere una migración supervisada para no perder registros. Después de vincular la cuenta es obligatorio cerrar sesión y volver a ingresar. Roles: `admin`, `analyst`, `viewer`.

**Documentación mensual básica:** en la ficha de un contratista se puede elegir AAAA-MM, ver los requisitos orientativos según su naturaleza, subir un PDF/imagen, asociar uno ya cargado en el OCR y registrar aprobación, observación, rechazo o excepción No aplica. Se mantiene el archivo original en la biblioteca OCR y la vinculación en PostgreSQL, compartida por usuarios de la misma organización. **El pago no se valida automáticamente**, y documentos antiguos sin asociación deben ser vinculados por una persona para evitar falsos positivos.

**Importante:** ejecutar `python -m app.cli init-db` tras actualizar el código para crear las tablas adicionales de documentación y controles operativos. Realizar previamente respaldo de PostgreSQL y `preview-storage`, confirmar el ambiente y probar con dos cuentas. No ejecutar `docker compose down -v`. Para el procedimiento detallado consultar [manual de usuarios y períodos](docs/MULTIUSUARIO_MENSUAL.md).

## Revisión OCR — Beta

- Interfaz de carga, historial, bandeja de revisión y visor. La versión visible se consulta al backend desplegado.
- Carga privada de PDF / imágenes con límites, inspección de firma PDF y deduplicación SHA256.
- Cola persistente PostgreSQL y worker OCR que registra resultados y errores.
- PyMuPDF para texto seleccionable y páginas mixtas, Tesseract para escaneos con orientación corregida y contraste selectivo.
- Extracción completa por página en JSON privado con coordenadas, líneas identificables y diagnóstico. La reinterpretación reutiliza el JSON si no cambiaron el archivo, el motor y el idioma disponible.
- RapidOCR opcional, desactivado por defecto por su consumo de memoria observado.
- Reglas de evidencia de pago basadas en período, comprobante, estado y folio, en contexto de la misma página; nunca declarar verificación externa.
- Evidencia por página, confianza OCR orientativa, RUT válidos, exportación Excel de campos interpretados y reinterpretación sin repetir OCR.

## Despliegue aislado en Contabo

En Ubuntu 24.04 con Docker Compose v2 y Git instalados:

    git clone https://github.com/Alvarofritzsolis1/POST.git /opt/galant-post
    cd /opt/galant-post
    sudo bash scripts/install-preview.sh

Crear administrador mediante contraseña introducida en el VPS:

    sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email ADMIN@EMPRESA.CL

En el equipo Windows, abrir PowerShell (NO ejecutar el siguiente comando dentro del VPS):

    ssh -N -L 18512:127.0.0.1:18512 root@89.117.144.140

Entrar por http://127.0.0.1:18512 desde Windows.

Esta modalidad no modifica GALANT anterior, Nginx, DNS, 80/443 ni SSH. Publicación en Internet con HTTPS se decidirá solo después de seguridad y validación. POST utiliza 127.0.0.1:18512 privado.

## Pruebas

En apps/backend, instalar requirements-dev.txt, Tesseract español/inglés y ejecutar pytest -q. En apps/frontend ejecutar npm ci y npm run build. Para comparar OCR inicial y reinterpretación, ejecutar `python scripts/benchmark_ocr.py` o añadir `--file` con una ruta autorizada. El benchmark copia el documento a un directorio temporal privado y solo imprime métricas. GitHub Actions contiene verificaciones semanales una vez que el flujo esté en la rama principal.

## Pendiente

La matriz operativa de siete requisitos, comparación manual, informes CT/CI, dashboard inicial y calendario se encuentran implementados en v0.4.0-rc1. Quedan por validar en el VPS y completar los apartados señalados en GALANT_OPERATIVO_QA.md. No se ha recibido la planilla Excel histórica para validar el reconocimiento de sus columnas; pruebe primero una copia autorizada en vista previa. El esquema actual permite agregar tablas con `init-db`, pero todavía no dispone de migraciones versionadas. El backup/restore fue probado con datos sintéticos en CI, pero falta ejecutarlo con el VPS real. Continúan pendientes antivirus documental, políticas de retención y configuración HTTPS para la publicación. Un caso privado de 14 páginas corrigió la orientación OCR, pero no demuestra precisión general de pagos.

Consulta [especificación maestra](docs/ESPECIFICACION_MAESTRA_GALANT.md), [plan por etapas](docs/PLAN_GALANT_OPERATIVO.md), docs/ARQUITECTURA.md, docs/AUDITORIA_0.2.0.md, docs/OCR_EVALUACION.md y docs/VPS.md.
