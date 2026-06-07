"""
calcular_predictivas.py
Calcula patron_cliente, alertas_riesgo y borradores
a partir del historial que ya está en Supabase.
Correr DESPUÉS de 02_seed_datos.py.

Uso:
  python calcular_predictivas.py
"""

import os, json
from datetime import date, timedelta
from collections import defaultdict
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     os.getenv("DB_PORT", "5432"),
    "dbname":   os.getenv("DB_NAME", "postgres"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
}

UMBRAL_CHURN    = 0.40   # si últimas 4 sem < 40% del promedio → alerta churn
UMBRAL_RIESGO   = 0.65   # nivel_riesgo que va al dashboard como rojo
HOY = date(2025, 6, 1)   # misma referencia que el seed


def conectar():
    return psycopg2.connect(**DB_CONFIG)


# ─────────────────────────────────────────────────────────── patron_cliente
def calcular_patrones(cur):
    # Jala todo el historial: client_id, fecha, sku, cantidad
    cur.execute("""
        select p.client_id, p.fecha_pedido, d.sku, d.cantidad
        from pedidos p join pedido_detalle d using (numero_orden)
        where p.estatus_entrega != 'no_entregado'
        order by p.client_id, d.sku, p.fecha_pedido
    """)
    rows = cur.fetchall()

    # Agrupar por (client_id, sku)
    data = defaultdict(list)
    for client_id, fecha, sku, cantidad in rows:
        data[(client_id, sku)].append((fecha, cantidad))

    patrones = []
    for (client_id, sku), registros in data.items():
        if len(registros) < 2:
            continue
        cantidades  = [r[1] for r in registros]
        fechas      = [r[0] for r in registros]
        cantidad_prom = round(sum(cantidades) / len(cantidades), 1)
        # frecuencia promedio en días
        diffs = [(fechas[i+1]-fechas[i]).days for i in range(len(fechas)-1)]
        frecuencia = round(sum(diffs)/len(diffs), 1) if diffs else 7.0
        # día de semana típico (el más frecuente)
        dias = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
        dia_tipico = dias[max(set(f.weekday() for f in fechas),
                              key=lambda d: sum(1 for f in fechas if f.weekday()==d))]
        ultima = max(fechas)
        # tendencia: compara primera mitad vs segunda mitad
        mitad = len(cantidades)//2
        if mitad > 0:
            prom1 = sum(cantidades[:mitad])/mitad
            prom2 = sum(cantidades[mitad:])/mitad
            if prom2 < prom1 * 0.75:   tendencia = "bajando"
            elif prom2 > prom1 * 1.10: tendencia = "subiendo"
            else:                       tendencia = "estable"
        else:
            tendencia = "estable"

        patrones.append((client_id, sku, frecuencia, cantidad_prom,
                         dia_tipico, ultima, tendencia))
    return patrones


# ─────────────────────────────────────────────────────────── alertas_riesgo
def calcular_alertas(cur, patrones):
    alertas = []
    for client_id, sku, frecuencia, cantidad_prom, dia_tipico, ultima, tendencia in patrones:
        # 1) Churn: tendencia bajando Y volumen reciente < 60% del promedio histórico
        if tendencia == "bajando":
            # promedio últimas 4 semanas
            cur.execute("""
                select coalesce(avg(d.cantidad), 0)
                from pedidos p join pedido_detalle d using (numero_orden)
                where p.client_id=%s and d.sku=%s
                  and p.fecha_pedido >= %s
                  and p.estatus_entrega != 'no_entregado'
            """, (client_id, sku, HOY - timedelta(weeks=4)))
            ult_prom = float(cur.fetchone()[0])

            # promedio primeras 8 semanas (referencia sana)
            cur.execute("""
                select coalesce(avg(d.cantidad), 0)
                from pedidos p join pedido_detalle d using (numero_orden)
                where p.client_id=%s and d.sku=%s
                  and p.fecha_pedido < %s
                  and p.estatus_entrega != 'no_entregado'
            """, (client_id, sku, HOY - timedelta(weeks=4)))
            base_prom = float(cur.fetchone()[0])

            if base_prom > 0:
                ratio = ult_prom / base_prom
                nivel = round(max(0.0, 1.0 - ratio), 2)
                if nivel >= 0.25:   # bajó más del 25% vs su propia baseline
                    desc = (f"Promedio últimas 4 sem: {ult_prom:.0f} uds vs "
                            f"baseline primeras 8 sem: {base_prom:.0f} uds "
                            f"({ratio:.0%} del nivel sano) — volumen en caída.")
                    alertas.append((client_id, "churn", nivel, desc))

        # 2) Pedido atrasado
        dias_sin_pedir = (HOY - ultima).days
        if dias_sin_pedir > frecuencia * 1.5:
            nivel = min(0.99, round(dias_sin_pedir / (frecuencia * 3), 2))
            desc = (f"Último pedido hace {dias_sin_pedir} días. "
                    f"Frecuencia esperada: cada {frecuencia:.0f} días.")
            alertas.append((client_id, "pedido_atrasado", nivel, desc))

    # Dedup: solo la más grave por cliente+tipo
    dedup = {}
    for client_id, tipo, nivel, desc in alertas:
        key = (client_id, tipo)
        if key not in dedup or nivel > dedup[key][0]:
            dedup[key] = (nivel, desc)

    return [(cid, tipo, niv, desc) for (cid, tipo), (niv, desc) in dedup.items()]


