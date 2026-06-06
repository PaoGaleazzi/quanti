# Plan de Trabajo — Reto "Always on Shelf" (Arca Continental)
### Equipo: Fer · Xime · Steff · Pao

---

## 1. Qué estamos construyendo (visión compartida)

Una solución de IA que **observa una sola vez** a una persona llenar un pedido en el portal de un cliente del canal moderno (HEB, Soriana, restaurante, etc.) y lo replica en el portal interno de Arca — y de ahí en adelante lo hace **sola**, traduciendo de un portal a otro sin reglas de mapeo programadas.

**El problema real que resolvemos:** hoy el pedido se llena DOS veces (una en el portal del cliente, otra en el de Arca). Queremos que se llene una sola vez.

**Por qué importa para Arca:** el EDI tradicional toma meses y es caro por cada cliente nuevo. Nuestro "EDI de IA" aprende cualquier portal observándolo una vez → **escalable y replicable sin implementación pesada.**

### Las 3 fases (rúbrica oficial)
1. **Conexión** — la solución se conecta al portal origen (cliente) y al destino (Arca).
2. **Observación** — un usuario llena el pedido UNA vez; el sistema aprende qué campo del portal del cliente corresponde a cuál de Arca.
3. **Automatización** — con datos NUEVOS, el sistema ejecuta solo: lee, interpreta, transcribe.

### Criterios de la rúbrica (lo que nos dan puntos)
| Criterio | Cómo lo ganamos |
|---|---|
| Aprendizaje por observación | Mapeo del portal cliente inferido por LLM, NO hardcodeado. Código abierto al jurado. |
| Reproducción autónoma | Demo en vivo con datos nuevos. |
| Exactitud | Campo por campo, sin errores. **Es binario.** |
| Replicabilidad (opcional) | Segundo portal distinto que el bot aprende en vivo. |

---

## 2. Principio transversal: ESCALABILIDAD

> **Un solo sistema, N clientes, sin reimplementar nada.**

Esto NO es un extra — es el corazón del argumento de negocio. El portal de **Arca es fijo y conocido**; los portales de los **clientes cambian** en cada caso. El sistema:
- Conoce el destino (Arca) → eso puede ir explicado en el prompt (no es hardcoding).
- Aprende el origen (cliente) por observación → distinto en cada cliente, se infiere.

**Por eso aprende UNA vez por cliente y queda listo.** Frente al EDI tradicional (meses por cliente), nuestro sistema escala a cualquier portal nuevo observándolo una sola vez. Cada decisión de diseño debe preservar esto: nada que amarre la solución a UN cliente específico.

### Sobre el prompt y el hardcoding (aclaración para el jurado)
El prompt explica **la tarea** (observar, razonar, capturar datos del portal cliente) y **qué buscar en Arca** (destino fijo y conocido). Esto NO es hardcoding, porque NO escribimos el mapeo campo-a-campo del cliente — ese se infiere por observación. Explicar el destino conocido y la tarea es legítimo; programar la correspondencia sería lo prohibido.

---

## 3. Regla de oro del equipo

> **El CORE primero. Las capas "wow" solo cuando el core no falla.**

Orden de prioridad innegociable:
1. 🟥 **CORE** (observación → mapeo → ejecución con datos nuevos, exactitud perfecta).
2. 🟥 **STOPPERS** (robustez ante cambios de UI del cliente) — parte del core y nuestro mejor diferenciador.
3. 🟨 **OBSERVABILIDAD** (% de confiabilidad + tablero) — refuerza la prueba de "no hardcodeado".
4. 🟩 **CAPAS OPCIONALES** (predictivo, insights, WhatsApp, visión, churn) — entran solo si sobra tiempo. Si no se construyen, van en el pitch como "visión de producto".

**Un demo del core perfecto vence a un demo lleno de features que truena en vivo.**

---

## 4. FASE 0 — Lo que hacemos TODAS juntas primero (antes de dividirnos)

⏱️ *Sentadas juntas. No avanzar individual hasta cerrar esto.*

El cimiento. Si no está claro, todo lo demás se construye torcido.

- [ ] **Definir el esquema de datos del pedido** (producto, SKU, cantidad, precio unitario, fecha de entrega, cliente_id, etc.)
- [ ] **Definir el "mapa aprendido"** — el JSON que el LLM produce tras observar. Para cada campo de Arca: de qué campo del cliente viene + qué transformación aplica + nivel de confianza. *(Esta pieza es el cerebro Y la observabilidad a la vez.)*
- [ ] **Definir los 3 portales** con diferencias semánticas DELIBERADAS:
  - Portal Cliente A (super) → "Cantidad", tabla de productos
  - Portal Cliente B (restaurante) → "Unidades pedidas", estructura distinta
  - Portal Arca (destino, FIJO) → "Qty", SKU interno, etc.
