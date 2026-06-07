-- =====================================================================
-- ALWAYS ON SHELF — Equivalencias de productos (resolución semántica)
-- Pao · pegar en el SQL Editor de Supabase y ejecutar.
-- =====================================================================
-- Cuando el portal del CLIENTE usa un nombre propio ("Refresco Cola 600 ml")
-- que no existe igual en el catálogo de Arca ("Coca-Cola 600ml"), el motor lo
-- resuelve (match normalizado y, si falla, el LLM) y guarda aquí el resultado:
--   - sirve de CACHÉ (no se vuelve a llamar al LLM por el mismo producto), y
--   - es la EVIDENCIA para el dashboard / jurado (confianza + razonamiento).
--
-- La clave de caché es el nombre del cliente NORMALIZADO (minúsculas, sin
-- acentos ni puntuación, espacios colapsados), para que aguante las variaciones
-- de escritura del cliente entre pedidos.

create table if not exists equivalencias_productos (
    id                  serial primary key,
    cliente_portal      text,                       -- HEB / Sanborns (puede ser null)
    nombre_cliente      text not null,              -- NORMALIZADO (clave de caché)
    nombre_cliente_raw  text,                       -- último texto crudo visto (referencia)
    sku                 text references productos(sku),
    nombre_catalogo     text,                       -- nombre canónico de Arca resuelto
    metodo              text,                       -- 'normalizado' | 'llm'
    confianza           numeric(4,3),               -- 0.000 a 1.000
    razonamiento        text,                       -- por qué (prueba anti-hardcoding)
    fecha               timestamptz default now(),
    unique (cliente_portal, nombre_cliente)
);
