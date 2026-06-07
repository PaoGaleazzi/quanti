"""Prueba del grabador de acciones: simula las acciones de un usuario con Playwright."""
import json
from playwright.sync_api import sync_playwright
from grabar_acciones import instalar_grabador, PORTALES


def editar(page, selector, valor):
    # Escribimos y luego salimos del campo (blur) para disparar 'change'.
    page.fill(selector, valor)
    page.locator(selector).blur()


def correr(nombre, acciones):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        traza, estado = instalar_grabador(page)
        page.goto(PORTALES[nombre])
        page.wait_for_timeout(300)  # deja que arranque el observer
        acciones(page)
        page.wait_for_timeout(300)  # deja llegar los últimos eventos
        browser.close()
    print(f"\n===== TRAZA {nombre.upper()} =====")
    print(json.dumps(traza, indent=2, ensure_ascii=False))
    return traza


def acciones_sanborns(page):
    editar(page, "#client_id", "2")
    editar(page, "#articulo", "Bokados Mix 60g")
    editar(page, "#unidades_pedidas", "4")
    editar(page, "#costo", "15.00")
    editar(page, "#fecha_requerida", "2025-06-25")
    page.click("#btn-guardar")


def acciones_heb(page):
    editar(page, "#user_id", "1")
    # primer renglón de la tabla
    editar(page, "#tabla-productos tbody tr:nth-of-type(1) .product", "Coca-Cola 600ml")
    editar(page, "#tabla-productos tbody tr:nth-of-type(1) .qty", "80")
    editar(page, "#tabla-productos tbody tr:nth-of-type(1) .unit_price", "18.00")
    page.click("#btn-continuar")          # -> transición a pantalla "entrega"
    page.wait_for_timeout(200)
    editar(page, "#delivery_date", "2025-06-10")
    editar(page, "#delivery_window", "08:00-12:00")
    page.click("#btn-confirmar")          # -> transición a pantalla "confirmacion"
    page.wait_for_timeout(200)
    page.click("#btn-enviar")


if __name__ == "__main__":
    correr("sanborns", acciones_sanborns)
    correr("heb", acciones_heb)
