"""Lee un pedido del portal de HEB con Playwright y devuelve los datos crudos."""

from playwright.sync_api import sync_playwright

URL_HEB = "http://localhost:3000/heb_portal.html"


def leer_portal_heb():
    datos = {"productos": [], "entrega": {}}

    with sync_playwright() as p:
        # headless=False -> ves el navegador trabajar (bueno para el demo y para entender)
        browser = p.chromium.launch(headless=False, slow_mo=800)  # slow_mo: pausa para ver los pasos
        page = browser.new_page()
        page.goto(URL_HEB)

        # ----- PANTALLA 1: PRODUCTOS -----
        datos["user_id"] = page.input_value("#user_id")

        # leer todas las filas de la tabla
        filas = page.query_selector_all("#tabla-productos tbody tr")
        for fila in filas:
            producto = fila.query_selector(".product").input_value()
            qty = fila.query_selector(".qty").input_value()
            precio = fila.query_selector(".unit_price").input_value()
            datos["productos"].append({
                "product": producto,
                "qty": qty,
                "unit_price": precio,
            })

        # ----- NAVEGAR A PANTALLA 2: ENTREGA -----
        page.click("#btn-continuar")
        page.wait_for_selector("#delivery_date")  # esperar a que cargue la pantalla

        # ----- PANTALLA 2: ENTREGA -----
        datos["entrega"]["delivery_date"] = page.input_value("#delivery_date")
        datos["entrega"]["delivery_window"] = page.input_value("#delivery_window")

        # ----- NAVEGAR A PANTALLA 3 (solo para demostrar el flujo) -----
        page.click("#btn-confirmar")
        page.wait_for_selector("#btn-enviar")

        browser.close()

    return datos


if __name__ == "__main__":
    resultado = leer_portal_heb()
    print("Datos capturados del portal HEB:")
    import json
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
