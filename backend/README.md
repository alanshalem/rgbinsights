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
uvicorn app.main:app --port 8000   # correr (sin --reload: el source Playwright
                                   # maneja un Chrome; --reload lo dejaría huérfano)

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

## Login a Instagram real

```bash
python -m app.login
```

Login interactivo de una sola vez: resuelve challenge/2FA (te pide el código por
terminal) y guarda `session.json`. Después la API reusa esa sesión y no vuelve a
loguear de cero — la mejor forma de evitar bloqueos. Usa el mismo `build_client`
(`infrastructure/instagram/session.py`) que el adapter, así proxy/país/locale son
consistentes.

## Config (`.env`)

Ver `.env.example`. Clave: `USE_FAKE_INSTAGRAM` (default `true`) corre con datos
de ejemplo; ponelo en `false` y completá credenciales para ir a Instagram real.
Anti-bloqueo (opcional): `IG_PROXY` (uno estable), `IG_COUNTRY`, `IG_LOCALE`,
`IG_TIMEZONE_OFFSET` (default `-10800`, Argentina).

## Anti-ban: cómo se protege la cuenta

Todo pedido HTTP a Instagram pasa por un único guardián
(`infrastructure/instagram/guard.py`), instalado en las sesiones HTTP del cliente
instagrapi — así cuenta y frena **cada página** de una lectura paginada, no cada
llamada del código.

- **`/ig/status` nunca se loguea**: solo informa el último estado conocido
  (sesión en memoria, último OK, error y hasta cuándo hay pausa — campos
  `cooldown_until` y `last_error`). El login ocurre solo al apretar
  "conectar"/pegar el sessionid, o al lanzar una operación (escaneo, sync,
  enriquecer, campaña) que lo necesite.
- **Circuit breaker de login**: si un login falla, no se reintenta por 15 min,
  después 1 h y después 6 h (tope). Un login exitoso lo resetea. Pegar un
  sessionid nuevo puede saltearlo una vez, salvo si Instagram bloqueó la IP.
- **Una sola operación contra Instagram a la vez** (candado global entre la
  campaña y los pedidos de la UI). Quien llega segundo espera hasta
  `IG_LOCK_WAIT_SECONDS` (600 s) y si no, avisa que está ocupado.
- **Presupuesto real**: `IG_MAX_REQUESTS_PER_HOUR` (200) e
  `IG_MAX_REQUESTS_PER_DAY` (1500) cuentan todos los pedidos HTTP, en horas/días
  de Argentina (cada salto de una redirección cuenta y espera como un pedido
  más; como máximo 3 saltos). Al llegar al tope se frena todo hasta que cambie
  la ventana.
- **Cooldown**: ante un 429, "please wait a few minutes", `feedback_required`,
  `rate_limit_error` o `sentry_block`, no se hace ningún pedido por
  `IG_THROTTLE_COOLDOWN_MINUTES` (60). Los reintentos automáticos del transporte
  están desactivados para no repetir un 429 por detrás.
- **Ritmo humano**: antes de cada pedido, una espera variable (triangular entre
  `SCAN_MIN_DELAY_SECONDS`=2 y `SCAN_MAX_DELAY_SECONDS`=6, más alguna distracción
  larga ocasional) y un descanso de `IG_REST_MIN_SECONDS`–`IG_REST_MAX_SECONDS`
  (45–150 s) cada `IG_REST_EVERY_REQUESTS` (25) pedidos.
- **Campañas**: el horario activo y el tope diario usan hora argentina. Ante
  sesión caída, IP bloqueada o un freno de seguridad (tope/cooldown) la campaña
  queda `paused` con el motivo en `error` (el destinatario sigue pendiente);
  ante action-block (incluido un 403 al enviar) o challenge/checkpoint queda
  `blocked` como antes. Un error de red solo marca ese destinatario como fallido.
  Una sesión caída o con challenge se descarta: no se reusa para el próximo envío.
- **Avatares**: se bajan una vez con encabezados de navegador y por el mismo
  `IG_PROXY`; después se sirven del caché en disco.

El estado del breaker, el cooldown y los contadores se guardan en
`IG_GUARD_FILE` (default `ig_guard.json`), así sobreviven a reinicios. Es un
archivo y no la DB a propósito: los casos de uso tienen una transacción SQLite
abierta mientras llaman a Instagram, y escribir desde otra conexión se
bloquearía. Si el archivo está corrupto o mal formado, se ignora (con un
warning en el log) y se arranca con estado limpio.
