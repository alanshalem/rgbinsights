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

## Instalación de un click (para el cliente)

La **primera vez**, bajá el instalador y ejecutalo — clona el proyecto desde
GitHub y lo levanta solo:

- **Windows:** bajá `install.ps1` → click derecho → **Ejecutar con PowerShell**.
- **macOS / Linux:** bajá `install.sh` y corré `bash install.sh`.

**Para actualizar** (cada vez que hay una versión nueva): no hace falta nada
especial — **corré `start.ps1` / `start.sh` de siempre**. Arranca haciendo
`git pull` solo, así que siempre levanta la última versión. (Si preferís, volver
a correr el instalador también actualiza.)

> Requiere **Git** (el instalador te ayuda a ponerlo). El repo:
> https://github.com/alanshalem/rgbinsights

---

## Arranque rápido (recomendado)

Un solo comando que **chequea requisitos, instala lo que falte y levanta todo**.
Si te falta Python o Node, te dice exactamente qué instalar.

- **Windows:** click derecho en `start.ps1` → **Ejecutar con PowerShell**.
  (o en terminal: `powershell -ExecutionPolicy Bypass -File start.ps1`)
- **macOS / Linux:**
  ```bash
  chmod +x start.sh   # una sola vez
  ./start.sh
  ```

Abre el frontend en http://localhost:5173. Para hacerlo manual (dos terminales),
seguí los pasos de abajo.

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

Instagram bloquea el login por API con un *checkpoint*, y el `sessionid` de web
solo da acceso a `/users/*` (no a DMs). Por eso el modo real anda con un
**navegador real logueado** (Playwright): te logueás a mano una vez y la app
maneja el navegador headless.

### Opción recomendada: navegador real (Playwright)

1. En `backend/.env`: `USE_FAKE_INSTAGRAM=false` y `IG_SOURCE=playwright`.
2. Logueate una vez (abre una ventana de Chromium):
   ```bash
   cd backend
   .venv\Scripts\python.exe -m app.login_browser   # Mac/Linux: .venv/bin/python -m app.login_browser
   ```
   Logueate en la ventana (resolvé cualquier checkpoint como humano), volvé a la
   terminal y apretá Enter. La sesión queda guardada en `.pw-profile/`.
3. Verificá que anda (identidad + DMs + un post):
   ```bash
   .venv\Scripts\python.exe -m app.web_check https://www.instagram.com/p/TU_POST/
   ```
4. Levantá la app (`.\start.ps1`) y escaneá.

> La carpeta `.pw-profile/` guarda tu sesión de Instagram: no la compartas
> (está en `.gitignore`). Para más velocidad corre headless (`IG_BROWSER_HEADLESS=true`);
> poné `false` si querés ver el navegador.

### Alternativa: login con usuario y contraseña (instagrapi)

Suele frenar con checkpoint; solo si tu cuenta permite login móvil.

1. Editá `backend/.env`:
   - `USE_FAKE_INSTAGRAM=false`
   - `IG_USERNAME=` y `IG_PASSWORD=` con la cuenta.
   - Si la cuenta tiene 2FA, poné el seed TOTP en `IG_2FA_SECRET`.
2. **Logueate una sola vez** (resuelve la verificación y guarda la sesión):
   ```bash
   cd backend
   .venv\Scripts\Activate.ps1      # Mac/Linux: source .venv/bin/activate
   python -m app.login
   ```
   Si Instagram pide un código (email/SMS/2FA), te lo pregunta por terminal.
   Al terminar guarda `session.json`.
3. Levantá la app normalmente: **reusa esa sesión** y no vuelve a loguear.

Si Instagram igual pide **verificación** durante el uso, la app lo avisa en
pantalla (cartel amarillo) y **no se rompe** — corré `python -m app.login` de
nuevo para re-validar.

### Que Instagram no te bloquee

Lo que más ayuda, en orden:

1. **Corré desde tu conexión de casa** (la misma donde usás Instagram). **Sin VPN.**
2. **Logueate primero en la app oficial** de Instagram en esa red y aprobá el
   *"¿Fuiste vos?"*.
3. Usá `python -m app.login` para dejar la **sesión guardada** (reusar sesión es
   la defensa #1).
4. Poné país/locale en `.env`: `IG_COUNTRY=AR`, `IG_LOCALE=es_AR`.
5. Si aún así te bloquea, configurá un **proxy estable** (residencial/móvil, uno
   fijo — no rotativo) en `IG_PROXY=`.
6. Andá **despacio**: pocas requests. Las demoras y el tope por corrida se
   configuran con `SCAN_*` en `.env`.

---

## Detalles técnicos

- Backend: FastAPI + SQLModel sobre SQLite (`backend/rgb.db`). Ver
  [`backend/README.md`](backend/README.md).
- Frontend: Vite + React + TypeScript (strict) + TanStack Query, con cliente
  HTTP **tipado generado desde el OpenAPI** del backend.
- La app escucha solo en `127.0.0.1` (no se expone a internet).
