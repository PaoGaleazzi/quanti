# Estructura del "Mapa Aprendido" (learned_map)
### La pieza central — la produce Pao, la leen Steff, Xime y Fer

Este es el JSON que el LLM genera tras **observar una vez** el llenado de un pedido.
Es a la vez el **cerebro** (lo que se ejecuta después) y la **observabilidad** (lo que prueba que aprendió sin hardcodear).

---

## 1. Estructura completa (con todos los campos)

El mapa ahora tiene DOS partes:
- **`navigation_flow`** → la SECUENCIA de pasos/pantallas (para flujos multi-pantalla)
- **`field_mappings`** → la correspondencia de campos (qué va a dónde)

```json
{
  "map_id": "uuid-o-timestamp",
  "cliente_portal": "HEB",
  "fecha_aprendizaje": "2025-06-06T16:00:00",
  "modelo_llm": "gpt-4o",

  "navigation_flow": [
    {
      "paso": 1,
      "pantalla": "productos",
      "accion": "leer_datos",
      "descripcion": "Leer la tabla de productos del pedido",
      "selector_referencia": "tabla de productos",
      "confianza": 0.95
    },
    {
      "paso": 2,
      "pantalla": "productos",
      "accion": "click",
      "descripcion": "Avanzar a la pantalla de entrega",
      "selector_referencia": "boton 'Continuar' / 'Programar entrega'",
      "confianza": 0.93
    },
    {
      "paso": 3,
      "pantalla": "entrega",
      "accion": "leer_datos",
      "descripcion": "Leer fecha y datos de entrega",
      "selector_referencia": "campos de entrega",
      "confianza": 0.90
    },
    {
      "paso": 4,
      "pantalla": "confirmacion",
      "accion": "click",
      "descripcion": "Confirmar/guardar el pedido",
      "selector_referencia": "boton 'Confirmar'",
      "confianza": 0.92
    }
  ],

  "field_mappings": [
    {
      "campo_origen": "user_id",
      "campo_destino": "client_id",
      "transformacion": "directa",
      "pantalla_origen": "productos",
      "confianza": 0.98,
      "razonamiento": "Ambos identifican al cliente; valores numéricos que coinciden en posición y tipo."
    },
    {
      "campo_origen": "product",
      "campo_destino": "producto_nombre",
      "transformacion": "directa",
      "pantalla_origen": "productos",
      "confianza": 0.95,
      "razonamiento": "Nombre de producto en ambos sistemas; texto idéntico observado."
    },
    {
      "campo_origen": "qty",
      "campo_destino": "cantidad",
      "transformacion": "directa",
      "pantalla_origen": "productos",
      "confianza": 0.93,
      "razonamiento": "Cantidad en piezas en ambos; HEB y Arca usan la misma unidad."
    },
    {
      "campo_origen": "unit_price",
      "campo_destino": "precio_unitario",
      "transformacion": "directa",
      "pantalla_origen": "productos",
      "confianza": 0.90,
      "razonamiento": "Precio por unidad; mismo orden de magnitud observado."
    },
    {
      "campo_origen": "delivery_date",
      "campo_destino": "fecha_entrega_estimada",
      "transformacion": "formato_fecha",
      "parametros": { "formato_origen": "YYYY-MM-DD", "formato_destino": "YYYY-MM-DD" },
      "pantalla_origen": "entrega",
      "confianza": 0.92,
      "razonamiento": "Fecha de entrega; capturada en la pantalla de entrega."
    }
  ],

  "campos_sin_mapeo": [
    {
      "campo": "sku",
      "lado": "destino",
      "nota": "Arca requiere SKU pero el portal no lo da; se infiere por nombre de producto vía catálogo."
    }
  ],

  "confianza_global": 0.94
}
```

> 💡 **El `navigation_flow` es lo que sube a nivel "Avanzado" en la rúbrica.** Captura que el proceso tiene varios pasos y pantallas, no solo un formulario. El campo `pantalla_origen` en cada mapping dice en qué pantalla se lee ese dato. Para un flujo de UNA sola pantalla, `navigation_flow` tiene un solo paso de "leer y guardar" — la estructura sirve igual para simple y complejo.

---

## 2. Ejemplo con SANBORNS (el caso difícil: cajas → piezas)

Aquí el LLM debe demostrar **razonamiento**, no copia. Sanborns pide en CAJAS, Arca registra en PIEZAS.

