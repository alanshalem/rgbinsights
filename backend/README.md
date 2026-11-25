# Backend — RGB Semáforo

FastAPI + SQLModel (SQLite) + instagrapi. Clean architecture pragmática.

## Estructura

```
app/
  domain/          # entidades, errores de Instagram, TrafficLight, classify() — sin deps
    config.py      # los ajustes de "Configuración": valores de fábrica y topes de seguridad
  application/     # casos de uso, tareas en segundo plano, envío de campañas + DTOs
    ports.py       # las interfaces que usan: InstagramSource, repos, UnitOfWork, CampaignStore, ConfigStore
    runtime_config.py  # la configuración efectiva (DB > entorno > fábrica), leída en cada pedido
  infrastructure/
    instagram/     # adapter instagrapi (fachada) + FakeInstagramSource + guardián anti-ban
      instagrapi_source.py  # fachada fina que implementa InstagramSource
      login.py              # la sesión (sessionid pegado -> session.json, reusada)
      reads.py              # posts, comentarios, likers, perfiles, seguidores/seguidos
      direct.py             # inbox de DMs y envío
      error_mapping.py      # excepciones de instagrapi -> errores del dominio
    persistence/   # rows SQLModel, engine, repos (upserts idempotentes), SqlUnitOfWork
    export/        # Excel / PDF del semáforo
    config/        # settings del entorno (solo IG_PROXY + overrides de desarrollo)
  api/             # routers FastAPI, schemas, deps, mapeo Result->HTTP
  bootstrap.py     # raíz de composición: el único lugar que arma y conecta todo
  main.py
tests/             # todo con FakeInstagramSource o stubs (nunca toca Instagram real)
```

Puntos de diseño:

- **Regla de dependencias**: `domain` no depende de nada; `application` (casos de
  uso, tareas, campañas) solo del dominio y de sus **ports** — nunca de la
  infraestructura, FastAPI ni la DB (`tests/test_architecture.py` lo verifica).
  La infraestructura implementa los ports y `app/bootstrap.py` los conecta
  (settings, engine, unidades de trabajo, source de Instagram, guardián,
  registro de tareas, envío de campañas); la API los recibe por `api/deps.py`.
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
uvicorn app.main:app --port 8000   # correr (--reload también sirve para desarrollar)

