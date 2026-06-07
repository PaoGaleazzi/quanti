"""
Fase EJECUTAR — Always on Shelf · Pao
=====================================

Toma un pedido NUEVO de un cliente y lo registra en Arca aplicando el mapa
que ya se aprendió antes (tabla mapas_aprendidos).

DIFERENCIA CLAVE con la fase "aprender":
  - "aprender" llama al LLM UNA vez por cliente para inferir el mapa.
  - "ejecutar" NO llama al LLM. Solo LEE el mapa guardado y lo aplica
    mecánicamente. Por eso cada pedido es gratis y rápido.

Qué hace, en orden:
  1. Lee el mapa_json del cliente desde Supabase.
  2. Aplica la transformación de cada campo (directa, conversion_unidad,
     lookup_catalogo, formato_fecha, calculado).
  3. Devuelve los datos ya listos para Arca.
  4. Guarda el pedido en las tablas pedidos y pedido_detalle.

NOTA anti-hardcoding: aquí SÍ conocemos la estructura FIJA de Arca (qué campos
son de cabecera y cuáles de cada producto) — eso es legítimo porque Arca es
nuestro destino fijo. Lo que NUNCA está hardcodeado es la correspondencia
origen→destino: esa la leemos del mapa que infirió el LLM.

Cómo correr la prueba con un pedido dummy de Sanborns:
    uv run python motor/ejecutar.py
"""

import os
from datetime import datetime, date

from dotenv import load_dotenv
import psycopg2

# URL del portal de Arca NUEVO (el de las compañeras). Se sirve en localhost.
URL_ARCA = "http://localhost:3000/portal_arca.html"

# Carga DB_* del .env (nunca se imprimen).
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# Estructura FIJA de Arca: qué campos del destino son de la CABECERA del pedido
# y cuáles se repiten por cada PRODUCTO. Conocer esto es legítimo (Arca es fijo);
# el mapeo origen→destino NO está aquí, viene del mapa aprendido.
CAMPOS_CABECERA = ["client_id", "fecha_entrega_estimada"]
CAMPOS_PRODUCTO = ["producto_nombre", "cantidad", "precio_unitario", "sku"]


# ---------------------------------------------------------------------------
# 1. LEER EL MAPA APRENDIDO
# ---------------------------------------------------------------------------
def leer_mapa(cliente_portal, cur):
    """
    Trae el mapa_json del cliente desde la tabla mapas_aprendidos.
    psycopg2 convierte la columna jsonb directamente en un dict de Python.
    """
    cur.execute(
        "select mapa_json from mapas_aprendidos where cliente_portal = %s",
        (cliente_portal,),
    )
    fila = cur.fetchone()
    if not fila:
        raise ValueError(
            f"No hay mapa aprendido para '{cliente_portal}'. "
            f"Corre primero la fase de aprender."
        )
    return fila[0]


def _indexar_mapa(mapa):
    """
    Convierte la lista field_mappings en un diccionario fácil de consultar:
        { campo_destino: {"origen": <nombre del campo origen>, "transf": <tipo>} }

    El campo_origen del LLM puede venir como "productos[].articulo" (campo que
    está dentro de cada producto). Nos quedamos solo con el nombre de la hoja
    ("articulo") para poder leerlo del dict del pedido.
    """
    indice = {}
    for m in mapa["field_mappings"]:
        origen_hoja = m["campo_origen"].split(".")[-1]  # "productos[].articulo" -> "articulo"
        indice[m["campo_destino"]] = {
            "origen": origen_hoja,
            "transf": m["transformacion"],
        }
    return indice


# ---------------------------------------------------------------------------
# 2. LAS TRANSFORMACIONES (el corazón de ejecutar)
# ---------------------------------------------------------------------------
def _piezas_por_caja(cur, producto_nombre):
    """Busca en el catálogo (tabla productos) cuántas piezas trae una caja."""
    cur.execute(
        "select piezas_por_caja from productos where nombre = %s",
        (producto_nombre,),
    )
    fila = cur.fetchone()
    if not fila:
        raise ValueError(f"Producto no encontrado en catálogo: {producto_nombre}")
    return fila[0]


def _buscar_sku(cur, producto_nombre):
    """Busca el SKU interno de Arca por el nombre del producto (lookup_catalogo)."""
    cur.execute(
        "select sku from productos where nombre = %s",
        (producto_nombre,),
    )
    fila = cur.fetchone()
    if not fila:
        raise ValueError(f"No hay SKU para el producto: {producto_nombre}")
    return fila[0]


