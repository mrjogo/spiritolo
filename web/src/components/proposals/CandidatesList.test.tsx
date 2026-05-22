import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CandidatesList } from './CandidatesList';

const CANDS = [
  { node_id: 10, display_name: 'Lemon Peel', similarity: 0.87 },
  { node_id: 11, display_name: 'Lemon Twist', similarity: 0.74 },
];

describe('<CandidatesList>', () => {
  it('renders one row per candidate with similarity', () => {
    render(<CandidatesList candidates={CANDS} onPick={vi.fn()} />);
    expect(screen.getByText(/Lemon Peel/)).toBeInTheDocument();
    expect(screen.getByText(/0\.87/)).toBeInTheDocument();
    expect(screen.getByText(/Lemon Twist/)).toBeInTheDocument();
  });

  it('clicking a candidate calls onPick with its node_id', async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<CandidatesList candidates={CANDS} onPick={onPick} />);
    await user.click(screen.getByText(/Lemon Twist/));
    expect(onPick).toHaveBeenCalledWith(11);
  });

  it('renders an empty-state message when there are no candidates', () => {
    render(<CandidatesList candidates={[]} onPick={vi.fn()} />);
    expect(screen.getByText(/no candidates/i)).toBeInTheDocument();
  });
});
