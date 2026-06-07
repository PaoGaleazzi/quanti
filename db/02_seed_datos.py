"""Genera y carga datos de prueba (catalogo de productos, clientes y pedidos historicos) en la base de datos."""

import os
import random
from datetime import date, timedelta

import psycopg2
from dotenv import load_dotenv

# ---------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------
load_dotenv()
DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     os.getenv("DB_PORT", "5432"),
    "dbname":   os.getenv("DB_NAME", "postgres"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
}
if not DB_CONFIG["host"] or not DB_CONFIG["password"]:
    raise SystemExit("Faltan campos de conexión en el .env (DB_HOST y DB_PASSWORD)")

random.seed(42)          # <-- semilla fija: misma data para todas
SEMANAS = 12             # histórico a generar
HOY = date(2025, 6, 1)   # fecha de referencia fija (no usar date.today para reproducibilidad)
INICIO = HOY - timedelta(weeks=SEMANAS)

# ---------------------------------------------------------------------
# Catálogo de productos (precio_lista, piezas_por_caja)
# ---------------------------------------------------------------------
PRODUCTOS = [
    # sku, nombre, categoria, presentacion, precio_lista, piezas_por_caja
    ("SKU-0001", "Coca-Cola 600ml",      "Refresco", "Botella 600ml", 18.00, 24),
    ("SKU-0002", "Coca-Cola Sin Azúcar 600ml", "Refresco", "Botella 600ml", 18.00, 24),
    ("SKU-0003", "Sprite 600ml",         "Refresco", "Botella 600ml", 17.00, 24),
    ("SKU-0004", "Agua Ciel 1L",         "Agua",     "Botella 1L",    12.00, 12),
    ("SKU-0005", "Powerade Mora Azul 600ml", "Hidratante", "Botella 600ml", 20.00, 12),
    ("SKU-0006", "Bokados Mix 60g",      "Botana",   "Bolsa 60g",      15.00, 30),
    ("SKU-0007", "Topo Chico 355ml",     "Agua Mineral", "Botella 355ml", 16.00, 24),
    ("SKU-0008", "Fuze Tea Durazno 600ml", "Té",     "Botella 600ml",  19.00, 24),
    # Productos reales de Arca presentes en los portales de cliente (HEB).
    # Agregar productos reales NO es hardcodear: completa el catálogo de Arca.
    ("SKU-0009", "Fanta Naranja 600ml",  "Refresco", "Botella 600ml", 17.00, 24),
    ("SKU-0010", "Fresca Toronja 600ml", "Refresco", "Botella 600ml", 17.00, 24),
    ("SKU-0011", "Agua Ciel 600ml",      "Agua",     "Botella 600ml", 11.00, 24),
    ("SKU-0012", "Ciel Mineralizada 600ml", "Agua Mineral", "Botella 600ml", 12.00, 24),
    ("SKU-0013", "Té Verde Limón 600ml", "Té",       "Botella 600ml", 18.00, 24),
    ("SKU-0014", "Del Valle Manzana 413ml", "Jugo",  "Botella 413ml", 13.00, 24),
    ("SKU-0015", "Del Valle Durazno 413ml", "Jugo",  "Botella 413ml", 13.00, 24),
    ("SKU-0016", "Santa Clara Fresa 200ml", "Lácteo", "Botella 200ml",  9.50, 27),
    ("SKU-0017", "Santa Clara Chocolate 200ml", "Lácteo", "Botella 200ml", 9.50, 27),
    ("SKU-0018", "Monster Energy 473ml", "Energético", "Lata 473ml",   36.00, 24),
]

# ---------------------------------------------------------------------
# Clientes  (nombre, tipo_canal, rfc, requiere_factura, portal_origen)
# ---------------------------------------------------------------------
CLIENTES = [
    ("HEB Valle Oriente",   "super",       "HEB930101AAA", True,  "HEB"),
    ("Sanborns Centro",     "restaurante", "SAN850202BBB", True,  "Sanborns"),
    ("HEB Cumbres",         "super",       "HEB930101AAA", True,  "HEB"),
    ("Sanborns San Pedro",  "restaurante", "SAN850202BBB", False, "Sanborns"),
    ("Sanborns Plaza Galerías", "restaurante", "SAN850202BBB", True, "Sanborns"),
]

# Clientes ADICIONALES con client_id EXPLÍCITO. Los portales de cliente ofrecen
# ciertos ids fijos en sus <select> (ej. Sanborns ofrece el 9 = "Sanborns San
# Ángel") que deben existir en la tabla para que el FK de pedidos no truene.
# Se insertan con su id fijo (no por serial); la secuencia se ajusta después.
# (client_id, nombre, tipo_canal, rfc, requiere_factura, portal_origen)
CLIENTES_EXTRA = [
    (9, "Sanborns San Ángel", "restaurante", "SAN850202BBB", True, "Sanborns"),
]

# Perfil de pedido por cliente: qué SKUs pide, día típico, frecuencia (días),
# cantidad base, y si DECAE (para churn).
# El índice corresponde al orden de CLIENTES (client_id 1..5).
PERFILES = [
    # HEB Valle Oriente: pide mucho, estable, lunes y jueves
    {"skus": ["SKU-0001","SKU-0003","SKU-0004","SKU-0006"], "dias": [0,3], "base": 80, "decae": False},
    # Sanborns Centro: DECAE en el tiempo -> CHURN. martes.
    {"skus": ["SKU-0001","SKU-0008","SKU-0007"],            "dias": [1],   "base": 40, "decae": True},
    # HEB Cumbres: estable, miércoles
    {"skus": ["SKU-0001","SKU-0002","SKU-0005"],            "dias": [2],   "base": 60, "decae": False},
    # Sanborns San Pedro: estable bajo, viernes
    {"skus": ["SKU-0004","SKU-0007"],                       "dias": [4],   "base": 25, "decae": False},
    # Sanborns Plaza Galerías (client_id=5): SIN historial sembrado (empieza limpio;
    # su primer pedido lo crea el demo en vivo). skus vacío -> no se siembran pedidos.
    {"skus": [],                                            "dias": [],    "base": 0,  "decae": False},
]

