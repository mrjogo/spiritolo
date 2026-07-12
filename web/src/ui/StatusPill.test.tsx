import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusPill } from './StatusPill';

describe('<StatusPill>', () => {
  it('maps a stage_run outcome to its label and --st-* token', () => {
    render(<StatusPill kind="resolved" />);
    const pill = screen.getByText('resolved');
    expect(pill.style.color).toBe('var(--st-resolved)');
  });

  it('maps a job state to its label and --job-* token', () => {
    render(<StatusPill kind="running" />);
    const pill = screen.getByText('running');
    expect(pill.style.color).toBe('var(--job-running)');
  });

  it('renders "proposes new" with spaces for the proposes_new outcome', () => {
    render(<StatusPill kind="proposes_new" />);
    expect(screen.getByText('proposes new')).toBeInTheDocument();
  });

  it('falls back to a neutral pill for an unknown kind without throwing', () => {
    expect(() => render(<StatusPill kind="totally-unknown" />)).not.toThrow();
    const pill = screen.getByText('totally-unknown');
    expect(pill.style.color).toBe('var(--ops-muted)');
  });
});
