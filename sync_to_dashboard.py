"""
sync_to_dashboard.py — lee la BD real de Arca (Supabase) y escribe
engine_output.json, que es lo que el tablero relee solo cada 4 s.

USO:
    uv run python sync_to_dashboard.py            # una vez
    uv run python sync_to_dashboard.py --loop     # cada 4 s (demo en vivo)

Y para que el navegador pueda leer el JSON, en OTRA pestaña del Terminal:
    uv run python -m http.server 8000
    # luego abre http://localhost:8000/dashboard_arca.html
"""
import os, json, time, sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

ARCA_FIELDS = ["client_id", "producto_nombre", "cantidad", "precio_unitario", "fecha_entrega_estimada"]


def conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], sslmode="require",
    )


def build():
    c = conn(); cur = c.cursor()
    cur.execute("""
        SELECT  p.numero_orden,
                cl.nombre_cliente,
                COALESCE(cl.portal_origen, 'Arca'),
                COALESCE(p.origen_captura, 'auto_IA'),
                COALESCE(p.confiabilidad_llenado, 95)
        FROM pedidos p
        JOIN clientes cl ON cl.client_id = p.client_id
        ORDER BY p.numero_orden DESC
        LIMIT 200;
    """)
    pedidos = []
    for oid, cliente, portal, modo, conf100 in cur.fetchall():
        conf = float(conf100) / 100.0 if float(conf100) > 1 else float(conf100)
        fields = [[f, round(conf, 2), 1 if conf >= 0.66 else 0] for f in ARCA_FIELDS]
        pedidos.append({
            "id": f"ORD-{oid}", "cliente": cliente,
            "portal": (portal or "Arca").upper(), "modo": modo, "fields": fields,
        })

    out = {"pedidos": pedidos}
    try:
        with open("mapa_aprendido.json", encoding="utf-8") as f:
            out["portales"] = json.load(f)
    except FileNotFoundError:
        pass

    with open("engine_output.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    c.close()
    print(f"OK - engine_output.json escrito con {len(pedidos)} pedidos")


if __name__ == "__main__":
    loop = "--loop" in sys.argv
    while True:
        try:
            build()
        except Exception as e:
            print("ERROR:", e)
        if not loop:
            break
        time.sleep(4)
