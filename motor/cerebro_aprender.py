"""Infiere con un modelo de lenguaje el mapeo de campos entre el portal de origen y el de Arca, y lo guarda."""

import os
import json
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors
import psycopg2

# Carga las variables del .env (GEMINI_API_KEY y DB_*). Nunca se imprimen.
load_dotenv()

# Cliente de Gemini, autenticado con la API key del .env.
cliente_gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Datos de conexión a Supabase (Postgres). Vienen del .env.
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# Campos FIJOS de Arca (destino conocido). Decirle al LLM cómo es el destino
# NO es hardcodear el mapeo: solo describimos el formulario al que debe llegar.
# El "cómo se llega" (qué campo de origen alimenta cada uno) lo infiere él.
CAMPOS_ARCA = """
- client_id (identificador del cliente)
- producto_nombre (nombre del producto)
- cantidad (en PIEZAS; ojo: algunos portales piden en cajas)
- unidad (la unidad en que el ORIGEN expresa la cantidad: caja/tarima/pieza; sirve para la conversión)
- precio_unitario
- sku (codigo interno; puede requerir lookup por nombre de producto)
- fecha_entrega_estimada
"""

# Catálogo CERRADO de transformaciones. El LLM elige de esta lista, no inventa
# código. Esto hace el sistema escalable y refuerza el anti-hardcoding.
TRANSFORMACIONES = (
    "directa, conversion_unidad, formato_fecha, lookup_catalogo, "
    "split, concat, calculado"
)


def construir_prompt(datos_origen, datos_destino):
    """
    Arma el texto que se le manda a Gemini.

    Le da: el ROL, los campos fijos de Arca, el catálogo de transformaciones,
    y el EJEMPLO (origen + destino). Le pide SOLO un JSON con la estructura
    de field_mappings y confianza_global. No le da ninguna correspondencia.
    """
    return f"""Eres un sistema que aprende a mapear datos entre dos sistemas web
observando UN solo ejemplo. NO conoces de antemano la correspondencia entre
campos; debes INFERIRLA comparando los dos lados.

El sistema DESTINO (Arca) es fijo y tiene estos campos:
{CAMPOS_ARCA}
El sistema ORIGEN es un portal de cliente DESCONOCIDO y varía por cliente
(nombres de campo distintos, otro idioma, otras unidades).

Te doy un ejemplo de lo que un usuario LEYÓ del origen y lo que ESCRIBIÓ en el
destino. Infiere, campo por campo:
  - campo_origen: de qué campo del origen viene cada campo del destino
  - campo_destino: el campo de Arca correspondiente
  - transformacion: una de [{TRANSFORMACIONES}]
  - confianza: número de 0 a 1
  - razonamiento: por qué dedujiste ese mapeo (breve, en español)

Reglas:
  - Si un campo del destino no tiene origen claro (ej. sku), explícalo en el
    razonamiento y usa la transformación adecuada (ej. lookup_catalogo).
  - Si el origen está en cajas y Arca en piezas, usa conversion_unidad.

ORIGEN: {json.dumps(datos_origen, ensure_ascii=False)}
DESTINO: {json.dumps(datos_destino, ensure_ascii=False)}

Devuelve SOLO un JSON válido con esta estructura, sin texto adicional:
{{
  "field_mappings": [
    {{"campo_origen": "...", "campo_destino": "...", "transformacion": "...",
      "confianza": 0.0, "razonamiento": "..."}}
  ],
  "confianza_global": 0.0
}}"""


