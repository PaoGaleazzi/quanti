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

# Capa que traduce el nombre del cliente -> producto del catálogo de Arca
# (caché -> match normalizado -> LLM). Ver motor/resolver_producto.py.
# Reusamos su normalizador (_normalizar) como _norm para NO tener dos lógicas de
# normalización distintas: una sola fuente de verdad para comparar nombres.
from resolver_producto import resolver_producto, _normalizar as _norm

# URL del portal de Arca NUEVO (el de las compañeras). Se sirve en localhost.
URL_ARCA = "http://localhost:3000/arca_portal.html"

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
# _norm es resolver_producto._normalizar (ver import arriba): minúsculas, sin
# acentos y solo alfanuméricos. Es el MISMO criterio que usa la caché semántica,
# así que el match por formato aquí y el de resolver_producto son consistentes.


def _buscar_producto(cur, producto_nombre):
    """
    Resuelve UNA fila del catálogo (tabla productos) por nombre, con match
    tolerante al FORMATO (ver _norm). Devuelve (sku, piezas_por_caja).
    El catálogo es chico, así que traemos las filas y comparamos normalizado.
    Lanza ValueError claro si no hay coincidencia (exacta tras normalizar).

    OJO: esto resuelve SOLO formato. La resolución por SIGNIFICADO (nombres
    distintos como 'Refresco Cola' -> 'Coca-Cola') la hace resolver_producto
    (caché + LLM), que se llama en aplicar_transformaciones ANTES de llegar aquí.
    """
    objetivo = _norm(producto_nombre)
    cur.execute("select sku, nombre, piezas_por_caja from productos")
    for sku, nombre, ppc in cur.fetchall():
        if _norm(nombre) == objetivo:
            return sku, ppc
    raise ValueError(f"Producto no encontrado en catálogo: {producto_nombre!r}")


def _piezas_por_caja(cur, producto_nombre):
    """Cuántas piezas trae una caja (del catálogo), con match tolerante al formato."""
    return _buscar_producto(cur, producto_nombre)[1]


def _es_caja(unidad):
    """True si la unidad indica CAJA (entonces cantidad y precio vienen por caja)."""
    return (unidad or "").strip().lower() in ("caja", "cajas")


