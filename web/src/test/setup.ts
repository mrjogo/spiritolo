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

afterEach(async () => {
  cleanup();
  // Drain any pending real-timer callbacks left by unawaited userEvent calls
  // (e.g. userEvent.setup().type(el, text) without await). Without this,
  // pending setTimeout(0) events from one test fire into the next test's DOM
  // via userEvent's getActiveElementOrBody, corrupting keyboard state.
  // We drain 40 rounds to cover up to 40 pending setTimeout(0) chains.
  for (let i = 0; i < 40; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
});