def _limpiar_json(texto):
    """
    Red de seguridad: si el modelo envuelve la respuesta en ```json ... ```,
    le quitamos las comillas de bloque antes de parsear. (Pedimos JSON puro
    con response_mime_type, pero esto evita sustos.)
    """
    texto = texto.strip()
    if texto.startswith("```"):
        # quita la primera línea (``` o ```json) y la última (```)
        partes = texto.split("```")
        texto = partes[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return texto.strip()


def _generar_json(prompt, modelo, reintentos):
    """
    Manda un prompt a Gemini y devuelve el JSON parseado (dict).

    Maneja errores TRANSITORIOS con backoff exponencial:
      - 429 = demasiadas peticiones / cuota excedida
      - 503 = modelo saturado por demanda (UNAVAILABLE)
    Espera 1s, 2s, 4s, 8s entre intentos. Lo usan tanto aprender_mapa (datos
    estáticos) como aprender_mapa_desde_observacion (traza + snapshot).
    """
    config = types.GenerateContentConfig(response_mime_type="application/json")

    for intento in range(reintentos):
        try:
            resp = cliente_gemini.models.generate_content(
                model=modelo, contents=prompt, config=config,
            )
            texto = _limpiar_json(resp.text)
            try:
                return json.loads(texto)
            except json.JSONDecodeError:
                # A veces el modelo añade texto tras el JSON: tomamos el 1er objeto.
                obj, _ = json.JSONDecoder().raw_decode(texto)
                return obj
        except errors.APIError as e:
            if e.code in (429, 503) and intento < reintentos - 1:
                espera = 2 ** intento  # backoff exponencial: 1, 2, 4, 8 segundos
                print(f"[{e.code}] Error transitorio. Reintento {intento+1}/"
                      f"{reintentos} en {espera}s...")
                time.sleep(espera)
                continue
            raise  # otro error de API, o ya no quedan reintentos

    raise RuntimeError("No se pudo generar el mapa tras varios intentos.")


def aprender_mapa(datos_origen, datos_destino, cliente_portal,
                  modelo="gemini-3.5-flash", reintentos=4):
    """
    [Versión clásica] Infiere el mapa a partir de dos dicts ESTÁTICOS
    (origen y destino). Se mantiene para compatibilidad. Devuelve el mapa_json.
    """
    prompt = construir_prompt(datos_origen, datos_destino)
    mapa = _generar_json(prompt, modelo, reintentos)
    # Metadatos para guardar/auditar (no afectan al mapeo inferido).
    mapa["cliente_portal"] = cliente_portal
    mapa["modelo_llm"] = modelo
    return mapa


def construir_prompt_flujo(obs_origen, obs_destino):
    """
    Arma el prompt para la observación ESCALABLE (traza + snapshot).

    Cada observación trae:
      - traza:    acciones EN ORDEN (input/click/navegacion). De aquí sale la
                  SECUENCIA de pantallas (navigation_flow).
      - snapshot: estado FINAL de todos los campos visibles, con su valor
                  (incluye los que el portal autocompletó solo).

    Igual que la versión clásica: le decimos la TAREA y los campos FIJOS de
    Arca, pero NUNCA la correspondencia campo-a-campo. Eso lo infiere el LLM.
    """
    return f"""Eres un sistema que aprende a mapear datos entre dos sistemas web
observando UNA sesión real. NO conoces de antemano la correspondencia entre
campos ni cuántas pantallas hay; debes INFERIRLO de lo observado.

El sistema DESTINO (Arca) es fijo y tiene estos campos:
{CAMPOS_ARCA}
El sistema ORIGEN es un portal de cliente DESCONOCIDO y varía por cliente
(nombres de campo distintos, otro idioma, otras unidades, una o varias pantallas).

Para CADA sistema te doy dos cosas observadas durante el llenado a mano:
  - "traza": la lista ORDENADA de acciones del usuario. Tipos:
        input      = escribió/cambió un campo (selector, valor, label)
        click      = pulsó un botón/enlace (selector, label)
        navegacion = cambió de pantalla (aparece otra sección o cambia la URL)
  - "snapshot": el estado FINAL de TODOS los campos visibles. Cada campo trae:
        "campo" (identificador limpio: id/name/clase), "selector", "label" y
        "valor". Incluye campos que el portal AUTOCOMPLETÓ solo (no están en la
        traza porque el usuario no los tecleó). USA EL SNAPSHOT como fuente de
        verdad de los VALORES, y la TRAZA para el ORDEN y las PANTALLAS.

IMPORTANTE: en field_mappings, "campo_origen" debe ser el valor de "campo"
(el identificador limpio del campo de origen), NUNCA el selector CSS.

Tu tarea, infiere:
1) navigation_flow: la SECUENCIA de pantallas/pasos del ORIGEN, deducida de las
   transiciones 'navegacion' de su traza. Si el origen es de UNA sola pantalla,
   navigation_flow tiene UN solo paso (leer y guardar). Cada paso:
   {{"paso": 1, "pantalla": "...", "accion": "leer_datos|click",
     "descripcion": "...", "selector_referencia": "...", "confianza": 0.0}}
2) field_mappings: de qué campo del ORIGEN viene cada campo de Arca. Cada uno:
   {{"campo_origen": "...", "campo_destino": "...",
     "transformacion": "una de [{TRANSFORMACIONES}]",
     "pantalla_origen": "...", "confianza": 0.0, "razonamiento": "..."}}
   - Compara los VALORES del snapshot de ambos lados para deducir el mapeo.
   - Si un campo de Arca no tiene origen claro (ej. sku), explícalo en el
     razonamiento y usa la transformación adecuada (ej. lookup_catalogo).
   - Si el origen está en cajas y Arca en piezas, usa conversion_unidad.

OBSERVACION DEL ORIGEN (cliente):
{json.dumps(obs_origen, ensure_ascii=False)}

OBSERVACION DEL DESTINO (Arca):
{json.dumps(obs_destino, ensure_ascii=False)}

Devuelve SOLO un JSON válido con esta estructura, sin texto adicional:
{{
  "navigation_flow": [
    {{"paso": 1, "pantalla": "...", "accion": "...", "descripcion": "...",
      "selector_referencia": "...", "confianza": 0.0}}
  ],
  "field_mappings": [
    {{"campo_origen": "...", "campo_destino": "...", "transformacion": "...",
      "pantalla_origen": "...", "confianza": 0.0, "razonamiento": "..."}}
  ],
  "confianza_global": 0.0
}}"""


def aprender_mapa_desde_observacion(obs_origen, obs_destino, cliente_portal,
                                    modelo="gemini-3.5-flash", reintentos=4):
    """
    [Versión escalable] Infiere el mapa a partir de las observaciones
    {traza, snapshot} del portal origen y del portal Arca (las que captura
    grabar_acciones.py). Devuelve el mapa_json con navigation_flow + field_mappings.
    """
    prompt = construir_prompt_flujo(obs_origen, obs_destino)
    mapa = _generar_json(prompt, modelo, reintentos)
    mapa["cliente_portal"] = cliente_portal
    mapa["modelo_llm"] = modelo
    return mapa


def guardar_mapa(mapa, cliente_portal):
    """
    Guarda el mapa en la tabla mapas_aprendidos de Supabase.

    Usa upsert: si el cliente ya tenía mapa, lo ACTUALIZA (on conflict).
    Así se cumple el "se aprende una sola vez por cliente".
    """
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        """
        insert into mapas_aprendidos
            (cliente_portal, mapa_json, modelo_llm, confianza_global)
        values (%s, %s, %s, %s)
        on conflict (cliente_portal) do update
        set mapa_json           = excluded.mapa_json,
            modelo_llm          = excluded.modelo_llm,
            confianza_global    = excluded.confianza_global,
            fecha_actualizacion = now();
        """,
        (
            cliente_portal,
            json.dumps(mapa, ensure_ascii=False),
            mapa.get("modelo_llm"),
            mapa.get("confianza_global"),
        ),
    )
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# PRUEBA con datos dummy (los del diseño). Esto NO toca Playwright todavía:
# solo demuestra que el LLM genera el mapa bien antes de conectar la captura.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    datos_origen = {
        "user_id": "1",
        "productos": [
            {"product": "Coca-Cola 600ml", "qty": "80", "unit_price": "18.00"}
        ],
        "delivery_date": "2025-06-10",
    }
    datos_destino = {
        "client_id": "1",
        "items": [
            {"producto_nombre": "Coca-Cola 600ml", "cantidad": "80",
             "precio_unitario": "18.00", "sku": "SKU-0001"}
        ],
        "fecha_entrega_estimada": "2025-06-10",
    }

    print("Pidiendo a Gemini que infiera el mapa (datos dummy HEB)...\n")
    mapa = aprender_mapa(datos_origen, datos_destino, "HEB")
    print(json.dumps(mapa, indent=2, ensure_ascii=False))

    # Guardado en Supabase (requiere que la tabla mapas_aprendidos exista):
    guardar_mapa(mapa, "HEB")
    print("\nMapa guardado en Supabase.")
