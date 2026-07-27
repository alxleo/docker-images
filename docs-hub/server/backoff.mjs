export const UNCHANGED_MINUTES = Object.freeze([10, 15, 30, 60, 120]);
export const ERROR_MINUTES = Object.freeze([5, 10, 15, 30, 60]);
export const CHANGED_MINUTES = 5;

export function nextDelayMinutes(kind, attempt = 0) {
  if (kind === "changed") return CHANGED_MINUTES;
  const schedule = kind === "error" ? ERROR_MINUTES : UNCHANGED_MINUTES;
  return schedule[Math.min(Math.max(attempt, 0), schedule.length - 1)];
}

export function advanceState(previous, outcome, now = Date.now()) {
  const priorAttempt = Number(previous?.attempt ?? 0);
  const attempt = outcome === "changed" ? 0 : priorAttempt + 1;
  const minutes = nextDelayMinutes(outcome, outcome === "changed" ? 0 : priorAttempt);
  return {
    attempt,
    outcome,
    checkedAt: new Date(now).toISOString(),
    nextCheckAt: new Date(now + minutes * 60_000).toISOString()
  };
}
