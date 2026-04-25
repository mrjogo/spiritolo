import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Wrap vi.useFakeTimers to auto-set 'nextTimerAsync' tick mode. Required so
// @testing-library/user-event's internal `setTimeout(..., 0)` waits resolve
// while fake timers are active — otherwise user.click / user.type hang.
const originalUseFakeTimers = vi.useFakeTimers.bind(vi);
vi.useFakeTimers = ((config?: Parameters<typeof originalUseFakeTimers>[0]) => {
  const result = originalUseFakeTimers(config);
  vi.setTimerTickMode('nextTimerAsync');
  return result;
}) as typeof vi.useFakeTimers;

afterEach(() => {
  cleanup();
});