def _normalizar_fecha(valor):
    """Reformatea una fecha a YYYY-MM-DD aceptando varios formatos de entrada."""
    if not valor:
        return valor
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(valor.strip(), formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return valor  # si no reconoce el formato, lo deja igual


def aplicar_transformacion(transformacion, valor, producto_nombre, cur, unidad=None):
    """
    Aplica UNA transformación a UN valor, según lo que diga el mapa.

      - directa:           copia el valor tal cual.
      - conversion_unidad: convierte a piezas según la UNIDAD del origen.
      - lookup_catalogo:   busca el SKU por nombre de producto.
      - formato_fecha:     reformatea a YYYY-MM-DD.
      - calculado:         se deriva al guardar (ej. importe); aquí no aplica.

    `producto_nombre` se usa en las transformaciones que consultan el catálogo.
    `unidad` (Caja/Tarima/…) decide el factor en conversion_unidad.
    """
    if transformacion == "directa":
        return valor
    if transformacion == "conversion_unidad":
        # Por ahora SOLO soportamos Caja (factor = piezas_por_caja del catálogo).
        # Si la unidad es otra (ej. Tarima) avisamos claro en vez de convertir mal.
        u = (unidad or "caja").strip().lower()
        if u not in ("caja", "cajas", ""):
            raise ValueError(
                f"Unidad '{unidad}' no soportada aún (solo Caja). "
                f"Falta el factor en el catálogo de productos."
            )
        cantidad = int(valor)
        ppc = _piezas_por_caja(cur, producto_nombre)
        return cantidad * ppc                   # ej. 3 cajas x 24 = 72 piezas
    if transformacion == "lookup_catalogo":
        return _buscar_sku(cur, producto_nombre)
    if transformacion == "formato_fecha":
        return _normalizar_fecha(valor)
    if transformacion == "calculado":
        return None                             # importe se calcula en guardar_pedido
    # El LLM es no determinista: a veces etiqueta transformaciones que no soportamos
    # (split, concat, etc.). En vez de tronar el flujo, hacemos el fallback más seguro
    # —tratarla como "directa" (copiar el valor tal cual)— y avisamos claro para saberlo.
    print(
        f"[AVISO] Transformacion desconocida '{transformacion}'"
        f"{f' en campo (producto={producto_nombre})' if producto_nombre else ''}"
        f"; se aplica 'directa' (valor copiado tal cual): {valor!r}"
    )
    return valor


def aplicar_transformaciones(pedido, mapa, cur):
    """
    Aplica el mapa completo al pedido nuevo y devuelve los datos listos para Arca:

        {
          "client_id": ...,
          "fecha_entrega_estimada": ...,
          "items": [ {"producto_nombre","cantidad","precio_unitario","sku"}, ... ]
        }

    La cabecera se arma una vez; los items, uno por cada producto del pedido.
    """
    indice = _indexar_mapa(mapa)
    datos = {}

    # --- CABECERA (datos que no se repiten por producto) ---
    for campo in CAMPOS_CABECERA:
        if campo in indice:
            info = indice[campo]
            valor_origen = pedido.get(info["origen"])
            datos[campo] = aplicar_transformacion(info["transf"], valor_origen, None, cur)

    # --- PRODUCTOS (un item por cada producto del pedido) ---
    datos["items"] = []
    for prod in pedido["productos"]:
        # El NOMBRE del producto se toma DIRECTO de su campo origen: es el nombre
        # tal cual. (Las transformaciones de catálogo/conversión aplican a sku y
        # cantidad, no al nombre; así somos robustos aunque el LLM etiquete el
        # nombre como 'lookup_catalogo'.) Lo resolvemos primero porque sku y
        # conversion_unidad lo necesitan para consultar el catálogo.
        info_nombre = indice["producto_nombre"]
        nombre = prod.get(info_nombre["origen"])

        # Unidad del origen para este producto (si el mapa la capturó). Decide el
        # factor de conversion_unidad. Si no hay, se asume Caja (compatibilidad).
        unidad = prod.get(indice["unidad"]["origen"]) if "unidad" in indice else None

        item = {"producto_nombre": nombre}
        for campo in ["cantidad", "precio_unitario", "sku"]:
            info = indice[campo]
            valor_origen = prod.get(info["origen"])
            item[campo] = aplicar_transformacion(
                info["transf"], valor_origen, nombre, cur, unidad
            )
        datos["items"].append(item)

    return datos


# ---------------------------------------------------------------------------
# 3. GUARDAR EL PEDIDO EN ARCA (pedidos + pedido_detalle)
# ---------------------------------------------------------------------------
def guardar_pedido(datos, cur):
    """
    Inserta la cabecera en `pedidos` y un renglón por producto en `pedido_detalle`.
    El importe de cada renglón se calcula aquí: cantidad (piezas) x precio_unitario.
    Devuelve (numero_orden, monto_total).
    """
    # Monto total = suma de los importes de cada renglón.
    monto_total = sum(
        int(it["cantidad"]) * float(it["precio_unitario"]) for it in datos["items"]
    )

    # Cabecera del pedido. fecha_pedido = hoy (current_date de Postgres).
    cur.execute(
        """
        insert into pedidos
            (client_id, fecha_pedido, fecha_entrega_estimada, monto_total, origen_captura)
        values (%s, current_date, %s, %s, 'auto_IA')
        returning numero_orden;
        """,
        (datos["client_id"], datos["fecha_entrega_estimada"], monto_total),
    )
    numero_orden = cur.fetchone()[0]

    # Un renglón por producto.
    for it in datos["items"]:
        cantidad = int(it["cantidad"])
        precio = float(it["precio_unitario"])
        importe = cantidad * precio
        cur.execute(
            """
            insert into pedido_detalle
                (numero_orden, sku, producto_nombre, cantidad, unidad, precio_unitario, importe)
            values (%s, %s, %s, %s, 'pieza', %s, %s);
            """,
            (numero_orden, it["sku"], it["producto_nombre"], cantidad, precio, importe),
        )

    return numero_orden, monto_total


# ---------------------------------------------------------------------------
# ORQUESTADOR: junta todo
# ---------------------------------------------------------------------------
def ejecutar(cliente_portal, pedido_nuevo):
    """
    Flujo completo de la fase ejecutar para UN pedido:
      lee el mapa -> transforma -> guarda en Arca -> devuelve el resultado.
    Abre una sola conexión y hace commit al final.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        mapa = leer_mapa(cliente_portal, cur)
        datos = aplicar_transformaciones(pedido_nuevo, mapa, cur)
        numero_orden, monto_total = guardar_pedido(datos, cur)
        conn.commit()
        return datos, numero_orden, monto_total, mapa
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. LLENAR EL PORTAL VISUAL DE ARCA (Playwright) — solo demo, no toca la base.
# ---------------------------------------------------------------------------
def llenar_portal_arca(cliente_portal, datos, pedido_origen, mapa, numero_orden):
    """
    Abre el portal de Arca NUEVO (portal_arca.html) y TECLEA los datos
    transformados con Playwright, para que en el demo se VEA al bot llenar el
    formulario, y al final hace clic en 'Registrar en Arca'.

    Usa los ids/clases reales del portal: #client_id, #fecha_entrega_estimada,
    #numero_orden, y la tabla #lines con .c-sku/.c-prod/.c-qty/.c-price (un
    renglón por producto, agregados con el botón "+ Agregar línea").

    OJO: esto NO guarda en la base (eso ya lo hizo ejecutar()). Es la capa visual.
    (pedido_origen y mapa se mantienen en la firma por compatibilidad; no se usan.)
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # headless=False + slow_mo para VER al bot teclear (importante en el demo).
        browser = p.chromium.launch(headless=False, slow_mo=600)
        page = browser.new_page()
        page.goto(URL_ARCA)

        # CABECERA (ids/data-field reales del portal nuevo).
        page.fill("#numero_orden", f"ORD-{numero_orden}")
        page.fill("#client_id", str(datos["client_id"]))
        page.fill("#fecha_entrega_estimada", str(datos["fecha_entrega_estimada"]))
        # portal_origen es readonly -> lo ponemos por JS (contexto, no se teclea).
        page.evaluate(
            "(v) => { const e = document.getElementById('portal_origen'); if (e) e.value = v; }",
            cliente_portal,
        )

        # RENGLONES: tabla limpia y un renglón por producto.
        page.evaluate("document.getElementById('lines').innerHTML = ''")
        for it in datos["items"]:
            page.click(".addline")                 # botón "+ Agregar línea"
            fila = "#lines tr:last-of-type"
            page.fill(f"{fila} .c-sku", str(it["sku"]))
            page.fill(f"{fila} .c-prod", str(it["producto_nombre"]))
            page.fill(f"{fila} .c-qty", str(it["cantidad"]))
            page.fill(f"{fila} .c-price", str(it["precio_unitario"]))
            # (el total se recalcula solo por el oninput del portal)

        # Clic final en 'Registrar en Arca'.
        page.click("button:has-text('Registrar en Arca')")
        page.wait_for_timeout(2000)  # pausa para ver el banner de éxito
        browser.close()


