"""
Interfaz Streamlit — Always on Shelf · Arca Continental
=======================================================

Envuelve el demo de terminal (motor/demo.py) en botones, para que un asesor de
tienda lo opere sin terminal ni Enters. NO reescribe el motor: solo llama a las
funciones que YA existen.

  - "Iniciar observación (aprender)" -> aprender_flujo(nombre, url_origen, URL_ARCA, True)
  - "Ejecutar (llenar Arca)"         -> ejecutar_desde_portal(nombre, url_origen, esperar_listo=True)
  - "Desaprender"                    -> fase0_desaprender(nombre)

El asesor solo escribe su ID de cliente. Los IDs 2, 5 y 9 son tiendas Sanborns;
cualquier otro es HEB. De ahi se deduce el portal a usar (no se muestran URLs).

El llenado manual del portal sigue pasando en la ventana de Playwright: la
persona llena ahi y hace clic en el boton flotante "Listo" que el motor ya
inyecta. Este Streamlit solo DISPARA la fase y espera con un spinner; cuando la
funcion retorna (= se hizo clic en Listo), pinta el resultado.

Detalle tecnico: la Sync API de Playwright choca con el event-loop de asyncio
de Streamlit. Por eso cada llamada al motor corre en un threading.Thread NUEVO
(sin event-loop) y capturamos stdout/stderr para mostrar en pantalla.

NO toca .env, ni el dashboard, ni demo.py (que sigue sirviendo como respaldo).
"""

import os
import sys
import io
import threading
import contextlib
import traceback

# Los modulos del motor viven en ESTA carpeta. Aseguramos que sean importables
# sin importar desde donde se lance streamlit.
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import streamlit as st

# --- Funciones y constantes del motor (se REUSAN tal cual, no se reescriben) ---
from grabar_acciones import PORTALES          # URLs de los portales de cliente
from aprender_flujo import aprender_flujo, URL_ARCA
from ejecutar import ejecutar_desde_portal
from demo import fase0_desaprender, CLIENTES  # CLIENTES = {"sanborns":"Sanborns","heb":"HEB"}
from arca_logo import LOGO_DATA_URI           # logo de Arca (mismo que los portales)

# Tiendas Sanborns por ID de cliente; cualquier otro ID se atiende como HEB.
IDS_SANBORNS = {2, 5, 9}


def alias_por_id(client_id):
    """Deduce el portal (alias del motor) a partir del ID de cliente."""
    return "sanborns" if client_id in IDS_SANBORNS else "heb"


# ---------------------------------------------------------------------------
# NUCLEO TECNICO: correr el motor en un hilo nuevo (sin event-loop) + capturar
# stdout. Bloquea hasta que la persona da clic en "Listo" en la ventana.
# ---------------------------------------------------------------------------
def correr_en_hilo(fn, *args, **kwargs):
    """
    Ejecuta `fn` (funcion del motor que abre Playwright) en un threading.Thread
    NUEVO, que no tiene event-loop de asyncio: asi la Sync API de Playwright no
    choca con el loop de Streamlit.

    Captura stdout/stderr (los prints del motor) y bloquea hasta que `fn`
    termina —es decir, hasta que la persona hace clic en "Listo" en la ventana.
    Devuelve un dict: {"value", "logs", "error", "trace"}.
    """
    salida = {"value": None, "logs": "", "error": None, "trace": None}

    def worker():
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                salida["value"] = fn(*args, **kwargs)
        except Exception as e:  # lo mostramos en pantalla, no tronamos la app
            salida["error"] = str(e)
            salida["trace"] = traceback.format_exc()
        finally:
            salida["logs"] = buf.getvalue()

    hilo = threading.Thread(target=worker, daemon=True)
    hilo.start()
    hilo.join()  # bloquea el rerun de Streamlit hasta el clic en "Listo"
    return salida


# ---------------------------------------------------------------------------
# ESTETICA ARCA: fondo blanco, logo de marca, rojo #ed1c2e, limpio y profesional.
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Always on Shelf · Arca Continental",
    page_icon=LOGO_DATA_URI,
    layout="centered",
)

