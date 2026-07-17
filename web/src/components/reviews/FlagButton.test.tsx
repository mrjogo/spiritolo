import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FlagButton } from './FlagButton';

const useIsAdminMock = vi.fn();
const flagReviewMock = vi.fn();

vi.mock('../../auth/useIsAdmin', () => ({ useIsAdmin: () => useIsAdminMock() }));
vi.mock('../../reviews/flagReview', () => ({
  flagReview: (arg: unknown) => flagReviewMock(arg),
}));

beforeEach(() => {
  useIsAdminMock.mockReset();
  flagReviewMock.mockReset();
  flagReviewMock.mockResolvedValue(1);
});

describe('<FlagButton>', () => {
  it('renders null for a non-admin', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
    const { container } = render(
      <FlagButton entityKind="recipe" entityId="r-1" stage="map" />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('button')).toBeNull();
    expect(flagReviewMock).not.toHaveBeenCalled();
  });

  it('renders a Flag button for an admin', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    render(<FlagButton entityKind="recipe" entityId="r-1" stage="map" />);
    expect(screen.getByRole('button', { name: /flag/i })).toBeInTheDocument();
    expect(flagReviewMock).not.toHaveBeenCalled();
  });

  it('clicking calls flagReview with the right args and shows the flagged state', async () => {
    const user = userEvent.setup();
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    render(<FlagButton entityKind="ingredient" entityId="gin" stage="cluster" />);

    await user.click(screen.getByRole('button', { name: /flag/i }));

    expect(flagReviewMock).toHaveBeenCalledTimes(1);
    expect(flagReviewMock).toHaveBeenCalledWith({
      entityKind: 'ingredient',
      entityId: 'gin',
      stage: 'cluster',
    });

    // After success it collapses into the subtle "flagged" marker and the
    // button is gone (no double-flagging).
    expect(await screen.findByText(/flagged/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
