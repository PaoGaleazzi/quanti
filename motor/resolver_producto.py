"""Traduce el nombre de producto del cliente al del catalogo de Arca (formato, cache y modelo de lenguaje)."""

import re
import unicodedata

# Reusamos la llamada a Gemini con manejo de 429/backoff que ya existe.
from cerebro_aprender import _generar_json

# Si el LLM no llega a esta confianza, NO registramos: avisamos para revisar.
UMBRAL_CONFIANZA = 0.7


class ProductoNoResueltoError(Exception):
    """El producto del cliente no se pudo resolver con confianza al catálogo."""


def _normalizar(texto):
    """
    minúsculas + sin acentos + SOLO alfanuméricos (sin espacios ni puntuación).
    Insensible al formato: 'Refresco Cola 600 ml', 'refresco cola 600ml' y
    'Refresco-Cola 600ML' colapsan todos a 'refrescocola600ml'. Así el caché
    reconoce el mismo producto aunque el cliente lo escriba distinto cada vez.
    """
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))   # quita acentos
    t = t.lower()
    return re.sub(r"[^a-z0-9]+", "", t)                          # solo alfanuméricos


def _tabla_existe(cur, nombre):
    """True si la tabla existe (para degradar sin romper si no se ha creado)."""
    cur.execute("select to_regclass(%s)", (f"public.{nombre}",))
    return cur.fetchone()[0] is not None


# ---------------------------------------------------------------------------
# CACHÉ (tabla equivalencias_productos)
# ---------------------------------------------------------------------------
def _cache_buscar(cur, cliente_portal, clave_norm):
    """Devuelve una resolución previa (por nombre normalizado) o None."""
    if not _tabla_existe(cur, "equivalencias_productos"):
        return None
    cur.execute(
        """
        select e.sku, p.nombre, p.piezas_por_caja, e.confianza, e.razonamiento, e.metodo
        from equivalencias_productos e
        join productos p on p.sku = e.sku
        where e.cliente_portal is not distinct from %s and e.nombre_cliente = %s
        """,
        (cliente_portal, clave_norm),
    )
    fila = cur.fetchone()
    if not fila:
        return None
    return {
        "sku": fila[0], "nombre_catalogo": fila[1], "piezas_por_caja": fila[2],
        "confianza": float(fila[3]) if fila[3] is not None else None,
        "razonamiento": fila[4], "metodo": (fila[5] or "cache"),
    }


def _cache_guardar(cur, cliente_portal, clave_norm, nombre_raw, res):
    """Guarda/actualiza la equivalencia (upsert por cliente_portal + nombre normalizado)."""
    if not _tabla_existe(cur, "equivalencias_productos"):
        return
    cur.execute(
        """
        insert into equivalencias_productos
            (cliente_portal, nombre_cliente, nombre_cliente_raw, sku,
             nombre_catalogo, metodo, confianza, razonamiento)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (cliente_portal, nombre_cliente) do update
        set nombre_cliente_raw = excluded.nombre_cliente_raw,
            sku                = excluded.sku,
            nombre_catalogo    = excluded.nombre_catalogo,
            metodo             = excluded.metodo,
            confianza          = excluded.confianza,
            razonamiento       = excluded.razonamiento,
            fecha              = now();
        """,
        (cliente_portal, clave_norm, nombre_raw, res["sku"],
         res["nombre_catalogo"], res["metodo"], res["confianza"], res["razonamiento"]),
    )


# ---------------------------------------------------------------------------
# RESOLUCIÓN POR LLM (solo si el match normalizado falla)
# ---------------------------------------------------------------------------
def _resolver_con_llm(nombre_cliente, catalogo, modelo="gemini-3.5-flash", reintentos=4):
    """
    Pregunta a Gemini a qué producto del catálogo corresponde, por SIGNIFICADO.
    `catalogo` = lista de (sku, nombre, piezas_por_caja). Devuelve {sku, confianza, razonamiento}.
    """
    lineas = "\n".join(f"- {sku} | {nombre}" for sku, nombre, _ in catalogo)
    prompt = f"""Eres un asistente que relaciona el nombre de un producto escrito por un
CLIENTE con el catálogo FIJO de Arca. Elige el producto del catálogo que corresponde
POR SIGNIFICADO (misma bebida/botana y presentación/tamaño), NO por parecido de letras.

Nombre del producto del cliente: "{nombre_cliente}"

Catálogo de Arca (sku | nombre):
{lineas}

Devuelve SOLO un JSON con esta forma, sin texto extra:
{{"sku": "<el sku del catálogo que corresponde, o null si ninguno>",
  "confianza": 0.0, "razonamiento": "..."}}
La confianza va de 0 a 1. Si ninguno corresponde, sku=null y confianza baja."""
    return _generar_json(prompt, modelo, reintentos)


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA
# ---------------------------------------------------------------------------
def resolver_producto(cur, nombre_cliente, cliente_portal=None):
    """
    Resuelve el nombre del cliente al producto del catálogo de Arca.
    Devuelve {sku, nombre_catalogo, piezas_por_caja, confianza, razonamiento, metodo}.
    Lanza ProductoNoResueltoError si el LLM no está seguro (no adivina).
    """
    clave = _normalizar(nombre_cliente)

    # 1) CACHÉ (por nombre normalizado)
    cached = _cache_buscar(cur, cliente_portal, clave)
    if cached:
        return cached

    # Catálogo de Arca (destino fijo).
    cur.execute("select sku, nombre, piezas_por_caja from productos")
    catalogo = cur.fetchall()

    # 2) MATCH NORMALIZADO (sin LLM)
    for sku, nombre, ppc in catalogo:
        if _normalizar(nombre) == clave:
            res = {
                "sku": sku, "nombre_catalogo": nombre, "piezas_por_caja": ppc,
                "confianza": 1.0, "metodo": "normalizado",
                "razonamiento": "Coincidencia exacta por nombre normalizado (mismo producto, distinto formato).",
            }
            _cache_guardar(cur, cliente_portal, clave, nombre_cliente, res)
            return res

    # 3) LLM (significado)
    llm = _resolver_con_llm(nombre_cliente, catalogo)
    sku = llm.get("sku")
    conf = float(llm.get("confianza") or 0)
    fila = next((c for c in catalogo if c[0] == sku), None)

    if not fila or conf < UMBRAL_CONFIANZA:
        raise ProductoNoResueltoError(
            f"No estoy seguro de a qué producto del catálogo corresponde "
            f"'{nombre_cliente}' (candidato sku={sku}, confianza={conf:.2f}). "
            f"Revisar manualmente."
        )

    res = {
        "sku": fila[0], "nombre_catalogo": fila[1], "piezas_por_caja": fila[2],
        "confianza": conf, "metodo": "llm",
        "razonamiento": llm.get("razonamiento", ""),
    }
    _cache_guardar(cur, cliente_portal, clave, nombre_cliente, res)
    return res