- [ ] **Definir la base de datos** — dónde se guardan los pedidos ejecutados (alimenta el predictivo y WhatsApp después).
- [ ] **Acordar el stack** — lenguaje, librería de browser (Playwright recomendado), proveedor de LLM (OpenRouter / Azure OpenAI for Students / Gemini free tier para cuidar tokens).
- [ ] **Definir el guión del demo** (5 pasos oficiales) para saber hacia qué construimos.

📌 **Salida de Fase 0:** documento corto con esquema del pedido, JSON del mapa aprendido, campos de cada portal, diseño de BD. Todas con la misma foto mental.

---

## 5. Reparto individual

### 🧠 PAO — Motor de aprendizaje (CORE) 🟥
*La parte más crítica. Es lo que el jurado evalúa primero.*

**Responsabilidad:** que el bot aprenda el mapeo observando una vez y lo ejecute solo con datos nuevos.

- [ ] **Fase Observación:** capturar lo que el usuario hace en el portal del cliente y en el de Arca (qué dato salió de dónde, dónde se puso).
- [ ] **Inferencia del mapeo con LLM:** dado el ejemplo observado, producir el "mapa aprendido". El LLM resuelve nombres y unidades distintas — sin reglas escritas a mano para el cliente.
- [ ] **Fase Automatización:** con un pedido NUEVO, aplicar el mapa y llenar el portal de Arca solo.
- [ ] **Log de inferencia visible** — para mostrar CÓMO razonó (clave contra la sospecha de hardcoding).
- [ ] **Manejo de STOPPERS** 🟥 (coordinado con Xime/Fer): cuando aparece algo no previsto (pop-up, botón movido, campo nuevo), el bot consulta al LLM "¿esto bloquea mi tarea? ¿qué hago?" en vez de tronar. **Mejor diferenciador — la anécdota de Ecuador.**

⚠️ *Si Pao se atora en browser automation, Xime/Fer la apoyan con Playwright/DOM. El core no es de una sola persona.*

---

### 🎨 XIME — Frontends + apoyo a Fer + apoyo a predictivo 🟥🟩
*Construye el escenario donde todo sucede.*

**Responsabilidad principal:** los 3 portales y sus variantes con stoppers.

- [ ] **Portal Cliente A (super)** — realista, con su estructura de pedido.
- [ ] **Portal Cliente B (restaurante)** — estructura DISTINTA, para probar generalización (replicabilidad).
- [ ] **Portal Arca (destino)** — nombres de campo distintos a los clientes ("Qty", SKU interno).
- [ ] **Variantes con stoppers** 🟥 — botón movido, campo nuevo, pop-up de confirmación inesperado. *(Coordinar con Pao: las necesita para probar robustez.)*
- [ ] **Diferencias semánticas deliberadas** entre portales (Cantidad / Unidades pedidas / Qty).
- [ ] **Apoyo a Fer** en BD y flujo (lo trabajan juntas).
- [ ] **Apoyo a Steff en el modelo de predicción** 🟩 (cuando el core esté estable) — feature engineering, armado del dataset simulado.

---

### 📊 STEFF — Negocio, observabilidad e inteligencia 🟨🟩
*Convierte la automatización en algo que a Arca le importa.*

**Responsabilidad principal (🟨 entra después del core):** el % de confiabilidad y el tablero.

- [ ] **% de confiabilidad del llenado** 🟨 — qué tan seguro está el modelo de que llenó bien cada pedido. **Alertar si baja de un umbral.**
- [ ] **Visualización de evolución del modelo** 🟨 — cómo cambia la confiabilidad en el tiempo.
- [ ] **Dashboard de observabilidad** 🟨 — tabla de campos aprendidos, mapeo visible, estado de procesos. *(También sirve como prueba anti-hardcoding en el demo.)*

**Responsabilidad opcional (🟩 solo si el core ya está blindado, con apoyo de Xime):**
- [ ] **Insights de negocio para Arca** — "este cliente suele pedir X y no lo ha hecho" → warning.
- [ ] **Modelo de predicción** — sobre historial SIMULADO. Predecir patrones de pedido / si un cliente pedirá menos.
- [ ] **Borradores predictivos** — "esto es lo que sueles pedir" pre-llenado (se conecta con WhatsApp).

⚠️ **Nota honesta:** el predictivo/insights dependen de historial simulado. Son legítimos PERO hay que presentarlos con transparencia ("corre sobre datos simulados; en producción se alimenta del historial real"). Un jurado de data scientists lo nota — la honestidad SUMA.

---

### 🔧 FER (mecatrónica) — Flujo, BD y apoyo a fronts 🟥
*Pensamiento de sistemas: percibir → decidir → actuar. Justo el loop de un agente.*

**Responsabilidad:** la lógica del flujo y la base de datos, en dupla con Xime.

- [ ] **Diseño del flujo completo** — pedido entra → se mapea → se llena Arca → se guarda en BD → (factura automática como cierre visual).
- [ ] **Base de datos** — estructura donde se guardan los pedidos ejecutados (alimenta predictivo y WhatsApp).
- [ ] **Lógica de estados y manejo de errores** del agente — su fuerte de mecatrónica. Qué pasa cuando un paso falla, cómo se recupera. *(Conecta con los stoppers de Pao.)*
- [ ] **Apoyo a Xime** en los frontends (HTML/estructura).
- [ ] **Apoyo a Pao** probando el flujo end-to-end.

