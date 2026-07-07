import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, toApiError, type CampaignCreate, type CampaignPreview } from '../../api/client';
import {
  useCampaign,
  usePresets,
  useResumeCampaign,
  useStopCampaign,
  useUsers,
} from '../../api/hooks';
import { toParams } from '../../lib/campaign';
import { DEFAULT_MSG, audienceToFlags, stripLinks, type Audience, type Params } from './types';

/** All the state, data and actions behind the campaign modal. Extracted so the
 * modal + its sub-panels stay presentational. Behaviour is unchanged. */
export function useCampaignForm(event: number, eventName: string) {
  const qc = useQueryClient();
  const presets = usePresets();
  const campaign = useCampaign(event);
  const stop = useStopCampaign();
  const resume = useResumeCampaign();

  const [templates, setTemplates] = useState<string[]>([DEFAULT_MSG, '', '']);
  const [presetName, setPresetName] = useState<string>('max');
  const [params, setParams] = useState<Params>({
    delay_min: 60,
    delay_max: 180,
    daily_cap: 25,
    hour_start: 11,
    hour_end: 23,
  });
  const [audience, setAudience] = useState<Audience>('only');
  const [includeLink, setIncludeLink] = useState(true);
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testedTo, setTestedTo] = useState<string | null>(null);
  const [testTarget, setTestTarget] = useState('');

  const active = campaign.data;
  const showProgress = active != null && ['running', 'paused', 'blocked'].includes(active.status);

  const flags = audienceToFlags(audience);
  const body: CampaignCreate = useMemo(
    () => ({
      templates: templates
        .map((t) => t.trim())
        .filter(Boolean)
        .map((t) => (includeLink ? t : stripLinks(t))),
      ...params,
      ...audienceToFlags(audience),
    }),
    [templates, params, audience, includeLink]
  );

  // Red list for the test-send picker (respects the audience follow filter).
  const reds = useUsers({
    event,
    status: 'red',
    follows: flags.only_followers ? true : undefined,
    order: 'followers',
    limit: 500,
  });
  const redUsers = reds.data ?? [];

  const applyPreset = (name: string) => {
    setPresetName(name);
    if (name === 'custom') return;
    // "Óptimo" is computed by the backend from the target count (finish in ~2-3
    // days at the safest pace); it rides on the preview response.
    const chosen =
      name === 'optimo' ? preview?.optimal : presets.data?.find((x) => x.name === name);
    if (chosen) setParams(toParams(chosen));
  };

  const previewMut = useMutation({
    mutationFn: () => api.previewCampaign(event, body),
    onSuccess: setPreview,
    onError: (e) => setError(toApiError(e).message),
  });
  const testMut = useMutation({
    mutationFn: () => api.testCampaign(event, body, testTarget.trim() || undefined),
    onSuccess: (r) => setTestedTo(r.username),
    onError: (e) => setError(toApiError(e).message),
  });
  const createMut = useMutation({
    mutationFn: () => api.createCampaign(event, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['campaign'] });
      void qc.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e) => setError(toApiError(e).message),
  });

  // Recalc whenever the audience or send params change (not on every keystroke
  // in the message — those are picked up by the Recalcular button).
  const settingsKey = JSON.stringify({ ...params, audience });
  useEffect(() => {
    if (!showProgress && body.templates.length > 0) previewMut.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsKey, showProgress]);

  // Keep "Óptimo" in sync: if the target count changes (e.g. the audience
  // filter), re-apply the freshly computed sweet-spot params.
  const optimalCap = preview?.optimal?.daily_cap;
  const optimalDelay = preview?.optimal?.delay_min;
  useEffect(() => {
    if (presetName === 'optimo' && preview?.optimal) applyPreset('optimo');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimalCap, optimalDelay]);

  const launch = () => {
    setError(null);
    const n = preview?.targets_count ?? 0;
    if (
      !confirm(
        `Vas a enviar DMs a ${n} rojos de "${eventName}". Enviar masivo tiene riesgo de ban. ¿Confirmás?`
      )
    )
      return;
    createMut.mutate();
  };

  const recalc = () => {
    setError(null);
    previewMut.mutate();
  };
  const onTest = () => {
    setTestedTo(null);
    setError(null);
    testMut.mutate();
  };

  return {
    // form state
    templates,
    setTemplates,
    presetName,
    applyPreset,
    params,
    setParams,
    audience,
    setAudience,
    includeLink,
    setIncludeLink,
    testTarget,
    setTestTarget,
    // data
    preview,
    presets: presets.data ?? [],
    redUsers,
    count: preview?.targets_count ?? redUsers.length,
    // status / feedback
    error,
    testedTo,
    showProgress,
    active,
    // actions
    recalc,
    recalcBusy: previewMut.isPending,
    onTest,
    testBusy: testMut.isPending,
    onLaunch: launch,
    launchBusy: createMut.isPending,
    onStop: () => active && stop.mutate(active.id),
    onResume: () => active && resume.mutate(active.id),
    progressBusy: stop.isPending || resume.isPending,
  };
}

export type CampaignForm = ReturnType<typeof useCampaignForm>;