pytest            # tests
ruff check .      # lint
ruff format .     # format
mypy              # tipado estricto
```

Docs interactivas: http://localhost:8000/docs · OpenAPI: `/openapi.json`.

## Endpoints

| Método | Ruta                       | Qué hace                                                        |
| ------ | -------------------------- | --------------------------------------------------------------- |
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
| GET    | `/health`                  | Estado (+ si corre la fuente de prueba de desarrollo).          |
| GET    | `/config`                  | Cada ajuste: valor, por defecto, topes, etiqueta y ayuda.       |
| PUT    | `/config`                  | Cambia algunos ajustes `{ values: {...} }` (422 en castellano). |
| POST   | `/config/reset`            | Vuelve al valor por defecto uno (`{ key }`) o todos (`{}`).     |
| GET    | `/ig/status`               | Estado de la sesión (nunca le pide nada a Instagram).           |
| POST   | `/ig/sessionid`            | Pega un sessionid: lo valida una vez y lo guarda.               |
| POST   | `/ig/reauth`               | "Volver a conectar": revisa una vez la sesión guardada.         |
| POST   | `/ig/disconnect`           | Borra la sesión guardada (`session.json`).                      |

### Tareas en segundo plano (escaneo, sync, actualizar, enriquecer)

Las operaciones largas contra Instagram ya no dejan un request HTTP abierto
varios minutos: el POST valida (404 si la fiesta no existe, 422 si falta
`urls`/rango), arranca una **tarea** en un hilo de fondo (daemon, con su propia
sesión de DB) y responde enseguida **202** con la tarea (`Location:
/tasks/{id}`). La tarea es `{ id, kind, label, status: running|done|error,
current, total, message, result, warning, error, error_code, started_at,
finished_at }`: `result` es el resumen ("2 posts · 4 nuevos"), `warning` un aviso
aparte (p. ej. si la sync de DMs llegó al tope de chats por sync; por ahora
también va en `result.aviso` para la UI actual) y `error` el motivo, siempre en
castellano (`error_code`, p. ej. `challenge_required`, para el aviso de
reconectar). Para escanear un solo post se usa la misma `/scan/posts` con una
URL (el viejo `POST /scan/post` sincrónico se eliminó: la UI no lo usaba).

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

## Conectar Instagram real

Hay **una sola forma**, desde la app: chip **IG** de arriba → **"Pegá tu
sesión"**. Pegás la cookie `sessionid` de un navegador donde ya estés logueado a
la cuenta (lo más seguro: no hay login nuevo). Se valida con un solo pedido y se
guarda en `session.json` (`POST /ig/sessionid`); después se reusa en cada
arranque y nunca se vuelve a loguear de cero.

- **No hay login con usuario y contraseña** (ni 2FA) **ni reconexión
  automática**: si la sesión vence, la operación falla con "La sesión venció:
  pegá un sessionid nuevo desde el chip IG", el cliente se descarta y no se
  intenta ningún login. `IG_USERNAME`, `IG_PASSWORD`, `IG_2FA_SECRET` e
  `IG_SESSIONID` ya no se leen (un `.env` viejo que los tenga se ignora).
- **"Volver a conectar"** (`POST /ig/reauth`) revisa **una vez** la sesión
  guardada (`session.json`, un solo pedido liviano), por ejemplo después de
  confirmar en el celu un "¿Fuiste vos?". Sin sesión guardada responde 401 sin
  ningún pedido. Respeta el breaker de login.
- Si Instagram pide verificación (challenge), confirmá desde el celu y volvé a
  pegar el sessionid. **Desconectar** (`POST /ig/disconnect`) borra
  `session.json`.

## Configuración (en la app, no en `.env`)

Todo lo que cambia cómo trabaja la app se edita en la pantalla
**Configuración** (`GET/PUT /config`, `POST /config/reset`) y se guarda en la DB
(tabla `app_config`; "Borrar todo" no la toca). Se aplica desde el **próximo
pedido** a Instagram, sin reiniciar (nunca en medio de uno): el guardián lee el
ritmo, el presupuesto, la pausa y la espera del candado en cada pedido, y las
lecturas leen sus topes en cada lectura. Valor efectivo = lo guardado en la app;
si no, el valor por defecto: el de un `.env` viejo si lo tenía (así una
instalación existente sigue igual), si no el de fábrica — siempre dentro de los
topes.

**Solo se puede ir hacia lo más seguro** (S0), y lo controla el backend
(`domain/config.py`), no solo la pantalla: un valor fuera de los topes responde
**422** con el motivo en castellano (p. ej. "«Tope de pedidos por hora» no puede
ser mayor que 200 pedidos (el valor de fábrica): …"); un `.env` viejo más
rápido que la fábrica se lleva al tope.

| Ajuste (clave) | Fábrica | Topes |
| --- | --- | --- |
| Espera mínima / máxima entre pedidos (`scan_min_delay_seconds` / `scan_max_delay_seconds`) | 2 s / 6 s | fábrica … 60 s, mínima ≤ máxima |
| Descanso largo cada (`ig_rest_every_requests`) | 25 pedidos | 5 … 25 |
| Descanso mínimo / máximo (`ig_rest_min_seconds` / `ig_rest_max_seconds`) | 45 s / 150 s | fábrica … 900 s, mínimo ≤ máximo |
| Tope de pedidos por hora / día (`ig_max_requests_per_hour` / `_per_day`) | 200 / 1500 | 1 … fábrica |
| Pausa si Instagram pide frenar (`ig_throttle_cooldown_minutes`) | 60 min | 60 … 1440 min |
| Espera si Instagram está ocupado (`ig_lock_wait_seconds`) | 600 s | 30 … 3600 s |
| Posts recientes a revisar (`recent_posts_limit`) | 50 | 1 … 50 |
| Chats por sincronización (`dm_threads_limit`) | 60 | 1 … 60 |
| Comentarios por post (`scan_comments_limit`) | 200 | 1 … 200 |
| Tope de seguidores/seguidos a leer (`relationship_fetch_max`) | 0 (todos) | 0 … 1.000.000 (un tope solo baja pedidos) |
| Perfiles por corrida / por día (`enrich_profiles_per_run` / `_per_day`) | 60 / 150 | 1 … fábrica |
| Reusar tus seguidores durante (`relationship_cache_hours`) | 12 h | 12 … 168 h |
| No releer un post escaneado hace menos de (`rescan_skip_hours`) | 6 h | 6 … 168 h |
| Lectura completa de seguidores cada (`relationship_full_refresh_days`) | 7 días | 7 … 90 días |

- **Siempre Instagram real** (L25, L27): sin una sesión pegada la app no hace
  **ningún** pedido a Instagram (no hay cliente: estado "desconectado";
  escanear, sincronizar, enriquecer, el DM de prueba, la campaña y "Volver a
  conectar" fallan al toque con "No hay una sesión de Instagram guardada: pegá tu
  sessionid desde el chip IG"; una campaña queda en pausa sin gastar
  destinatarios). No hay modo demo en la app.
- Un cuerpo que `/config` no puede leer (p. ej. `PUT /config` con `{}`) responde
  **422** en castellano, como sus otros errores. Si un valor viejo del `.env` se
  tuvo que llevar al tope, se avisa una vez en el log al arrancar y `GET /config`
  lo informa en `clamped_from` (la pantalla lo muestra en amarillo). Una fila
  guardada ilegible (o de un ajuste que ya no existe) se ignora y no cuenta como
  "cambiado".
- El descanso largo cuenta los pedidos **desde el último descanso**: si cambiás
  "Descanso largo cada", nunca pasan más pedidos seguidos sin descanso que el
  valor viejo o el nuevo.
- La sync de DMs es **siempre incremental** (salvo "Traer todo de cero"): ya no
  se puede apagar.
- País, idioma y zona horaria que se le informan a Instagram están **fijos en
  Argentina** (`AR`, `es_AR`, UTC-3) en el código.

### Variables de entorno

La única documentada es **`IG_PROXY`** (opcional: un proxy estable,
residencial/móvil y fijo). Para desarrollo y tests existen `DATABASE_URL`,
`IG_SESSION_FILE` e `IG_GUARD_FILE`.

**Nota para desarrollo y tests**: `RGB_DEV_FAKE_INSTAGRAM=1` cambia la cuenta real
por `FakeInstagramSource` (datos inventados, nunca toca Instagram; el chip dice
"prueba · sin IG"). No es una opción para usuarios. Los tests lo fuerzan con
`Settings(dev_fake_instagram=True)`. Las viejas `IG_SOURCE` y `USE_FAKE_INSTAGRAM`
**ya no se leen** (L28): un `.env` copiado del ejemplo viejo con
`USE_FAKE_INSTAGRAM=true` o `IG_SOURCE=fake` no deja la app trabada en datos
inventados.

## Anti-ban: cómo se protege la cuenta

Todo pedido HTTP a Instagram pasa por un único guardián
(`infrastructure/instagram/guard.py`), instalado en las sesiones HTTP del cliente
instagrapi — así cuenta y frena **cada página** de una lectura paginada, no cada
llamada del código.

- **`/ig/status` nunca se loguea**: solo informa el último estado conocido
  (sesión en memoria, último OK, error y hasta cuándo hay pausa — campos
  `cooldown_until` y `last_error`). Nunca hay login: la sesión sale del
  sessionid pegado (guardado en `session.json`), que se revisa con un pedido
  liviano al pegarlo, al apretar "Volver a conectar" o en la primera operación
  (escaneo, sync, enriquecer, campaña) después de arrancar.
- **Circuit breaker de login**: si esa revisión (o el sessionid pegado) falla,
  no se reintenta por 15 min, después 1 h y después 6 h (tope). Una conexión
  exitosa lo resetea. Pegar un sessionid nuevo puede saltearlo una vez, salvo si
  Instagram bloqueó la IP.
- **Una sola operación contra Instagram a la vez** (candado global entre la
  campaña y los pedidos de la UI). Quien llega segundo espera hasta "Espera si
  Instagram está ocupado" (Configuración, 600 s) y si no, avisa que está
  ocupado.
- **Presupuesto real**: los topes de pedidos por hora (200) y por día (1500)
  de Configuración cuentan todos los pedidos HTTP, en horas/días
  de Argentina (cada salto de una redirección cuenta y espera como un pedido
  más; como máximo 3 saltos). Al llegar al tope se frena todo hasta que cambie
  la ventana.
- **Cooldown**: ante un 429, "please wait a few minutes", `feedback_required`,
  `rate_limit_error` o `sentry_block`, no se hace ningún pedido durante "Pausa
  si Instagram pide frenar" (60 min). Los reintentos automáticos del transporte
  están desactivados para no repetir un 429 por detrás, y el hook
  `handle_exception` de instagrapi nunca reintenta, reloguea ni resuelve un
  challenge.
- **Ritmo humano**: antes de cada pedido, una espera variable (triangular entre
  la espera mínima de 2 s y la máxima de 6 s, más alguna distracción larga
  ocasional) y un descanso de 45–150 s cada 25 pedidos (todo en Configuración →
  Ritmo humano, solo hacia lo más lento).
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
  de la tarea dicen cuántos faltan). Topes (Configuración): 60 perfiles por
  corrida y 150 por día argentino.
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
  7 días ("Lectura completa de seguidores cada") o al forzar. **Seguidos** (a
  quién seguís) no tiene un orden garantizado, así que se lee entero como antes
  cada vez que vence el caché. Se sigue respetando "Reusar tus seguidores
  durante" (12 h sin volver a leer) y "Tope de seguidores/seguidos a leer".
- **Rescan sin volver a pedir el post**: si el post ya está guardado (mismo
  shortcode) no se pide `media_info`; el rango de fechas usa los posts que ya
  devolvió `user_medias`. Además, comentarios y likers usan el id completo del
  post cuando ya se conoce, sin la búsqueda extra que instagrapi hace por cada
  llamada (antes: 3 búsquedas del post por escaneo; ahora 1, o 0).
- **Comentarios incrementales**: se pagina de los más nuevos a los más viejos y
  se corta después de la primera página en la que **todos** los comentarios son
  iguales o anteriores al más nuevo ya guardado (`posts.last_comment_at`); uno
  viejo fijado arriba no corta. Siempre con el tope "Comentarios por post"
  (200).
- **DMs realmente incrementales**: el inbox se pagina de lo más reciente a lo
  más viejo y se corta en el primer chat sin actividad desde la sync anterior
  (los fijados no cortan); la marca es la hora de inicio de la sync anterior,
  redondeada al segundo como las horas de Instagram. **Toda** sync (primera,
  forzada o incremental) trae como máximo "Chats por sincronización" (60) = 3
  páginas, las mismas que antes; cada chat trae sus últimos 10 mensajes. Si una
  sync incremental llega a ese tope antes de alcanzar la sync anterior, la marca
  igual avanza a su hora de inicio y se avisa (log, progreso de la tarea y el
  `warning` de la tarea "Sincronizar DMs" y de "Actualizar fiesta") que los
  chats más viejos con mensajes nuevos no se sincronizaron (el tope no se puede
  subir por encima de los 60 de fábrica, S0).
