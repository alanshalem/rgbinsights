import { Modal } from '../ui/Modal';
import { AudiencePicker } from './AudiencePicker';
import { CampaignProgress } from './CampaignProgress';
import { CampaignSummary } from './CampaignSummary';
import { CautelaPicker } from './CautelaPicker';
import { MessageEditor } from './MessageEditor';
import { TestSend } from './TestSend';
import { useCampaignForm } from './useCampaignForm';

export function CampaignModal({
  event,
  eventName,
  onClose,
}: {
  event: number;
  eventName: string;
  onClose: () => void;
}) {
  const f = useCampaignForm(event, eventName);

  return (
    <Modal onClose={onClose} size="xl">
      <div>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <h2 className="display text-xl font-black tracking-tight uppercase">Campaña de DMs</h2>
            <span className="mono text-xs text-muted">{eventName}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg bg-panel-2 px-3 py-1 text-sm hover:bg-border"
          >
            Cerrar
          </button>
        </div>

        {f.showProgress && f.active ? (
          <CampaignProgress
            c={f.active}
            onStop={f.onStop}
            onResume={f.onResume}
            busy={f.progressBusy}
          />
        ) : (
          <div className="grid gap-6 text-sm lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
            {/* ================= LEFT: componer ================= */}
            <div className="flex min-w-0 flex-col gap-6">
              <MessageEditor
                templates={f.templates}
                setTemplates={f.setTemplates}
                includeLink={f.includeLink}
                setIncludeLink={f.setIncludeLink}
              />
              <AudiencePicker audience={f.audience} setAudience={f.setAudience} />
              {f.audience !== 'only' &&
                f.preview &&
                f.preview.targets_count > f.preview.follower_targets && (
                  <div className="rounded-lg border border-yellow/50 bg-yellow/10 p-2.5 text-xs text-yellow">
                    ⚠ {f.preview.targets_count - f.preview.follower_targets} de{' '}
                    {f.preview.targets_count} <strong>no te siguen</strong>. Instagram bloquea los
                    DMs a no-seguidores mucho más rápido. Lo más seguro: “Solo a los que me siguen”.
                  </div>
                )}
              <CautelaPicker
                presetName={f.presetName}
                applyPreset={f.applyPreset}
                presets={f.presets}
                params={f.params}
                setParams={f.setParams}
                preview={f.preview}
                count={f.count}
              />
            </div>

            {/* ================= RIGHT: revisar + lanzar ================= */}
            <aside className="flex min-w-0 flex-col gap-3">
              <CampaignSummary
                preview={f.preview}
                params={f.params}
                recalc={f.recalc}
                recalcBusy={f.recalcBusy}
              />
              <TestSend
                error={f.error}
                testedTo={f.testedTo}
                redUsers={f.redUsers}
                testTarget={f.testTarget}
                setTestTarget={f.setTestTarget}
                onTest={f.onTest}
                testBusy={f.testBusy}
                onLaunch={f.onLaunch}
                launchBusy={f.launchBusy}
                count={f.count}
              />
            </aside>
          </div>
        )}
      </div>
    </Modal>
  );
}
