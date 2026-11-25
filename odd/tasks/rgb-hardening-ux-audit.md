# UX audit for T8 (S24)

Read-only audit (explore task mwvewe0b-l-usiw, gentle-ui-design guidance). Implement in T8 after T6b. Keep the dark neon identity; clarity, not redesign. No item may add Instagram requests (S0).

## Parent decisions (L18)
- Campaign default preset: keep the safest preset as the default and make the recommendation say the same thing everywhere (CautelaPicker card label, CampaignSummary risk box, HelpPage): "Máxima cautela (recomendado)". Verify which preset key is the slowest/safest in frontend/src/components/campaign/types.ts and backend campaign presets; default `useCampaignForm` to it.
- `includeLink` default stays as today (true); add a one-line risk hint next to the checkbox instead of changing the default.
- Toasts read the task warning from `task.warning` (new TaskOut field from T6a) with fallback to `result.aviso` (L17).

## Top 10
1. Test DM is a real DM to a real lead — TestSend.tsx:44 "Probá primero: mandá 1 DM (por defecto, al primero de la lista)"; backend sends to the first red or a username in the red list (backend campaigns router test_send). Copy: "⚠ Es un DM real: le llega a esa persona. Elegí a alguien de confianza que te siga." Button: "Enviar 1 DM real de prueba". Confirm in backend whether the target turns 🟡 immediately or after the next sync and say it accurately.
2. First run has no guidance — Board.tsx:67 bare "—"; add a 3-step card when there are 0 fiestas / 0 users: "1. Creá una fiesta · 2. Pegá los links de sus posts y tocá Escanear · 3. Actualizar ▾ → Sincronizar DMs" with ✓ per step from events/counts data; empty column text "Nadie en {Rojo} todavía".
3. Campaign status in raw English — CampaignProgress.tsx:25 `{c.status}`; map running/paused/blocked/done/... to "Enviando", "Pausada", "Frenada por Instagram", "Terminada" (check all statuses in backend); show the label in CampaignToast too.
4. Toasts: errors vanish after 7 s and can't be closed — Toasts.tsx:214; keep error toasts until ✕, add ✕ to every toast, container role="status" aria-live="polite", errors role="alert".
5. Actualizar menu jargon and unexplained disabled state — ActionsMenu.tsx:113,120,96: labels "Sincronizar DMs — actualiza los colores", "Re-escanear la fiesta — posts nuevos + DMs", "Quién te sigue + seguidores (lento)"; disabled hint "Elegí una fiesta arriba"; busy label by running job kind; force checkbox "Traer todo de cero (más lento y más pedidos a Instagram; usalo solo si algo quedó mal)"; aria-expanded/aria-haspopup; Escape closes.
6. Bug: UsersTable.tsx:22 page reset deps miss `query.follows` → "Página 3 de 1" empty table.
7. Filtered empty states — UsersTable.tsx:31 says "Sin usuarios. Escaneá un post para empezar." even when search/"Solo seguidores" hides results; Board has no no-results state. Show "Nadie coincide con “{search}”{ · solo seguidores}" + "Limpiar filtros" button.
8. Campaign recommendation inconsistent — useCampaignForm.ts:24 default 'max' vs "Óptimo (recomendado)" (types.ts) vs CampaignSummary "empezá con Óptimo o Máxima" vs HelpPage.tsx:171,175 (mentions checkboxes that are radios). Apply L18 decision; fix Help wording.
9. Help troubleshooting tells users to run a terminal command — HelpPage.tsx:199 `.venv\Scripts\python.exe -m app.login_browser` (also check it still exists). Replace with in-app flow: "Tocá el chip IG arriba a la derecha → Volver a conectar. Si no anda, “Pegá tu sesión” y seguí los pasos." Add Help sections: "IG en pausa hasta las HH:MM" (cooldown, breaker), "Campaña pausada / frenada", "Exportar".
10. Export scope/confirmation — ExportButtons.tsx:39 scope only in a tooltip; labels "⬇ Excel" / "⬇ PDF", caption "Baja lo que ves: {fiesta|Todas} · {N} personas{ · filtros}", disabled at 0 rows ("No hay nada para exportar"), success toast "Listo: se descargó la lista ({N})".