PRECIO = {p[0]: p[4] for p in PRODUCTOS}


def conectar():
    return psycopg2.connect(**DB_CONFIG)


def limpiar(cur):
    """Vacía las tablas para re-sembrar limpio."""
    cur.execute("""
        truncate borradores, alertas_riesgo, patron_cliente,
                 pedido_detalle, pedidos, productos, clientes
        restart identity cascade;
    """)


def sembrar_catalogo(cur):
    cur.executemany(
        "insert into productos (sku,nombre,categoria,presentacion,precio_lista,piezas_por_caja)"
        " values (%s,%s,%s,%s,%s,%s)",
        PRODUCTOS,
    )
    cur.executemany(
        "insert into clientes (nombre_cliente,tipo_canal,razon_social,rfc,requiere_factura,portal_origen)"
        " values (%s,%s,%s,%s,%s,%s)",
        [(c[0], c[1], c[0], c[2], c[3], c[4]) for c in CLIENTES],
    )
    # Clientes con id EXPLÍCITO que los portales esperan (ej. Sanborns id=9).
    cur.executemany(
        "insert into clientes (client_id,nombre_cliente,tipo_canal,razon_social,rfc,requiere_factura,portal_origen)"
        " values (%s,%s,%s,%s,%s,%s,%s)",
        [(c[0], c[1], c[2], c[1], c[3], c[4], c[5]) for c in CLIENTES_EXTRA],
    )
    # Metimos ids explícitos mayores al serial (ej. 9); avanzamos la secuencia para
    # que el próximo insert por serial no choque con uno ya usado.
    cur.execute("select setval('clientes_client_id_seq', (select max(client_id) from clientes))")


def sembrar_pedidos(cur):
    numero_orden = 0
    for idx, perfil in enumerate(PERFILES):
        client_id = idx + 1
        if not perfil["skus"]:
            continue                      # cliente sin historial sembrado (empieza limpio)
        for semana in range(SEMANAS):
            # factor de decaimiento: si decae, baja gradualmente hasta ~30% al final
            if perfil["decae"]:
                factor = max(0.3, 1.0 - (semana / SEMANAS) * 0.8)
            else:
                factor = random.uniform(0.9, 1.1)  # ruido leve

            for dia_semana in perfil["dias"]:
                fecha_pedido = INICIO + timedelta(weeks=semana, days=dia_semana)
                if fecha_pedido > HOY:
                    continue
                fecha_entrega = fecha_pedido + timedelta(days=2)  # entrega ~2 días después

                numero_orden += 1
                # ¿entregado? los recientes pueden seguir pendientes
                entregado = fecha_entrega <= HOY
                estatus_entrega = "entregado" if entregado else "pendiente"
                # ~5% no entregados por falta de stock
                if entregado and random.random() < 0.05:
                    estatus_entrega = "no_entregado"

                facturado = estatus_entrega == "entregado"
                numero_factura = f"F-{numero_orden:05d}" if facturado else None
                estatus_factura = "facturado" if facturado else "no_facturado"

                # confiabilidad del llenado: alta, con algo de variación
                confiabilidad = round(random.uniform(92, 99.5), 2)

                # construir detalle
                detalles = []
                monto_total = 0
                for sku in perfil["skus"]:
                    cantidad = max(1, int(perfil["base"] * factor * random.uniform(0.8, 1.2)))
                    precio = PRECIO[sku]
                    importe = round(cantidad * precio, 2)
                    monto_total += importe
                    detalles.append((sku, cantidad, precio, importe))

                cur.execute(
                    "insert into pedidos (client_id,fecha_pedido,fecha_entrega_estimada,"
                    "fecha_entrega_real,estatus_entrega,estatus_factura,numero_factura,"
                    "monto_total,confiabilidad_llenado,origen_captura)"
                    " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'auto_IA') returning numero_orden",
                    (client_id, fecha_pedido, fecha_entrega,
                     fecha_entrega if estatus_entrega == "entregado" else None,
                     estatus_entrega, estatus_factura, numero_factura,
                     round(monto_total, 2), confiabilidad),
                )
                orden_id = cur.fetchone()[0]

                for sku, cantidad, precio, importe in detalles:
                    nombre = next(p[1] for p in PRODUCTOS if p[0] == sku)
                    cur.execute(
                        "insert into pedido_detalle (numero_orden,sku,producto_nombre,"
                        "cantidad,unidad,precio_unitario,importe)"
                        " values (%s,%s,%s,%s,'pieza',%s,%s)",
                        (orden_id, sku, nombre, cantidad, precio, importe),
                    )
    return numero_orden


def main():
    conn = conectar()
    cur = conn.cursor()
    print("Limpiando tablas...")
    limpiar(cur)
    print("Sembrando catálogo y clientes...")
    sembrar_catalogo(cur)
    print("Generando pedidos históricos...")
    total = sembrar_pedidos(cur)
    conn.commit()
    print(f"Listo. {total} pedidos generados.")
    print("Sanborns Centro (client_id=2) DECAE en el tiempo -> úsalo para el demo de churn.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