# ---------------------------------------------------------------------------
# CICLO COMPLETO SOLO: el bot recorre el portal origen (1 o varias pantallas)
# guiado por el navigation_flow, transforma y llena Arca. GENÉRICO: sirve igual
# para Sanborns (1 pantalla) que para HEB (varias). No tiene pasos hardcodeados.
# ---------------------------------------------------------------------------
def ejecutar_desde_portal(cliente_portal, url_origen, esperar_listo=False):
    """
    1) Lee el mapa del cliente (para guiar la navegación / lectura).
    2) Lee el portal origen:
         - esperar_listo=False -> el bot RECORRE solo el portal según navigation_flow
           (la data ya está en el portal; modo autónomo).
         - esperar_listo=True  -> abre el portal, ESPERA a que la persona llene un
           pedido nuevo y haga clic en '✅ Listo', y entonces lee esa ventana.
    3) Valida que el pedido no venga vacío (guard).
    4) Transforma y guarda en la base (reusa ejecutar()).
    5) Llena el portal de Arca en pantalla.
    Devuelve (pedido, lecturas, datos, numero_orden, monto_total).
    """
    from leer_portal_guiado import (
        leer_portal_segun_flujo, leer_portal_con_confirmacion, validar_pedido,
    )

    # 1) El mapa primero: contiene el navigation_flow / los campos a leer.
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        mapa = leer_mapa(cliente_portal, conn.cursor())
    finally:
        conn.close()

    # 2) Leer el portal origen (esperando a la persona, o recorriéndolo solo).
    if esperar_listo:
        pedido, lecturas = leer_portal_con_confirmacion(url_origen, mapa)
    else:
        pedido, lecturas = leer_portal_segun_flujo(url_origen, mapa)

    # 3) Guard: si llegó vacío, avisa claro (no truena con un error feo después).
    validar_pedido(pedido)

    # 4) Transformar + guardar (la misma función que ya usa Sanborns).
    datos, numero_orden, monto_total, mapa = ejecutar(cliente_portal, pedido)

    # 5) Llenar el portal de Arca en pantalla.
    llenar_portal_arca(cliente_portal, datos, pedido, mapa, numero_orden)

    return pedido, lecturas, datos, numero_orden, monto_total


