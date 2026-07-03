# Prompt Maestro — RGB Collective · Semáforo de usuarios de Instagram

> Pegá esto en Claude Code como especificación del proyecto.

## Contexto y objetivo

Necesito una app **local** (la corren 2-3 personas en su propia máquina, **sin sistema de usuarios ni auth propia**) que, a partir de los posts de nuestra cuenta de Instagram (`@rgb.collective___`), liste a la gente que **comentó y/o likeó** cada post y los clasifique en un **semáforo** según el estado de la conversación por mensaje directo (DM):

- 🔴 **Rojo:** nunca tuvimos interacción por DM con ese usuario (no hay hilo, o no le escribimos ni nos escribió).
- 🟡 **Amarillo:** le escribimos por DM pero nunca nos contestó (hay mensajes salientes, cero entrantes de él).
- 🟢 **Verde:** tuvimos interacción real por DM (hay al menos un mensaje entrante de él).

Es una herramienta interna para hacer seguimiento/outreach de nuestras fiestas. Prioridades: **que se corra simple** y que el código sea **limpio, tipado y mantenible**.

## Stack obligatorio

**Backend**
- Python 3.12+
- FastAPI (API REST) + Uvicorn
- SQLModel (SQLAlchemy + Pydantic) sobre **SQLite** (un archivo `.db`, cero infra)
- `instagrapi` para acceso a Instagram (comentarios, likers, hilos de DM)
- Config con `pydantic-settings` leyendo un `.env`
- Tooling: `ruff` (lint + format), `mypy` (tipado estricto), `pytest`

**Frontend**
- Vite + React + TypeScript en modo **strict** (`"strict": true`, sin `any` implícitos)
- Cliente HTTP **tipado generado desde el OpenAPI del backend** con `openapi-typescript` (+ un fetch wrapper), para tipado de punta a punta y cero tipos de respuesta escritos a mano
- TanStack Query para data fetching / estado de servidor
- Estilos simples y prolijos (Tailwind o CSS modules), sin design system pesado
- Tooling: ESLint + Prettier

## Arquitectura

Clean Architecture **pragmática** (sin sobre-ingeniería, es una app chica), con separación por capas:

```
backend/
  app/
    domain/          # entidades, enums (TrafficLight), reglas puras. Sin deps externas.
    application/     # casos de uso / servicios (ScanPostUseCase, SyncDmsUseCase, ...). Orquesta.
    infrastructure/
      instagram/     # InstagramSource: interfaz + adapter instagrapi (+ Fake para tests)
      persistence/   # repos SQLModel, sesión de DB, creación de tablas
      config/        # settings desde .env
    api/             # routers FastAPI, schemas request/response, dependencias
    main.py
  tests/
  .env.example
  requirements.txt   # (o pyproject.toml)
  README.md
frontend/
  src/
  ...
```

**Reglas de diseño:**
- **Abstracción de la fuente de datos (Strategy):** definí una interfaz `InstagramSource` (`Protocol`/`ABC`) con métodos como:
  - `get_post(url: str) -> Post`
  - `get_recent_posts(limit: int) -> list[Post]`
  - `get_likers(media_pk: str) -> list[IgUser]`
  - `get_comments(media_pk: str) -> list[Comment]`
  - `get_dm_threads() -> list[DmThread]`
  - `current_user_pk() -> str`
  Implementala con `InstagrapiInstagramSource`. Esto aísla la parte frágil/ToS y permite un `FakeInstagramSource` para tests.
- La **lógica del semáforo** vive en `domain` como **función pura y testeable**.
- **Manejo de errores estilo Result** donde tenga sentido: no tirar excepciones para flujo esperable ("post no encontrado", "challenge requerido"); excepciones solo para lo verdaderamente excepcional. Mapear a HTTP status apropiados en `api`.
- DRY / KISS / YAGNI. Nombres autoexplicativos. Comentarios **solo en lógica no obvia** (por ej.: por qué keyeamos por `pk` y no por username, paginación de IG, mapeo de hilos a usuarios).

## Modelo de datos (SQLite)

- `users`: `pk` (PK, id numérico **estable** de IG), `username`, `full_name`, `profile_pic_url`, `is_private`, `first_seen_at`, `last_seen_at`. La identidad es `pk`; el username puede cambiar.
- `posts`: `media_pk` (PK), `shortcode`, `url`, `caption`, `taken_at`, `last_scanned_at`.
- `engagements`: `id`, `user_pk` (FK), `post_media_pk` (FK), `type` (`comment` | `like`), `comment_text` (nullable), `created_at`. **Único por (`user_pk`, `post_media_pk`, `type`)** para idempotencia al re-escanear.
- `dm_threads`: `thread_id` (PK), `user_pk` (FK, el otro participante), `has_outgoing` (bool), `has_incoming` (bool), `last_message_at`, `last_synced_at`.
- El estado del semáforo por usuario se **deriva** de `dm_threads` (calcularlo al vuelo está bien para este volumen; cachear solo si hiciera falta).

**Mapeo:** los hilos de DM se matchean a `users` por `pk`. Un usuario puede haber comentado/likeado sin tener hilo (→ rojo). Puede existir un hilo de un usuario que no engagó (simplemente no aparece en la vista de un post, pero existe en la DB).

## Lógica del semáforo (dominio)

```python
def classify(has_outgoing: bool, has_incoming: bool) -> TrafficLight:
    if has_incoming:   # nos contestó / ida y vuelta
        return TrafficLight.GREEN
    if has_outgoing:   # le escribimos, no contestó
        return TrafficLight.YELLOW
    return TrafficLight.RED  # sin interacción por DM (incluye "sin hilo")
```

