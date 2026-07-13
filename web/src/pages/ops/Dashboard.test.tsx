import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('./StageCard', () => ({
  StageCard: ({ stage }: { stage: string }) => <div data-testid="stage-card">{stage}</div>,
}));

import { Dashboard } from './Dashboard';

describe('<Dashboard>', () => {
  it('renders one StageCard per pipeline stage in discover -> ... -> export order', () => {
    render(<Dashboard />);
    const cards = screen.getAllByTestId('stage-card');
    expect(cards.map((c) => c.textContent)).toEqual([
      'discover', 'classify', 'fetch', 'extract', 'parse', 'map', 'role', 'cluster', 'export',
    ]);
  });
});
