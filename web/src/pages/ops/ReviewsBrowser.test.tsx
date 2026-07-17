import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const useOpenReviewsMock = vi.fn();
const useNeedsReviewMock = vi.fn();
vi.mock('../../reviews/useOpenReviews', () => ({
  useOpenReviews: () => useOpenReviewsMock(),
  openReviewsQueryKey: ['openReviews'],
}));
vi.mock('../../reviews/useNeedsReview', () => ({
  useNeedsReview: () => useNeedsReviewMock(),
}));
// Stub the card so this stays a pure render test of the browser's grouping.
vi.mock('../../components/reviews/ReviewCard', () => ({
  ReviewCard: ({ review }: { review: { stage: string; entity_id: string } }) => (
    <div data-testid="review-card" data-stage={review.stage}>
      {review.entity_id}
    </div>
  ),
}));

import { ReviewsBrowser } from './ReviewsBrowser';

function renderBrowser() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ReviewsBrowser />
    </QueryClientProvider>,
  );
}

function review(over: Record<string, unknown>) {
  return {
    id: 1, entity_kind: 'x', entity_id: 'e', stage: 'map',
    state: 'open', origin: 'human_flag', payload: null, note: null, ...over,
  };
}

beforeEach(() => {
  useOpenReviewsMock.mockReset();
  useNeedsReviewMock.mockReset().mockReturnValue({ status: 'loaded', rows: [] });
});

describe('<ReviewsBrowser>', () => {
  it('renders open reviews as cards grouped by stage', () => {
    useOpenReviewsMock.mockReturnValue({
      status: 'loaded',
      total: 2,
      rows: [
        review({ id: 1, entity_id: 'gin', stage: 'map' }),
        review({ id: 2, entity_id: '5:0', stage: 'parse' }),
      ],
    });
    renderBrowser();
    expect(screen.getAllByTestId('review-card')).toHaveLength(2);
    expect(within(screen.getByRole('region', { name: 'map reviews' })).getByText('gin')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'parse reviews' })).getByText('5:0')).toBeInTheDocument();
  });

  it('lists stuck needs_review rows (abstains) separately, excluding open-review reasons', () => {
    useOpenReviewsMock.mockReturnValue({ status: 'loaded', total: 0, rows: [] });
    useNeedsReviewMock.mockReturnValue({
      status: 'loaded',
      rows: [
        { entity_kind: 'recipe', entity_id: '10', stage: 'parse', reason: 'abstain' },
        { entity_kind: 'ingredient', entity_id: 'suze', stage: 'map', reason: 'human_flag' },
      ],
    });
    renderBrowser();
    const stuck = screen.getByRole('region', { name: 'pipeline stuck' });
    expect(within(stuck).getByText('abstain')).toBeInTheDocument();
    expect(within(stuck).getByText('10')).toBeInTheDocument();
    expect(within(stuck).queryByText('suze')).not.toBeInTheDocument();
  });

  it('shows an empty-state when there are no open reviews', () => {
    useOpenReviewsMock.mockReturnValue({ status: 'loaded', total: 0, rows: [] });
    renderBrowser();
    expect(screen.getByText(/no open reviews/i)).toBeInTheDocument();
  });
});
