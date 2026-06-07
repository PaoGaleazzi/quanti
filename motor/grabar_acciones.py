"""
Grabador de Acciones — Always on Shelf · Pao
============================================

Esta es la fase de OBSERVACIÓN rediseñada para ser ESCALABLE a cualquier
portal SIN instrucciones previas.

La idea (ver docs/Diseno_Observacion_Escalable.md):
  No leemos el estado FINAL del formulario (eso obligaría a saber de antemano
  qué campos hay y cuántas pantallas). En vez de eso GRABAMOS, en orden, cada
  ACCIÓN que la persona realiza mientras llena el portal a mano. La estructura
  (campos, pantallas, transiciones) EMERGE de esa traza; no se programa.

Cómo lo logra (Camino A del diseño):
  - page.expose_function(...)  -> crea una función de Python visible desde el
    navegador (window.__grab_evento). Cada vez que el JS la llama, el evento
    llega a Python y se agrega a la traza, en orden.
  - page.add_init_script(...)  -> inyecta JS que corre en CADA página ANTES de
    que carguen los scripts del portal. Ese JS instala los "escuchas"
    (listeners) del DOM y, cuando ocurre algo, llama a window.__grab_evento.

Qué captura el listener (todo genérico, nada específico de un portal):
  - "input"      -> la persona escribió/cambió un campo (selector + valor)
  - "click"      -> la persona hizo clic en un botón/enlace (selector + texto)
  - "navegacion" -> cambió de pantalla. Dos formas, ambas genéricas:
        a) cambió la URL/hash (portales multipágina clásicos)
        b) un contenedor antes oculto se volvió VISIBLE (portales de una sola
           página que muestran/ocultan "pantallas" con CSS, como HEB)

La traza resultante es una lista ordenada de dicts:
    {orden, tipo, selector, valor, url, label}

Uso por una persona (modo real):
    # 1) servir los portales:  python -m http.server 3000 -d fronts
    # 2) grabar:
    uv run python motor/grabar_acciones.py sanborns
    uv run python motor/grabar_acciones.py heb
  Se abre el navegador, la persona llena el portal y al terminar hace clic en
  el botón flotante "✅ Listo" (arriba a la derecha) o cierra la ventana.

NOTA: este archivo NO toca el .env, ni la base de datos, ni el LLM. Solo graba.
El siguiente paso (otro día) será pasar las trazas al cerebro.
"""

import sys
import json

from playwright.sync_api import sync_playwright


# Portales servidos como archivos estáticos en localhost:3000 (carpeta fronts).
# Mismo patrón que leer_portal_*.py: hay que correr antes
#     python -m http.server 3000 -d fronts
PORTALES = {
    "sanborns": "http://localhost:3000/sanborns_portal.html",
    "heb": "http://localhost:3000/heb_portal.html",
}


