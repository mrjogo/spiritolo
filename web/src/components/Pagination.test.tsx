import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { Pagination } from './Pagination';

function Harness({ initialPath, totalPages }: { initialPath: string; totalPages: number }) {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <Pagination totalPages={totalPages} />
              <CurrentPage />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

function CurrentPage() {
  const [params] = useSearchParams();
  return <div data-testid="current-page">{params.get('page') ?? '1'}</div>;
}

describe('<Pagination>', () => {
  it('shows "Page N of M"', () => {
    render(<Harness initialPath="/?page=3" totalPages={10} />);
    expect(screen.getByText('Page 3 of 10')).toBeInTheDocument();
  });

  it('defaults to page 1 when no ?page param', () => {
    render(<Harness initialPath="/" totalPages={5} />);
    expect(screen.getByText('Page 1 of 5')).toBeInTheDocument();
  });

  it('disables Prev on page 1', () => {
    render(<Harness initialPath="/" totalPages={5} />);
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
  });

  it('disables Next on the last page', () => {
    render(<Harness initialPath="/?page=5" totalPages={5} />);
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });

  it('advances page on Next click', async () => {
    render(<Harness initialPath="/?page=2" totalPages={5} />);
    await userEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByTestId('current-page').textContent).toBe('3');
  });

  it('decrements page on Prev click', async () => {
    render(<Harness initialPath="/?page=3" totalPages={5} />);
    await userEvent.click(screen.getByRole('button', { name: /prev/i }));
    expect(screen.getByTestId('current-page').textContent).toBe('2');
  });

  it('renders nothing when totalPages <= 1', () => {
    const { container } = render(<Harness initialPath="/" totalPages={1} />);
    expect(container.querySelector('.pagination')).toBeNull();
  });
});
