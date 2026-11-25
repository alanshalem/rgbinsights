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

| Método | Ruta                       | Qué hace                                                        |
| ------ | -------------------------- | --------------------------------------------------------------- |
| POST   | `/scan/post`               | Escanea comentarios + likers de un post. `{ url }` (sincrónico).|
| POST   | `/scan/posts`              | **Tarea**: varios `{ urls: [...] }` **o** rango `{ from, to }`. |
| POST   | `/events/{id}/rescan`      | **Tarea**: re-escanea los posts de la fiesta (`?force=`).       |
| POST   | `/events/{id}/refresh`     | **Tarea**: rescan + sync de DMs en una (`?force=`).             |
| POST   | `/events/{id}/enrich`      | **Tarea**: relación + perfiles (`?force=`).                     |
| POST   | `/sync/dms`                | **Tarea**: sincroniza hilos de DM (`?force=`, `?event=`).       |
| GET    | `/tasks`                   | Las tareas actuales (respaldo por polling del stream).          |
| GET    | `/tasks/stream`            | SSE: la lista de tareas al conectar y en cada cambio.           |
| GET    | `/tasks/{id}`              | Una tarea: progreso, `result` o `error` (404 si ya se purgó).   |
| GET    | `/users`                   | Usuarios + semáforo. Query: `post`, `status`, `search`, `order`.|
| GET    | `/posts`                   | Posts escaneados.                                               |
| GET    | `/health`                  | Estado + si está en modo fake.                                  |

### Tareas en segundo plano (escaneo, sync, actualizar, enriquecer)

Las operaciones largas contra Instagram ya no dejan un request HTTP abierto
varios minutos: el POST valida (404 si la fiesta no existe, 422 si falta
`urls`/rango), arranca una **tarea** en un hilo de fondo (daemon, con su propia
sesión de DB) y responde enseguida **202** con la tarea (`Location:
/tasks/{id}`). La tarea es `{ id, kind, label, status: running|done|error,
current, total, message, result, error, error_code, started_at, finished_at }`:
`result` es el resumen ("2 posts · 4 nuevos", con `aviso` si la sync de DMs
llegó al tope `DM_THREADS_LIMIT`) y `error` el motivo en castellano
(`error_code`, p. ej. `challenge_required`, para el aviso de reconectar).

- **Una sola tarea con Instagram a la vez** (todas tocan Instagram): si ya hay
  una corriendo, pedir **la misma** (mismo tipo y mismos parámetros: doble clic,
  otra pestaña) devuelve esa misma tarea (202, mismo `id`); pedir **otra**
  responde **409** `{ code: "conflict", message: "Ya hay una tarea con Instagram
  en curso («…»). Esperá a que termine y probá de nuevo." }`. Nunca se encola ni
  corre en paralelo, y dentro de la tarea cada pedido sigue pasando por el
  guardián (candado, presupuesto, ritmo humano, sin reintentos). La campaña
  sigue en su propio hilo y comparte el candado del guardián como antes.
- **Progreso empujado (SSE)**: `GET /tasks/stream` (`text/event-stream`) manda
  un `event: tasks` con la lista completa (igual que `GET /tasks`) al conectar y
  cada vez que una tarea cambia (progreso, fin, error), y un comentario `: ping`
  cada 15 s si no pasa nada. La UI lo usa con `EventSource` y deja de consultar
  cada 1,2 s; si el stream se cae, vuelve al polling hasta reconectar. Lee solo
  memoria: ni el stream ni el polling hacen pedidos a Instagram ni a la DB.
- **Apagado/recarga**: los hilos de las tareas son daemon (no traban la salida)
  y la señal de apagado (Ctrl+C, `SIGTERM`, la de `--reload`) cierra los
  streams antes de que uvicorn espere las conexiones abiertas. Las tareas viven
  en memoria: se purgan 25 s después de terminar y un reinicio las pierde (lo ya
  guardado en la DB queda).

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
  sesión caída, IP bloqueada o un cooldown (Instagram pidió frenar: 429 /
  "please wait" / `feedback_required`) la campaña queda `paused` con el motivo en
  `error` (el destinatario sigue pendiente); ante action-block (incluido un 403
  al enviar) o challenge/checkpoint queda `blocked` como antes. Si lo que se
  agotó es nuestro propio presupuesto por hora/día, la campaña **no** se pausa:
  espera (sin ningún pedido a Instagram) a que se reabra la ventana, más 1–5 min
  al azar, y sigue sola con el mismo destinatario (queda registrado en
  Actividad como "campaña en espera"). Un error de red solo marca ese
  destinatario como fallido. Una sesión caída o con challenge se descarta: no se
  reusa para el próximo envío.
