# CLAUDE.md

Guía para trabajar en este repositorio con Claude Code.

## Qué es

Modelo de atribución data-driven para ecommerce: rutas de conversión desde el export de GA4 unido a los pedidos del
backend, modelos (reglas, Markov, Shapley), métricas de decisión, dashboard en Streamlit e intérprete con Claude.
La hoja de ruta está en `docs/RQ_mejoras.md`: trabaja siempre sobre un RQ concreto.

## Comandos

```bash
python generar_datos.py        # datos sintéticos en data/ecommerce.duckdb (~3 min)
python run_demo.py             # pipeline completo: SQL, modelos, marts y narrativa (~3-5 min)
streamlit run dashboard.py     # dashboard
python -m pytest tests         # pruebas (no gastan API)
```

## Reglas del proyecto

1. **La lógica vive en el pipeline.** `run_demo.py`, `atribucion.py`, `metricas_decision.py` y `proximos_pasos.py`
   calculan; el dashboard (`dashboard.py`, `dashboard_comun.py`, `app_pages/`) y el intérprete (`interprete/`) **solo
   leen tablas `mart_*`**. No agregues cálculos de métricas en las páginas.
2. **Las tablas `mart_*` son el contrato.** Si cambias una columna, actualiza la sección 4 de `docs/RQ_mejoras.md`,
   el README, `interprete/datos.py` (lista blanca `TABLAS` y `construir_hechos`) y las páginas que la leen.
3. **El intérprete no calcula cifras.** Todo número que cite debe estar en los hechos o en herramientas de solo
   lectura; el verificador lo comprueba. No relajes esas garantías.
4. **La venta sale del backend** (`orders`), no del evento `purchase` de GA4.
5. **Las definiciones de negocio** (roles abre/asiste/cierra/único, cuota, ROAS, ventanas) están en la sección 1 de
   `docs/RQ_mejoras.md` y en `interprete/conocimiento/glosario.md`. Si cambias una, cambia ambas.
6. **SQL en dos dialectos**: `sql/` (DuckDB) y `sql_bigquery/`. Un cambio de lógica va en los dos, con prueba de
   paridad.
7. **`efecto_real` y la tabla `truth` existen solo en modo demo.** El código de producción no debe depender de ellos.
8. **Idioma:** nombres de variables, funciones, tablas, columnas y textos en español, como el código actual.
9. **Nunca** pongas credenciales en el código: `ANTHROPIC_API_KEY` por variable de entorno o
   `.streamlit/secrets.toml` (ignorado por git).
10. **Datos personales:** no leas ni guardes correo, teléfono, nombre ni dirección; los `mart_*` no llevan
    identificadores de usuario.

## Cómo entregar un cambio

- Antes de editar, resume el plan y los archivos que vas a tocar.
- Agrega o actualiza pruebas en `tests/` para los criterios de aceptación del RQ.
- Corre `python -m pytest tests` y `python run_demo.py`; compara `resultados/*.csv` con la versión anterior y explica
  cualquier cifra que cambie.
- Actualiza el README si cambia el uso, y marca el RQ como terminado en `docs/RQ_mejoras.md`.
