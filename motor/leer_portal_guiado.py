"""
Lector guiado por navigation_flow — Always on Shelf · Pao
========================================================

Lee un portal de cliente en la fase EJECUTAR, recorriéndolo SOLO según el
navigation_flow que el cerebro aprendió. Es GENÉRICO: el mismo código sirve
para un portal de UNA pantalla (Sanborns) o de VARIAS (HEB), porque no tiene
pasos hardcodeados — sigue el plan del mapa.

Cómo se guía (sin LLM):
  - navigation_flow: la SECUENCIA de pasos. Cada paso trae:
        accion = "leer_datos"  -> en esta pantalla hay que LEER campos
                 "click"/otro  -> hay que hacer CLIC para avanzar de pantalla
        selector_referencia    -> a qué esperar (pantalla) o qué clicar (botón)
  - field_mappings: de aquí salen los CAMPOS a leer (campo_origen) y si cada
        uno es de cabecera o de producto (según su campo_destino fijo de Arca).

Cómo decide qué leer en cada pantalla (robusto):
  En cada paso "leer_datos" intenta leer TODOS los campos del mapa que estén
  VISIBLES en ese momento. Como cada pantalla muestra/oculta sus campos, solo
  se leen los de la pantalla actual. Así no dependemos de que el nombre de la
  pantalla coincida exactamente entre navigation_flow y field_mappings.

Devuelve el pedido en la MISMA forma que consume ejecutar.py:
    { <campo_cabecera>: valor, ..., "productos": [ {<campo_item>: valor, ...}, ... ] }
"""

from playwright.sync_api import sync_playwright

# Estructura FIJA de Arca: qué campos de destino son de PRODUCTO (se repiten por
# renglón) y cuáles de cabecera. Conocer esto es legítimo (Arca es fijo). NO es
# el mapeo origen->destino, que sigue saliendo del mapa aprendido.
CAMPOS_PRODUCTO_DESTINO = {"producto_nombre", "cantidad", "precio_unitario", "sku"}


def _resolver(page, campo):
    """
    Encuentra en el DOM el/los elementos de un campo, probando de forma genérica
    por id, luego por clase, luego por atributo name. Devuelve solo los VISIBLES.
    Un campo de tabla (ej. 'qty' en HEB) devuelve varios; uno simple, uno.
    """
    for selector in (f"#{campo}", f".{campo}", f"[name='{campo}']"):
        elementos = [e for e in page.query_selector_all(selector) if e.is_visible()]
        if elementos:
            return elementos
    return []


def _leer_visibles(page, mappings, pedido, columnas_item):
    """
    Lee los campos del mapa que estén visibles AHORA. Los de cabecera van al
    pedido (valor único); los de producto se acumulan por columna (una lista de
    valores, un valor por renglón). Devuelve lo leído en esta pantalla (reporte).
    """
    leido = {}
    for m in mappings:
        campo = m.get("campo_origen")
        if not campo:
            continue
        elementos = _resolver(page, campo)
        if not elementos:
            continue  # no visible en esta pantalla (o no existe)

        if m.get("campo_destino") in CAMPOS_PRODUCTO_DESTINO:
            valores = [e.input_value() for e in elementos]   # un valor por renglón
            columnas_item[campo] = valores
            leido[campo] = valores if len(valores) > 1 else valores[0]
        else:
            valor = elementos[0].input_value()               # campo de cabecera
            pedido[campo] = valor
            leido[campo] = valor
    return leido


def _armar_productos(columnas_item):
    """
    Convierte las columnas de producto (campo -> [v0, v1, ...]) en una lista de
    productos (un dict por renglón), alineando por posición.
    Ej.: {'product':[A,B], 'qty':[1,2]} -> [{'product':A,'qty':1},{'product':B,'qty':2}]
    """
    n = max((len(v) for v in columnas_item.values()), default=0)
    productos = []
    for i in range(n):
        prod = {campo: vals[i] for campo, vals in columnas_item.items() if i < len(vals)}
        productos.append(prod)
    return productos


def leer_portal_segun_flujo(url, mapa, headless=False, slow_mo=700):
    """
    Abre `url` y recorre el portal SOLO, siguiendo el navigation_flow del mapa.
    Devuelve (pedido, lecturas):
      - pedido:  el dict listo para ejecutar (cabecera + lista productos)
      - lecturas: lista de {pantalla, leido} para mostrar qué se leyó por pantalla
    """
    # Si no hay navigation_flow (portal de una pantalla sin flujo), leemos una vez.
    flujo = mapa.get("navigation_flow") or [{"accion": "leer_datos", "selector_referencia": None}]
    mappings = mapa.get("field_mappings", [])

    pedido = {}
    columnas_item = {}
    lecturas = []

    with sync_playwright() as p:
        # headless=False + slow_mo para VER al bot recorrer y leer (demo).
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        page = browser.new_page()
        page.goto(url)

        for paso in flujo:
            accion = (paso.get("accion") or "").lower()
            selector = paso.get("selector_referencia")

            if "leer" in accion:
                # Espera a que la pantalla esté VISIBLE antes de leer.
                if selector:
                    try:
                        page.wait_for_selector(selector, state="visible", timeout=5000)
                    except Exception:
                        pass  # si el selector de referencia falla, igual intentamos leer
                leido = _leer_visibles(page, mappings, pedido, columnas_item)
                lecturas.append({"pantalla": paso.get("pantalla"), "leido": leido})
            else:
                # Paso de transición: clic para avanzar a la siguiente pantalla.
                if selector:
                    page.click(selector)

        browser.close()

    pedido["productos"] = _armar_productos(columnas_item)
    return pedido, lecturas