- **Pegar el sessionid** puede saltear el breaker de login una vez solo si es
  distinto del que falló (se guarda un hash SHA-256, nunca el valor).
- **Último error**: `last_error` se limpia con la primera operación exitosa
  contra Instagram una vez terminado el cooldown/breaker (no solo al loguear).
- **Avatares**: se bajan una vez con encabezados de navegador y por el mismo
  `IG_PROXY`; después se sirven del caché en disco. Cada descarga tiene 4 s de
  timeout y una que falla no se reintenta por 10 min (caché negativo en memoria),
  así un proxy caído no traba al servidor.

El estado del breaker, el cooldown y los contadores se guardan en
`IG_GUARD_FILE` (default `ig_guard.json`), así sobreviven a reinicios. Es un
archivo y no la DB a propósito: el guardián no debe depender de la transacción
SQLite de un caso de uso. Si el archivo está corrupto o mal formado, se ignora
(con un warning en el log) y se arranca con estado limpio.

## Menos pedidos a Instagram

- **Relación + perfiles** (`POST /events/{id}/enrich`): la relación (te sigue /
  lo seguís) se guarda apenas se lee; los perfiles se guardan de a 10. Ninguna
  transacción de escritura de SQLite queda abierta mientras se habla con
  Instagram. Si falla a la mitad (tope, cooldown, red), lo ya traído queda
  guardado y la próxima corrida pide solo los que faltan (el error y el resumen
  de la tarea dicen cuántos faltan). Topes: `ENRICH_PROFILES_PER_RUN` (60) por
  corrida y `ENRICH_PROFILES_PER_DAY` (150) por día argentino.
- **Mismos pedidos que instagrapi**: cada pedido (endpoint, método, parámetros,
  tamaño de página) es exactamente el que arma instagrapi para la misma lectura
  — instagrapi imita la app oficial y cualquier diferencia es una huella. Nuestro
  código solo decide **cuándo dejar de paginar** (`tests/test_request_shape.py`
  lo verifica contra instagrapi real).
- **Seguidores incrementales**: se leen de los más nuevos a los más viejos
  (`order=date_followed_latest`, como `user_followers(order=...)` de instagrapi)
  y se corta en la primera página sin nadie nuevo; las listas leídas se guardan
  en la tabla `follow_edges`. Así solo se suman seguidores; para ver los que
  dejaron de seguir hay una lectura completa cada
  `RELATIONSHIP_FULL_REFRESH_DAYS` (7) días o al forzar. **Seguidos** (a quién
  seguís) no tiene un orden garantizado, así que se lee entero como antes cada
  vez que vence el caché. Se sigue respetando `RELATIONSHIP_CACHE_HOURS` (12 h
  sin volver a leer) y `RELATIONSHIP_FETCH_MAX`.
- **Rescan sin volver a pedir el post**: si el post ya está guardado (mismo
  shortcode) no se pide `media_info`; el rango de fechas usa los posts que ya
  devolvió `user_medias`. Además, comentarios y likers usan el id completo del
  post cuando ya se conoce, sin la búsqueda extra que instagrapi hace por cada
  llamada (antes: 3 búsquedas del post por escaneo; ahora 1, o 0).
- **Comentarios incrementales**: se pagina de los más nuevos a los más viejos y
  se corta después de la primera página en la que **todos** los comentarios son
  iguales o anteriores al más nuevo ya guardado (`posts.last_comment_at`); uno
  viejo fijado arriba no corta. Siempre con el tope `SCAN_COMMENTS_LIMIT`.
- **DMs realmente incrementales**: el inbox se pagina de lo más reciente a lo
  más viejo y se corta en el primer chat sin actividad desde la sync anterior
  (los fijados no cortan); la marca es la hora de inicio de la sync anterior,
  redondeada al segundo como las horas de Instagram. **Toda** sync (primera,
  forzada o incremental) trae como máximo `DM_THREADS_LIMIT` (60) chats = 3
  páginas, las mismas que antes; cada chat trae sus últimos 10 mensajes. Si una
  sync incremental llega a ese tope antes de alcanzar la sync anterior, la marca
  igual avanza a su hora de inicio y se avisa (log, progreso de la tarea y el
  `aviso` del resumen de "Sincronizar DMs" y de "Actualizar fiesta") que los
  chats más viejos con mensajes nuevos no se sincronizaron; subí `DM_THREADS_LIMIT` si pasa seguido.
