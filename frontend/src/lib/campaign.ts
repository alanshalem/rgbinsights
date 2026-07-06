// Client-side mirror of backend app/application/campaign.py `estimate()`.
// Lets the setup screen show each preset's ETA without a round-trip per preset.
// Keep the formula in sync with the backend (there's a unit test on that side).

export type SendParams = {
  delay_min: number;
  delay_max: number;
  daily_cap: number;
  hour_start: number;
  hour_end: number;
};

export type LocalEstimate = {
  per_day: number;
  days: number;
  avg_delay_seconds: number;
  window_hours: number;
  minutes_per_day: number;
};

/** Pull the 5 send knobs out of a preset/optimal object (which also carries a
 * `name` and possibly extra fields). One place to keep the shape in sync. */
export function toParams(p: {
  delay_min: number;
  delay_max: number;
  daily_cap: number;
  hour_start: number;
  hour_end: number;
}): SendParams {
  return {
    delay_min: p.delay_min,
    delay_max: p.delay_max,
    daily_cap: p.daily_cap,
    hour_start: p.hour_start,
    hour_end: p.hour_end,
  };
}

export function estimateFor(count: number, p: SendParams): LocalEstimate {
  const avg = (p.delay_min + p.delay_max) / 2;
  const windowHours = (p.hour_end - p.hour_start) % 24 || 24;
  const maxByTime = avg > 0 ? Math.floor((windowHours * 3600) / avg) : count;
  const perDay = Math.max(1, Math.min(p.daily_cap, maxByTime));
  const days = count > 0 ? Math.ceil(count / perDay) : 0;
  return {
    per_day: perDay,
    days,
    avg_delay_seconds: avg,
    window_hours: windowHours,
    minutes_per_day: Math.round((perDay * avg) / 6) / 10,
  };
}

/** "1 cada ~2 min" style gap. */
export function fmtGap(seconds: number): string {
  return seconds >= 90 ? `~${Math.round(seconds / 60)} min` : `~${Math.round(seconds)}s`;
}
