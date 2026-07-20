import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConnectReviewBody } from './ConnectReviewBody';
import type { StageReview } from '../ReviewCard';

function makeReview(payload: unknown): StageReview {
  return {
    id: 1,
    entity_kind: 'taxonomy_node',
    entity_id: 'abc-123',
    stage: 'connect-nodes',
    state: 'open',
    origin: 'machine_proposal',
    payload,
    note: null,
  };
}

describe('<ConnectReviewBody>', () => {
  it('renders the candidate parents with slug and display name', () => {
    const review = makeReview({
      candidate_parents: [
        { slug: 'aromatic-bitters', display_name: 'Aromatic Bitters' },
        { slug: 'bitters', display_name: 'Bitters' },
      ],
    });
    render(<ConnectReviewBody review={review} />);
    expect(screen.getByTestId('connect-review-body')).toBeInTheDocument();
    expect(screen.getByText('aromatic-bitters')).toBeInTheDocument();
    expect(screen.getByText('Aromatic Bitters')).toBeInTheDocument();
    expect(screen.getByText('bitters')).toBeInTheDocument();
  });

  it('renders a rejected proposed placement when present', () => {
    const review = makeReview({
      candidate_parents: [],
      proposed: { node_kind: 'brand', parent_slugs: ['whiskey'] },
    });
    render(<ConnectReviewBody review={review} />);
    expect(screen.getByText(/proposed \(rejected\)/i)).toBeInTheDocument();
    expect(screen.getByText(/whiskey/)).toBeInTheDocument();
  });

  it('renders the Resolve payload-shape hint', () => {
    render(<ConnectReviewBody review={makeReview({ candidate_parents: [] })} />);
    expect(
      screen.getByText(
        '{ "node_kind": "brand"|"expression"|null, "parent_slugs": [...], "is_cluster_node": <bool> }',
      ),
    ).toBeInTheDocument();
  });

  it('handles a missing/empty candidate_parents array gracefully', () => {
    render(<ConnectReviewBody review={makeReview(null)} />);
    expect(screen.getByTestId('connect-review-body')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
