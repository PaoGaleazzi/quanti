# whatsapp_alerta.py
# Se llama solo cuando confianza_global < 0.80.
# Lee credenciales del .env — nunca las pongas en el código.
# Uso: python whatsapp_alerta.py  (lo llama el motor de Pao)

import os, json
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER   = os.getenv("TWILIO_WHATSAPP_FROM")   # "whatsapp:+14155238886"
TO_NUMBER     = os.getenv("TWILIO_WHATSAPP_TO")     # "whatsapp:+521..."

UMBRAL = 0.80   # por debajo de esto se dispara la alerta

def campo_critico(field_mappings):
    """Devuelve el campo con menor confianza del mapa."""
    if not field_mappings:
        return None
    return min(field_mappings, key=lambda f: f.get("confianza", 1.0))

def enviar_alerta(pedido: dict, learned_map: dict = None):
    """
    pedido: {
        numero_orden, cliente_portal, client_id,
        confianza_global, lineas: [...]
    }
    learned_map: el JSON que produce Pao (opcional, para mostrar campo crítico)
    """
    conf = pedido.get("confianza_global", pedido.get("confiabilidad", 1.0))

    if conf >= UMBRAL:
        print(f"Confianza {conf:.0%} — sobre umbral, no se manda alerta.")
        return False

    # campo crítico (el que más dudas tiene)
    critico = ""
    if learned_map and learned_map.get("field_mappings"):
        c = campo_critico(learned_map["field_mappings"])
        if c:
            critico = (f"\nCampo crítico: {c['campo_origen']} → {c['campo_destino']} "
                       f"({c.get('confianza',0):.0%}) — {c.get('razonamiento','')[:80]}")

    portal   = pedido.get("cliente_portal", pedido.get("portal_origen", "?"))
    cliente  = pedido.get("client_id", "?")
    orden    = pedido.get("numero_orden", "—")
    n_lineas = len(pedido.get("lineas", []))

    mensaje = (
        f"*Always on Shelf · Alerta de confianza baja*\n\n"
        f"Portal origen: {portal}\n"
        f"Cliente: {cliente}\n"
        f"Pedido: {orden} ({n_lineas} líneas)\n"
        f"Confianza: *{conf:.0%}* — requiere revisión humana"
        f"{critico}\n\n"
        f"Revisa el dashboard antes de registrar en Arca."
    )

    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    msg = client.messages.create(
        body=mensaje,
        from_=FROM_NUMBER,
        to=TO_NUMBER
    )
    print(f"Alerta enviada — SID: {msg.sid}")
    return True


# ── Demo / prueba directa ──────────────────────────────────────────────────
if __name__ == "__main__":
    pedido_demo = {
        "numero_orden": "ORD-2072",
        "cliente_portal": "Sanborns",
        "client_id": "2",
        "confianza_global": 0.62,   # bajo umbral → dispara
        "lineas": [
            {"sku": "SKU-0001", "producto_nombre": "Coca-Cola 600ml",
             "cantidad": 72, "precio_unitario": 18.00}
        ]
    }
    mapa_demo = {
        "field_mappings": [
            {"campo_origen": "unidades_pedidas", "campo_destino": "cantidad",
             "confianza": 0.62,
             "razonamiento": "Sanborns pide en cajas; Arca en piezas. Conversión incierta."}
        ]
    }
    enviar_alerta(pedido_demo, mapa_demo)
