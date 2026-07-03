# Diseño — Fiestas, semáforo por fecha y outreach

Fecha: 2026-07-03

## Contexto

La app clasifica en un semáforo (🔴🟡🟢) a la gente que comentó/likeó posts de
`@rgb.collective___`, según el estado del DM. Funciona (fuente Playwright). Ahora
se escala a **muchas fiestas**, cada una con **5-10 posts**. El semáforo hoy es
**global** por usuario; hay que volverlo **relativo a la fiesta**.

## Objetivo

Que la unidad de trabajo sea la **fiesta**: agrupar sus posts, guardarlos,
re-escanearlos de un botón, y ver el semáforo/outreach **por fiesta**, con un
corte de fecha para no arrastrar DMs de fiestas anteriores.

## Modelo de datos (SQLite)

```
events (fiestas)
  id            PK
  name          str
  promo_start   datetime   # inicio de campaña -> CORTE del semáforo
  event_date    datetime   # cuándo sucede/sucedió la fiesta (metadata/estado)
  notes         str | None
  created_at    datetime

posts
  + event_id    FK events.id | None     # un post pertenece a 0..1 fiesta

dm_threads
  - has_outgoing / has_incoming  (se derivan)
  + last_outgoing_at  datetime | None
  + last_incoming_at  datetime | None
```

Migración: columnas nuevas se agregan con `ALTER TABLE ADD COLUMN` (SQLite) sin
perder los datos ya escaneados/sincronizados. La tabla `events` es nueva.

## Regla del semáforo por fiesta

Dada una fiesta con `promo_start = D`, para cada usuario:

```
entrante = last_incoming_at is not None and last_incoming_at >= D
saliente = last_outgoing_at is not None and last_outgoing_at >= D
classify(saliente, entrante)   # función pura, sin cambios
```

- 🟢 Verde: nos contestó **después de D**.
- 🟡 Amarillo: le escribimos después de D, sin respuesta.
- 🔴 Rojo: cero interacción por DM **después de D** (aunque hayan hablado antes).

Sin fiesta seleccionada ("Todos") → corte = None → comportamiento global (alguna
vez). `event_date` no entra en el corte por ahora; queda para estado y análisis.

Limitación: la dirección sale de los ~20 mensajes recientes de cada hilo. Para
cortes de fiestas recientes es exacto; hilos muy viejos podrían perder una
respuesta fuera de esa ventana. Se documenta; si hace falta, se chequea el hilo
completo bajo demanda.

## API (cambios)

- `POST /events` — crear fiesta `{ name, promo_start, event_date, notes? }`.
- `GET /events` — listar fiestas (con conteo de posts).
- `PATCH /events/{id}` — editar.
- `POST /scan/post` y `/scan/posts` — aceptan `event_id` opcional → asignan el post.
- `POST /events/{id}/rescan` — re-escanea todos los posts de la fiesta.
- `GET /posts?event=` — posts (filtrables por fiesta), con `last_scanned_at`.
- `GET /users` — nuevo query `event=` → clasifica con el corte `promo_start`.
  Suma `engagement_count` (fan-score) y respeta filtros existentes.
- `GET /users/counts?event=` — conteos por estado (para el header, server-side).
- Paginación: `limit`/`offset` en `/users`.

## Frontend (cambios)

- **Selector de fiesta** en la barra: elegir o crear al escanear.
- **Panel de fiestas/posts**: lista de fiestas con sus posts; botón "Re-escanear
  fiesta" y por post. Estado ("próxima / pasó", "escaneado hace X").
- **Filtro por fiesta** en board/tabla; contadores del header por fiesta.
- **Vista "Por contactar"**: los 🔴 de la fiesta (lista de outreach).
- **Fan-score**: chip/orden por cantidad de posts/fiestas enganchadas.
- **Barra de progreso** de outreach por fiesta (contactados/total).
- **Paginación**: "cargar más" por columna del board; páginas en la tabla.
- **Manual in-app**: página que explica todo de punta a punta.

## Fases

1. **Fiestas + posts guardados**: modelo, migración, CRUD fiestas, scan con
   fiesta, panel de posts, re-escanear, filtro por fiesta. (back + front)
2. **Semáforo por fecha**: timestamps en dm_threads, `/users?event` con corte,
   conteos por fiesta.
3. **Outreach**: vista "por contactar", fan-score, progreso, filtro comentó/likeó.
4. **Paginación + performance**: paginación server-side, conteos, sync de DMs
   incremental + progreso.
5. **Manual in-app + extras**: página de ayuda, export CSV, plantilla de DM,
   abrir DMs en lote.

## No-goals (por ahora)

- Marcar "contactado" a mano (confiamos en la detección por DM).
- Multiusuario/auth, nube, notificaciones.

## Criterios de aceptación

- Creo una fiesta con inicio y fecha, le escaneo 5-10 posts, y veo el semáforo
  **de esa fiesta** con el corte por `promo_start`.
- Re-escaneo la fiesta de un botón, sin pegar URLs.
- Un usuario que me habló en una fiesta anterior aparece 🔴 en la fiesta nueva.
- El board pagina y no se traba con miles de usuarios.
- Un manual in-app explica cada feature.
