# Diseño del "Cerebro de Aprender"
### Always on Shelf · Pao
### Pieza: datos capturados → Gemini Flash → mapa aprendido → Supabase

---

## 1. Qué hace esta pieza (en una frase)

Recibe lo que el usuario llenó en AMBOS portales durante la observación, le pide a Gemini que **infiera la correspondencia** entre campos, y guarda ese mapa para reutilizarlo después sin volver a llamar al LLM.

---

## 2. Qué recibe (input)

Dos cosas capturadas durante la observación (Playwright las leyó):

```python
# Lo que el usuario LEYÓ del portal del cliente
datos_origen = {
    "user_id": "1",
    "productos": [
        {"product": "Coca-Cola 600ml", "qty": "80", "unit_price": "18.00"}
    ],
    "delivery_date": "2025-06-10"
}

# Lo que el usuario ESCRIBIÓ en el portal de Arca
datos_destino = {
    "client_id": "1",
    "items": [
        {"producto_nombre": "Coca-Cola 600ml", "cantidad": "80",
         "precio_unitario": "18.00", "sku": "SKU-0001"}
    ],
    "fecha_entrega_estimada": "2025-06-10"
}
```

El LLM ve **los dos lados** y deduce qué campo de origen alimentó cada campo de destino.

---

## 3. El prompt (la parte más delicada)

### Por qué este prompt NO es hardcoding
- Le explicamos la TAREA (observa estos dos lados, infiere la correspondencia).
- Le decimos qué campos tiene Arca (destino FIJO y conocido — eso es legítimo).
- **NO le decimos** qué campo de origen va a qué campo de destino. Eso lo infiere él.
- Por eso funciona con cualquier portal nuevo: el origen siempre es desconocido para el prompt.

### Estructura del prompt
```
[ROL] Eres un sistema que aprende a mapear datos entre dos sistemas web
observando un ejemplo. NO conoces de antemano la correspondencia; debes inferirla.

[CONTEXTO] El sistema DESTINO (Arca) es fijo y tiene estos campos:
  - client_id (identificador del cliente)
  - producto_nombre (nombre del producto)
  - cantidad (en piezas)
  - precio_unitario
  - sku (código interno, puede requerir lookup por nombre)
  - fecha_entrega_estimada
El sistema ORIGEN es desconocido y varía por cliente.

[TAREA] Te doy un ejemplo de lo que un usuario LEYÓ del origen y lo que
ESCRIBIÓ en el destino. Infiere, campo por campo:
  - de qué campo de origen viene cada campo de destino
  - qué transformación se aplicó (directa, conversión de unidad, formato fecha, lookup, etc.)
  - tu nivel de confianza (0 a 1)
  - tu razonamiento (por qué dedujiste eso)

[DATOS]
ORIGEN: {datos_origen}
DESTINO: {datos_destino}

[FORMATO DE SALIDA] Devuelve SOLO un JSON con esta estructura: {...estructura del mapa...}
No incluyas texto fuera del JSON.
```

> 💡 Pedir "SOLO JSON, sin texto fuera" es clave para poder parsearlo después.
> Gemini a veces envuelve en ```json ... ``` — hay que limpiar eso al recibir.

---

## 4. Qué devuelve y dónde se guarda

Devuelve el `mapa_json` (la estructura que definimos en Mapa_Aprendido_JSON.md).
Se guarda en la tabla `mapas_aprendidos` con `on conflict do update`
(si el cliente ya tenía mapa, lo actualiza → "se aprende una vez").

---

## 5. Código base (para construir/afinar con Claude Code)

