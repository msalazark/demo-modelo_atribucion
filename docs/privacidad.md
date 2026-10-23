# Privacidad y datos personales (RQ-28)

Cumplimiento de la **Ley 29733** (Ley de Protección de Datos Personales, Perú) en este pipeline.

## Qué datos personales toca el pipeline

El contrato de entrada (`docs/contratos_datos.md`) permite que la fuente **pedidos** traiga
`customer_id`. No se lee correo, teléfono, nombre ni dirección en ningún punto del pipeline: no
están en el contrato y el código no los referencia.

| Dato | Tratamiento |
|---|---|
| `user_pseudo_id` (GA4) | Pseudónimo de GA4; se usa solo en las tablas de trabajo (`sesiones`, `rutas`, `pedidos_resueltos`), nunca en una tabla `mart_*` |
| `ga_client_id` / `ga_session_id` | Igual que `user_pseudo_id`: solo en tablas de trabajo |
| `customer_id` | Si se necesita guardar (hoy no se persiste en ninguna tabla), se guarda con `privacidad.hash_customer_id()` (sha256), nunca en texto plano |
| `user_id` | Pseudónimo que el sitio asigna al loguearse (RQ-07); mismo tratamiento que `user_pseudo_id` |
| correo, teléfono, nombre, dirección | **No se leen.** No están en el contrato de datos (`docs/contratos_datos.md`) |

## Garantía: las tablas `mart_*` no llevan identificadores de usuario

`privacidad.verificar_marts_sin_pii(con)` revisa el esquema de todas las tablas `mart_*` contra
una lista de columnas sensibles (identificadores de usuario y PII directa) y falla si encuentra
una coincidencia. Se corre en `tests/test_privacidad.py` contra la base de datos de la demo
después de `run_demo.py`, y debe correr igual contra BigQuery en producción.

Por diseño, los `mart_*` solo agregan por canal, modelo, ventana y segmento — nunca por usuario —
así que esta prueba no debería fallar nunca salvo que un cambio futuro agregue una columna de
usuario a una tabla `mart_*` por error.

## Retención

`privacidad.aplicar_retencion_eventos(con, meses)` borra de `events` las filas con más de
`retencion_eventos_meses` (configurable, por defecto 13 meses) de antigüedad. **No se corre
automáticamente en cada corrida de `run_demo.py`**: es una operación destructiva que se agenda
aparte (p. ej. un job mensual en Cloud Scheduler, RQ-24), para no borrar datos de golpe como
efecto secundario de correr el pipeline.

## Pendiente

- Decidir el mecanismo de baja/rectificación de datos a pedido del titular (derecho ARCO de la
  Ley 29733) cuando haya un cliente real con usuarios identificables — hoy no aplica porque el
  pipeline no guarda PII directa.
- Si en el futuro se agrega `margen` (RQ-03, campo opcional de pedidos) u otro dato comercial
  sensible, confirmar que tampoco llegue a una tabla `mart_*` sin agregar.
