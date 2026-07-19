import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ReviewCard, type StageReview } from './ReviewCard';
import { resolveReview, dismissReview } from '../../reviews/flagReview';

function RouterWrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

vi.mock('../../reviews/flagReview', () => ({
  resolveReview: vi.fn().mockResolvedValue(undefined),
  dismissReview: vi.fn().mockResolvedValue(undefined),
  flagReview: vi.fn(),
}));

const resolveReviewMock = vi.mocked(resolveReview);
const dismissReviewMock = vi.mocked(dismissReview);

function makeReview(over: Partial<StageReview> = {}): StageReview {
  return {
    id: 1,
    entity_kind: 'recipe_ingredient',
    entity_id: '42',
    stage: 'map-ingredient',
    state: 'open',
    origin: 'human_flag',
    payload: null,
    note: null,
    ...over,
  };
}

beforeEach(() => {
  resolveReviewMock.mockReset().mockResolvedValue(undefined);
  dismissReviewMock.mockReset().mockResolvedValue(undefined);
});

describe('<ReviewCard>', () => {
  it('renders MapReviewBody for a map review', () => {
    const review = makeReview({
      stage: 'map-ingredient',
      payload: { proposed_slug: 'aromatic-bitters', candidates: [{ slug: 'angostura-bitters', score: 0.9 }] },
    });
    render(<ReviewCard review={review} />, { wrapper: RouterWrapper });
    expect(screen.getByTestId('map-review-body')).toBeInTheDocument();
    expect(screen.queryByTestId('parse-review-body')).not.toBeInTheDocument();
  });

  it('renders ParseReviewBody for a parse review', () => {
    const review = makeReview({ stage: 'parse-ingredients', payload: { name: 'Angostura', amount: 2, unit: 'dash' } });
    render(<ReviewCard review={review} />, { wrapper: RouterWrapper });
    expect(screen.getByTestId('parse-review-body')).toBeInTheDocument();
    expect(screen.queryByTestId('map-review-body')).not.toBeInTheDocument();
  });

  it('shows the editable payload JSON for a stage without a body', () => {
    const review = makeReview({ stage: 'cluster-recipes', payload: { foo: 'bar' } });
    render(<ReviewCard review={review} />, { wrapper: RouterWrapper });
    expect(screen.queryByTestId('map-review-body')).not.toBeInTheDocument();
    const editor = screen.getByLabelText('payload JSON') as HTMLTextAreaElement;
    expect(editor.value).toContain('bar');
  });

  it('shows the origin and note', () => {
    const review = makeReview({ origin: 'distance_gate', note: 'looks off' });
    render(<ReviewCard review={review} />, { wrapper: RouterWrapper });
    expect(screen.getByText('distance_gate')).toBeInTheDocument();
    expect(screen.getByText('looks off')).toBeInTheDocument();
  });

  it('Resolve sends the id and the (default) payload, then calls onActed', async () => {
    const user = userEvent.setup();
    const onActed = vi.fn();
    const review = makeReview({ id: 7, stage: 'map-ingredient', payload: { proposed_slug: 'rye-whiskey' } });
    render(<ReviewCard review={review} onActed={onActed} />, { wrapper: RouterWrapper });

    await user.click(screen.getByRole('button', { name: /resolve/i }));
    expect(resolveReviewMock).toHaveBeenCalledWith({ id: 7, payload: { proposed_slug: 'rye-whiskey' } });
    expect(onActed).toHaveBeenCalled();
    expect(dismissReviewMock).not.toHaveBeenCalled();
  });

  it('Resolve sends the EDITED payload', async () => {
    const user = userEvent.setup();
    const review = makeReview({ id: 8, stage: 'map-ingredient', payload: { slug: 'old' } });
    render(<ReviewCard review={review} />, { wrapper: RouterWrapper });

    fireEvent.change(screen.getByLabelText('payload JSON'), {
      target: { value: '{"slug":"lime-juice"}' },
    });
    await user.click(screen.getByRole('button', { name: /resolve/i }));
    expect(resolveReviewMock).toHaveBeenCalledWith({ id: 8, payload: { slug: 'lime-juice' } });
  });

  it('does not submit invalid JSON and shows an error', async () => {
    const user = userEvent.setup();
    render(<ReviewCard review={makeReview()} />, { wrapper: RouterWrapper });
    fireEvent.change(screen.getByLabelText('payload JSON'), { target: { value: '{not json' } });
    await user.click(screen.getByRole('button', { name: /resolve/i }));
    expect(resolveReviewMock).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/not valid json/i);
  });

  it('Dismiss calls dismissReview with the id', async () => {
    const user = userEvent.setup();
    const review = makeReview({ id: 9 });
    render(<ReviewCard review={review} />, { wrapper: RouterWrapper });
    await user.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(dismissReviewMock).toHaveBeenCalledWith(9);
    expect(resolveReviewMock).not.toHaveBeenCalled();
  });
});
