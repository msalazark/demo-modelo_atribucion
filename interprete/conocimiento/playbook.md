# Cómo redactar

## Resumen ejecutivo (para gerencia)
Máximo 170 palabras, en este orden:
1. **Titular**: la conclusión en una frase con una cifra (qué canal pesa más y cuánto).
2. **Tres hallazgos** con cifras: quién llena el embudo (alcance), quién empuja hacia la compra (asistencia) y quién cierra (conversión). Si los tres ganadores son distintos, decir que cada canal cumple un rol.
3. **Qué hacer**: una o dos acciones, tomadas de las señales. "Escalar" siempre como hipótesis a validar.
4. **Una cautela** si corresponde: evidencia baja, canal número 1 que cambia con la ventana, estado del modelo "cambió", alertas de reajuste, o vista de segmento sin costo.

## Siguientes pasos (para decidir)
Entre 4 y 5 pasos priorizados, cada uno con: qué hacer, por qué (con una cifra) y qué se necesita.
Orden recomendado:
1. Validar con una prueba de incrementalidad el canal marcado "Escalar (validar)". Si con el tráfico actual la prueba por usuario no alcanza el EMD de referencia (30 %), proponer una prueba geográfica o un control mayor y decir cuánto cuesta en ventas.
2. Fijar la ventana de atribución: debe cubrir al menos el percentil 90 del tiempo hasta la compra; mencionar si el canal número 1 cambia entre ventanas.
3. Mantener el modelo al día: reajuste mensual; antes si hay alertas de disparadores o canales con estado "cambió".
4. Completar datos: costos de canales sin costo, client_id en todos los pedidos, impresiones para Display y Paid Social, margen por producto.
5. Llevar las tablas mart_* a BigQuery y publicar en Looker Studio.

## Cadencia de actualización
- Datos y KPIs descriptivos: diaria o semanal.
- Modelos de atribución: mensual (trimestral si el volumen es bajo); recalcular más seguido solo mueve cifras por ruido.
- Pruebas de incrementalidad: trimestral por canal grande y antes de mover más del 10–15 % del presupuesto.

## Tono
Español, ejecutivo, concreto. Sin jerga innecesaria. Cifras con su unidad (S/, %, pp, días).
