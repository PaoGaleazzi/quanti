# Always on Shelf

Solución de inteligencia artificial para el reto "Always on Shelf" de Arca Continental.

El sistema observa **una sola vez** a una persona capturar un pedido en el portal de un cliente del canal moderno (HEB, Sanborns) y replicarlo en el portal interno de Arca. A partir de esa observación aprende la equivalencia entre ambos portales y, de ahí en adelante, ejecuta el proceso de forma autónoma con pedidos nuevos.

Equipo: Fer, Xime, Steff y Pao.

## El problema

En el canal moderno, cada pedido se captura dos veces: primero en el portal del cliente (HEB, Sanborns, etc.) y después, manualmente, en el sistema interno de Arca. Es trabajo repetido, lento y propenso a errores de transcripción. Además, cada cliente tiene su propio portal, con nombres de campo, estructura y unidades distintas, por lo que automatizarlo "a mano" implicaría programar y mantener una integración por cada cliente.

## La propuesta

Un conector que aprende por observación, sin reglas de mapeo escritas a mano. El portal de destino (Arca) es fijo y conocido; los portales de origen (los clientes) cambian y son distintos entre sí, así que su correspondencia se **infiere** en lugar de programarse.

El flujo tiene tres etapas:

1. **Observar.** Una persona llena un pedido en el portal del cliente y el mismo pedido en el portal de Arca, una sola vez. El sistema registra la traza de acciones y el estado final de ambos formularios.
2. **Aprender.** A partir de esas dos observaciones, un modelo de lenguaje infiere el mapa de campos entre el portal de origen y el de Arca (por ejemplo, que `user_id` o `client_id` del cliente corresponde a `client_id` en Arca, o que el cliente pide en cajas y Arca registra en piezas). El mapa se guarda y queda asociado a ese cliente.
3. **Ejecutar.** Con un pedido nuevo, el sistema recorre el portal del cliente, lee los datos, aplica el mapa aprendido y registra el pedido en Arca. Esta etapa no vuelve a llamar al modelo de lenguaje: solo aplica el mapa, por lo que cada pedido es rápido y de costo marginal nulo.

Un principio de diseño guía todo el proyecto: **el mapeo entre portales nunca está programado**. Lo único fijo es la estructura del destino (Arca), que sí se conoce de antemano. La correspondencia entre el portal del cliente y Arca siempre proviene del mapa que infiere el modelo durante el aprendizaje.

## Cómo le ayuda a Arca

- **Elimina la doble captura.** El pedido se llena una vez en el portal del cliente y llega solo al sistema de Arca.
- **Escala sin desarrollo por cliente.** Incorporar un portal nuevo no requiere programar una integración: basta con observarlo una vez. Esto reduce el costo y el tiempo de incorporación frente a una integración tradicional tipo EDI.
- **Reduce errores de transcripción** y normaliza diferencias de formato y de unidades (cajas a piezas, nombres con o sin espacios, etc.).
- **Genera información de negocio.** Al concentrar los pedidos en una base común, habilita métricas de confiabilidad del llenado, autocompletado y borradores predictivos, alertas de riesgo por cliente y notificaciones operativas.

## Arquitectura

El núcleo del aprendizaje y la ejecución vive en `motor/`:

| Componente | Responsabilidad |
| --- | --- |
| `grabar_acciones.py` | Captura la observación de un portal: traza de acciones y estado final de los campos. |
| `cerebro_aprender.py` | Llama al modelo de lenguaje (Google Gemini) para inferir el mapa de campos. |
| `aprender_flujo.py` | Orquesta el aprendizaje: observa origen y destino, infiere el mapa y lo guarda. |
| `ejecutar.py` | Aplica el mapa a un pedido nuevo, resuelve productos contra el catálogo y registra el pedido. |
| `resolver_producto.py` | Traduce el nombre de producto del cliente al del catálogo de Arca (coincidencia por formato y, si hace falta, por significado vía modelo de lenguaje, con caché). |
| `leer_portal_guiado.py` | Lee un portal de una o varias pantallas siguiendo el flujo aprendido. |
| `app.py` | Interfaz web (Streamlit) que opera el ciclo completo con botones, sin terminal. |
| `demo.py` | Versión por terminal del mismo ciclo; se conserva como respaldo. |