st.markdown(
    """
    <style>
      :root{ --arca:#ed1c2e; --arca-deep:#a90f18; --arca-soft:#fdecec; --line:#ececed; --ink:#1d1d1f; }
      /* Fondo blanco en toda la app */
      [data-testid="stAppViewContainer"], [data-testid="stHeader"], .main, body{ background:#ffffff; }
      .block-container{ padding-top:3rem; max-width:920px; }

      /* Inputs siempre claros (respaldo aunque el tema este en oscuro) */
      [data-testid="stNumberInput"] div[data-baseweb="input"]{
        background:#fff; border:1.5px solid var(--line); border-radius:11px; }
      [data-testid="stNumberInput"] input{ background:#fff; color:var(--ink); }
      [data-testid="stNumberInput"] button{ background:#fafafa; color:var(--ink); }
      [data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within{
        border-color:var(--arca); box-shadow:0 0 0 3px var(--arca-soft); }

      /* Barra superior con el logo de Arca */
      .arca-top{
        display:flex; align-items:center; gap:18px; padding:16px 22px; background:#fff;
        border:1px solid var(--line); border-bottom:3px solid var(--arca); border-radius:14px;
        box-shadow:0 4px 18px rgba(0,0,0,.05); margin-bottom:22px;
      }
      .arca-top img{ height:46px; }
      .arca-top .sep{ width:1px; height:34px; background:var(--line); }
      .arca-top .t{ font-weight:800; color:var(--ink); font-size:18px; line-height:1.1; }
      .arca-top .d{ color:#8a8a8a; font-size:12.5px; margin-top:3px; }

      .sec-title{ font-weight:800; color:var(--ink); font-size:15px; letter-spacing:.2px;
                  margin:14px 0 6px; }

      /* Botones primarios en rojo Arca */
      .stButton>button[kind="primary"]{ background:var(--arca); border-color:var(--arca);
        font-weight:700; border-radius:11px; }
      .stButton>button[kind="primary"]:hover{ background:var(--arca-deep); border-color:var(--arca-deep); }
      .stButton>button[kind="secondary"]{ border-radius:11px; font-weight:700; }

      .pill{ display:inline-flex; align-items:center; gap:8px; background:var(--arca-soft);
        color:var(--arca-deep); border:1px solid #f6c9cd; border-radius:999px;
        padding:7px 15px; font-weight:700; font-size:13.5px; }

      .map-card{ border:1px solid var(--line); border-left:4px solid var(--arca); border-radius:10px;
        padding:11px 15px; margin-bottom:9px; background:#fff; }
      .map-card .head{ font-weight:700; color:var(--ink); }
      .map-card .meta{ color:#8a8a8a; font-size:12px; margin:3px 0 5px; }
      .map-card .why{ color:#4a4a4a; font-size:13px; }

      .cv-card{ border:2px dashed #dcdcdc; border-radius:14px; padding:30px; text-align:center;
        color:#9a9a9a; background:#fcfcfc; }
      .cv-card .t{ font-weight:700; color:#7a7a7a; margin-bottom:4px; font-size:15px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="arca-top">
      <img src="{LOGO_DATA_URI}" alt="Arca Continental" />
      <div class="sep"></div>
      <div>
        <div class="t">Always on Shelf</div>
        <div class="d">Observa, aprende y ejecuta tus pedidos en automatico</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 1) IDENTIFICACION: solo el ID de cliente (de ahi se deduce la cadena/portal)
# ---------------------------------------------------------------------------
st.markdown('<div class="sec-title">Identificate</div>', unsafe_allow_html=True)
client_id = st.number_input(
    "ID de cliente",
    min_value=1,
    step=1,
    value=2,
    help="Tu numero de cliente. Con el sabemos a que portal entrar.",
)
client_id = int(client_id)

alias = alias_por_id(client_id)
nombre = CLIENTES[alias]          # nombre con el que se guarda en mapas_aprendidos
url_origen = PORTALES[alias]      # URL del portal (interno, no se muestra al asesor)

st.markdown(
    f'<span class="pill">Cliente #{client_id} &nbsp;·&nbsp; {nombre}</span>',
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 2) ACCIONES
# ---------------------------------------------------------------------------
st.markdown('<div class="sec-title">Acciones</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns([1.3, 1.1, 0.9])
with c1:
    btn_aprender = st.button(
        "Iniciar observacion (aprender)", type="primary", use_container_width=True
    )
with c2:
    btn_ejecutar = st.button(
        "Ejecutar (llenar Arca)", type="primary", use_container_width=True
    )
with c3:
    btn_desaprender = st.button(
        "Desaprender", type="secondary", use_container_width=True
    )

st.caption(
    "Se abrira la ventana del portal. Llena el pedido ahi y haz clic en el boton "
    "\"Listo\" dentro de esa ventana; aqui veras el resultado."
)


# --- Disparadores: cada boton corre su funcion del motor en un hilo nuevo -----
if btn_aprender:
    with st.spinner(
        f"Observando {nombre}. Llena el portal del cliente y luego el de Arca en las "
        f"ventanas que se abren, y da clic en \"Listo\" en cada una."
    ):
        res = correr_en_hilo(aprender_flujo, nombre, url_origen, URL_ARCA, True)
    st.session_state["last"] = {"tipo": "aprender", "nombre": nombre, "res": res}

if btn_ejecutar:
    with st.spinner(
        f"Ejecutando {nombre}. Llena un pedido nuevo en la ventana del portal y da "
        f"clic en \"Listo\". El bot leerá, transformará y llenará Arca solo."
    ):
        res = correr_en_hilo(ejecutar_desde_portal, nombre, url_origen, True)
    st.session_state["last"] = {"tipo": "ejecutar", "nombre": nombre, "res": res}

if btn_desaprender:
    with st.spinner(f"Borrando el mapa aprendido de {nombre}."):
        res = correr_en_hilo(fase0_desaprender, nombre)
    st.session_state["last"] = {"tipo": "desaprender", "nombre": nombre, "res": res}


# ---------------------------------------------------------------------------
# 3) RESULTADOS (lo que antes salia en la terminal)
# ---------------------------------------------------------------------------
def _mostrar_logs(res):
    logs = (res.get("logs") or "").strip()
    with st.expander("Detalle del proceso", expanded=False):
        st.code(logs or "(sin mensajes)", language="text")


def _render_mapa(mapa, nombre):
    nav = mapa.get("navigation_flow", []) or []
    pantallas = []
    for paso in nav:
        p = paso.get("pantalla")
        if p and p not in pantallas:
            pantallas.append(p)

    st.success(f"Mapa de '{nombre}' aprendido y guardado.")

    m1, m2, m3 = st.columns(3)
    m1.metric("Pantallas detectadas", len(pantallas))
    m2.metric("Pasos de navegacion", len(nav))
    m3.metric("Confianza global", mapa.get("confianza_global", "—"))

    if pantallas:
        st.write("**Pantallas:** " + " → ".join(str(p) for p in pantallas))

    st.markdown("**Mapeos inferidos** (nadie se los dijo; los dedujo observando):")
    for m in mapa.get("field_mappings", []) or []:
        st.markdown(
            f"""
            <div class="map-card">
              <div class="head"><code>{m.get('campo_origen')}</code> → <code>{m.get('campo_destino')}</code></div>
              <div class="meta">transformacion: <b>{m.get('transformacion')}</b>
                  · confianza: <b>{m.get('confianza')}</b></div>
              <div class="why">{m.get('razonamiento', '')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("Mapa completo (JSON)", expanded=False):
        st.json(mapa)


def _render_ejecucion(res_value, nombre):
    pedido, lecturas, datos, numero_orden, monto_total = res_value

    st.success(
        f"Pedido de '{nombre}' registrado en Arca · "
        f"numero de orden **{numero_orden}** · monto total **{monto_total}**"
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Lo que el bot leyo del cliente**")
        st.json(lecturas)
    with col_b:
        st.markdown("**Lo que el bot escribio en Arca**")
        st.json(datos)

    with st.expander("Pedido armado (antes de transformar)", expanded=False):
        st.json(pedido)


st.markdown('<div class="sec-title">Resultado</div>', unsafe_allow_html=True)
last = st.session_state.get("last")

if not last:
    st.info("Escribe tu ID de cliente y elige una accion para ver aqui el resultado.")
else:
    res = last["res"]
    _mostrar_logs(res)

    if res.get("error"):
        st.error(res["error"])
        with st.expander("Detalle tecnico", expanded=False):
            st.code(res.get("trace") or "", language="text")
    elif last["tipo"] == "aprender":
        if res["value"]:
            _render_mapa(res["value"], last["nombre"])
    elif last["tipo"] == "ejecutar":
        if res["value"]:
            _render_ejecucion(res["value"], last["nombre"])
    elif last["tipo"] == "desaprender":
        st.success(
            f"Mapa de '{last['nombre']}' borrado. "
            f"El sistema quedo sin conocimiento previo de ese portal."
        )


# ---------------------------------------------------------------------------
# 4) PLACEHOLDER — Captura por imagen (proximamente). NO funcional.
# ---------------------------------------------------------------------------
st.divider()
st.markdown('<div class="sec-title">ArcaSync · Captura por imagen</div>', unsafe_allow_html=True)
st.caption("Sube la foto del pedido. Gemini la lee y registra en Arca.")

gemini_key = st.text_input("Gemini API key", type="password", placeholder="AIzaSy...")
archivos = st.file_uploader("Imágenes de pedidos", type=["png","jpg","jpeg"], accept_multiple_files=True)

if archivos and gemini_key and st.button("Leer con Gemini", type="primary"):
    import base64, json, requests as rq
    for f in archivos:
        b64 = base64.b64encode(f.read()).decode()
        r = rq.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}",
            json={"contents":[{"parts":[
                {"text":'Extrae del pedido: fecha_entrega_estimada, y lineas=[{producto_nombre,cantidad,unidad,precio_unitario}]. Solo JSON, sin texto extra.'},
                {"inline_data":{"mime_type":f.type,"data":b64}}
            ]}],"generationConfig":{"responseMimeType":"application/json"}},
            timeout=30
        )
        if r.ok:
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            resultado = json.loads(txt)
            resultado["client_id"] = client_id

            # ── Vista lado a lado (estilo ArcaSync) ──────────────────────
            st.markdown(f"**{f.name}** — leído")
            CAT=[
                {"sku":"SKU-0001","nombre":"Coca-Cola 600ml","ppc":24,"alias":["coca","cola","refresco cola"]},
                {"sku":"SKU-0002","nombre":"Coca-Cola Sin Azucar 600ml","ppc":24,"alias":["zero","sin azucar","light"]},
                {"sku":"SKU-0003","nombre":"Sprite 600ml","ppc":24,"alias":["sprite","lima","limon"]},
                {"sku":"SKU-0004","nombre":"Agua Ciel 1L","ppc":12,"alias":["ciel","agua natural","agua"]},
                {"sku":"SKU-0005","nombre":"Powerade 500ml","ppc":12,"alias":["powerade","mora"]},
                {"sku":"SKU-0006","nombre":"Bokados Mix 60g","ppc":30,"alias":["bokados","botana","snack"]},
                {"sku":"SKU-0007","nombre":"Topo Chico 355ml","ppc":24,"alias":["topo chico","mineral"]},
                {"sku":"SKU-0008","nombre":"Fuze Tea Durazno 600ml","ppc":24,"alias":["fuze","durazno","tea"]},
            ]
            def match_prod(txt):
                t=(txt or "").lower()
                for p in CAT:
                    if any(a in t for a in p["alias"]): return p
                return None

            lineas = resultado.get("lineas", [])
            total = 0; mapeadas = []
            matched = 0
            for l in lineas:
                prod = match_prod(l.get("producto_nombre",""))
                qty = int(l.get("cantidad") or 0)
                unidad = (l.get("unidad","") or "").lower()
                nota = ""
                if prod and ("caja" in unidad or "case" in unidad):
                    nota = f"{qty} {l.get('unidad','')} × {prod['ppc']} = {qty*prod['ppc']} pzas"
                    qty = qty * prod["ppc"]
                precio = float(l.get("precio_unitario") or 0)
                if not precio and prod: precio = 18.0
                total += qty * precio
                if prod: matched += 1
                mapeadas.append({"sku": prod["sku"] if prod else "","nombre_arca": prod["nombre"] if prod else l.get("producto_nombre",""),"cantidad": qty,"precio_unitario": precio,"importe": qty*precio,"nota": nota,"matched": bool(prod)})

            conf = 0.55 + 0.42*(matched/len(lineas)) if lineas else 0

            col_orig, col_dest = st.columns(2)
            with col_orig:
                st.markdown("**Lo que leyó del cliente**")
                st.caption(f"Fecha: {resultado.get('fecha_entrega_estimada','—')}")
                rows_orig = [{"Producto (texto)": l.get("producto_nombre",""), "Cant.": l.get("cantidad",""), "Unidad": l.get("unidad","")} for l in lineas]
                st.dataframe(rows_orig, hide_index=True, use_container_width=True)

            with col_dest:
                st.markdown("**Mapeado a Arca**")
                st.caption(f"client_id: {client_id} · fecha_entrega: {resultado.get('fecha_entrega_estimada','—')}")
                rows_dest = []
                for m in mapeadas:
                    rows_dest.append({"SKU": m["sku"] or "sin match","Producto Arca": m["nombre_arca"],"Cant. (pzas)": m["cantidad"],"Nota conv.": m["nota"]})
                st.dataframe(rows_dest, hide_index=True, use_container_width=True)

            st.progress(conf, text=f"Confiabilidad: {round(conf*100)}%")
            st.divider()

            # Guardar en Supabase
            import datetime, requests as rq2
            def fix_fecha(fstr):
                if not fstr: return str(datetime.date.today()+datetime.timedelta(days=2))
                for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%m/%d/%Y","%d %b %Y","%d/%m/%y"):
                    try: return datetime.datetime.strptime(fstr.strip(),fmt).strftime("%Y-%m-%d")
                    except: pass
                return str(datetime.date.today()+datetime.timedelta(days=2))
            SB_URL="https://tlntymneqeaeezdgiqsq.supabase.co"
            SB_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRsbnR5bW5lcWVhZWV6ZGdpcXNxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA3NzQyOTAsImV4cCI6MjA5NjM1MDI5MH0.9E5BLzaQkokpCMyJonWrey96MQXx5x86qkANNH2d87w"
            SBH={"apikey":SB_KEY,"Authorization":"Bearer "+SB_KEY,"Content-Type":"application/json","Prefer":"return=representation"}
            fecha_ok=fix_fecha(resultado.get("fecha_entrega_estimada",""))
            rped=rq2.post(SB_URL+"/rest/v1/pedidos",headers=SBH,json={"client_id":client_id,"fecha_pedido":str(datetime.date.today()),"fecha_entrega_estimada":fecha_ok,"estatus_entrega":"pendiente","estatus_factura":"no_facturado","monto_total":round(total,2),"confiabilidad_llenado":round(conf*100),"origen_captura":"auto_IA"})
            if rped.ok:
                num=rped.json()[0]["numero_orden"]
                for m in mapeadas:
                    rq2.post(SB_URL+"/rest/v1/pedido_detalle",headers=SBH,json={"numero_orden":num,"sku":m["sku"] or "SKU-0001","producto_nombre":m["nombre_arca"],"cantidad":m["cantidad"],"unidad":"pieza","precio_unitario":m["precio_unitario"],"importe":m["importe"]})
                st.success(f"Guardado en Arca — ORD-{num}")
            else:
                st.error(f"Error BD: {rped.status_code} · {rped.text[:200]}")
        else:
            st.error(f"Error {r.status_code}: {r.text[:120]}")
