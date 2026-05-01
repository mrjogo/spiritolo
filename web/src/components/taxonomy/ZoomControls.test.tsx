import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ZoomControls } from './ZoomControls';

describe('<ZoomControls>', () => {
  it('emits zoomIn on +', async () => {
    const user = userEvent.setup();
    const onZoomIn = vi.fn();
    render(<ZoomControls onZoomIn={onZoomIn} onZoomOut={() => {}} onFit={() => {}} />);
    await user.click(screen.getByRole('button', { name: /zoom in/i }));
    expect(onZoomIn).toHaveBeenCalled();
  });

  it('emits zoomOut on −', async () => {
    const user = userEvent.setup();
    const onZoomOut = vi.fn();
    render(<ZoomControls onZoomIn={() => {}} onZoomOut={onZoomOut} onFit={() => {}} />);
    await user.click(screen.getByRole('button', { name: /zoom out/i }));
    expect(onZoomOut).toHaveBeenCalled();
  });

  it('emits fit on the fit button', async () => {
    const user = userEvent.setup();
    const onFit = vi.fn();
    render(<ZoomControls onZoomIn={() => {}} onZoomOut={() => {}} onFit={onFit} />);
    await user.click(screen.getByRole('button', { name: /fit/i }));
    expect(onFit).toHaveBeenCalled();
  });
});
