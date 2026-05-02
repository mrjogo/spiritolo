import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, vi } from 'vitest';

// jsdom does not implement HTMLCanvasElement.getContext('2d'). Patch it to return
// a minimal fake so canvas-dependent code (e.g. shapeData.getMeasureCtx) doesn't
// throw during tests.
beforeAll(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (HTMLCanvasElement.prototype as any).getContext = () => ({
    font: '',
    measureText: (text: string) => ({ width: text.length * 6 } as TextMetrics),
  });
});

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
