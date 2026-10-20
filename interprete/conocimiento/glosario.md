# Glosario

- **Ventana de análisis**: los 12 meses más recientes de datos. Se reajusta cada mes (ventana móvil).
- **Ventana de atribución** (lookback): cuántos días antes de la compra se consideran los contactos del usuario. La vigente es de 30 días; se prueban 7, 14, 30, 60 y 90.
- **Ruta de compra**: lista ordenada de los canales por los que entró el usuario antes de comprar (o hasta su última visita, si no compró).
- **Cuota**: % de las ventas que un modelo atribuye a un canal. Las cuotas de un modelo suman 100 %.
- **Modelos de regla**: primer clic, último clic, último clic no directo, lineal, posición U (40 % primera, 40 % última, 20 % medio) y decaimiento temporal (el crédito baja a la mitad cada 7 días).
- **Markov**: modelo de transiciones entre canales; mide cuánto bajarían las ventas si se quita el canal.
- **Shapley**: reparte cada venta entre los canales de su ruta según lo que cada uno aporta a la probabilidad de compra. Es el modelo más cercano al efecto real en los datos sintéticos de esta demo.
- **Brecha vs. último clic**: cuota del modelo elegido menos cuota de último clic no directo, en puntos porcentuales (pp). Positiva: el último clic subestima al canal (suele abrir o asistir). Negativa: el último clic le regala crédito (suele cerrar).
- **Roles**: abridor (primer contacto), asistente (aparece en la ruta sin ser el último canal no directo) y conversor/cerrador (último canal no directo).
- **Asistencias por cierre**: ventas en las que el canal asistió dividido entre ventas que cerró.
- **Alcance**: usuarios que pasaron al menos una vez por el canal. **Usuarios nuevos**: aquellos cuyo primer contacto fue el canal.
- **ROAS**: ingresos atribuidos / costo del canal. **CPA**: costo / ventas atribuidas. **MER**: ingresos totales / inversión total en medios pagados. Son promedios, no márgenes.
- **EMD (efecto mínimo detectable)**: la menor diferencia relativa en conversiones entre grupo expuesto y grupo de control que una prueba de incrementalidad puede detectar con 95 % de confianza y 80 % de poder.
- **Intervalo del 90 %**: rango en que cae la cuota Shapley al remuestrear los datos; mide la estabilidad del resultado.
- **Estado del modelo**: compara la cuota actual con la del mes anterior; "cambió" si la cuota previa queda fuera del intervalo actual.
