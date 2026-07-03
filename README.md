# RGB Collective — Semáforo de Instagram

Herramienta **local** para hacer seguimiento de outreach por DM. A partir de los
posts de [`@rgb.collective___`](https://instagram.com/rgb.collective___), lista a
la gente que **comentó y/o likeó** y la clasifica en un **semáforo** según el
estado de la conversación por mensaje directo:

- 🔴 **Rojo** — nunca hubo interacción por DM (no hay hilo).
- 🟡 **Amarillo** — le escribimos y nunca contestó.
- 🟢 **Verde** — hubo conversación real (nos contestó al menos una vez).

Corre en tu propia máquina. No hay usuarios, login propio ni nube.

---

## Qué necesitás instalar (una sola vez)

1. **Python 3.12 o superior** → https://www.python.org/downloads/
   (en el instalador, tildá **"Add Python to PATH"**).
2. **Node.js 20 o superior** → https://nodejs.org/ (elegí la versión "LTS").

Para chequear que quedaron instalados, abrí una terminal y escribí:

```bash
python --version
node --version
```

Si te muestran un número de versión, estás listo.

---

## Cómo correrlo

Son dos partes: el **backend** (el motor) y el **frontend** (la pantalla).
Abrí **dos terminales**, una para cada uno.

### Terminal 1 — Backend

```bash
cd backend
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Mac / Linux:
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env      # Windows   (Mac/Linux: cp .env.example .env)
uvicorn app.main:app --reload --port 8000
```

Cuando veas `Application startup complete`, dejá esa terminal abierta.

> **Modo demo (por defecto):** viene con `USE_FAKE_INSTAGRAM=true`, así que
> funciona con **datos de ejemplo** sin tocar Instagram. Perfecto para probarlo.
> Para usar Instagram de verdad, ver [Usar Instagram real](#usar-instagram-real).

### Terminal 2 — Frontend

```bash
cd frontend
npm install
npm run gen:api    # genera el cliente tipado desde el backend (tiene que estar corriendo)
npm run dev
```

Abrí el navegador en **http://localhost:5173**.

---

## Cómo se usa

1. Pegá una o varias **URLs de posts** en el cuadro de arriba y tocá **Escanear**.
2. Tocá **Sincronizar DMs** para traer el estado de las conversaciones.
3. Mirá el **Board** (3 columnas) o cambiá a la vista de **Tabla**.
4. Filtrá por estado, por post o buscá por `@usuario`.
5. **Abrir DM** te lleva al chat en Instagram; si no hay chat, **Ver perfil**.

Re-escanear un post no duplica nada: podés hacerlo las veces que quieras.

---

## Usar Instagram real

1. Editá `backend/.env`:
   - `USE_FAKE_INSTAGRAM=false`
   - `IG_USERNAME=` y `IG_PASSWORD=` con la cuenta.
   - Si la cuenta tiene 2FA, poné el seed TOTP en `IG_2FA_SECRET`.
2. Reiniciá el backend.

La sesión se guarda en `session.json` para no tener que loguearse en cada corrida.
Si Instagram pide **verificación (challenge)**, la app lo avisa en pantalla y **no
se rompe** — resolvé la verificación y volvé a intentar.

La herramienta usa demoras aleatorias y un tope de requests por corrida para
comportarse bien (configurable en `.env`).

---

## Detalles técnicos

- Backend: FastAPI + SQLModel sobre SQLite (`backend/rgb.db`). Ver
  [`backend/README.md`](backend/README.md).
- Frontend: Vite + React + TypeScript (strict) + TanStack Query, con cliente
  HTTP **tipado generado desde el OpenAPI** del backend.
- La app escucha solo en `127.0.0.1` (no se expone a internet).
