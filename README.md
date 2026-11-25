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
uvicorn app.main:app --reload --port 8000
```

Cuando veas `Application startup complete`, dejá esa terminal abierta.

> **No hace falta configurar nada.** El archivo `backend/.env` es opcional y
> solo sirve para un proxy (`IG_PROXY`, ver abajo). Todo lo demás se ajusta
> desde la pantalla **Configuración** de la app.
>
> **Usa tu Instagram real**, pero no le pide nada a Instagram hasta que pegues
> tu sesión (ver [Usar Instagram real](#usar-instagram-real)).

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
6. **Exportar Excel** / **Exportar PDF** bajan la lista que estás viendo (misma
   fiesta, filtros, búsqueda y orden; todas las filas) para pasársela a las
   publicas. Sale de la base local: no le pide nada a Instagram.

Re-escanear un post no duplica nada: podés hacerlo las veces que quieras.

---

## Usar Instagram real

La app habla con Instagram por la API móvil (instagrapi) y se conecta de
**una sola forma**: **reusando la sesión de tu navegador** (`sessionid`). No hay
login con usuario y contraseña (Instagram lo frena con un *checkpoint*).

1. Tocá el chip **IG · pegá tu sesión** (arriba) → **Pegá tu sesión de
   Instagram** y seguí los pasos en pantalla: abrí instagram.com logueado, `F12` →
   **Application** → **Cookies** → `https://www.instagram.com`, copiá el valor de
   `sessionid`.
2. Pegalo y dale **Guardar y conectar**. La sesión queda guardada en
   `session.json` y se reusa en cada arranque (no vuelve a loguear de cero).

> `session.json` guarda tu sesión de Instagram: no la compartas (está en
> `.gitignore`). Para cortarla, chip **IG** → **Desconectar**.

Si la sesión vence o Instagram pide **verificación**, la app lo avisa en
pantalla y **no se rompe** ni intenta loguearse sola: confirmá desde el celu si
te lo pide y pegá un `sessionid` recién sacado del navegador (chip **IG**).

### Que Instagram no te bloquee

Lo que más ayuda, en orden:

1. **Corré desde tu conexión de casa** (la misma donde usás Instagram). **Sin VPN.**
2. **Logueate primero en la app oficial** de Instagram en esa red y aprobá el
   *"¿Fuiste vos?"*.
3. Conectá pegando el `sessionid` (chip **IG**): queda la **sesión guardada** y
   se reusa (reusar sesión es la defensa #1).
4. País, idioma y zona horaria ya van fijos en Argentina (`AR`, `es_AR`).
5. Si aún así te bloquea, configurá un **proxy estable** (residencial/móvil, uno
   fijo — no rotativo) en `backend/.env`: `IG_PROXY=http://usuario:clave@host:puerto`
   (es la única variable de entorno; reiniciá la app después).
6. Andá **despacio**: pocas requests. Las esperas, los descansos y los topes se
   ajustan en **Configuración** — solo hacia lo más seguro (esperas más largas y
   topes más bajos que los de fábrica).

---

## Detalles técnicos

- Backend: FastAPI + SQLModel sobre SQLite (`backend/rgb.db`). Ver
  [`backend/README.md`](backend/README.md).
- Configuración: `GET/PUT /config` y `POST /config/reset`, guardada en la DB y
  aplicada desde el próximo pedido a Instagram (sin reiniciar).
- Frontend: Vite + React + TypeScript (strict) + TanStack Query, con cliente
  HTTP **tipado generado desde el OpenAPI** del backend.
- La app escucha solo en `127.0.0.1` (no se expone a internet).
- Export del semáforo: `GET /users/export?format=xlsx|pdf` con los mismos
  filtros que `/users` (`event`, `post`, `status`, `search`, `order`, `follows`)
  más `by_status=true` (agrupado rojo → amarillo → verde, como el Board). Devuelve
  el archivo como descarga (`semaforo-<fiesta>-<AAAA-MM-DD>.xlsx|pdf`, fecha
  argentina) con todas las filas, sin paginar. Usa `openpyxl` y `fpdf2`.