💡 *Fer: tu valor es entender el flujo como sistema y asegurar que no haya casos sin manejar — eso es exactamente lo que rompe los demos malos.*

---

## 6. Capa de notificaciones — WhatsApp 🟩
*Cierra el loop con el asesor de tienda. Opcional, pero alto valor de pitch.*

El asesor de tienda recibe por WhatsApp:
- [ ] **Confirmación** de que el pedido se realizó.
- [ ] **Fecha de llegada** del pedido (entrega ~2 días después).
- [ ] **Borradores predictivos** — "esto es lo que sueles pedir" para facilitar el siguiente pedido (se conecta con el predictivo de Steff/Xime).

⚠️ **Nota honesta de alcance:** la API de WhatsApp (Business / Twilio) tiene fricción de setup real — verificación, números, plantillas aprobadas — que puede comerse horas. 
**Plan B:** si el setup se complica, simular la notificación con una vista que muestre el mensaje como se vería. Para el demo, una simulación creíble vale casi lo mismo y no arriesga el tiempo del core.

---

## 7. Checkpoints (en lugar de días fijos)

### ✅ Checkpoint 1 — Cimiento cerrado
- Fase 0 completa: esquema, mapa aprendido, portales definidos, BD, stack acordado.
- *Nadie avanza individual hasta aquí.*

### ✅ Checkpoint 2 — Core corriendo end-to-end
- El ciclo CORE funciona: observa → mapea → ejecuta con datos nuevos. Aunque sea feo.
- Portales listos + primera variante de stopper.
- % de confiabilidad básico conectado al motor.
- **🚨 DECISIÓN CRÍTICA:** ¿El core corre sin fallar con datos nuevos?
  - **NO →** todas al core. Se cancelan capas opcionales.
  - **SÍ →** seguimos con capas.

### ✅ Checkpoint 3 — Robustez + replicabilidad
- Stoppers robustos (Pao+Xime+Fer).
- Segundo portal funcionando para demostrar replicabilidad.

### ✅ Checkpoint 4 — Hora de corte de features
- Se deja de agregar. Lo que no esté, va al pitch como visión de producto.
- Empieza el pulido y los ensayos.

### ✅ Checkpoint 5 — Demo listo
- Demo en vivo ensayado VARIAS veces.
- Video de respaldo del ciclo completo grabado.
- Respuesta preparada a "¿cómo demuestran que aprendió y no está hardcodeado?"

---

## 8. El demo (guión oficial — lo ensayamos TODAS)

1. **Proceso manual (2 min):** mostrar los dos portales y llenar el pedido a mano una vez. Que se vea la fricción del doble llenado.
2. **Observación (3 min):** con el bot activo, llenar otra vez mientras observa. Mostrar en vivo cómo registra el mapeo (log / dashboard).
3. **Automatización con datos NUEVOS (3 min):** activar modo autónomo con datos distintos. El bot lo hace solo. **Momento clave.**
4. **Validar exactitud (2 min):** comparar origen vs destino campo por campo. Sin errores.
5. **Replicabilidad (2 min, diferenciador):** cambiar al segundo portal en vivo y mostrar que aprende el nuevo mapeo sin tocar código.

**La pregunta que SIEMPRE hace el jurado:** *"¿Cómo demuestran que aprendió y no lo hardcodearon?"*
**Nuestra respuesta:** código abierto + log de inferencia + el portal de Arca es fijo (eso puede ir en el prompt) pero el del cliente se infiere + cambiar un nombre de campo del cliente en vivo y mostrar que igual lo mapea.

---

## 9. Preguntas que aún confirmamos con mentores

- [ ] ¿Cuánto dura la presentación y quiénes son los jueces (técnicos / negocio)?
- [ ] ¿Algún límite de tokens / infraestructura que debamos respetar?

*(Resueltas ya: prompt explicando tarea+destino NO es hardcoding; datos nuevos los ponemos nosotras; no construimos sobre SAP; visión es fase posterior.)*

---

## 10. Riesgos y cómo los manejamos

| Riesgo | Mitigación |
|---|---|
| Demo en vivo truena | Video de respaldo del ciclo completo (Checkpoint 5). |
| Core no termina | Checkpoint 2: si no corre, se cancelan capas opcionales. |
| Sobre-ambición fragmenta al equipo | Regla de oro: core primero, capas solo si sobra tiempo. |
| Sospecha de hardcoding | Código abierto + log de inferencia + cambio de campo en vivo. |
| Setup de WhatsApp consume horas | Plan B: simular la notificación visualmente. |
| Steff sobrecargada | Predictivo es opcional y Xime apoya. |

---

*Documento vivo — actualizar conforme avancemos y confirmemos cosas con mentores.*
