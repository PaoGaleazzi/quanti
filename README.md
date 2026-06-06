# Always on Shelf 🛒
### Reto Arca Continental — Equipo: Fer · Xime · Steff · Pao

Solución de IA que **observa una sola vez** a una persona llenar un pedido en el portal de un cliente del canal moderno (HEB, Sanborns…) y lo replica en el portal interno de Arca — y de ahí en adelante lo hace **sola**, traduciendo de un portal a otro **sin reglas de mapeo programadas**.

> **El problema:** hoy el pedido se llena DOS veces (portal del cliente + portal de Arca). Queremos que se llene una sola vez.
> **La meta:** un "EDI de IA" que aprende cualquier portal observándolo una vez → escalable y replicable sin implementación pesada.

---

## 📁 Estructura del repo

```
.
├── README.md                  ← este archivo
├── CLAUDE.md                  ← contexto para Claude Code
├── .gitignore                 ← NO subir .env ni secretos
├── .env.example               ← plantilla de variables (copiar a .env)
├── docs/
│   ├── Plan_Hackathon_AlwaysOnShelf.md   ← plan de trabajo y reparto
│   └── Esquema_Base_de_Datos.md          ← diagramas y diseño de la BD
└── db/
    ├── 01_esquema.sql         ← tablas de Arca + predictivas
    ├── 03_portales_cliente.sql ← portales HEB/Sanborns (sistemas externos)
    └── 02_seed_datos.py       ← genera datos simulados
```

---

## 🚀 Setup (cada quien, una vez)

### 1. Clonar el repo
```bash
git clone <url-del-repo>
cd always-on-shelf
```

### 2. Crear el entorno e instalar dependencias
Usamos [uv](https://docs.astral.sh/uv/):
```bash
uv init
uv add psycopg2-binary python-dotenv
```

### 3. Crear el archivo `.env`
Copia la plantilla y llena los valores (te los pasa Pao **en privado**, NO van en GitHub):
```bash
cp .env.example .env
```
Edita `.env` con los datos del **Session pooler** de Supabase:
```
DB_HOST=aws-1-us-west-2.pooler.supabase.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres.tlntymneqeaeezdgiqsq
DB_PASSWORD=<la contraseña que les pasó Pao>
```
> ⚠️ Ojo: con el pooler, `DB_USER` lleva el project ref pegado (`postgres.tlntymneqeaeezdgiqsq`), no es solo `postgres`.

### 4. ¿La base ya tiene datos? → ya estás lista
La base vive en Supabase (compartida). Si ya está sembrada, solo conéctate. **No corras el seed** salvo que haga falta regenerar (ver abajo).

---

## 🗄️ Base de datos

- **Vive en Supabase (nube), compartida por las cuatro.** Lo que una escribe, las demás lo ven al instante.
- **El esquema** está en `db/01_esquema.sql` y `db/03_portales_cliente.sql`. Se corren en el SQL Editor de Supabase.
- **Los datos simulados** los genera `db/02_seed_datos.py` (semilla fija → idénticos para todas).

### Regenerar datos (⚠️ solo una persona designada)
El seed hace `truncate` (borra todo y regenera). Si dos lo corren a la vez o mientras alguien prueba, se pisan los datos.
```bash
uv run python db/02_seed_datos.py
```

### Reglas de coordinación
- El **seed lo corre UNA sola persona** cuando haga falta regenerar.
- Para pruebas individuales, cada quien usa sus propios `client_id` de prueba para no pisarse.
- Cambios de **estructura** (nueva columna/tabla): editar el `.sql`, correrlo en Supabase, hacer push del `.sql`. Las demás hacen `git pull`.
- Cambios de **datos**: automáticos, la base es compartida.

---

## 🔐 Seguridad
- **NUNCA** subas el `.env` (el `.gitignore` lo bloquea — no lo quites).
- La contraseña de la base se comparte **en privado** entre las cuatro, nunca en el chat público ni en el código.

---

## 📋 Documentación
- **Plan de trabajo y reparto de tareas:** `docs/Plan_Hackathon_AlwaysOnShelf.md`
- **Diseño de la base de datos (diagramas):** `docs/Esquema_Base_de_Datos.md`
