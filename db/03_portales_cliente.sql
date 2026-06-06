-- =====================================================================
-- PORTALES DE CLIENTE — sistemas EXTERNOS simulados (origen)
-- Equipo: Fer · Xime · Steff · Pao
--
-- IMPORTANTE: esto NO es el sistema de Arca. Son los portales de los
-- clientes (HEB, Sanborns) que el bot debe APRENDER a leer y mapear.
-- A propósito tienen nombres de campo DISTINTOS entre sí y vs Arca.
-- El LLM debe inferir que:
--    user_id (HEB) = client_id (Sanborns) = client_id (Arca)
--    qty (HEB, piezas) = unidades_pedidas (Sanborns, CAJAS) = cantidad (Arca, piezas)
--
-- Recomendación: montar cada portal como un servicio web aparte
-- (su propia app), aunque la tabla viva en la misma base. Lo que
-- importa para el reto es que las UIs y los nombres de campo difieran.
-- =====================================================================

drop table if exists heb_orders cascade;
drop table if exists sanborns_pedidos cascade;

-- ---------------------------------------------------------------------
-- HEB (super) — estructura en inglés, cantidad en PIEZAS
-- ---------------------------------------------------------------------
create table heb_orders (
    order_ref     serial primary key,
    user_id       text not null,        -- <-> client_id en Arca
    product       text not null,        -- <-> producto_nombre
    qty           integer not null,     -- <-> cantidad (PIEZAS)
    unit_price    numeric(10,2),        -- <-> precio_unitario
    delivery_date date                  -- <-> fecha_entrega_estimada
);

-- ---------------------------------------------------------------------
-- Sanborns (cafetería) — estructura en español, cantidad en CAJAS
-- ---------------------------------------------------------------------
create table sanborns_pedidos (
    folio            serial primary key,
    client_id        text not null,     -- <-> client_id en Arca
    articulo         text not null,     -- <-> producto_nombre
    unidades_pedidas integer not null,  -- <-> cantidad (¡CAJAS! requiere conversión)
    costo            numeric(10,2),     -- <-> precio_unitario
    fecha_requerida  date               -- <-> fecha_entrega_estimada
);

-- ---------------------------------------------------------------------
-- Datos de ejemplo para PROBAR la observación (un pedido cada uno)
-- Estos son los datos que el usuario "llena" mientras el bot observa.
-- Para la fase de automatización, usar datos DISTINTOS a estos.
-- ---------------------------------------------------------------------
insert into heb_orders (user_id, product, qty, unit_price, delivery_date) values
    ('1', 'Coca-Cola 600ml', 80, 18.00, '2025-06-03'),
    ('1', 'Sprite 600ml',    60, 17.00, '2025-06-03');

insert into sanborns_pedidos (client_id, articulo, unidades_pedidas, costo, fecha_requerida) values
    ('2', 'Coca-Cola 600ml', 3, 432.00, '2025-06-04'),   -- 3 cajas (24 pzas c/u = 72 piezas)
    ('2', 'Fuze Tea Durazno 600ml', 2, 456.00, '2025-06-04');

-- =====================================================================
-- El caso de las CAJAS de Sanborns es la prueba estrella:
-- 3 cajas -> el bot debe convertir a 72 piezas usando productos.piezas_por_caja.
-- Eso demuestra RAZONAMIENTO, no copia literal de campos.
-- =====================================================================