Para determinar `outgoing`/`incoming`: por cada hilo, comparar el `user_id` de cada mensaje contra `current_user_pk()`. Al menos un mensaje nuestro → `has_outgoing=True`; al menos un mensaje del otro → `has_incoming=True`. "Sin hilo" = ambos `False` → rojo.

## Endpoints de la API

- `POST /scan/post` — body `{ "url": "https://instagram.com/p/XXXX/" }`. Escanea comentarios + likers del post, upsertea `users`/`engagements`, devuelve `{ post, users_found, new_users }`.
- `POST /scan/posts` — body `{ "urls": [...] }` **o** `{ "from": "ISO", "to": "ISO" }`. Para el rango de fechas A→B: traer los últimos N posts del perfil (`get_recent_posts`) y filtrar por `taken_at`.
- `POST /sync/dms` — sincroniza los hilos de DM y actualiza `dm_threads`. **Separado** del scan de posts para correrlo independientemente.
- `GET /users` — query params: `post=`, `status=red|yellow|green`, `search=`, `order=`. Devuelve usuarios con su `traffic_light`, engagement (comentó/likeó + texto del comentario) y link de acción: al DM (`https://instagram.com/direct/t/{thread_id}/`) si hay hilo, o al perfil si no.
- `GET /posts` — posts escaneados.
- `GET /health`.

Paginación simple donde aplique. Respuestas tipadas (Pydantic) → alimentan el cliente TS.

## Frontend (UX)

Una pantalla principal con dos vistas conmutables:

1. **Board (kanban de 3 columnas):** Rojo / Amarillo / Verde. Cada card = un usuario (avatar, `@username`, chips "comentó"/"likeó", preview del comentario, botón **"Abrir DM"** que abre el link de Instagram en pestaña nueva).
2. **Tabla:** mismos datos, con orden/filtro por columna, filtro por post y por estado, y buscador por username.

Arriba: input para pegar la URL de un post (o varias) + botón **"Escanear"**, y botón **"Sincronizar DMs"**. Loading states y manejo de errores (incluido el caso *"Instagram pide verificación / challenge"*). Contadores por estado.

Todo el consumo de API vía el **cliente generado del OpenAPI**.

## Credenciales, sesión y operación segura

`.env` (con `.env.example` versionado, `.env` en `.gitignore`):

```
IG_USERNAME=
IG_PASSWORD=
IG_2FA_SECRET=          # opcional, TOTP seed si la cuenta tiene 2FA
IG_SESSION_FILE=session.json
DATABASE_URL=sqlite:///./rgb.db
SCAN_MIN_DELAY_SECONDS=1
SCAN_MAX_DELAY_SECONDS=3
SCAN_MAX_REQUESTS=200
```

- **Persistencia de sesión:** al iniciar, si existe `IG_SESSION_FILE`, cargar la sesión (`load_settings`) y reusarla; si falla o no existe, hacer login con user/pass y **guardar** la sesión. Objetivo: loguear una sola vez, no en cada corrida.
- **Challenge / 2FA:** implementar un challenge handler de `instagrapi`. Si hay `IG_2FA_SECRET`, resolver TOTP automáticamente; si no, exponer un flujo para ingresar el código manualmente sin que la app crashee.
- **Rate limiting / buen comportamiento (importante):** delays aleatorios entre requests (`SCAN_MIN/MAX_DELAY_SECONDS`), tope de requests por corrida (`SCAN_MAX_REQUESTS`), sin loops agresivos, paginación con pausas. Todo configurable.
- **Logging** claro (qué se escaneó, cuántos usuarios, errores) **sin loguear credenciales**.
- La API escucha en `127.0.0.1`, no se expone a internet.

## Cómo se corre (dejalo andando y documentado en el README)

**Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # completar credenciales
uvicorn app.main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run gen:api    # genera tipos desde http://localhost:8000/openapi.json
npm run dev
```

Idealmente un script raíz (Makefile o npm script) que levante ambos; dos terminales también está OK. El README debe explicar todo paso a paso, **pensado para alguien que no es dev**.

## Requisitos no funcionales

- Tipado estricto real (mypy en back, tsconfig strict en front, sin `any`).
- **Tests:** unitarios de `classify` (función pura) y de los casos de uso usando `FakeInstagramSource`. **No testear contra IG real.**
- Código comentado solo donde la lógica lo amerite.
- Commits con Conventional Commits.
- `.gitignore` correcto: `.env`, `session.json`, `*.db`, `node_modules`, `.venv`, etc.

## Entregables

1. Repo con `backend/` + `frontend/`.
2. `README.md` con instrucciones de corrida simples.
3. `.env.example`.
4. Tests mínimos en verde.
5. `FakeInstagramSource` con datos de ejemplo para probar el front sin Instagram.

## Criterios de aceptación

- Pego la URL de un post, escaneo, y veo a los usuarios que comentaron/likearon clasificados correctamente en rojo/amarillo/verde.
- El estado se deriva bien del estado real de los DMs.
- Corre local con los pasos del README, sin fricción.
- Re-escanear un post **no duplica** datos (idempotente).
- Si IG pide challenge, la app lo informa **sin romperse**.

## Restricción explícita

Priorizá simplicidad y legibilidad sobre optimización prematura. **No agregues features que no pedí** (auth, multiusuario, deploy en la nube, notificaciones, etc.). Mantené las dependencias al mínimo.
