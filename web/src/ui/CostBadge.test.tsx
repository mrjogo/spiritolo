import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CostBadge } from './CostBadge';
import { formatCents } from './formatCents';

describe('formatCents', () => {
  it('formats 42 cents as $0.42', () => {
    expect(formatCents(42)).toBe('$0.42');
  });
  it('formats 0 cents as $0.00', () => {
    expect(formatCents(0)).toBe('$0.00');
  });
  it('formats null/undefined as an em dash', () => {
    expect(formatCents(null)).toBe('—');
    expect(formatCents(undefined)).toBe('—');
  });
});

describe('<CostBadge>', () => {
  it('renders the formatted amount', () => {
    render(<CostBadge cents={1234} />);
    expect(screen.getByText('$12.34')).toBeInTheDocument();
  });

  it('adds a coin glyph and the metered class when metered', () => {
    const { container } = render(<CostBadge cents={5} metered />);
    expect(container.querySelector('.cost-badge--metered')).toBeInTheDocument();
    expect(container.querySelector('.cost-badge__coin')).toBeInTheDocument();
  });

  it('does not add the coin glyph when not metered', () => {
    const { container } = render(<CostBadge cents={5} />);
    expect(container.querySelector('.cost-badge__coin')).not.toBeInTheDocument();
  });

  it('distinguishes est vs actual labels', () => {
    const { rerender } = render(<CostBadge cents={100} variant="est" />);
    expect(screen.getByText('est')).toBeInTheDocument();
    rerender(<CostBadge cents={100} variant="actual" />);
    expect(screen.getByText('actual')).toBeInTheDocument();
  });
});