# ---------------------------------------------------------------------------
# FLUJO COMPLETO de Sanborns:
#   leer portal cliente -> transformar (mapa) -> guardar en BD -> llenar portal Arca.
# NO se llama al LLM aquí: solo lectura + aplicar el mapa ya aprendido.
#
# Antes de correr, servir los portales:
#   python -m http.server 3000 -d fronts
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import json

    cual = sys.argv[1] if len(sys.argv) > 1 else "sanborns"

    if cual == "heb":
        # HEB: el bot recorre SOLO las 3 pantallas guiado por el navigation_flow.
        print("Ejecutando HEB: el bot recorre el portal multi-pantalla solo...\n")
        pedido, lecturas, datos, numero_orden, monto_total = ejecutar_desde_portal(
            "HEB", "http://localhost:3000/portal_heb.html"
        )
        print("DATOS LEÍDOS POR PANTALLA:")
        print(json.dumps(lecturas, indent=2, ensure_ascii=False))
        print("\nPEDIDO ARMADO (de todas las pantallas):")
        print(json.dumps(pedido, indent=2, ensure_ascii=False))
        print("\nDATOS TRANSFORMADOS (listos para Arca):")
        print(json.dumps(datos, indent=2, ensure_ascii=False))
        print(f"\nGuardado OK -> numero_orden = {numero_orden}, monto_total = {monto_total}")

    else:
        # Sanborns (1 pantalla): flujo original con su lector dedicado. Intacto.
        from leer_portal_sanborns import leer_portal_sanborns

        print("Paso 1: leyendo el portal de Sanborns con Playwright...\n")
        pedido_sanborns = leer_portal_sanborns()
        print("DATOS LEÍDOS DEL PORTAL (crudos, en cajas):")
        print(json.dumps(pedido_sanborns, indent=2, ensure_ascii=False))

        print("\nPaso 2: aplicando el mapa y guardando en la base (sin LLM)...\n")
        datos, numero_orden, monto_total, mapa = ejecutar("Sanborns", pedido_sanborns)
        print("DATOS TRANSFORMADOS (listos para Arca):")
        print(json.dumps(datos, indent=2, ensure_ascii=False))
        print(f"\nGuardado OK -> pedidos.numero_orden = {numero_orden}, "
              f"monto_total = {monto_total}")

        print("\nPaso 3: el bot llena el portal de Arca (mira la ventana)...")
        llenar_portal_arca("Sanborns", datos, pedido_sanborns, mapa, numero_orden)
        print("Portal de Arca llenado y registrado.")