# ---------------------------------------------------------------------------
# EL LISTENER (JavaScript que se inyecta en la página)
# ---------------------------------------------------------------------------
# Se inyecta con add_init_script, así corre ANTES de los scripts del portal.
# Todo lo que detecta lo manda a Python con window.__grab_evento({...}).
#
# Es 100% genérico: no menciona ningún id, clase ni portal concreto. Por eso
# funciona igual con Sanborns (1 pantalla) que con HEB (3 pantallas) sin tocar
# una sola línea.
LISTENER_JS = r"""
() => {
  // Evita instalarse dos veces si el script corre varias veces.
  if (window.__grabInstalado) return;
  window.__grabInstalado = true;

  // --- Utilidad: construir un selector CSS único para un elemento ----------
  // Si tiene id, basta con #id. Si no, subimos por el árbol armando una ruta
  // (tag + :nth-of-type para desambiguar hermanos) hasta encontrar un id o el
  // body. Así el selector identifica al elemento aunque no tenga id.
  function rutaCss(el) {
    if (!el || el.nodeType !== 1) return null;
    const partes = [];
    while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== 'body') {
      if (el.id) { partes.unshift('#' + CSS.escape(el.id)); break; }
      let s = el.tagName.toLowerCase();
      const padre = el.parentElement;
      if (padre) {
        const hermanos = [...padre.children].filter(c => c.tagName === el.tagName);
        if (hermanos.length > 1) s += ':nth-of-type(' + (hermanos.indexOf(el) + 1) + ')';
      }
      partes.unshift(s);
      el = el.parentElement;
    }
    return partes.join(' > ');
  }

  // --- Utilidad: encontrar una "etiqueta" legible para un campo ------------
  // Intenta, en orden: <label for=id>, label que lo envuelve, label justo
  // antes, placeholder, name, id o clase. Da un nombre humano al campo sin
  // saber nada del portal.
  function etiquetaDe(el) {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return l.textContent.trim();
    }
    const env = el.closest('label');
    if (env) return env.textContent.trim();
    const prev = el.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') return prev.textContent.trim();
    // Si el campo está en una celda de tabla, usar el encabezado <th> de su
    // columna (genérico para cualquier portal con tablas, como HEB o Arca).
    const td = el.closest('td');
    if (td && td.parentElement) {
      const idx = [...td.parentElement.children].indexOf(td);
      const tabla = el.closest('table');
      const ths = tabla ? tabla.querySelectorAll('thead th') : [];
      if (ths[idx]) return ths[idx].textContent.trim();
    }
    return (el.getAttribute('placeholder') || el.getAttribute('name')
            || el.id || el.className || el.tagName.toLowerCase()).trim();
  }

  // --- Utilidad: ¿el elemento está visible en pantalla? --------------------
  function esVisible(el) {
    if (!el || el.nodeType !== 1) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetParent !== null;
  }

  // --- Utilidad: ¿es un "contenedor de sección/pantalla"? ------------------
  // Un bloque (div/section/form/...) que contiene campos o un encabezado.
  // Usamos esto para detectar cuándo aparece una nueva "pantalla".
  function esSeccion(el) {
    if (!el || el.nodeType !== 1) return false;
    const tag = el.tagName.toLowerCase();
    if (!['div', 'section', 'form', 'fieldset', 'main', 'article'].includes(tag)) return false;
    if (el.id === '__grab_barra') return false;  // ignorar nuestra propia UI
    return el.querySelector('input,select,textarea,h1,h2,h3,h4,h5,h6,button') !== null;
  }

  // Mandar un evento a Python (no esperamos la respuesta: fire-and-forget).
  function enviar(ev) {
    try { window.__grab_evento(ev); } catch (e) { /* binding aún no listo */ }
  }

  // =========================================================================
  // SNAPSHOT: estado FINAL de todos los campos visibles (incl. autocompletados)
  // =========================================================================
  // Los campos que el portal rellena solo (ej. nombre/presentación a partir del
  // SKU) se setean con el.value=... por JS y NO disparan eventos de usuario, así
  // que la traza por eventos no los ve. Para capturarlos LEEMOS el DOM: cada
  // tanto (y en momentos clave) recorremos los campos VISIBLES y guardamos su
  // valor actual. Como acumulamos por selector, en multipantalla cada pantalla
  // queda registrada mientras estuvo visible (no solo la última).
  window.__grabSnapshot = new Map();   // selector -> {selector, label, valor, tipo}

  function valorCampo(el) {
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? (el.value || 'on') : '';
    return el.value;
  }

  // Identificador LIMPIO del campo. Prefiere data-field (portales nuevos lo usan
  // con el nombre canónico, ej. "client_id") y si no, id/name/primera clase
  // (dummies). Así el mapa aprendido usa el mejor nombre disponible.
  function campoDe(el) {
    return el.getAttribute('data-field') || el.id || el.getAttribute('name')
           || (el.className || '').trim().split(/\s+/)[0] || '';
  }

  // OJO: a propósito NO capturamos el TEXTO visible de la opción de un <select>.
  // valorCampo(el) ya devuelve el VALUE de la opción (ej. "9"), que es lo que la
  // base espera. Incluir el texto ("9 — Sanborns San Ángel") en el snapshot solo
  // confundía al LLM (inventaba transformaciones como 'split' para "extraer el
  // nombre"). Manteniéndonos en el value, observar y ejecutar usan el mismo dato.

  // Atributos data-* del elemento como objeto (ej. {art:'Coca-Cola 600ml'}).
  // Sirve para recuperar el dato asociado a campos sin etiqueta (tablas dinámicas).
  function datosDe(el) {
    const d = {};
    for (const k in el.dataset) d[k] = el.dataset[k];
    return Object.keys(d).length ? d : null;
  }

  // Expone cada atributo data-* (SALVO data-field, que es marcador de nombre de
  // campo) como un campo propio del snapshot. Así un dato guardado en un atributo
  // (ej. data-art="Coca-Cola 600ml" en la fila) se vuelve un campo "art" que el
  // cerebro puede mapear (producto_nombre <- art). Deduplica por clave+valor
  // (la misma fila repite data-art en varios inputs).
  function emitirDatos(el) {
    for (const k in el.dataset) {
      if (k === 'field') continue;                 // data-field NO es un dato
      const v = el.dataset[k];
      if (v == null || v === '') continue;
      window.__grabSnapshot.set('attr:' + k + '=' + v, {
        campo: k, selector: 'attr:' + k, label: k, valor: String(v), tipo: 'atributo',
      });
    }
  }

  // Recorre los campos visibles AHORA y los vuelca al acumulador (último gana).
  window.__grabCapturar = function () {
    // (a) Campos de formulario: input / select / textarea.
    document.querySelectorAll('input, select, textarea').forEach(el => {
      if (el.id && el.id.indexOf('__grab') === 0) return;   // ignorar nuestra propia UI
      if (!esVisible(el)) return;                            // solo lo visible en este momento
      const sel = rutaCss(el);
      const dato = {
        campo: campoDe(el),
        selector: sel,
        label: etiquetaDe(el),
        valor: String(valorCampo(el)),
        tipo: el.tagName.toLowerCase(),
      };
      const datos = datosDe(el);         // data-* asociados (ej. data-art = nombre)
      if (datos) dato.datos = datos;
      window.__grabSnapshot.set(sel, dato);
      emitirDatos(el);                   // y los data-* como campos propios
    });

    // (b) Datos que NO son inputs pero están marcados con data-field/data-art
    //     (ej. el nombre de un producto en una tarjeta/celda). Leemos su TEXTO.
    document.querySelectorAll('[data-field], [data-art]').forEach(el => {
      const tag = el.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return; // ya en (a)
      if (!esVisible(el)) return;
      const sel = rutaCss(el);
      window.__grabSnapshot.set(sel, {
        campo: el.getAttribute('data-field') || el.getAttribute('data-art') || campoDe(el),
        selector: sel,
        label: etiquetaDe(el),
        valor: (el.textContent || '').trim(),
        tipo: 'texto',
      });
      emitirDatos(el);
    });
  };

  // =========================================================================
  // 1) CAMPOS: cuando la persona escribe/cambia un campo
  // =========================================================================
  // Escuchamos en 'document' en fase de captura (true) para oír CUALQUIER
  // campo, exista o no al inicio. Para una traza limpia (un evento por campo,
  // con el valor FINAL) no emitimos en cada tecla: en 'input' guardamos el
  // valor pendiente del campo, y lo emitimos una sola vez cuando la persona
  // SALE del campo ('change' o 'focusout', p.ej. al pasar al siguiente campo
  // o al hacer clic en un botón).
  const esCampo = (el) => el && ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName);
  const pendientes = new Map();  // elemento -> último valor escrito

  document.addEventListener('input', (e) => {
    if (esCampo(e.target)) pendientes.set(e.target, String(e.target.value));
  }, true);

  function emitirCampo(el) {
    if (!pendientes.has(el)) return;           // no se tocó: nada que emitir
    const valor = pendientes.get(el);
    pendientes.delete(el);
    enviar({ tipo: 'input', selector: rutaCss(el), valor,
             url: location.href, label: etiquetaDe(el) });
  }
  document.addEventListener('change',   (e) => { if (esCampo(e.target)) emitirCampo(e.target); window.__grabCapturar(); }, true);
  document.addEventListener('focusout', (e) => { if (esCampo(e.target)) emitirCampo(e.target); window.__grabCapturar(); }, true);

  // =========================================================================
  // 2) CLICS: botones, enlaces o cualquier elemento clickeable
  // =========================================================================
  document.addEventListener('click', (e) => {
    // Buscamos el botón/enlace más cercano al punto del clic.
    // Capturamos el estado de la pantalla ANTES de que el clic la cambie/oculte.
    // (Estamos en fase de captura, corremos antes del onclick del portal.)
    window.__grabCapturar();
    // Buscamos el elemento "clickeable" más cercano: un botón/enlace, o una
    // tarjeta/ítem marcado con data-*. Si no, el elemento clicado tal cual.
    const el = e.target.closest('button, a, [role=button], input[type=submit], '
               + 'input[type=button], [data-art], [data-field]')
               || e.target;
    if (el.id === '__grab_btn') return;  // ignorar nuestro botón "Listo"
    enviar({
      tipo: 'click',
      selector: rutaCss(el),
      valor: null,
      url: location.href,
      label: (el.textContent || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80),
      datos: datosDe(el),   // data-* del elemento (ej. data-art = producto elegido)
    });
  }, true);

  // =========================================================================
  // 3) NAVEGACIÓN (a): cambió la URL o el hash (multipágina clásico)
  // =========================================================================
  function navUrl() {
    enviar({ tipo: 'navegacion', selector: null, valor: null,
             url: location.href, label: 'cambió la URL' });
  }
  window.addEventListener('hashchange', navUrl);
  window.addEventListener('popstate', navUrl);

  // =========================================================================
  // 4) NAVEGACIÓN (b): una "pantalla" oculta se vuelve VISIBLE (SPA / HEB)
  // =========================================================================
  // Muchos portales no cambian la URL: solo muestran/ocultan divs con CSS.
  // Para captar esa transición observamos cambios de atributos (class/style) y
  // del árbol; cuando un contenedor de sección que estaba oculto pasa a
  // visible, lo registramos como 'navegacion'. Guardamos las secciones ya
  // visibles para NO contar la pantalla inicial como transición.
  let seccionesVisibles = new Set();

  function seccionesActuales() {
    const set = new Set();
    document.querySelectorAll('div,section,form,fieldset,main,article').forEach(el => {
      if (esSeccion(el) && esVisible(el)) set.add(el);
    });
    return set;
  }

  function revisarPantallas() {
    const ahora = seccionesActuales();
    // Recién visibles = están ahora pero no estaban antes.
    let nuevas = [...ahora].filter(el => !seccionesVisibles.has(el));
    // Si una nueva está DENTRO de otra nueva, nos quedamos solo con la externa
    // (evita duplicar la misma transición por contenedores anidados).
    nuevas = nuevas.filter(el => !nuevas.some(otro => otro !== el && otro.contains(el)));
    for (const el of nuevas) {
      const h = el.querySelector('h1,h2,h3,h4,h5,h6');
      enviar({
        tipo: 'navegacion',
        selector: rutaCss(el),
        valor: null,
        url: location.href,
        label: (h ? h.textContent.trim() : (el.id || 'nueva pantalla')),
      });
    }
    seccionesVisibles = ahora;
    window.__grabCapturar();  // registrar los campos de la pantalla recién visible
  }

  // Arranque: cuando el DOM esté listo, sembramos las secciones visibles
  // iniciales (la pantalla de inicio NO cuenta como transición) e instalamos
  // el observador y el botón "Listo".
  function arrancar() {
    seccionesVisibles = seccionesActuales();

    const obs = new MutationObserver(() => revisarPantallas());
    obs.observe(document.body, {
      attributes: true, attributeFilter: ['class', 'style', 'hidden'],
      childList: true, subtree: true,
    });

    // Captura inicial + un escaneo periódico de respaldo. El intervalo es lo que
    // atrapa los autocompletados que el portal hace sin disparar ningún evento.
    window.__grabCapturar();
    setInterval(window.__grabCapturar, 500);

    // Botón flotante "Listo" para que la persona cierre la grabación.
    const barra = document.createElement('div');
    barra.id = '__grab_barra';
    barra.style.cssText = 'position:fixed;top:10px;right:10px;z-index:2147483647;';
    const btn = document.createElement('button');
    btn.id = '__grab_btn';
    btn.textContent = '✅ Listo (terminar grabación)';
    btn.style.cssText = 'background:#111;color:#fff;border:none;padding:10px 14px;' +
                        'border-radius:8px;cursor:pointer;font:14px sans-serif;' +
                        'box-shadow:0 2px 8px rgba(0,0,0,.3);';
    btn.onclick = () => { try { window.__grab_terminar(); } catch (e) {} btn.textContent = 'Grabación terminada'; };
    barra.appendChild(btn);
    document.body.appendChild(barra);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arrancar);
  } else {
    arrancar();
  }
}
"""


