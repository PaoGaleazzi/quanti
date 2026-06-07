# Diseño de la Fase "Ejecutar" (Automatización)
### Always on Shelf · Pao
### Pieza: pedido nuevo + mapa aprendido → transformar → llenar Arca

---

## 1. Diferencia clave con "aprender"
- **Aprender** llama al LLM (una vez por cliente).
- **Ejecutar NO llama al LLM.** Solo lee el mapa guardado y lo aplica mecánicamente.
- Por eso es gratis y rápido en cada pedido. El LLM solo reaparece si hay un STOPPER (pieza aparte).

---

## 2. Flujo de la fase ejecutar
1. Recibe el `cliente_portal` (HEB/Sanborns) y los datos de un pedido NUEVO.
2. Lee el `mapa_json` de la tabla `mapas_aprendidos` para ese cliente.
3. Para cada campo del mapa, aplica su `transformacion`.
4. Llena el portal de Arca con los valores transformados (Playwright).
5. Guarda el pedido en `pedidos` + `pedido_detalle`.

> Versión SIMPLE primero: recibe los datos del pedido nuevo como dict (sin leer el portal cliente).
> Cuando funcione, se le agrega al inicio la lectura del portal cliente con Playwright.

---

## 3. Las transformaciones (el corazón de ejecutar)

| transformacion | qué hace | ejemplo |
|---|---|---|
| `directa` | copia el valor tal cual | "Coca-Cola 600ml" → "Coca-Cola 600ml" |
| `conversion_unidad` | convierte usando catálogo | 3 cajas × 24 = 72 piezas (Sanborns) |
| `lookup_catalogo` | busca SKU por nombre en `productos` | "Coca-Cola 600ml" → "SKU-0001" |
| `formato_fecha` | reformatea fecha si difiere | "11/06/2025" → "2025-06-11" |
| `calculado` | deriva de otros campos | importe = cantidad × precio_unitario |

**El caso estrella (Sanborns, conversion_unidad):**
- El pedido dice `unidades_pedidas = 3` (cajas).
- El mapa dice: transformacion = conversion_unidad, factor = productos.piezas_por_caja.
- El bot busca en la tabla `productos` el `piezas_por_caja` del producto (ej. 24).
- Calcula 3 × 24 = 72 y escribe 72 en `cantidad` de Arca.
- Esto demuestra RAZONAMIENTO, no copia. Mostrarlo en el demo.

---

## 4. Lo que necesita de la base
- Leer `mapas_aprendidos` (el mapa).
- Leer `productos` (para lookup de SKU y piezas_por_caja).
- Escribir en `pedidos` y `pedido_detalle` (el pedido ejecutado).

---

## 5. Prompt para Claude Code (construir el ejecutor)

```
Lee CLAUDE.md, docs/Diseno_Fase_Ejecutar.md y docs/Mapa_Aprendido_JSON.md.

Construye motor/ejecutar.py que:
1. Reciba cliente_portal (ej. "Sanborns") y un dict con un pedido NUEVO.
2. Lea el mapa_json de la tabla mapas_aprendidos para ese cliente (conexión DB_* del .env).
3. Aplique las transformaciones de cada campo segun el mapa:
   - directa: copia tal cual
   - conversion_unidad: busca piezas_por_caja en la tabla productos y multiplica
   - lookup_catalogo: busca el sku por nombre de producto en la tabla productos
   - formato_fecha: reformatea si hace falta
   - calculado: deriva (ej. importe = cantidad * precio_unitario)
4. Devuelva los datos ya transformados, listos para Arca.
5. Guarde el pedido en las tablas pedidos y pedido_detalle.

EMPIEZA SIMPLE: recibe el pedido nuevo como dict hardcodeado de prueba, NO leas el portal 
cliente todavia. Quiero ver que las transformaciones funcionan, sobre todo la conversion 
cajas->piezas de Sanborns (3 cajas de un producto con 24 piezas/caja debe dar 72).

Requisitos:
- NO llames al LLM en esta fase (solo aplica el mapa guardado).
- Codigo simple y comentado, que pueda explicar al jurado.
- Explicame cada funcion.
- No toques .env ni hagas commits.

Cuando termines, corre la prueba con un pedido dummy de Sanborns y muestrame:
- los datos transformados (que la conversion de cajas haya dado bien)
- confirmacion de que se guardo en pedidos/pedido_detalle.
```

---

## 6. Después de esto
- Probar con pedido NUEVO (datos distintos a la observación) → demuestra que aprendió, no memorizó.
- Conectar la lectura del portal cliente al inicio (Playwright) → flujo completo del demo.
- Luego: la pieza de STOPPERS (cuando aparece algo inesperado, ahí sí llama al LLM).
