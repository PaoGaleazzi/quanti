"""Lista las tablas y columnas existentes en la base de datos."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=os.environ["DB_PORT"],
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    sslmode="require",          # Supabase lo exige
)
cur = conn.cursor()

# 1) tablas del esquema public
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name;
""")
tablas = [r[0] for r in cur.fetchall()]
print("== TABLAS ==")
print(tablas, "\n")

# 2) columnas + tipo + conteo de filas por tabla
for t in tablas:
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
    """, (t,))
    cols = cur.fetchall()
    try:
        cur.execute(f'SELECT count(*) FROM "{t}";')
        n = cur.fetchone()[0]
    except Exception:
        n = "?"
    print(f"== {t}  ({n} filas) ==")
    for c, d in cols:
        print(f"   {c} :: {d}")
    # una fila de muestra
    try:
        cur.execute(f'SELECT * FROM "{t}" LIMIT 1;')
        row = cur.fetchone()
        if row:
            print("   muestra:", row)
    except Exception:
        pass
    print()

conn.close()
print("Listo. Pásame esta salida y afinamos el sync exacto a tu esquema.")
