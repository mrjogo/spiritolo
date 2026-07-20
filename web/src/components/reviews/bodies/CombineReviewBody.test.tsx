import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CombineReviewBody } from './CombineReviewBody';
import type { StageReview } from '../ReviewCard';

function makeReview(payload: unknown): StageReview {
  return {
    id: 1,
    entity_kind: 'taxonomy_node',
    entity_id: 'abc-123',
    stage: 'combine-nodes',
    state: 'open',
    origin: 'machine_proposal',
    payload,
    note: null,
  };
}

describe('<CombineReviewBody>', () => {
  it('renders the candidate nodes with slug, display name, and status chip', () => {
    const review = makeReview({
      candidates: [
        { slug: 'angostura-bitters', display_name: 'Angostura Bitters', status: 'live' },
        { slug: 'angostura-aromatic', display_name: 'Angostura Aromatic', status: 'provisional' },
      ],
    });
    render(<CombineReviewBody review={review} />);
    expect(screen.getByTestId('combine-review-body')).toBeInTheDocument();
    expect(screen.getByText('angostura-bitters')).toBeInTheDocument();
    expect(screen.getByText('Angostura Bitters')).toBeInTheDocument();
    expect(screen.getByText('live')).toBeInTheDocument();
    expect(screen.getByText('angostura-aromatic')).toBeInTheDocument();
    expect(screen.getByText('provisional')).toBeInTheDocument();
  });

  it('renders the Resolve payload-shape hint', () => {
    render(<CombineReviewBody review={makeReview({ candidates: [] })} />);
    expect(
      screen.getByText('{ "survivor_id": <id>, "absorbed_id": <id> }'),
    ).toBeInTheDocument();
  });

  it('handles a missing/empty candidates array gracefully', () => {
    render(<CombineReviewBody review={makeReview(null)} />);
    expect(screen.getByTestId('combine-review-body')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
