import type { ReactNode } from 'react';
import type { TrafficLight } from '../api/client';
import { JOB_META } from '../lib/jobs';
import { LIGHT_HINT, LIGHT_LABEL, LIGHTS } from '../lib/user';
import { PRESET_LABEL, RECOMMENDED_PRESET } from './campaign/types';

const EMOJI: Record<TrafficLight, string> = { red: '🔴', yellow: '🟡', green: '🟢' };

const SECTIONS: { id: string; title: string }[] = [
  { id: 'que-es', title: 'Qué es' },
  { id: 'semaforo', title: 'El semáforo' },
  { id: 'fiestas', title: 'Fiestas' },
  { id: 'paso-a-paso', title: 'Paso a paso' },
  { id: 'acciones', title: 'Las acciones' },
  { id: 'seguidores', title: 'Te sigue y seguidores' },
  { id: 'exportar', title: 'Exportar Excel / PDF' },
  { id: 'campana', title: 'Campaña de DMs' },
  { id: 'campana-pausada', title: 'Campaña pausada o frenada' },
  { id: 'ig-pausa', title: 'IG en pausa' },
  { id: 'progreso', title: 'Avisos y actividad' },
  { id: 'problemas', title: 'Si algo falla' },
];

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="mb-8 scroll-mt-20">
      <h2 className="display mb-2 text-lg font-black tracking-tight uppercase">{title}</h2>
      <div className="flex flex-col gap-2 text-sm text-ink/85">{children}</div>
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
          type="button"
          onClick={onBack}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-panel"
        >
          ← Volver al panel
        </button>
      </div>

      <div className="flex gap-8">
        <nav aria-label="Secciones de la ayuda" className="hidden w-48 shrink-0 md:block">
          <ul className="sticky top-20 flex flex-col gap-1 text-sm">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="block rounded px-2 py-1 text-muted hover:bg-panel hover:text-ink"
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
              la ordena en un semáforo según cómo va la charla por DM: a quién escribirle para
              invitarlo a la fiesta, y a quién ya le hablaste.
            </p>
            <p>Corre en tu compu, sin cuentas ni nube.</p>
          </Section>

          <Section id="semaforo" title="El semáforo 🔴🟡🟢">
            {LIGHTS.map((l) => (
              <p key={l}>
                {EMOJI[l]} <b>{LIGHT_LABEL[l]}</b>: {LIGHT_HINT[l].toLowerCase()}.
              </p>
            ))}
            <p>
              Los colores salen de tus DMs y se actualizan con{' '}
              <b>Actualizar ▾ → {JOB_META.sync.title}</b>. Si le escribís a alguien (a mano o con
              una campaña), sigue en 🔴 hasta la próxima vez que sincronices.
            </p>
          </Section>

          <Section id="fiestas" title="Fiestas (la unidad de trabajo)">
            <p>
              Cada fiesta agrupa sus posts (5-10). Tiene un <b>inicio de la promo</b> (el día que
              empezaste a publicarla) y una <b>fecha de la fiesta</b>.
            </p>
            <p>
              El semáforo <b>de una fiesta</b> cuenta los DMs <b>desde el inicio de la promo</b>: si
              a alguien le hablaste por una fiesta <i>anterior</i>, para la nueva vuelve a 🔴 — hay
              que volver a invitarlo. Con <b>Todas las fiestas</b>, el semáforo cuenta todos los
              DMs.
            </p>
            <p>
              El selector de fiesta de arriba maneja todo: <b>filtra</b> la lista <b>y</b> es a
              dónde van los posts que escaneás.
            </p>
          </Section>

          <Section id="paso-a-paso" title="Paso a paso">
            <p>
              Mientras falte algo, el panel muestra <b>Cómo empezar</b> con estos pasos y los va
              tildando solo.
            </p>
            <p>
              <b>1.</b> Creá una fiesta (<b>+ Nueva fiesta</b>) con nombre y fechas.
            </p>
            <p>
              <b>2.</b> Con esa fiesta elegida, pegá los links de sus posts y tocá <b>Escanear</b>.
            </p>
            <p>
              <b>3.</b> <b>Actualizar ▾ → {JOB_META.sync.title}</b> (trae cómo va cada charla).
            </p>
            <p>
              <b>4.</b> Los 🔴 de la fiesta son tu lista. Tocá <b>Abrir DM</b> o <b>Ver perfil</b>.
            </p>
            <p>
              <b>5.</b> (opcional) <b>Actualizar ▾ → {JOB_META.enrich.title}</b> para ver quién te
              sigue y cuántos seguidores tiene cada uno.
            </p>
          </Section>

          <Section id="acciones" title="Las acciones">
            <p>Cada una hace algo distinto, de más rápida a más lenta:</p>
            <p>
              <b>Escanear</b> (al lado de donde pegás los links) — trae los likes y comentarios de
              los posts que pegás. Solo cuando sumás posts nuevos.
            </p>
            <p>
              <b>{JOB_META.sync.title}</b> (en Actualizar ▾) — actualiza los colores del semáforo.
              Rápido.
            </p>
            <p>
              <b>{JOB_META.refresh.title}</b> (en Actualizar ▾) — vuelve a leer los posts que ya
              tiene la fiesta (likes y comentarios nuevos) <b>y</b> sincroniza DMs. Sin pegar links.
            </p>
            <p>
              <b>{JOB_META.rescan.title}</b> (en <b>Ver posts</b>) — lo mismo, pero sin DMs: solo
              likes y comentarios nuevos.
            </p>
            <p>
              <b>{JOB_META.enrich.title}</b> (en Actualizar ▾) — lento y opcional: marca quién{' '}
              <b>te sigue</b> (lee tu lista de seguidores) y trae seguidores, verificado y bio.
            </p>
            <p>
              Cada opción del menú muestra <b>la última vez</b> que se hizo. Para pedirle menos a
              Instagram (y bajar el riesgo de bloqueo) la app <b>reusa lo reciente</b>: tu lista de
              seguidores se reusa ~12 h, los DMs traen solo lo que cambió, y no vuelve a leer un
              post visto hace poco. Si algo quedó mal, tildá <b>“Traer todo de cero”</b> (más lento
              y más pedidos a Instagram).
            </p>
            <p>
              La app hace <b>una tarea de Instagram a la vez</b>: mientras corre una, los otros
              botones esperan y te lo dicen.
            </p>
          </Section>

          <Section id="seguidores" title="Te sigue, seguidores y filtros">
            <p>
              El chip <b>te sigue</b> / <b>mutuo</b> aparece después de{' '}
              <b>{JOB_META.enrich.title}</b>. Un 🔴 que te sigue es el mejor para escribirle: más
              interesado <b>y</b> más seguro para la cuenta.
            </p>
            <p>
              <b>1.2k seguidores</b> es cuántos seguidores tiene esa persona (sirve para detectar
              DJs o influencers). <b>🔥 3 posts</b> es con cuántos posts interactuó en total. Ordená
              por <b>más seguidores</b> o <b>más interacciones 🔥</b>, y filtrá con{' '}
              <b>Solo seguidores</b>. Si nadie coincide, tocá <b>Limpiar filtros</b>.
            </p>
            <p>
              Podés ver la lista como <b>Tarjetas</b> (una columna por color) o como <b>Tabla</b>{' '}
              (con filtro por color).
            </p>
          </Section>

          <Section id="exportar" title="Exportar Excel / PDF">
            <p>
              <b>⬇ Excel</b> y <b>⬇ PDF</b> (en la barra de filtros) bajan{' '}
              <b>lo que estás viendo</b>: la misma fiesta, búsqueda, filtros y orden, con{' '}
              <b>todas</b> las filas (no solo las cargadas). Al lado dice qué vas a bajar y cuántas
              personas son. En <b>Tarjetas</b> sale agrupado por color (🔴 → 🟡 → 🟢). Trae usuario
              con link al perfil, nombre, color, si te sigue, seguidores, likes/comentarios y el
              link de DM. Sale de lo que ya está guardado: <b>no le pide nada a Instagram</b>.
            </p>
            <p>
              Ideal para pasárselo a las publicas: el <b>link al perfil</b> les sirve a todas; el{' '}
              <b>link de DM</b> abre el chat de la cuenta de RGB (solo funciona logueado con esa
              cuenta).
            </p>
          </Section>

          <Section id="campana" title="Campaña de DMs (envío masivo, con cuidado)">
            <p>
              <b>✉ Campaña de DMs</b> manda un mensaje (con varias versiones y {'{nombre}'}) a los
              🔴 de la fiesta, <b>lento</b> para no arriesgar la cuenta. Primero elegí una fiesta.
            </p>
            <p>
              Elegís <b>a quién</b> (una sola opción): <b>Solo a los que me siguen</b>{' '}
              (recomendado), <b>Seguidores primero</b> o <b>Todos, sin orden</b>. Los DMs a
              seguidores son <b>mucho menos riesgosos</b>.
            </p>
            <p>
              Elegís la <b>velocidad de envío</b>: <b>{PRESET_LABEL[RECOMMENDED_PRESET]}</b> viene
              elegida y es la más segura. <b>{PRESET_LABEL.optimo}</b> calcula el ritmo para
              terminar en 2-3 días (con listas grandes manda más DMs por día).{' '}
              <b>{PRESET_LABEL.custom}</b> te deja poner los números vos. Las horas son de
              Argentina.
            </p>
            <p>
              <b>Enviar 1 DM real de prueba</b>: le llega de verdad a esa persona, así que elegí a
              alguien de confianza que te siga. Sigue en 🔴 hasta la próxima vez que hagas{' '}
              <b>{JOB_META.sync.title}</b>: si lanzás la campaña antes, también le llega el mensaje
              de la campaña.
            </p>
            <p className="text-red">
              Mandar muchos DMs es lo más riesgoso en Instagram. Empezá con{' '}
              {PRESET_LABEL[RECOMMENDED_PRESET]}, sin link en el primer mensaje, y no lo hagas todos
              los días.
            </p>
          </Section>

          <Section id="campana-pausada" title="Campaña pausada o frenada">
            <p>
              <b>Pausada</b>: la pausaste vos, o la app la pausó sola para cuidar la cuenta (se cayó
              la sesión, Instagram pidió frenar o bloqueó tu conexión). El motivo aparece en la
              campaña. Arreglalo (chip <b>IG</b> arriba a la derecha) y tocá <b>Reanudar</b>.
            </p>
            <p>
              <b>Frenada por Instagram</b>: Instagram bloqueó el envío de DMs. <b>No reanudes</b>{' '}
              hasta que pase (suele durar 12 a 48 h): probar antes lo alarga.
            </p>
            <p>
              <b>Terminada</b>: ya se mandaron todos. Una campaña sigue sola mientras la app esté
              abierta en tu compu.
            </p>
          </Section>

          <Section id="ig-pausa" title="“IG en pausa hasta las HH:MM”">
            <p>
              El chip <b>IG</b> de arriba se pone amarillo y dice <b>IG en pausa hasta las …</b>{' '}
              cuando la app deja de pedirle cosas a Instagram por un rato, a propósito: porque
              Instagram pidió frenar, o porque falló la conexión y espera antes de volver a probar
              (15 min, después 1 h, después 6 h).
            </p>
            <p>
              No hace falta que hagas nada: esperá a que pase esa hora y después volvé a usar las
              acciones (una campaña pausada se reanuda a mano). Insistir antes no sirve y es lo que
              más llama la atención de Instagram.
            </p>
          </Section>

          <Section id="progreso" title="Avisos y actividad">
            <p>
              Toda acción larga muestra un <b>aviso abajo a la derecha</b> con el avance en vivo y
              el resultado al terminar. Los avisos de error quedan hasta que los cerrás con <b>✕</b>
              .
            </p>
            <p>
              La página <b>Actividad</b> (arriba) guarda el historial: qué se hizo, cuándo, y si
              salió bien o falló.
            </p>
          </Section>

          <Section id="problemas" title="Si algo falla">
            <p>
              <b>“Instagram pide verificación”</b> (cartel amarillo) o <b>IG desconectado</b>: entrá
              a la cuenta desde el celu y confirmá que sos vos. Después tocá el chip <b>IG</b>{' '}
              arriba a la derecha → <b>Volver a conectar</b>. Si no anda, tocá{' '}
              <b>“Pegá tu sesión”</b> y seguí los pasos que aparecen ahí.
            </p>
            <p>
              <b>“No se pudo conectar con la app”</b>: cerrá la app y abrila de nuevo.
            </p>
            <p>
              <b>Todo lento o se frena</b>: es a propósito (pausas para que Instagram no lo vea como
              un robot). La app hace una sola cosa de Instagram a la vez.
            </p>
            <p>
              <b>No aparece “te sigue”</b>: hacé <b>Actualizar ▾ → {JOB_META.enrich.title}</b> (no
              sale de sincronizar DMs).
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}
