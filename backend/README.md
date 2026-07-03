# Backend — RGB Semáforo

FastAPI + SQLModel (SQLite) + instagrapi. Clean architecture pragmática.

## Estructura

```
app/
  domain/          # entidades, TrafficLight, classify() — reglas puras, sin deps
  application/     # casos de uso (ScanPost, ScanPosts, SyncDms, ListUsers) + DTOs
  infrastructure/
    instagram/     # InstagramSource (port) + adapter instagrapi + FakeInstagramSource
    persistence/   # rows SQLModel, sesión de DB, repos (upserts idempotentes)
    config/        # settings desde .env
  api/             # routers FastAPI, schemas, deps, mapeo Result->HTTP
  main.py
tests/             # classify + casos de uso con FakeInstagramSource (no toca IG real)
```

Puntos de diseño:

- **`InstagramSource`** (Strategy) aísla la parte frágil/ToS. `instagrapi` se
  importa **lazy**, así la app y el `FakeInstagramSource` corren aunque no esté
  instalado.
- El **semáforo** es una función pura (`domain/traffic_light.py`).
- Errores esperables (post no encontrado, challenge) se devuelven como
  `Result.Err` y se mapean a HTTP en `api/deps.py` — no se tiran excepciones para
  flujo normal.
- Identidad de usuario = `pk` (id numérico estable); el `username` puede cambiar.

## Comandos

```bash
uvicorn app.main:app --reload --port 8000   # correr

pytest            # tests
ruff check .      # lint
ruff format .     # format
mypy              # tipado estricto
```

Docs interactivas: http://localhost:8000/docs · OpenAPI: `/openapi.json`.

## Endpoints

| Método | Ruta          | Qué hace                                                        |
| ------ | ------------- | --------------------------------------------------------------- |
| POST   | `/scan/post`  | Escanea comentarios + likers de un post. `{ url }`.             |
| POST   | `/scan/posts` | Varios: `{ urls: [...] }` **o** rango `{ from, to }` (ISO).     |
| POST   | `/sync/dms`   | Sincroniza hilos de DM (separado del scan de posts).            |
| GET    | `/users`      | Usuarios + semáforo. Query: `post`, `status`, `search`, `order`.|
| GET    | `/posts`      | Posts escaneados.                                               |
| GET    | `/health`     | Estado + si está en modo fake.                                  |

## Config (`.env`)

Ver `.env.example`. Clave: `USE_FAKE_INSTAGRAM` (default `true`) corre con datos
de ejemplo; ponelo en `false` y completá credenciales para ir a Instagram real.
`SCAN_*` controlan las demoras y el tope de requests por corrida.