```json
{
  "map_id": "...",
  "cliente_portal": "Sanborns",
  "field_mappings": [
    {
      "campo_origen": "client_id",
      "campo_destino": "client_id",
      "transformacion": "directa",
      "confianza": 0.97,
      "razonamiento": "Mismo nombre de campo e identificador de cliente."
    },
    {
      "campo_origen": "articulo",
      "campo_destino": "producto_nombre",
      "transformacion": "directa",
      "confianza": 0.94,
      "razonamiento": "'articulo' (es) corresponde a nombre de producto; coincide con el valor observado."
    },
    {
      "campo_origen": "unidades_pedidas",
      "campo_destino": "cantidad",
      "transformacion": "conversion_unidad",
      "parametros": {
        "de": "caja",
        "a": "pieza",
        "factor_desde": "productos.piezas_por_caja"
      },
      "confianza": 0.88,
      "razonamiento": "Sanborns expresa cantidad en cajas; Arca en piezas. Multiplicar por piezas_por_caja del catálogo. Ej: 3 cajas x 24 = 72 piezas."
    },
    {
      "campo_origen": "costo",
      "campo_destino": "precio_unitario",
      "transformacion": "directa",
      "confianza": 0.85,
      "razonamiento": "'costo' corresponde al precio unitario observado."
    },
    {
      "campo_origen": "fecha_requerida",
      "campo_destino": "fecha_entrega_estimada",
      "transformacion": "formato_fecha",
      "confianza": 0.91,
      "razonamiento": "'fecha_requerida' es la fecha de entrega deseada."
    }
  ],
  "confianza_global": 0.89
}
```

---

## 3. Qué significa cada campo

| Campo | Para qué sirve | Quién lo usa |
|---|---|---|
| `cliente_portal` | de qué cliente es este mapa (HEB / Sanborns) | todas |
| `field_mappings` | la lista de correspondencias aprendidas | Pao (ejecuta), Steff (dashboard) |
| `campo_origen` | nombre del campo en el portal del cliente | Pao |
| `campo_destino` | nombre del campo en Arca (fijo) | Pao |
| `transformacion` | tipo de operación (ver tabla abajo) | Pao |
| `parametros` | datos extra para la transformación (factor, formato) | Pao |
| `confianza` | qué tan seguro está el LLM de ese mapeo (0-1) | Steff (% confiabilidad + alertas) |
| `razonamiento` | por qué decidió ese mapeo (texto del LLM) | Steff (prueba anti-hardcoding) |
| `campos_sin_mapeo` | campos que faltan o sobran (se infieren/ignoran) | Pao, Fer |
| `confianza_global` | promedio del mapeo completo | Steff (umbral de alerta) |

---

## 4. Tipos de `transformacion` (catálogo cerrado)

| Tipo | Qué hace | Ejemplo |
|---|---|---|
| `directa` | copiar el valor tal cual | `product` → `producto_nombre` |
| `conversion_unidad` | convertir unidades (cajas↔piezas) | 3 cajas → 72 piezas |
| `formato_fecha` | reformatear fecha | `DD/MM/YYYY` → `YYYY-MM-DD` |
| `lookup_catalogo` | buscar en catálogo (ej. nombre → SKU) | "Coca 600" → `SKU-0001` |
| `split` | partir un campo en varios | "Nombre Apellido" → nombre + apellido |
| `concat` | unir varios campos en uno | nombre + apellido → "Nombre completo" |
| `calculado` | derivar de otros (ej. importe = cantidad × precio) | importe |

> Mantener este catálogo **cerrado y conocido** es lo que hace el sistema escalable: el LLM elige de una lista de transformaciones, no inventa código. Eso también ayuda contra la sospecha de hardcoding: las transformaciones son genéricas, el mapeo específico lo infiere.

---

## 5. Cómo se usa en cada fase

- **Observación (Pao):** el LLM ve el pedido en ambos portales → genera este JSON.
- **Almacenamiento (Fer):** se guarda el JSON (puede ir en una tabla `mapas_aprendidos` o como archivo por cliente).
- **Automatización (Pao):** llega un pedido nuevo → se aplica el JSON campo por campo → se llena Arca.
- **Observabilidad (Steff):** el dashboard lee `confianza` y `razonamiento` → muestra el % de confiabilidad y alerta si `confianza_global` baja del umbral.

---

## 6. Decisiones de equipo (TOMADAS)
- ✅ **Dónde se guarda:** tabla `mapas_aprendidos` en Supabase, columna `jsonb` (ver `db/04_mapas.sql`). Una fila por cliente. NO archivos JSON sueltos (se desincronizarían entre las cuatro).
- ✅ **Umbral de alerta:** `confianza_global < 0.70` → Steff lo marca para revisar.
- ✅ **Razonamiento:** el LLM SIEMPRE devuelve `razonamiento` en cada campo (cuesta algo de tokens pero es la prueba anti-hardcoding y la base del dashboard).

## 7. Importante: MAPA vs PATRÓN (no confundir)
- **`mapas_aprendidos`** → CÓMO traducir los campos del portal. Se aprende UNA vez por cliente y casi no cambia. *Estable.*
- **`patron_cliente`** → QUÉ suele pedir el cliente y cuándo. Se enriquece con CADA pedido. *Vivo.* De aquí salen los borradores personalizados.

Las dos van en Supabase, en tablas distintas. El "se aprende una sola vez" aplica al mapa, no al patrón.
