import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';

// useNeedsReview owns the supabase read; mock it so this stays a pure,
// no-DB render test of the grouping/row output.
const useNeedsReviewMock = vi.fn();
vi.mock('../../reviews/useNeedsReview', () => ({
  useNeedsReview: () => useNeedsReviewMock(),
}));

import { ReviewsBrowser } from './ReviewsBrowser';

beforeEach(() => {
  useNeedsReviewMock.mockReset();
});

describe('<ReviewsBrowser>', () => {
  it('renders needs_review rows grouped by stage, each with its reason', () => {
    useNeedsReviewMock.mockReturnValue({
      status: 'loaded',
      rows: [
        { entity_kind: 'recipe', entity_id: '10', stage: 'parse', reason: 'human_flag' },
        { entity_kind: 'ingredient', entity_id: 'gin', stage: 'map', reason: 'distance_gate' },
      ],
    });

    render(<ReviewsBrowser />);

    // Both entities render with their identifiers.
    expect(screen.getByText('recipe')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('ingredient')).toBeInTheDocument();
    expect(screen.getByText('gin')).toBeInTheDocument();

    // Each row shows its reason as a pill.
    expect(screen.getByText('human_flag')).toBeInTheDocument();
    expect(screen.getByText('distance_gate')).toBeInTheDocument();

    // Rows are grouped into a per-stage section, and each row lands under
    // the section for its stage.
    const parseSection = screen.getByRole('region', { name: 'parse reviews' });
    expect(within(parseSection).getByText('human_flag')).toBeInTheDocument();
    const mapSection = screen.getByRole('region', { name: 'map reviews' });
    expect(within(mapSection).getByText('distance_gate')).toBeInTheDocument();
  });

  it('groups multiple rows of the same stage under one section', () => {
    useNeedsReviewMock.mockReturnValue({
      status: 'loaded',
      rows: [
        { entity_kind: 'recipe', entity_id: '1', stage: 'map', reason: 'machine_proposal' },
        { entity_kind: 'recipe', entity_id: '2', stage: 'map', reason: 'distance_gate' },
      ],
    });

    render(<ReviewsBrowser />);

    const mapSection = screen.getByRole('region', { name: 'map reviews' });
    // The count in the heading reflects both rows...
    expect(within(mapSection).getByText('(2)')).toBeInTheDocument();
    // ...and only one section exists for the shared stage.
    expect(screen.getAllByRole('region', { name: 'map reviews' })).toHaveLength(1);
  });

  it('shows an empty-state message when nothing needs review', () => {
    useNeedsReviewMock.mockReturnValue({ status: 'loaded', rows: [] });
    render(<ReviewsBrowser />);
    expect(screen.getByText(/nothing needs review/i)).toBeInTheDocument();
  });
});
