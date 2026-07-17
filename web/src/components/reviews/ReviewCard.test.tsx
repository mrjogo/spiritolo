import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReviewCard, type StageReview } from './ReviewCard';
import { resolveReview, dismissReview } from '../../reviews/flagReview';

// Mock the RPC clients so the card's actions are observable without a backend.
vi.mock('../../reviews/flagReview', () => ({
  resolveReview: vi.fn(),
  dismissReview: vi.fn(),
  flagReview: vi.fn(),
}));

const resolveReviewMock = vi.mocked(resolveReview);
const dismissReviewMock = vi.mocked(dismissReview);

function makeReview(over: Partial<StageReview> = {}): StageReview {
  return {
    id: 1,
    entity_kind: 'recipe_ingredient',
    entity_id: '42',
    stage: 'map',
    state: 'open',
    origin: 'human_flag',
    payload: null,
    note: null,
    ...over,
  };
}

beforeEach(() => {
  resolveReviewMock.mockReset();
  dismissReviewMock.mockReset();
});

describe('<ReviewCard>', () => {
  it('renders MapReviewBody for a map review', () => {
    const review = makeReview({
      stage: 'map',
      payload: { proposed_slug: 'aromatic-bitters', candidates: [{ slug: 'angostura-bitters', score: 0.9 }] },
    });
    render(<ReviewCard review={review} />);

    expect(screen.getByTestId('map-review-body')).toBeInTheDocument();
    expect(screen.queryByTestId('parse-review-body')).not.toBeInTheDocument();
    expect(screen.getByText('aromatic-bitters')).toBeInTheDocument();
  });

  it('renders ParseReviewBody for a parse review', () => {
    const review = makeReview({
      stage: 'parse',
      payload: { name: 'Angostura', amount: 2, unit: 'dash' },
    });
    render(<ReviewCard review={review} />);

    expect(screen.getByTestId('parse-review-body')).toBeInTheDocument();
    expect(screen.queryByTestId('map-review-body')).not.toBeInTheDocument();
    expect(screen.getByText('Angostura')).toBeInTheDocument();
    expect(screen.getByText('dash')).toBeInTheDocument();
  });

  it('falls back to a raw payload dump for an unknown stage', () => {
    const review = makeReview({ stage: 'cluster', payload: { foo: 'bar' } });
    render(<ReviewCard review={review} />);

    expect(screen.getByTestId('review-payload-fallback')).toBeInTheDocument();
    expect(screen.queryByTestId('map-review-body')).not.toBeInTheDocument();
  });

  it('shows the origin and note', () => {
    const review = makeReview({ origin: 'distance_gate', note: 'looks off' });
    render(<ReviewCard review={review} />);

    expect(screen.getByText('distance_gate')).toBeInTheDocument();
    expect(screen.getByText('looks off')).toBeInTheDocument();
  });

  it('Resolve calls resolveReview with the id and payload', async () => {
    const user = userEvent.setup();
    const payload = { proposed_slug: 'rye-whiskey' };
    const review = makeReview({ id: 7, stage: 'map', payload });
    render(<ReviewCard review={review} />);

    await user.click(screen.getByRole('button', { name: /resolve/i }));
    expect(resolveReviewMock).toHaveBeenCalledWith({ id: 7, payload });
    expect(dismissReviewMock).not.toHaveBeenCalled();
  });

  it('Dismiss calls dismissReview with the id', async () => {
    const user = userEvent.setup();
    const review = makeReview({ id: 9 });
    render(<ReviewCard review={review} />);

    await user.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(dismissReviewMock).toHaveBeenCalledWith(9);
    expect(resolveReviewMock).not.toHaveBeenCalled();
  });
});
