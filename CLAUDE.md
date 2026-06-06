# CLAUDE.md — Contexto del proyecto para Claude Code

## Qué es este proyecto
Reto "Always on Shelf" de Arca Continental. Construimos una solución de IA que:
1. **Observa** una vez a un usuario llenar un pedido en el portal de un cliente (HEB, Sanborns) y replicarlo en el portal de Arca.
2. **Aprende** el mapeo de campos entre ambos portales SIN reglas hardcodeadas (lo infiere un LLM).
3. **Ejecuta** sola el proceso con datos nuevos.

Más capas: % de confiabilidad del llenado, predictivo (autocompletado/borradores), insights de negocio para Arca, notificaciones por WhatsApp, y (a futuro) visión computacional para pedidos en foto.

## Regla de oro
**Nada de mapeo hardcodeado.** El portal de Arca es FIJO (puede explicarse en el prompt). Los portales de cliente CAMBIAN y su mapeo se infiere por observación. El jurado revisa el código para verificar que no esté hardcodeado.

## Arquitectura de datos (importante)
Hay DOS mundos:
- **ORIGEN (clientes):** portales con estructura y nombres de campo DISTINTOS (`user_id`, `qty`, `unidades_pedidas`...). Tablas `heb_orders`, `sanborns_pedidos`.
- **DESTINO (Arca):** sistema interno FIJO, nombres fijos (`client_id`, `sku`, `cantidad`...). Tablas `clientes`, `pedidos`, `pedido_detalle`, `productos`.

El LLM debe aprender que `user_id` (HEB) = `client_id` (Sanborns) = `client_id` (Arca), y convertir unidades (Sanborns pide en CAJAS, Arca registra en PIEZAS, usando `productos.piezas_por_caja`).

## Base de datos
- Postgres en Supabase (nube, compartida por el equipo).
- Conexión vía Session pooler (IPv4). Credenciales en `.env` (NO subir).
- Esquema en `db/01_esquema.sql` y `db/03_portales_cliente.sql`.
- Datos simulados en `db/02_seed_datos.py` (semilla fija). Sanborns Centro (client_id=2) decae en el tiempo → señal para el modelo de churn.

## Stack
- Python + uv para entorno.
- psycopg2 para Postgres.
- Browser automation: Playwright (recomendado).
- LLM vía API (OpenRouter / Gemini / Azure OpenAI for Students) — cuidar presupuesto de tokens.

## Reparto del equipo
- **Pao:** motor de aprendizaje (observación → mapeo con LLM → ejecución). CORE.
- **Xime:** frontends (portales HEB/Sanborns/Arca) + variantes con stoppers + apoyo a predictivo.
- **Steff:** % de confiabilidad, dashboard, insights de negocio, modelo predictivo/churn.
- **Fer:** flujo, base de datos, lógica de estados y manejo de errores + apoyo a fronts.

## Convenciones
- El seed (`02_seed_datos.py`) lo corre UNA sola persona (hace truncate, borra todo).
- Para pruebas, cada quien usa sus propios `client_id` de prueba.
- Cambios de estructura → editar `.sql`, correr en Supabase, push del `.sql`.

## Documentación completa
- `docs/Plan_Hackathon_AlwaysOnShelf.md` — plan, checkpoints, rúbrica.
- `docs/Esquema_Base_de_Datos.md` — diagramas ER y diseño detallado.
