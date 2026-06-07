"""Orquesta la fase de aprendizaje: observa el portal de origen y el de Arca, infiere el mapeo de campos y lo guarda."""

import sys
import json

from grabar_acciones import grabar_acciones, PORTALES
from cerebro_aprender import aprender_mapa_desde_observacion, guardar_mapa

# El portal de Arca (destino) para la observación. El portal NUEVO de las compañeras.
URL_ARCA = "http://localhost:3000/arca_portal.html"


def aprender_desde_observaciones(cliente_portal, obs_origen, obs_destino,
                                 guardar=True):
    """
    Núcleo del flujo: dadas las dos observaciones {traza, snapshot}, infiere el
    mapa con el cerebro y (opcional) lo guarda. Separado de la captura para
    poder probarlo sin navegador.
    """
    print("Pasando las observaciones al cerebro (Gemini)...")
    mapa = aprender_mapa_desde_observacion(obs_origen, obs_destino, cliente_portal)

    if guardar:
        guardar_mapa(mapa, cliente_portal)
        print(f"Mapa de '{cliente_portal}' guardado en mapas_aprendidos.")

    return mapa


def aprender_flujo(cliente_portal, origen_url, destino_url, guardar=True):
    """
    Flujo real con captura: graba el origen, graba Arca, infiere y guarda.
    """
    print(f"\n[1/3] Graba la observación del ORIGEN ({cliente_portal})...")
    obs_origen = grabar_acciones(origen_url)

    print("\n[2/3] Graba la observación del DESTINO (Arca)...")
    obs_destino = grabar_acciones(destino_url)

    print("\n[3/3] Inferir el mapa con el cerebro y guardar...")
    return aprender_desde_observaciones(cliente_portal, obs_origen, obs_destino,
                                        guardar=guardar)


if __name__ == "__main__":
    # Uso: aprender_flujo.py <cliente_portal> <origen> <destino>
    cliente_portal = sys.argv[1] if len(sys.argv) > 1 else "Sanborns"
    origen = sys.argv[2] if len(sys.argv) > 2 else "sanborns"
    destino = sys.argv[3] if len(sys.argv) > 3 else "arca"

    # Los args de portal aceptan un alias conocido o una URL directa.
    origen_url = PORTALES.get(origen, origen)
    destino_url = URL_ARCA if destino == "arca" else PORTALES.get(destino, destino)

    mapa = aprender_flujo(cliente_portal, origen_url, destino_url)

    print("\n=== MAPA APRENDIDO ===")
    print(json.dumps(mapa, indent=2, ensure_ascii=False))
