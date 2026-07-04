import type { ReactNode } from 'react';
import { Modal } from './Modal';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="mb-1.5 font-semibold text-[var(--color-ink)]">{title}</h3>
      <div className="flex flex-col gap-1.5 text-sm text-[var(--color-ink)]/80">{children}</div>
    </section>
  );
}

export function Manual({ onClose }: { onClose: () => void }) {
  return (
    <Modal onClose={onClose} size="lg">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold">
            <span className="rgb-gradient">Manual</span> · cómo usar el Semáforo
          </h2>
          <button
            onClick={onClose}
            className="rounded-lg bg-[var(--color-panel-2)] px-3 py-1 text-sm hover:bg-[var(--color-border)]"
          >
            Cerrar
          </button>
        </div>

        <Section title="¿Qué hace esta app?">
          <p>
            Lista a la gente que <b>comentó o likeó</b> los posts de <b>@rgb.collective___</b> y la
            clasifica en un semáforo según el estado de la conversación por DM. Sirve para hacer{' '}
            <b>outreach</b>: saber a quién escribirle para invitarlo a la fiesta y a quién ya le
            hablaste.
          </p>
        </Section>

        <Section title="El semáforo 🔴🟡🟢">
          <p>
            🔴 <b>Rojo</b>: enganchó el post pero <b>no hubo DM</b> — es a quien tenés que escribir.
          </p>
          <p>
            🟡 <b>Amarillo</b>: le escribiste y <b>no contestó</b>.
          </p>
          <p>
            🟢 <b>Verde</b>: <b>te contestó</b> — conversación real.
          </p>
        </Section>

        <Section title="Fiestas (lo más importante)">
          <p>
            Cada fiesta agrupa sus 5-10 posts. Tiene un <b>inicio de campaña</b> (cuándo empezaste a
            publicar) y una <b>fecha de evento</b>.
          </p>
          <p>
            El semáforo <b>de una fiesta</b> cuenta los DMs <b>desde el inicio de campaña</b>: si a
            alguien le hablaste en una fiesta <i>anterior</i>, para la fiesta nueva aparece 🔴 (lo
            tenés que volver a contactar).
          </p>
          <p>
            Elegí la fiesta en el selector de arriba: eso filtra el board <b>y</b> es a dónde van
            los posts que escanees.
          </p>
        </Section>

        <Section title="Paso a paso">
          <p>
            <b>1.</b> Creá una fiesta (botón <b>+ Nueva</b>) con nombre y fechas.
          </p>
          <p>
            <b>2.</b> Con esa fiesta seleccionada, pegá las URLs de sus posts y tocá <b>Escanear</b>
            . Quedan guardados en la fiesta.
          </p>
          <p>
            <b>3.</b> Tocá <b>Sincronizar DMs</b> (tarda ~1 min, trae el estado de las charlas).
          </p>
          <p>
            <b>4.</b> Mirá el board. Los 🔴 de la fiesta son tu lista de a quién escribir. Tocá{' '}
            <b>Abrir DM</b>.
          </p>
        </Section>

        <Section title="Actualizar / re-escanear">
          <p>
            Con una fiesta seleccionada, el botón <b>↻ Actualizar fiesta</b> (arriba) hace todo de
            una: re-trae likers/comentarios de <b>todos</b> sus posts <b>y</b> sincroniza los DMs.
            No hace falta pegar URLs ni tocar “Sincronizar DMs” por separado.
          </p>
          <p>
            En el panel de <b>Posts</b> también está <b>↻ Re-escanear fiesta</b> si solo querés
            refrescar los posts (sin DMs).
          </p>
        </Section>

        <Section title="Progreso, fan-score y filtros">
          <p>
            La <b>barra de progreso</b> muestra a cuántos de la fiesta ya contactaste (amarillos +
            verdes sobre el total).
          </p>
          <p>
            El chip <b>🔥 N</b> es el <b>fan-score</b>: cuántos posts enganchó esa persona. Ordená
            por <b>Fans</b> para priorizar a los habitués.
          </p>
          <p>
            Filtrá por estado, buscá por usuario/nombre, y cambiá entre <b>Board</b> y <b>Tabla</b>.
          </p>
        </Section>

        <Section title="Seguidores y perfiles">
          <p>
            Al sincronizar DMs se trae si cada uno <b>te sigue</b> (chip <b>te sigue</b> /{' '}
            <b>mutuo</b>). Un rojo que te sigue es lead más caliente <b>y</b> más seguro para
            escribirle.
          </p>
          <p>
            <b>🌟 Enriquecer perfiles</b> trae seguidores, verificado y bio (lento, opcional) →
            detectás influencers/DJs. Ordená por <b>seguidores 🌟</b> o filtrá{' '}
            <b>Solo seguidores</b>.
          </p>
        </Section>

        <Section title="Campaña de DMs (envío masivo, con cuidado)">
          <p>
            En una fiesta, <b>✉ Campaña de DMs</b> manda un mensaje (con variantes y {'{nombre}'}) a
            los rojos, <b>lento</b> para no arriesgar la cuenta: elegís cautela (máxima/media), ves
            ETA, mandás 1 de prueba, y lanzás.
          </p>
          <p>
            Tildá <b>seguidores primero</b> o <b>solo a los que me siguen</b> — DMs a seguidores son
            <b> mucho menos riesgosos</b>. Se frena solo si Instagram avisa.
          </p>
        </Section>

        <Section title="Si Instagram pide verificación">
          <p>
            Si aparece un cartel amarillo de “verificación”, la sesión del navegador se venció. En
            una terminal, corré <code>python -m app.login_browser</code>, logueate, y reintentá.
          </p>
        </Section>
      </div>
    </Modal>
  );
}