def _buscar_sku(cur, producto_nombre):
    """SKU interno de Arca por nombre de producto (lookup_catalogo), match tolerante."""
    return _buscar_producto(cur, producto_nombre)[0]


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
        # La conversión depende del VALOR de la unidad (genérico, no "si es X cliente"):
        #   - Pieza -> NO convertir: el cliente ya pide en PIEZAS, igual que Arca.
        #   - Caja  -> convertir: cantidad x piezas_por_caja del catálogo.
        #   - otra  -> avisar claro en vez de convertir mal.
        u = (unidad or "caja").strip().lower()
        if u in ("pieza", "piezas"):
            return valor                        # ya está en piezas: se copia tal cual
        if u not in ("caja", "cajas", ""):
            raise ValueError(
                f"Unidad '{unidad}' no soportada (solo Caja o Pieza). "
                f"Falta el factor de conversión para esa unidad."
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


class MapaIncompletoError(Exception):
    """El mapa aprendido no trae un campo que Arca necesita (LLM no determinista)."""


def _exigir(indice, campo):
    """
    Devuelve el mapeo de un campo que SÍ depende del mapa aprendido (cantidad,
    precio, nombre…). Si el LLM no lo incluyó esta vez, avisa CLARO qué falta y
    cómo resolverlo, en vez de tronar con un KeyError pelón.
    """
    if campo not in indice:
        disponibles = ", ".join(sorted(indice)) or "(ninguno)"
        raise MapaIncompletoError(
            f"El mapa aprendido no incluye el campo '{campo}'. "
            f"Campos que sí mapeó: {disponibles}. "
            f"Vuelve a aprender el portal (Fase 1) para regenerar el mapa."
        )
    return indice[campo]


def aplicar_transformaciones(pedido, mapa, cur, cliente_portal=None):
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
        # Nombre tal como lo escribió el CLIENTE (puede no existir en el catálogo).
        info_nombre = _exigir(indice, "producto_nombre")
        nombre_cliente = prod.get(info_nombre["origen"])

        # RESOLUCIÓN: traducimos el nombre del cliente al producto del catálogo de
        # Arca (match normalizado y, si falla, el LLM). Usamos el nombre canónico
        # resuelto para TODO lo demás, así sku y conversion_unidad (que buscan por
        # nombre en el catálogo) encuentran sin cambios.
        prod_cat = resolver_producto(cur, nombre_cliente, cliente_portal)
        nombre = prod_cat["nombre_catalogo"]

        # Unidad del origen para este producto (si el mapa la capturó). Decide el
        # factor de conversion_unidad. Si no hay, se asume Caja (compatibilidad).
        unidad = prod.get(indice["unidad"]["origen"]) if "unidad" in indice else None

        item = {"producto_nombre": nombre}
        # cantidad y precio SÍ dependen del mapa aprendido -> se exigen con aviso
        # claro si el LLM no los mapeó (en vez de un KeyError feo).
        for campo in ["cantidad", "precio_unitario"]:
            info = _exigir(indice, campo)
            valor_origen = prod.get(info["origen"])
            transf = info["transf"]

            # 'calculado' anula el valor (return None): está pensado para campos que
            # Arca DERIVA sola (ej. importe). Si el LLM (no determinista) lo aplicó a
            # un campo que SÍ trae dato del portal, lo tratamos como 'directa' para no
            # perder el valor real. Mismo criterio de robustez que con 'split'/'sku'.
            if transf == "calculado":
                print(f"[AVISO] '{campo}' venía marcado como 'calculado' en el mapa; "
                      f"se trata como 'directa' (usa el valor del portal: {valor_origen!r}).")
                transf = "directa"

            # Guard: cantidad y precio deben traer un valor del portal. Si llegó
            # vacío/None (portal sin llenar o campo no leído), avisamos CLARO
            # nombrando el producto, en vez de tronar feo con int()/float() de None.
            if valor_origen is None or str(valor_origen).strip() == "":
                raise ValueError(
                    f"Falta '{campo}' del producto '{nombre}' en el portal del cliente. "
                    f"Complétalo y reintenta."
                )

            item[campo] = aplicar_transformacion(
                transf, valor_origen, nombre, cur, unidad
            )

        # PRECIO POR PIEZA: si la unidad es Caja, el precio venía POR CAJA, así
        # que lo pasamos a precio por pieza dividiendo por piezas_por_caja del
        # catálogo (mismo factor que la cantidad). Genérico: solo cuando la unidad
        # lo indica (los dummies y HEB no traen unidad 'Caja' -> no se toca).
        if _es_caja(unidad) and item.get("precio_unitario") not in (None, ""):
            ppc = _piezas_por_caja(cur, nombre)
            item["precio_unitario"] = round(float(item["precio_unitario"]) / ppc, 2)

        # sku NO depende del mapa: es estructura FIJA de Arca y SIEMPRE se resuelve
        # del catálogo por nombre de producto. Así el pedido se registra aunque el
        # LLM (no determinista) no haya incluido el mapeo 'sku' esta vez. No es
        # hardcodear el mapeo origen->destino; es la estructura fija de Arca, igual
        # que CAMPOS_PRODUCTO_DESTINO.
        item["sku"] = _buscar_sku(cur, nombre)
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
        datos = aplicar_transformaciones(pedido_nuevo, mapa, cur, cliente_portal)
        numero_orden, monto_total = guardar_pedido(datos, cur)
        conn.commit()
        return datos, numero_orden, monto_total, mapa
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. LLENAR EL PORTAL VISUAL DE ARCA (Playwright) — solo demo, no toca la base.
# ---------------------------------------------------------------------------
def _fill_editable(page, selector, valor):
    """
    Hace fill SOLO si el campo existe y es EDITABLE. Si es readonly/disabled
    (ej. #numero_orden de Arca, que la base autogenera), lo SALTA en vez de
    trabarse: Playwright no puede escribir en readonly y se queda esperando hasta
    el timeout de 30s. Genérico para CUALQUIER campo no editable del portal.
    """
    el = page.query_selector(selector)
    if el is None:
        return                                   # el campo no existe en este portal
    if not el.is_editable():                      # False si es readonly o disabled
        print(f"[AVISO] Campo '{selector}' es readonly/no editable; se omite (no se teclea).")
        return
    page.fill(selector, str(valor))


def _set_select(page, selector, valor):
    """
    Elige un valor en un <select> (no se usa fill en selects). Si el valor no está
    entre las opciones del portal, lo inyecta antes (igual que hace el front con
    prodOptions) y dispara 'change' para que corra su onChange. Robusto.
    """
    el = page.query_selector(selector)
    if el is None or valor is None:
        return
    el.evaluate(
        """(sel, val) => {
            if (val && ![...sel.options].some(o => o.value === val)) {
                const o = document.createElement('option');
                o.value = val; o.textContent = val; sel.appendChild(o);
            }
            sel.value = val;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        str(valor),
    )


def llenar_portal_arca(cliente_portal, datos, pedido_origen, mapa, numero_orden):
    """
    Abre el portal de Arca NUEVO (arca_portal.html) y TECLEA los datos
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

        # CABECERA: SOLO campos editables. Los readonly (numero_orden autogenerado,
        # fecha_pedido, origen_captura) se saltan solos vía _fill_editable, en vez
        # de trabar Playwright. El numero_orden lo asigna la base; el bot NO lo teclea.
        _fill_editable(page, "#numero_orden", f"ORD-{numero_orden}")   # readonly -> se salta
        _fill_editable(page, "#client_id", datos["client_id"])
        _fill_editable(page, "#fecha_entrega_estimada", datos["fecha_entrega_estimada"])
        # portal_origen es readonly -> lo ponemos por JS (solo contexto, no se teclea).
        page.evaluate(
            "(v) => { const e = document.getElementById('portal_origen'); if (e) e.value = v; }",
            cliente_portal,
        )

        # RENGLONES: tabla limpia y un renglón por producto.
        page.evaluate("document.getElementById('lines').innerHTML = ''")
        for it in datos["items"]:
            page.click(".addline")                 # botón "+ Agregar línea"
            fila = "#lines tr:last-of-type"
            # c-prod es un <select>: se elige con _set_select (no fill). Va primero
            # para que su onChange autollene; luego sobreescribimos con nuestros datos.
            _set_select(page, f"{fila} .c-prod", it["producto_nombre"])
            _fill_editable(page, f"{fila} .c-sku", it["sku"])
            _fill_editable(page, f"{fila} .c-qty", it["cantidad"])
            _fill_editable(page, f"{fila} .c-price", it["precio_unitario"])
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
            "HEB", "http://localhost:3000/heb_portal.html"
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
