-- =====================================================================
-- ALWAYS ON SHELF — Esquema de base de datos (Supabase / Postgres)
-- Equipo: Fer · Xime · Steff · Pao
-- Cómo usar: pegar TODO esto en el SQL Editor de Supabase y ejecutar.
-- =====================================================================

-- Limpieza por si se re-ejecuta (orden inverso por las llaves foráneas)
drop table if exists borradores cascade;
drop table if exists alertas_riesgo cascade;
drop table if exists patron_cliente cascade;
drop table if exists pedido_detalle cascade;
drop table if exists pedidos cascade;
drop table if exists productos cascade;
drop table if exists clientes cascade;

-- ---------------------------------------------------------------------
-- MUNDO ARCA (destino fijo)
-- ---------------------------------------------------------------------

create table clientes (
    client_id        serial primary key,
    nombre_cliente   text not null,
    tipo_canal       text not null check (tipo_canal in ('super','restaurante')),
    razon_social     text,
    rfc              text,
    requiere_factura boolean default true,
    portal_origen    text,                 -- qué portal usa (HEB / Sanborns)
    fecha_alta       date default current_date
);

create table productos (
    sku              text primary key,
    nombre           text not null,
    categoria        text,
    presentacion     text,
    precio_lista     numeric(10,2),
    piezas_por_caja  integer default 1     -- para conversión caja <-> pieza
);

create table pedidos (
    numero_orden            serial primary key,
    client_id               integer not null references clientes(client_id),
    fecha_pedido            date not null,
    fecha_entrega_estimada  date,
    fecha_entrega_real      date,
    estatus_entrega         text default 'pendiente'
                              check (estatus_entrega in ('pendiente','entregado','no_entregado')),
    estatus_factura         text default 'no_facturado'
                              check (estatus_factura in ('facturado','no_facturado')),
    numero_factura          text,           -- null si no facturado
    monto_total             numeric(12,2),
    confiabilidad_llenado   numeric(5,2),   -- % del motor IA (0-100)
    origen_captura          text default 'auto_IA'
                              check (origen_captura in ('auto_IA','manual'))
);

create table pedido_detalle (
    detalle_id       serial primary key,
    numero_orden     integer not null references pedidos(numero_orden),
    sku              text references productos(sku),
    producto_nombre  text,
    cantidad         integer not null,
    unidad           text default 'pieza',  -- pieza / caja
    precio_unitario  numeric(10,2),
    importe          numeric(12,2)
);

-- ---------------------------------------------------------------------
-- TABLAS PREDICTIVAS (derivadas del histórico)
-- ---------------------------------------------------------------------

create table patron_cliente (
    patron_id         serial primary key,
    client_id         integer not null references clientes(client_id),
    sku               text references productos(sku),
    frecuencia_dias   numeric(6,2),          -- cada cuánto lo pide
    cantidad_promedio numeric(10,2),
    dia_semana_tipico text,                  -- ej. 'lunes'
    ultima_compra     date,
    tendencia         text                   -- 'subiendo' / 'estable' / 'bajando'
);

create table alertas_riesgo (
    alerta_id     serial primary key,
    client_id     integer not null references clientes(client_id),
    tipo          text check (tipo in ('churn','pedido_atrasado','volumen_bajo')),
    nivel_riesgo  numeric(4,3),              -- 0 a 1
    descripcion   text,
    fecha_generada date default current_date,
    atendida      boolean default false
);

create table borradores (
    borrador_id        serial primary key,
    client_id          integer not null references clientes(client_id),
    fecha_sugerida     date,                 -- cuándo suele pedir
    productos_sugeridos jsonb,               -- SKUs + cantidades pre-llenadas
    enviado_whatsapp   boolean default false,
    autorizado_cliente boolean default false
);

-- ---------------------------------------------------------------------
-- Índices útiles para las consultas del predictivo
-- ---------------------------------------------------------------------
create index idx_pedidos_cliente_fecha on pedidos(client_id, fecha_pedido);
create index idx_detalle_orden on pedido_detalle(numero_orden);
create index idx_patron_cliente on patron_cliente(client_id);
create index idx_alertas_cliente on alertas_riesgo(client_id);

-- =====================================================================
-- NOTA: las tablas de los PORTALES de cliente (HEB, Sanborns) NO van aquí.
-- Esas simulan sistemas EXTERNOS y viven aparte (ver 03_portales_cliente.sql).
-- La gracia del reto es que el LLM aprenda a mapear de esos a estas.
-- =====================================================================
