"""
sync_to_dashboard.py — jala los pedidos de la BD de Arca y escribe
engine_output.json, que es justo lo que tu tablero relee solo cada 4 s.

    uv run python sync_to_dashboard.py            # una vez
    uv run python sync_to_dashboard.py --loop     # cada 4 s, modo demo en vivo

Y para que el navegador pueda leer el JSON, sirve la carpeta:
    uv run python -m http.server 8000
    # abre http://localhost:8000/dashboard_arca.html

OJO: los nombres de tabla/columna de abajo son los del esquema documentado.
Corre primero inspect_db.py; si Pao los nombró distinto, ajusta el bloque MAP.
"""
import os, json, time, sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ---- ajusta esto a lo que veas en inspect_db.py ----
MAP = {
    "tabla_pedidos":   "pedidos",
    "col_id":          "numero_orden",
    "col_cliente_fk":  "client_id",
    "col_confiab":     "confiabilidad_llenado",   # 0-1 que escribe el motor
    "col_origen":      "origen_captura",          # 'auto_IA' / 'manual'
    "tabla_clientes":  "clientes",
    "col_cli_id":      "client_id",
    "col_cli_nombre":  "nombre_cliente",
    "col_cli_portal":  "portal_origen",           # qué portal usó
}
# campos Arca que muestra el tablero (orden = como se pintan)
ARCA_FIELDS = ["client_id", "producto_nombre", "cantidad", "precio_unitario", "fecha_entrega_estimada"]


def conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], sslmode="require",
    )


def build():
    c = conn(); cur = c.cursor()
    q = f"""
        SELECT p."{MAP['col_id']}", cl."{MAP['col_cli_nombre']}",
               COALESCE(cl."{MAP['col_cli_portal']}", 'DESCONOCIDO'),
               COALESCE(p."{MAP['col_origen']}", 'auto_IA'),
               COALESCE(p."{MAP['col_confiab']}", 0.9)
        FROM "{MAP['tabla_pedidos']}" p
        LEFT JOIN "{MAP['tabla_clientes']}" cl
          ON cl."{MAP['col_cli_id']}" = p."{MAP['col_cliente_fk']}"
        ORDER BY p."{MAP['col_id']}" DESC
        LIMIT 200;
    """
    cur.execute(q)
    pedidos = []
    for oid, cliente, portal, modo, conf in cur.fetchall():
        conf = float(conf)
        # si la BD sólo guarda confiabilidad por pedido (no por campo),
        # repartimos esa confianza a cada campo. valid=1 si conf>=0.66.
        fields = [[f, round(conf, 2), 1 if conf >= 0.66 else 0] for f in ARCA_FIELDS]
        pedidos.append({
            "id": str(oid), "cliente": cliente or str(oid),
            "portal": str(portal), "modo": str(modo), "fields": fields,
        })
    c.close()

    out = {"pedidos": pedidos}
    # 'portales' (el mapa aprendido) lo produce el motor de Pao, no la BD.
    # Si Pao lo deja en un archivo aparte, lo mezclamos aquí:
    try:
        with open("mapa_aprendido.json", encoding="utf-8") as f:
            out["portales"] = json.load(f)
    except FileNotFoundError:
        pass  # el tablero usa su demo de portales si no hay mapa real

    with open("engine_output.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"escrito engine_output.json · {len(pedidos)} pedidos")


if __name__ == "__main__":
    loop = "--loop" in sys.argv
    while True:
        try:
            build()
        except Exception as e:
            print("error:", e)
        if not loop:
            break
        time.sleep(4)
