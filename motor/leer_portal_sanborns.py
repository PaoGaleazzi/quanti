"""Lee un pedido del portal de Sanborns con Playwright."""

from playwright.sync_api import sync_playwright

# El portal se sirve como archivo estático en localhost:3000 (carpeta fronts).
URL_SANBORNS = "http://localhost:3000/sanborns_portal.html"


def leer_portal_sanborns():
    """
    Abre el portal de Sanborns y lee los campos del pedido desde el DOM.
    Devuelve el dict de "pedido nuevo" listo para pasárselo a ejecutar().
    """
    with sync_playwright() as p:
        # headless=False -> se ve el navegador; slow_mo=800ms -> pausa entre
        # acciones para que el jurado alcance a ver cómo el bot lee cada campo.
        browser = p.chromium.launch(headless=False, slow_mo=800)
        page = browser.new_page()
        page.goto(URL_SANBORNS)

        # Leemos cada campo por su id (input_value = lo escrito en el input).
        pedido = {
            "client_id": page.input_value("#client_id"),
            "productos": [
                {
                    "articulo": page.input_value("#articulo"),
                    "unidades_pedidas": page.input_value("#unidades_pedidas"),
                    "costo": page.input_value("#costo"),
                }
            ],
            "fecha_requerida": page.input_value("#fecha_requerida"),
        }

        browser.close()

    return pedido


if __name__ == "__main__":
    # Prueba SOLO de la lectura (sin transformar ni guardar).
    import json
    datos = leer_portal_sanborns()
    print("Datos leídos del portal Sanborns:")
    print(json.dumps(datos, indent=2, ensure_ascii=False))
