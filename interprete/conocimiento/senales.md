# Reglas de las señales

Las señales se calculan en el pipeline, no las inventa el intérprete. Para el modelo elegido:

- **Escalar (validar)**: canal pagado con ROAS de 1.2 veces el promedio pagado o más. Es una hipótesis: el ROAS es promedio, no marginal; confirmar con una prueba de incrementalidad antes de mover más del 10–15 % del presupuesto.
- **Mantener**: canal pagado con ROAS entre 0.8 y 1.2 veces el promedio.
- **Revisar**: canal pagado con ROAS de 0.8 veces el promedio o menos.
- **Proteger**: canal sin costo que asiste 2 o más ventas por cada cierre propio; no recortarlo mirando solo el último clic.
- **Aprovechar**: canal sin costo cuya conversión por usuario es 1.2 veces la mediana o más; es canal de cierre, no de alcance.
- **No es palanca**: Direct. Es el regreso de usuarios que ya conocían la marca.
- **Dentro de un segmento** no existe costo por canal, así que no hay ROAS ni CPA; las señales son: **Sobre-índice** (el canal pesa 3 pp o más que en el total), **Sub-índice** (3 pp o menos) e **Igual al total**.

Confianza de una señal: con intervalo bootstrap, por su ancho (2 pp o menos alta, 4 pp o menos media, más baja). Sin intervalo, por el volumen de pedidos: más de 3,000 alta, más de 1,000 media, menos baja.

Disparadores de reajuste anticipado (últimos 60 días frente a los 60 previos): inversión ±25 %, mix de inversión de un canal ±10 pp, pedidos ±25 %, conversión por sesión ±15 %, o un canal nuevo.
