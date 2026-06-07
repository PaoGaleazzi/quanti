# -*- coding: utf-8 -*-
"""Renombra SKU-0019 a nombre estilo Arca y resuelve agua limon VIA LLM (queda en cache)."""
import sys; sys.path.insert(0, ".")
import psycopg2
from ejecutar import DB_CONFIG
from resolver_producto import resolver_producto, _normalizar as norm, ProductoNoResueltoError

NOMBRE_PORTAL = "Agua Saborizada Limón 1 L"   # como lo manda el portal Sanborns
NOMBRE_ARCA   = "Ciel Exprim Limón 1L"        # nombre canonico de Arca (marca Ciel)

conn = psycopg2.connect(**DB_CONFIG); cur = conn.cursor()

# Estado previo en cache
cur.execute("select nombre_cliente, sku, nombre_catalogo, metodo from equivalencias_productos "
            "where nombre_cliente = %s", (norm(NOMBRE_PORTAL),))
print("Cache ANTES:", cur.fetchall() or "(no esta en cache)")

# 1) Renombrar SKU-0019 a estilo Arca para que el match normalizado NO aplique.
cur.execute("update productos set nombre=%s, categoria=%s where sku='SKU-0019'",
            (NOMBRE_ARCA, "Agua saborizada"))
conn.commit()
print(f"\nSKU-0019 renombrado a {NOMBRE_ARCA!r} (filas: {cur.rowcount})")
print("Match normalizado ahora:",
      "FALLA (bien, entra LLM)" if norm(NOMBRE_PORTAL) != norm(NOMBRE_ARCA) else "coincide (mal)")

# 2) Resolver via LLM y cachear.
try:
    r = resolver_producto(cur, NOMBRE_PORTAL, "Sanborns")
    conn.commit()
    print(f"\nRESUELTO -> {r['sku']} {r['nombre_catalogo']} "
          f"(conf={r['confianza']}, metodo={r['metodo']})")
    print("razonamiento:", r.get("razonamiento"))
except ProductoNoResueltoError as e:
    conn.rollback(); print("\nBAJA CONFIANZA:", e)
except Exception as e:
    conn.rollback(); print(f"\nERROR {type(e).__name__}: {str(e)[:200]}")

# 3) Confirmar que quedo en cache.
cur.execute("select nombre_cliente_raw, sku, nombre_catalogo, confianza, metodo "
            "from equivalencias_productos where nombre_cliente = %s", (norm(NOMBRE_PORTAL),))
print("\nCache DESPUES:", cur.fetchall() or "(sigue sin estar)")
conn.close()
