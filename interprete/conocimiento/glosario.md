# Glosario

- **Ventana de análisis**: los 12 meses más recientes de datos. Se reajusta cada mes (ventana móvil).
- **Ventana de atribución** (lookback): cuántos días antes de la compra se consideran los contactos del usuario. La vigente es de 30 días; se prueban 7, 14, 30, 60 y 90.
- **Ruta de compra**: lista ordenada de los canales por los que entró el usuario antes de comprar (o hasta su última visita, si no compró).
- **Cuota**: % de las ventas que un modelo atribuye a un canal. Las cuotas de un modelo suman 100 %.
- **Modelos de regla**: primer clic, último clic, último clic no directo, lineal, posición U (40 % primera, 40 % última, 20 % medio) y decaimiento temporal (el crédito baja a la mitad cada 7 días).
- **Markov**: modelo de transiciones entre canales; mide cuánto bajarían las ventas si se quita el canal.
- **Shapley**: reparte cada venta entre los canales de su ruta según lo que cada uno aporta a la probabilidad de compra. Es el modelo más cercano al efecto real en los datos sintéticos de esta demo.
- **Brecha vs. último clic**: cuota del modelo elegido menos cuota de último clic no directo, en puntos porcentuales (pp). Positiva: el último clic subestima al canal (suele abrir o asistir). Negativa: el último clic le regala crédito (suele cerrar).
- **Roles** (rutas con 2 o más sesiones): **abre** (primera sesión), **asiste** (aparece en una posición que no es la primera ni la última; cuenta una vez por venta aunque se repita) y **cierra** (última sesión; variante configurable: último canal distinto de Direct). Una ruta de una sola sesión es **única**: no suma a abre ni a cierra.
- **Asistencias por cierre**: ventas en las que el canal asistió dividido entre ventas que cerró.
- **Alcance**: usuarios que pasaron al menos una vez por el canal. **Usuarios nuevos**: aquellos cuyo primer contacto fue el canal.
- **ROAS**: ingresos atribuidos / costo del canal. **CPA**: costo / ventas atribuidas. **MER**: ingresos totales / inversión total en medios pagados. Son promedios, no márgenes.
- **EMD (efecto mínimo detectable)**: la menor diferencia relativa en conversiones entre grupo expuesto y grupo de control que una prueba de incrementalidad puede detectar con 95 % de confianza y 80 % de poder.
- **Intervalo del 90 %**: rango en que cae la cuota Shapley al remuestrear los datos; mide la estabilidad del resultado.
- **Estado del modelo**: compara la cuota actual con la del mes anterior; "cambió" si la cuota previa queda fuera del intervalo actual.
- **Validación con experimentos**: comparar el crédito que el modelo atribuye a un canal (prorrateado a los días de la prueba) con las ventas incrementales que una prueba de incrementalidad midió de verdad. **Validado**: el atribuido cae dentro del intervalo medido. **Sin validar**: cae fuera (el modelo sobre- o subestima el canal). **Sin probar**: el canal no tiene todavía un experimento cargado.
- **Factor de calibración**: ventas incrementales medidas / ventas atribuidas por el modelo para ese mismo periodo. Es informativo: se muestra junto a la cuota pero no se aplica solo a las cuotas de ningún modelo.