def instalar_grabador(page):
    """
    Conecta el listener JS con Python en una página de Playwright.

    Devuelve (traza, estado):
      - traza: lista donde se van agregando los eventos EN ORDEN.
      - estado: dict con la bandera 'terminado' (la pone el botón "Listo").

    Debe llamarse ANTES de page.goto(...) para que el init script alcance a
    instalarse en la carga de la página.
    """
    traza = []
    estado = {"terminado": False}

    # Función Python visible desde el navegador. El JS la llama por cada acción.
    def _registrar(ev):
        ev["orden"] = len(traza) + 1
        traza.append(ev)

    def _terminar():
        estado["terminado"] = True

    page.expose_function("__grab_evento", _registrar)
    page.expose_function("__grab_terminar", _terminar)
    # add_init_script corre en cada documento ANTES de los scripts del portal.
    # LISTENER_JS es una flecha () => {...}; la envolvemos en (...)() para que
    # se EJECUTE (add_init_script corre la string tal cual, no la invoca sola).
    page.add_init_script("(" + LISTENER_JS + ")()")

    return traza, estado


def leer_snapshot(page):
    """
    Lee el SNAPSHOT acumulado en el navegador: el estado final de todos los
    campos visibles que se vieron durante la observación (incl. autocompletados).
    Hace una última captura por si quedó algo de la pantalla actual.
    """
    return page.evaluate(
        "() => { window.__grabCapturar(); return Array.from(window.__grabSnapshot.values()); }"
    )