## Other findings
- Hierarchy (App.tsx:85-131): 3 neon buttons compete (Actualizar, Campaña, Escanear). Row 1 fiesta context (select + dates + progress), row 2 actions; Escanear the only filled/glowing button while the fiesta has 0 posts.
- App.tsx:111 hides Campaña when no fiesta → show disabled with "Elegí una fiesta para armar una campaña".
- App.tsx:121 "campaña 01 nov → evento…" confuses promo period with DM campaign → "Promo desde 01 nov · fiesta 15 nov (próxima)".
- App.tsx:129 "contactaste 40/120" → "Contactados 40 de 120 (33%)" with tooltip "🟡 + 🟢".
- App.tsx:162 "¿Está corriendo el backend en :8000?" → "No se pudo conectar con la app. Cerrala y abrila de nuevo."
- Color legend: add one-line legend above the table "🔴 a escribir · 🟡 le escribiste, no contestó · 🟢 te contestó"; title/aria on TrafficChip and Navbar counts; identical plain wording everywhere (lib/user.ts LIGHT_HINT, Help).
- Jargon: FilterBar.tsx:52 "Board" → "Tarjetas"; FilterBar.tsx:88 "Orden: fans 🔥" → "Orden: más interacciones 🔥"; UsersTable.tsx:44-45 "🔥" header → "Posts", "Engagement" → "Interacción"; types.ts:15 "Custom" → "A mano"; CautelaPicker.tsx:99+ "delay min (s)" → "Espera mínima entre DMs (seg)", "tope/día" → "Máximo por día"; picker title "Velocidad de envío (más lento = más seguro)"; ActivityPage.tsx:8,10 labels share one map with Toasts KIND and menu labels; PostsDrawer "↻ Re-escanear fiesta" vs menu "Actualizar fiesta" — one name + hint; Toasts.tsx:74 "sin novedades ·" stray dot → "Sin cambios".
- UserCard: UserCard.tsx:57 red "🔥 N" badge reads as Rojo → neutral/blue + "🔥 N posts"; :72 "🌟 1.2k" → "1.2k seguidores"; :35 "3/5 posts" → "3 de 5 posts"; ✔️/🔒 add aria-label.
- Long jobs: ScanBar.tsx:51 and PostsDrawer "Esperá…" only on hover → inline text "Hay una tarea de Instagram en curso (abajo a la derecha). Esperá que termine."; ScanBar.tsx:43 placeholder "Pegá el link de un post (instagram.com/p/…)".
- IgSession: modal header dot ignores cooldown (IgSession.tsx:193) → same dot logic as chip; hide stale last_error when connected or show "(hace X)"; "Reconectar igual" → "Volver a conectar"; narrow widths (IgSession.tsx:184, Navbar.tsx:37) keep short text "IG ✓"/"IG ⏸" and aria-labels on counts.
- ResetModal.tsx:36 raw table names → Spanish labels. Campaign launch confirm repeats audience + ETA: "Vas a mandar 84 DMs (solo seguidores), ~3 días. ¿Arrancamos?".
- ErrorBanner.tsx: add ✕ close, drop "Error:" prefix (:22).
- FiestaModal: validate event date ≥ promo start, autofocus name, hint under "Inicio de campaña": "El día que empezaste a publicar esta fiesta", title in display style like other modals.
- Accessibility: avoid 10–11 px text (ActionsMenu.tsx:48, chips); Navbar page buttons aria-current; Modal focus trap + return focus to trigger; disable the custom Cursor inside modals/forms (index.css cursor:none).
