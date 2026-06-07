"""
DEMO EN VIVO — Always on Shelf · Pao
====================================

Corre el ciclo completo para presentar al jurado, partiendo de CERO:

  FASE 0  DESAPRENDER  -> borra el mapa del cliente (sistema sin conocimiento).
  FASE 1  OBSERVAR Y APRENDER -> la persona llena el portal del cliente y el de
          Arca a mano UNA vez; el bot observa, el cerebro infiere el mapa y lo
          guarda. Se muestra qué aprendió (pantallas + mapeos con razonamiento).
  FASE 2  EJECUTAR SOLO -> la persona pone un pedido NUEVO; el bot recorre el
          portal solo, lee, transforma y llena Arca en automático.

Es GENÉRICO: el mismo script sirve para Sanborns (1 pantalla) o HEB (varias),
sin código específico. Solo ORQUESTA piezas que ya existen:
  - grabar_acciones.grabar_acciones        (observación: traza + snapshot)
  - cerebro vía aprender_desde_observaciones (inferir y guardar el mapa)
  - ejecutar.ejecutar_desde_portal          (recorrer el portal y llenar Arca)

Uso:
    # 1) servir los portales:
    python -m http.server 3000 -d fronts
    # 2) correr el demo:
    uv run python motor/demo.py sanborns
    uv run python motor/demo.py heb

No toca .env ni la lógica del motor; solo guía el demo con pausas y mensajes.
"""

import os
import sys
import json

import psycopg2

from grabar_acciones import grabar_acciones, PORTALES
from aprender_flujo import aprender_desde_observaciones, URL_ARCA
from ejecutar import ejecutar_desde_portal, DB_CONFIG

# Mapa alias -> nombre con el que se guarda en mapas_aprendidos.
CLIENTES = {"sanborns": "Sanborns", "heb": "HEB"}

# Función de observación. Se puede sustituir en pruebas (modo simulado).
observar = grabar_acciones


def pausa(mensaje):
    """Pausa para narrar. En modo DEMO_AUTO (pruebas) no espera input."""
    if os.getenv("DEMO_AUTO"):
        print(mensaje + "   (auto)")
    else:
        input(mensaje)


def titulo(texto):
    """Imprime un encabezado de fase bien visible para el demo."""
    print("\n" + "=" * 64)
    print("  " + texto)
    print("=" * 64)


# ---------------------------------------------------------------------------
# FASE 0 — DESAPRENDER
# ---------------------------------------------------------------------------
def fase0_desaprender(nombre):
    titulo(f"FASE 0 · DESAPRENDER ({nombre})")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("delete from mapas_aprendidos where cliente_portal = %s", (nombre,))
    conn.commit()
    borradas = cur.rowcount
    conn.close()
    print(f"Borrado el mapa de '{nombre}' ({borradas} fila[s]).")
    print(">>> Sistema SIN conocimiento previo de este portal. Empezamos de cero.")


# ---------------------------------------------------------------------------
# FASE 1 — OBSERVAR Y APRENDER
# ---------------------------------------------------------------------------
def resumen_aprendido(mapa):
    """Imprime, legible para el jurado, lo que el sistema infirió."""
    nav = mapa.get("navigation_flow", [])
    pantallas = []
    for paso in nav:
        p = paso.get("pantalla")
        if p and p not in pantallas:
            pantallas.append(p)

    print("\n--- LO QUE EL SISTEMA APRENDIÓ ---")
    print(f"Pantallas detectadas: {len(pantallas)}  ->  {pantallas}")
    print(f"Pasos de navegación (navigation_flow): {len(nav)}")
    print("\nMapeos inferidos (NADIE se los dijo; los dedujo observando):")
    for m in mapa.get("field_mappings", []):
        print(f"  • {m.get('campo_origen')}  ->  {m.get('campo_destino')}"
              f"   [{m.get('transformacion')}]   confianza={m.get('confianza')}")
        print(f"      razonamiento: {m.get('razonamiento')}")
    print(f"\nConfianza global: {mapa.get('confianza_global')}")


def fase1_observar_aprender(nombre, url_origen):
    titulo(f"FASE 1 · OBSERVAR Y APRENDER ({nombre})")
    print("Vas a llenar DOS portales a mano una sola vez; el bot observa.")

    pausa("\n>> Enter para abrir el portal del CLIENTE y llenarlo "
          "(al terminar, clic en '✅ Listo')...")
    obs_origen = observar(url_origen)

    pausa("\n>> Ahora el portal de ARCA con el MISMO pedido. Enter para abrirlo "
          "(al terminar, clic en '✅ Listo')...")
    obs_destino = observar(URL_ARCA)

    print("\nPasando lo observado al cerebro (Gemini) para inferir el mapa...")
    mapa = aprender_desde_observaciones(nombre, obs_origen, obs_destino, guardar=True)
    print(">>> Mapa APRENDIDO y GUARDADO en mapas_aprendidos.")
    resumen_aprendido(mapa)
    return mapa


# ---------------------------------------------------------------------------
# FASE 2 — EJECUTAR SOLO
# ---------------------------------------------------------------------------
def fase2_ejecutar(nombre, url_origen):
    titulo(f"FASE 2 · EJECUTAR SOLO ({nombre})")
    print("El bot abrirá el portal del cliente. TÚ llenas un pedido NUEVO con calma")
    print("y haces clic en '✅ Listo' EN LA VENTANA. Solo entonces el bot lee,")
    print("transforma y llena Arca en automático.")

    # Este Enter solo ABRE la ventana; la confirmación real es el botón "Listo".
    pausa("\n>> Enter para abrir el portal del cliente...")

    try:
        pedido, lecturas, datos, numero_orden, monto_total = ejecutar_desde_portal(
            nombre, url_origen, esperar_listo=True
        )
    except Exception as e:
        # Guard amable: por ejemplo, campos de producto vacíos.
        print(f"\n⚠  {e}")
        print("   No se registró nada. Llena bien el portal y vuelve a intentar.")
        return

    print("\n--- LO QUE EL BOT LEYÓ DEL CLIENTE (por pantalla) ---")
    print(json.dumps(lecturas, indent=2, ensure_ascii=False))

    print("\n--- LO QUE EL BOT ESCRIBIÓ EN ARCA ---")
    print(json.dumps(datos, indent=2, ensure_ascii=False))

    print(f"\n>>> Pedido registrado en Arca. numero_orden={numero_orden}, "
          f"monto_total={monto_total}")


# ---------------------------------------------------------------------------
def main():
    alias = (sys.argv[1] if len(sys.argv) > 1 else "sanborns").lower()
    nombre = CLIENTES.get(alias)
    url_origen = PORTALES.get(alias)
    if not nombre or not url_origen:
        print(f"Cliente no reconocido: '{alias}'. Usa 'sanborns' o 'heb'.")
        return

    titulo(f"DEMO ALWAYS ON SHELF — cliente: {nombre}")
    print("El mismo motor, sin código específico del portal. Empezamos de cero.")

    fase0_desaprender(nombre)
    pausa("\n>> Enter para ir a la FASE 1 (observar y aprender)...")

    fase1_observar_aprender(nombre, url_origen)
    pausa("\n>> Enter para ir a la FASE 2 (ejecutar solo)...")

    fase2_ejecutar(nombre, url_origen)

    titulo("DEMO TERMINADO")


if __name__ == "__main__":
    main()