Hay dos "mundos" de datos. El **origen** son los portales de cliente, con estructuras y nombres distintos. El **destino** es el sistema interno de Arca, con un esquema fijo (clientes, pedidos, detalle de pedido y catálogo de productos). El modelo aprende a traducir del primero al segundo.

## Requisitos

- Python 3.12 o superior.
- [uv](https://docs.astral.sh/uv/) para gestionar el entorno y las dependencias.
- Credenciales de la base de datos (PostgreSQL en Supabase) y una API key de Google Gemini. Ambas se solicitan al equipo; no se incluyen en el repositorio.

## Instalación

1. Clonar el repositorio y entrar al directorio del proyecto:

   ```bash
   git clone <url-del-repositorio>
   cd quanti
   ```

2. Instalar las dependencias con uv (lee `pyproject.toml` y `uv.lock`):

   ```bash
   uv sync
   ```

3. Instalar el navegador que usa Playwright para automatizar los portales:

   ```bash
   uv run playwright install chromium
   ```

4. Crear el archivo de configuración a partir de la plantilla y completarlo:

   ```bash
   cp .env.example .env
   ```

   Editar `.env` con las credenciales reales (ver la siguiente sección).

## Configuración

Las variables de entorno se definen en `.env`, a partir de `.env.example`. El archivo `.env` no se versiona (está en `.gitignore`) y no debe compartirse en canales públicos ni incluirse en el código.

| Variable | Descripción |
| --- | --- |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Conexión a la base de datos. |
| `GEMINI_API_KEY` | API key de Google Gemini; solo se usa en la fase de aprendizaje. |
| `TWILIO_*` | Credenciales de Twilio para las alertas por WhatsApp (opcional). |

### Base de datos

La base de datos es **privada**. Corre en Supabase y es compartida por el equipo, de modo que el esquema y los datos ya están disponibles para quien tenga las credenciales. No se publican el host ni las credenciales en este repositorio; se entregan de forma directa a cada integrante.

El esquema está documentado en `db/01_esquema.sql` y `db/03_portales_cliente.sql`. Los datos de prueba se generan con `db/02_seed_datos.py`. Ese script reinicia las tablas, por lo que **lo ejecuta una sola persona** cuando es necesario regenerar los datos; el resto del equipo no necesita correrlo.

## Ejecución

La aplicación se opera desde una interfaz web hecha en Streamlit (`motor/app.py`), que envuelve el ciclo completo en botones para que un asesor pueda usarla sin terminal. Hacen falta dos procesos: un servidor estático que sirva los portales y la app de Streamlit.

1. Servir los portales (en una terminal):

   ```bash
   python -m http.server 3000 -d fronts
   ```

2. Levantar la interfaz (en otra terminal):

   ```bash
   uv run streamlit run motor/app.py
   ```

   Streamlit abre la app en el navegador (por defecto en `http://localhost:8501`).

Desde la interfaz, el asesor escribe el ID del cliente (los IDs 2, 5 y 9 son tiendas Sanborns; cualquier otro es HEB; el portal correspondiente se deduce solo) y usa los botones del flujo:

- **Iniciar observación (aprender):** abre el portal del cliente y el de Arca para llenarlos una vez; al terminar, el sistema infiere y guarda el mapa.
- **Ejecutar (llenar Arca):** con un pedido nuevo, el sistema lee el portal del cliente y registra el pedido en Arca de forma autónoma.
- **Desaprender:** borra el mapa de un cliente para empezar desde cero.

El llenado manual de cada portal ocurre en la ventana del navegador que abre la automatización; al terminar se confirma con el botón "Listo" que aparece en esa ventana. El mismo flujo sirve para un portal de una pantalla (Sanborns) o de varias (HEB), sin lógica específica por cliente.

> El script de terminal `motor/demo.py` sigue disponible como respaldo del mismo flujo, pero la forma habitual de operarlo es la interfaz de Streamlit.

## Estructura del repositorio

```
.
├── README.md
├── pyproject.toml / uv.lock     Dependencias y entorno (uv)
├── .env.example                 Plantilla de variables de entorno
├── motor/                       Aprendizaje, resolución y ejecución
├── fronts/                      Portales de cliente y de Arca (HTML)
├── db/                          Esquema SQL y generador de datos
└── docs/                        Diagramas de arquitectura y anexo técnico
```
