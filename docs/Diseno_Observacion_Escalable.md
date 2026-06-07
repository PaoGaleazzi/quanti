# Diseño: Observación Escalable (Grabador de Acciones)
### Always on Shelf · Pao
### La pieza que hace el sistema escalable a CUALQUIER portal, sin instrucciones

---

## 1. El problema que resuelve

No podemos decirle al sistema de antemano:
- cuántas pantallas tiene el portal
- qué campos existen
- en qué orden se llenan

Porque si lo hiciéramos, no sería escalable: cada portal nuevo necesitaría configuración.
**La solución: no asumir NADA. Grabar lo que la persona hace, en orden, y que la
estructura emerja de ahí.**

---

## 2. El concepto: grabar acciones, no estados

Durante el modo "aprender", inyectamos un listener en el navegador que escucha
cada acción de la persona y construye una TRAZA (lista ordenada de eventos):

```json
[
  {"orden": 1, "tipo": "input",    "selector": "#user_id",      "valor": "1",            "url": ".../heb_portal.html", "label": "user_id"},
  {"orden": 2, "tipo": "input",    "selector": ".qty",          "valor": "80",           "url": ".../heb_portal.html", "label": "qty"},
  {"orden": 3, "tipo": "click",    "selector": "#btn-continuar", "valor": null,           "url": ".../heb_portal.html", "label": "Continuar a entrega"},
  {"orden": 4, "tipo": "navegacion","selector": null,           "valor": null,           "url": ".../heb_portal.html#entrega", "label": "cambió de pantalla"},
  {"orden": 5, "tipo": "input",    "selector": "#delivery_date", "valor": "2025-06-10",  "url": ".../heb_portal.html", "label": "delivery_date"},
  ...
]
```

> Si el portal es de UNA pantalla (Sanborns), la traza no tiene eventos de navegación.
> Si es de VARIAS (HEB), la traza incluye los clics y cambios de pantalla.
> **El sistema NO decidió cuántas pantallas: lo capturó.**

---

## 3. Por qué esto es escalable sin instrucciones
- El grabador no conoce los campos de antemano → captura cualquiera.
- No sabe cuántas pantallas hay → registra las transiciones que ocurran.
- No sabe qué portal es → funciona con cualquier URL.
- La ESTRUCTURA (pantallas, campos, orden) EMERGE de la traza, no se programa.

Para un portal nuevo: la persona lo llena una vez, el grabador captura la traza,
el LLM la interpreta. Cero código nuevo por portal.

---

## 4. Cómo capturar la traza (dos caminos)

### Camino A — Listener inyectado con Playwright (recomendado)
Con Playwright se inyecta un script JS en la página (`page.expose_function` +
`add_init_script`) que escucha eventos del DOM:
- `input` / `change` en campos → registra qué se escribió y dónde
- `click` en botones/enlaces → registra la acción
- cambios de URL o de pantalla → registra la transición

Cada evento se manda a Python, que lo va guardando en la traza en orden.

### Camino B — Playwright codegen
`playwright codegen <url>` graba las acciones del usuario y genera un script.
Más rápido de montar, pero menos control sobre el formato de la traza.
Útil como prototipo, pero el Camino A da una traza más limpia para el LLM.

**Recomendación:** Camino A. Da una traza estructurada y controlada que el LLM
interpreta bien.

---

## 5. De la traza al mapa (el LLM)

Una vez capturada la traza de AMBOS portales (origen y destino), se la damos al LLM:

```
[TAREA] Te doy la secuencia de acciones que un usuario hizo para pasar un pedido
del portal ORIGEN al portal DESTINO (Arca, fijo). Infiere:
  - navigation_flow: la secuencia de pantallas/pasos (cuántas pantallas, en qué orden)
  - field_mappings: qué dato del origen alimentó cada campo del destino, con transformación
  - confianza y razonamiento por campo

[TRAZA ORIGEN] {traza del portal cliente}
[TRAZA DESTINO] {traza del portal Arca}

Devuelve el mapa_json (estructura conocida).
```

El LLM ve la secuencia completa y deduce solo si fue una o varias pantallas
(por los eventos de navegación en la traza). Eso llena el `navigation_flow`
que ya tenemos en el JSON.

---

## 6. Cómo encaja con lo que ya existe
- **Reemplaza** la captura estática (los dicts) por la traza de acciones.
- **El cerebro (cerebro_aprender.py)** casi no cambia: solo que ahora recibe trazas
  en vez de dicts, y el prompt le pide inferir también el navigation_flow.
- **La fase ejecutar** ya está lista para usar navigation_flow (lo diseñamos así).

---

## 7. Prompt para Claude Code

```
Lee CLAUDE.md, docs/Diseno_Observacion_Escalable.md, docs/Mapa_Aprendido_JSON.md 
y motor/cerebro_aprender.py.

Quiero rediseñar la fase de OBSERVACIÓN para que sea escalable a cualquier portal 
sin instrucciones previas. En vez de leer el estado final, debe GRABAR la secuencia 
de acciones que la persona hace.

Construye motor/grabar_acciones.py que:
1. Abra un portal con Playwright (headless=False).
2. Inyecte un listener JS que capture, EN ORDEN, cada acción de la persona:
   - input/change en campos (qué selector, qué valor)
   - click en botones/enlaces (qué selector)
   - cambios de pantalla/URL (transiciones)
   Usa page.expose_function + add_init_script para mandar cada evento a Python.
3. La persona llena el portal a mano; cuando termina, presiona un botón "Listo" 
   (o cierra) y se cierra la grabación.
4. Devuelva la TRAZA: lista ordenada de eventos (orden, tipo, selector, valor, url, label).

Requisitos clave:
- El grabador NO debe asumir cuántas pantallas hay, qué campos existen, ni qué portal es. 
  Debe funcionar igual para una pantalla (Sanborns) o varias (HEB) sin cambiar código.
- Pruébalo PRIMERO con Sanborns (una pantalla) y LUEGO con HEB (multi-pantalla), 
  mostrándome las dos trazas para confirmar que captura las transiciones de HEB.
- Código simple y comentado. Explícame cómo funciona el listener.
- No toques .env ni hagas commits.

Cuando funcione, lo siguiente (NO ahora) será: capturar traza de origen Y destino, 
y pasarlas al cerebro para que infiera navigation_flow + field_mappings.
```

---

## 8. Nota honesta de alcance
Grabar acciones en vivo es más complejo que leer el estado final. Es lo correcto
para escalabilidad real, PERO si en el hackathon se complica demasiado, hay un
fallback aceptable: para flujos de UNA pantalla, leer el estado final basta; el
grabador de acciones se vuelve indispensable solo para multi-pantalla. Prioriza
que funcione en Sanborns (simple) antes de pelear con HEB (multi).