```python
import os, json, time
import google.generativeai as genai
import psycopg2
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

DB_CONFIG = {
    "host": os.getenv("DB_HOST"), "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "postgres"), "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# Campos fijos de Arca (destino conocido — NO es hardcodear el mapeo)
CAMPOS_ARCA = """
- client_id (identificador del cliente)
- producto_nombre (nombre del producto)
- cantidad (en piezas)
- precio_unitario
- sku (codigo interno, puede requerir lookup por nombre de producto)
- fecha_entrega_estimada
"""

def construir_prompt(datos_origen, datos_destino):
    return f"""Eres un sistema que aprende a mapear datos entre dos sistemas web
observando UN ejemplo. NO conoces de antemano la correspondencia; debes inferirla.

El sistema DESTINO (Arca) es fijo y tiene estos campos:
{CAMPOS_ARCA}
El sistema ORIGEN es desconocido y varia por cliente.

Te doy un ejemplo de lo que un usuario LEYO del origen y lo que ESCRIBIO en el destino.
Infiere, campo por campo: de que campo de origen viene cada campo de destino,
que transformacion se aplico (directa, conversion_unidad, formato_fecha, lookup_catalogo,
split, concat, calculado), tu confianza (0 a 1), y tu razonamiento.

ORIGEN: {json.dumps(datos_origen, ensure_ascii=False)}
DESTINO: {json.dumps(datos_destino, ensure_ascii=False)}

Devuelve SOLO un JSON con esta estructura, sin texto adicional:
{{
  "field_mappings": [
    {{"campo_origen": "...", "campo_destino": "...", "transformacion": "...",
      "confianza": 0.0, "razonamiento": "..."}}
  ],
  "confianza_global": 0.0
}}"""


def aprender_mapa(datos_origen, datos_destino, cliente_portal,
                  modelo="gemini-3.5-flash", reintentos=4):
    """Llama a Gemini para inferir el mapa. Maneja errores 429 con backoff."""
    prompt = construir_prompt(datos_origen, datos_destino)
    model = genai.GenerativeModel(modelo)

    for intento in range(reintentos):
        try:
            resp = model.generate_content(prompt)
            texto = resp.text.strip()
            # limpiar posibles ```json ... ```
            if texto.startswith("```"):
                texto = texto.split("```")[1]
                if texto.startswith("json"):
                    texto = texto[4:]
            mapa = json.loads(texto.strip())
            mapa["cliente_portal"] = cliente_portal
            mapa["modelo_llm"] = modelo
            return mapa
        except Exception as e:
            espera = 2 ** intento  # 1s, 2s, 4s, 8s
            print(f"Intento {intento+1} fallo ({e}); esperando {espera}s...")
            time.sleep(espera)
    raise RuntimeError("No se pudo generar el mapa tras varios intentos.")


def guardar_mapa(mapa, cliente_portal):
    """Guarda el mapa en Supabase. Si el cliente ya tenia, lo actualiza."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        insert into mapas_aprendidos (cliente_portal, mapa_json, modelo_llm, confianza_global)
        values (%s, %s, %s, %s)
        on conflict (cliente_portal) do update
        set mapa_json = excluded.mapa_json,
            confianza_global = excluded.confianza_global,
            fecha_actualizacion = now();
    """, (cliente_portal, json.dumps(mapa), mapa.get("modelo_llm"), mapa.get("confianza_global")))
    conn.commit()
    cur.close()
    conn.close()


# --- prueba rápida ---
if __name__ == "__main__":
    datos_origen = {
        "user_id": "1",
        "productos": [{"product": "Coca-Cola 600ml", "qty": "80", "unit_price": "18.00"}],
        "delivery_date": "2025-06-10"
    }
    datos_destino = {
        "client_id": "1",
        "items": [{"producto_nombre": "Coca-Cola 600ml", "cantidad": "80",
                   "precio_unitario": "18.00", "sku": "SKU-0001"}],
        "fecha_entrega_estimada": "2025-06-10"
    }
    mapa = aprender_mapa(datos_origen, datos_destino, "HEB")
    print(json.dumps(mapa, indent=2, ensure_ascii=False))
    guardar_mapa(mapa, "HEB")
    print("Mapa guardado en Supabase.")
```

---

## 6. Para construir con Claude Code
- Verificar el nombre exacto del modelo Flash disponible (`gemini-3.5-flash` o el vigente).
- Confirmar que el paquete es `google-generativeai` (`uv add google-generativeai`).
- Probar con los datos dummy de arriba antes de conectar con la captura real de Playwright.
- Luego: conectar la salida de `leer_portal_heb.py` (la captura) como input de `aprender_mapa`.

## 7. Nota de diseño (para defender ante el jurado)
El prompt explica la tarea y los campos fijos de Arca, pero NUNCA la correspondencia
origen→destino. Esa la infiere el LLM viendo el ejemplo. Por eso:
1. Funciona con cualquier portal nuevo (el origen siempre es desconocido para el prompt).
2. No es hardcoding (no hay reglas campo-a-campo escritas).
3. El `razonamiento` de cada campo es la evidencia de que infirió, no memorizó.
