# Límites que siempre hay que respetar

1. **Correlación no es causalidad.** Los modelos de atribución reparten crédito entre canales observados; no miden cuántas ventas se perderían sin un canal. Solo una prueba de incrementalidad (grupo de control) lo mide.
2. **ROAS y CPA son promedios**, no marginales. No dicen qué pasa con el próximo sol invertido.
3. **Datos sintéticos.** Esta demo usa datos generados; el "error frente al efecto real" solo existe por eso. Con un cliente real ese número no se puede calcular y la validación se hace con pruebas de incrementalidad.
4. **El costo existe solo por canal pagado** (Paid Social, Paid Search, Display). Email, orgánico, referral y Direct no tienen costo en los datos, y dentro de un segmento no hay ROAS.
5. **Evidencia mínima:** unas 3,000 conversiones para una atribución estable; con menos de 1,000 las cuotas son muy inestables.
6. **La ventana de atribución importa.** Una ventana corta (7 días) borra los primeros contactos de más de la mitad de las compras y favorece a los canales de cierre. Si el canal número 1 cambia con la ventana, la recomendación es sensible a esa decisión.
7. **Las plataformas** (Meta, Google Ads) reportan con sus propias ventanas y reglas; sus cifras no cuadran con las de este reporte.
8. **Direct no se invierte:** aparece en casi todas las rutas porque es la puerta de regreso.
9. Las ventas salen del backend (no del evento purchase de GA4) y dependen de que el pedido guarde el client_id de GA4; los pedidos sin client_id no tienen ruta.
