-- =====================================================================
-- ALWAYS ON SHELF — Tabla de mapas aprendidos (cerebro de aprender)
-- Pao · pegar en el SQL Editor de Supabase y ejecutar.
-- =====================================================================
-- Guarda el JSON que el LLM infiere al observar UN pedido en ambos
-- portales. Una fila por cliente_portal (HEB, Sanborns, ...).
-- "Se aprende una sola vez": si ya existe, se actualiza (on conflict).

create table if not exists mapas_aprendidos (
    id                  serial primary key,
    cliente_portal      text not null unique,   -- HEB / Sanborns (clave de upsert)
    mapa_json           jsonb not null,         -- el mapa completo (field_mappings, etc.)
    modelo_llm          text,                   -- qué modelo lo generó (auditoría)
    confianza_global    numeric(4,3),           -- 0.000 a 1.000 (umbral de alerta < 0.70)
    fecha_creacion      timestamptz default now(),
    fecha_actualizacion timestamptz default now()
);
