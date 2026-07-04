import type { ReactNode } from 'react';

const SECTIONS: { id: string; title: string }[] = [
  { id: 'que-es', title: 'Qué es' },
  { id: 'semaforo', title: 'El semáforo' },
  { id: 'fiestas', title: 'Fiestas' },
  { id: 'paso-a-paso', title: 'Paso a paso' },
  { id: 'acciones', title: 'Las acciones' },
  { id: 'seguidores', title: 'Te sigue y perfiles' },
  { id: 'campana', title: 'Campaña de DMs' },
  { id: 'progreso', title: 'Progreso y actividad' },
  { id: 'problemas', title: 'Si algo falla' },
];

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="mb-8 scroll-mt-20">
      <h2 className="display mb-2 text-lg font-black tracking-tight uppercase">{title}</h2>
      <div className="flex flex-col gap-2 text-sm text-[var(--color-ink)]/85">{children}</div>
    </section>
  );
}

export function HelpPage({ onBack }: { onBack: () => void }) {
  return (
    <div className="mx-auto max-w-5xl p-4 md:p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          <span className="rgb-gradient">Ayuda</span> · manual de uso
        </h1>
        <button
          onClick={onBack}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-sm hover:bg-[var(--color-panel)]"
        >
          ← Volver al panel
        </button>
      </div>

      <div className="flex gap-8">
        <nav className="hidden w-48 shrink-0 md:block">
          <ul className="sticky top-20 flex flex-col gap-1 text-sm">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="block rounded px-2 py-1 text-[var(--color-muted)] hover:bg-[var(--color-panel)] hover:text-[var(--color-ink)]"
                >
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 flex-1">
          <Section id="que-es" title="Qué es">
            <p>
              Lista a la gente que <b>comentó o likeó</b> los posts de <b>@rgb.collective___</b> y
              la clasifica en un semáforo según el estado de la conversación por DM. Es una
              herramienta de <b>outreach</b>: a quién escribirle para invitarlo a la fiesta, y a
              quién ya le hablaste.
            </p>
            <p>Corre local en tu máquina, sin usuarios ni nube.</p>
          </Section>

          <Section id="semaforo" title="El semáforo 🔴🟡🟢">
            <p>
              🔴 <b>Rojo</b>: enganchó el post pero <b>no hubo DM</b> — es a quién escribir.
            </p>
            <p>
              🟡 <b>Amarillo</b>: le escribiste y <b>no contestó</b>.
            </p>
            <p>
              🟢 <b>Verde</b>: <b>te contestó</b> — conversación real.
            </p>
          </Section>

          <Section id="fiestas" title="Fiestas (la unidad de trabajo)">
            <p>
              Cada fiesta agrupa sus posts (5-10). Tiene un <b>inicio de campaña</b> (cuándo
              empezaste a publicar) y una <b>fecha de evento</b>.
            </p>
            <p>
              El semáforo <b>de una fiesta</b> cuenta los DMs <b>desde el inicio de campaña</b>: si
              a alguien le hablaste en una fiesta <i>anterior</i>, para la fiesta nueva vuelve a 🔴
              — hay que re-invitarlo. Sin fiesta seleccionada (“Todas”), el semáforo es global.
            </p>
            <p>
              El selector de fiesta arriba maneja todo: <b>filtra</b> el board <b>y</b> es a dónde
              van los posts que escaneás.
            </p>
          </Section>

          <Section id="paso-a-paso" title="Paso a paso">
            <p>
              <b>1.</b> Creá una fiesta (<b>+ Nueva fiesta</b>) con nombre y fechas.
            </p>
            <p>
              <b>2.</b> Con esa fiesta elegida, pegá las URLs de sus posts → <b>Escanear</b>.
            </p>
            <p>
              <b>3.</b> <b>Actualizar ▾ → Sincronizar DMs</b> (trae el estado de las charlas).
            </p>
            <p>
              <b>4.</b> Los 🔴 de la fiesta son tu lista. Tocá <b>Abrir DM</b>.
            </p>
            <p>
              <b>5.</b> (opcional) <b>Actualizar ▾ → Relación + perfiles</b> para ver quién te sigue
              y los seguidores.
            </p>
          </Section>

          <Section id="acciones" title="Las acciones (Actualizar ▾)">
            <p>Cada una hace algo distinto, de más rápida a más lenta:</p>
            <p>
              <b>Escanear</b> — trae likers + comentarios de los posts que pegás. Solo cuando
              agregás posts nuevos.
            </p>
            <p>
              <b>Sincronizar DMs</b> — refresca el semáforo (rápido, ~1 min). Global.
            </p>
            <p>
              <b>Actualizar fiesta</b> — re-escanea los posts guardados de la fiesta <b>+</b>{' '}
              sincroniza DMs. Sin pegar URLs.
            </p>
            <p>
              <b>Relación + perfiles</b> — lento, opcional: trae <b>te sigue</b> (lee tu lista de
              seguidores) + seguidores/verificado/bio.
            </p>
          </Section>

          <Section id="seguidores" title="Te sigue, seguidores y filtros">
            <p>
              El chip <b>te sigue</b> / <b>mutuo</b> aparece después de <b>Relación + perfiles</b>.
              Un 🔴 que te sigue es lead más caliente <b>y</b> más seguro para escribirle.
            </p>
            <p>
              El chip <b>🌟</b> es la cantidad de seguidores (para detectar DJs/influencers). Ordená
              por <b>seguidores 🌟</b> o <b>fans 🔥</b> (cuántos posts enganchó), y filtrá{' '}
              <b>Solo seguidores</b>.
            </p>
          </Section>

          <Section id="campana" title="Campaña de DMs (envío masivo, con cuidado)">
            <p>
              <b>✉ Campaña de DMs</b> manda un mensaje (con variantes y {'{nombre}'}) a los 🔴 de la
              fiesta, <b>lento</b> para no arriesgar la cuenta: elegís cautela (máxima/media), ves
              ETA, mandás 1 de prueba, y lanzás.
            </p>
            <p>
              Tildá <b>seguidores primero</b> o <b>solo a los que me siguen</b> — DMs a seguidores
              son <b>mucho menos riesgosos</b>. Se frena solo si Instagram avisa.
            </p>
            <p className="text-[var(--color-red)]">
              Enviar masivo es la acción más riesgosa de Instagram. Empezá con máxima cautela y no
              lo hagas todos los días.
            </p>
          </Section>

          <Section id="progreso" title="Progreso y actividad">
            <p>
              Toda acción larga muestra un <b>toast abajo a la derecha</b> con el avance en vivo y
              el resultado al terminar.
            </p>
            <p>
              La página <b>Actividad</b> (arriba) guarda el historial: qué corrió, cuándo, y si
              anduvo o falló.
            </p>
          </Section>

          <Section id="problemas" title="Si algo falla">
            <p>
              <b>“Instagram pide verificación”</b> (cartel amarillo): la sesión del navegador se
              venció. En una terminal: <code>cd backend</code> y{' '}
              <code>.venv\Scripts\python.exe -m app.login_browser</code>, logueate, y reintentá.
            </p>
            <p>
              <b>Todo lento o se frena</b>: es a propósito (pausas anti-bloqueo). No corras dos
              cosas pesadas a la vez.
            </p>
            <p>
              <b>No aparecen “te sigue”</b>: corré <b>Actualizar ▾ → Relación + perfiles</b> (no
              sale del sync).
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}
