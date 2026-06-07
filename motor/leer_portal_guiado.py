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


def _resolver(page, campo, solo_visibles=True):
    """
    Encuentra en el DOM el/los elementos de un campo, probando de forma genérica
    por id, luego por clase, luego por atributo name.
    Un campo de tabla (ej. 'qty' en HEB) devuelve varios; uno simple, uno.

    solo_visibles=True  -> solo los visibles en este momento (recorrido guiado).
    solo_visibles=False -> todos los presentes en el DOM (lectura tras confirmar,
                           cuando la persona ya navegó y otras pantallas quedaron
                           ocultas pero sus valores siguen en el DOM).
    """
    for selector in (f"#{campo}", f".{campo}", f"[name='{campo}']"):
        elementos = page.query_selector_all(selector)
        if solo_visibles:
            elementos = [e for e in elementos if e.is_visible()]
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


# ===========================================================================
# LECTURA CON CONFIRMACIÓN (para la fase EJECUTAR del demo en vivo)
# ===========================================================================
# Aquí la PERSONA llena un pedido nuevo en la ventana y avisa con un botón
# "✅ Listo". El bot NO navega (la persona ya recorrió las pantallas); solo
# espera la confirmación y LEE todos los campos del mapa presentes en el DOM.

class PedidoIncompletoError(Exception):
    """Se lanza cuando el pedido leído tiene campos de producto vacíos."""


# Botón flotante "Listo" que se inyecta en la página y avisa a Python al clic.
_BOTON_LISTO_JS = r"""
() => {
  if (document.getElementById('__demo_listo_btn')) return;
  const b = document.createElement('button');
  b.id = '__demo_listo_btn';
  b.textContent = '✅ Listo (ya llené el pedido)';
  b.style.cssText = 'position:fixed;top:10px;right:10px;z-index:2147483647;' +
    'background:#0a7d32;color:#fff;border:none;padding:12px 16px;border-radius:8px;' +
    'cursor:pointer;font:14px sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.3)';
  b.onclick = () => { b.textContent = 'Leyendo...'; b.disabled = true;
                      try { window.__demo_listo(); } catch (e) {} };
  document.body.appendChild(b);
}
"""


def _leer_todo(page, mappings):
    """
    Lee TODOS los campos del mapa presentes en el DOM (visibles u ocultos), porque
    la persona pudo navegar varias pantallas y dejar las anteriores ocultas pero
    con sus valores. Agrupa lo leído por pantalla_origen para mostrarlo.
    """
    pedido = {}
    columnas_item = {}
    por_pantalla = {}
    for m in mappings:
        campo = m.get("campo_origen")
        if not campo:
            continue
        elementos = _resolver(page, campo, solo_visibles=False)
        if not elementos:
            continue
        pantalla = m.get("pantalla_origen") or "pantalla"
        if m.get("campo_destino") in CAMPOS_PRODUCTO_DESTINO:
            valores = [e.input_value() for e in elementos]
            columnas_item[campo] = valores
            por_pantalla.setdefault(pantalla, {})[campo] = (
                valores if len(valores) > 1 else (valores[0] if valores else "")
            )
        else:
            valor = elementos[0].input_value()
            pedido[campo] = valor
            por_pantalla.setdefault(pantalla, {})[campo] = valor

    pedido["productos"] = _armar_productos(columnas_item)
    lecturas = [{"pantalla": k, "leido": v} for k, v in por_pantalla.items()]
    return pedido, lecturas


def validar_pedido(pedido):
    """
    Guard: avisa CLARO si el pedido llegó con campos de producto vacíos, en vez
    de tronar feo más adelante (ej. 'No hay SKU para None').
    """
    productos = pedido.get("productos", [])
    if not productos:
        raise PedidoIncompletoError(
            "No se leyó ningún producto. Revisa que el portal esté lleno "
            "antes de hacer clic en '✅ Listo'."
        )
    for i, prod in enumerate(productos, start=1):
        for campo, valor in prod.items():
            if valor is None or str(valor).strip() == "":
                raise PedidoIncompletoError(
                    f"Campo de producto vacío (renglón {i}: '{campo}'). "
                    f"Revisa que el portal esté lleno antes de confirmar."
                )


def leer_portal_con_confirmacion(url, mapa, headless=False, slow_mo=0, _auto=None):
    """
    Abre `url`, deja que la PERSONA llene un pedido nuevo y ESPERA su clic en
    '✅ Listo'. Recién entonces lee los campos de ESA misma ventana.
    Devuelve (pedido, lecturas).

    `_auto` es solo para pruebas: una función que recibe la página, la llena y
    hace clic en Listo (emula a la persona). En vivo se deja en None.
    """
    mappings = mapa.get("field_mappings", [])
    estado = {"listo": False}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        page = browser.new_page()
        # Función Python visible desde el navegador: el botón la llama al hacer clic.
        page.expose_function("__demo_listo", lambda: estado.update(listo=True))
        page.goto(url)
        page.evaluate("(" + _BOTON_LISTO_JS + ")()")  # inyecta el botón "Listo"

        print("   >> Llena el pedido NUEVO en la ventana y haz clic en "
              "'✅ Listo' cuando termines (sin prisa)...")

        if _auto:
            _auto(page)  # SOLO pruebas: llena y confirma automáticamente

        # Espera a la confirmación de la persona (o a que cierre la ventana).
        while not estado["listo"] and not page.is_closed():
            page.wait_for_timeout(200)

        pedido, lecturas = _leer_todo(page, mappings)
        if not page.is_closed():
            browser.close()

    return pedido, lecturas
