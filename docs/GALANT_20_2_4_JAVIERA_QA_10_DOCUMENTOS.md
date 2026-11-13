# GALANT 20.2.4-rc1 — Prueba integral de documentos de Proyecto Javiera

## Incidencia observada
La captura mostraba «EPP ambiguo o no contemplado en matriz original: 13-11-2026». El motor recibía una **fecha** en `event.epp_items` y la trataba como descripción de EPP.

### Causa raíz
El formulario permitía texto libre para un campo que la planilla original representa mediante solo ocho filas de cantidad, D12:D19. El error era detectado después de intentar generar un PDF, en lugar de comunicarse desde la validación de campos.

### Solución
- Backend y Excel comparten `javiera_epp.py`, único catálogo autorizado de ocho elementos y sus alias conocidos.
- `validate_requirements` muestra antes de la conversión los errores de EPP, fechas, cantidades fuera de rango, categorías desconocidas o ambiguas.
- React carga el catálogo desde API y muestra cantidades numéricas (0–30), sin un campo de texto libre.
- Los expedientes antiguos conservan sus datos originales; si contienen una fecha u otro texto inválido, el usuario debe retirarlo explícitamente antes de registrar los EPP realmente entregados.
- Los valores vacíos no se rellenan con EPP ficticios: en D12:D19 las cantidades no declaradas permanecen vacías.
- Se conservan las validaciones de matriz, plantilla aprobada, firmas y fecha efectiva de la entrega.

## Matriz de pruebas automatizadas
| Documento | Caso positivo | Caso negativo |
|---|---|---|
| Contrato de trabajo | Datos completos | Sueldo faltante |
| Anexo de traslado | Obra y traslado completos | Fecha de traslado faltante |
| Anexo de prórroga | Nuevo término posterior | Nuevo término faltante |
| Declaración jurada | Empresa sin trabajador y período | Período faltante |
| Recepción Reglamento Interno | Comuna, ciudad y fecha | Comuna faltante |
| Entrega de EPP | EPP autorizado y cantidades válidas | Fecha en campo EPP |
| IRL | Cargo y matriz aprobada | Cargo faltante |
| PTS | Matriz aprobada, representante | RUT representante faltante |
| Recepción de PTS | Versión y fecha real | Versión PTS faltante |
| Inducción prevención | Mandante y datos completos | Mandante faltante |

Adicionalmente:
- Pruebas parametrizadas de fechas, EPP ambiguos, cantidades excesivas y elementos desconocidos.
- Verificación de ocho EPP contra las celdas reales D12:D19 del Excel sintético.
- Prueba de navegador de ocho entradas numéricas y eliminación del campo de texto libre.
- CI completa de frontend, backend, PDF, IRL, navegador, copias de seguridad y aislamiento de usuarios.

## Alcance real de la garantía
Las pruebas sintéticas y la compilación son **necesarias, no suficientes**, para certificar el Excel privado de producción. La matriz, fotos, fórmulas y textos legales deben contrastarse documento por documento contra el archivo Excel original cargado por el usuario, usando una copia y expedientes ficticios autorizados.

No modificar ni autoaprobar plantillas productivas por un error de prueba. No suprimir alertas sin corregir la causa. Documentar resultados, errores residuales y tiempos medidos.

## Criterios de entrega
1. Ninguna fecha interpretada como EPP.
2. Ningún EPP ficticio añadido por defecto.
3. Ninguna descarga habilitada mientras un documento conserve errores reales.
4. Los diez formatos se prueban con un ejemplo válido y otro incompleto.
5. CI aprobada antes del despliegue.
6. Versión y commit exactos verificados desde la API del VPS.