# ─────────────────────────────────────────────────────────── borradores
def calcular_borradores(cur, patrones):
    """Crea un borrador por cliente con sus SKUs típicos y cantidad sugerida."""
    por_cliente = defaultdict(list)
    for client_id, sku, frecuencia, cantidad_prom, dia_tipico, ultima, tendencia in patrones:
        # sugerir solo si la compra anterior fue hace > 0.7x la frecuencia
        dias = (HOY - ultima).days
        if dias >= frecuencia * 0.7:
            por_cliente[client_id].append({
                "sku": sku, "cantidad_sugerida": int(round(cantidad_prom)), "dia_tipico": dia_tipico
            })

    borradores = []
    for client_id, items in por_cliente.items():
        if not items:
            continue
        # fecha sugerida: HOY + 1 día
        fecha_sugerida = HOY + timedelta(days=1)
        borradores.append((client_id, fecha_sugerida, json.dumps(items)))
    return borradores


# ─────────────────────────────────────────────────────────── main
def main():
    conn = conectar()
    cur  = conn.cursor()

    print("Limpiando tablas predictivas...")
    cur.execute("truncate borradores, alertas_riesgo, patron_cliente restart identity cascade;")

    print("Calculando patrones...")
    patrones = calcular_patrones(cur)
    cur.executemany(
        "insert into patron_cliente "
        "(client_id,sku,frecuencia_dias,cantidad_promedio,dia_semana_tipico,ultima_compra,tendencia)"
        " values (%s,%s,%s,%s,%s,%s,%s)",
        patrones
    )
    print(f"  {len(patrones)} patrones insertados.")

    print("Calculando alertas de riesgo...")
    alertas = calcular_alertas(cur, patrones)
    cur.executemany(
        "insert into alertas_riesgo (client_id,tipo,nivel_riesgo,descripcion,fecha_generada,atendida)"
        " values (%s,%s,%s,%s,%s,false)",
        [(a[0], a[1], a[2], a[3], HOY) for a in alertas]
    )
    print(f"  {len(alertas)} alertas generadas.")

    print("Calculando borradores...")
    borradores = calcular_borradores(cur, patrones)
    cur.executemany(
        "insert into borradores (client_id,fecha_sugerida,productos_sugeridos,enviado_whatsapp,autorizado_cliente)"
        " values (%s,%s,%s,false,false)",
        borradores
    )
    print(f"  {len(borradores)} borradores generados.")

    conn.commit()
    cur.close(); conn.close()

    # Mostrar alertas para que veas qué churners salieron
    print("\n─── Alertas generadas ───")
    for cid, tipo, nivel, desc in sorted(alertas, key=lambda x:-x[2]):
        emoji = "RIESGO ALTO" if nivel >= UMBRAL_RIESGO else "riesgo medio"
        print(f"  client_id={cid} | {tipo} | nivel={nivel:.0%} [{emoji}]")
        print(f"    {desc}")

    print("\nListo. Ahora el dashboard ya puede leer las tablas predictivas.")


if __name__ == "__main__":
    main()