def grabar_acciones(url, headless=False):
    """
    Abre `url`, deja que la persona llene el portal a mano y graba la observación.

    Termina cuando la persona hace clic en "✅ Listo" o cierra la ventana.
    Devuelve un dict con DOS partes:
      - "traza":    lista ordenada de acciones (input/click/navegación).
      - "snapshot": estado final de todos los campos visibles (incl. autocompletados).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        traza, estado = instalar_grabador(page)
        page.goto(url)

        print("Grabando... llena el portal y haz clic en '✅ Listo' "
              "(o cierra la ventana) para terminar.")
        # Esperamos a que la persona termine: o pulsa "Listo", o cierra.
        while not estado["terminado"] and not page.is_closed():
            page.wait_for_timeout(200)

        # Si la ventana sigue abierta (pulsó "Listo"), leemos el snapshot final.
        snapshot = leer_snapshot(page) if not page.is_closed() else []

        if not page.is_closed():
            browser.close()

    return {"traza": traza, "snapshot": snapshot}


if __name__ == "__main__":
    # Uso: uv run python motor/grabar_acciones.py [sanborns|heb|<url>]
    arg = sys.argv[1] if len(sys.argv) > 1 else "sanborns"
    url = PORTALES.get(arg, arg)  # acepta un alias conocido o una URL directa

    print(f"Abriendo: {url}")
    observacion = grabar_acciones(url)

    print("\n=== TRAZA DE ACCIONES ===")
    print(json.dumps(observacion["traza"], indent=2, ensure_ascii=False))
    print("\n=== SNAPSHOT FINAL (todos los campos, incl. autocompletados) ===")
    print(json.dumps(observacion["snapshot"], indent=2, ensure_ascii=False))
