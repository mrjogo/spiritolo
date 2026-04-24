import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { Pagination } from './Pagination';

function Harness({
  initialPath,
  total,
  pageSize = 50,
}: {
  initialPath: string;
  total: number;
  pageSize?: number;
}) {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <Pagination total={total} pageSize={pageSize} />
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
  it('shows the row range and total ("1–50 of 127" on page 1)', () => {
    render(<Harness initialPath="/" total={127} />);
    expect(screen.getByText('1–50 of 127')).toBeInTheDocument();
  });

  it('shows the correct range on a middle page', () => {
    render(<Harness initialPath="/?page=2" total={127} />);
    expect(screen.getByText('51–100 of 127')).toBeInTheDocument();
  });

  it('clamps the range end to the total on the last page', () => {
    render(<Harness initialPath="/?page=3" total={127} />);
    expect(screen.getByText('101–127 of 127')).toBeInTheDocument();
  });

  it('disables Prev on page 1', () => {
    render(<Harness initialPath="/" total={250} />);
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
  });

  it('disables Next on the last page', () => {
    render(<Harness initialPath="/?page=5" total={250} />);
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });

  it('advances page on Next click', async () => {
    render(<Harness initialPath="/?page=2" total={250} />);
    await userEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByTestId('current-page').textContent).toBe('3');
  });

  it('decrements page on Prev click', async () => {
    render(<Harness initialPath="/?page=3" total={250} />);
    await userEvent.click(screen.getByRole('button', { name: /prev/i }));
    expect(screen.getByTestId('current-page').textContent).toBe('2');
  });

  it('renders nothing when there is only one page', () => {
    const { container } = render(<Harness initialPath="/" total={40} />);
    expect(container.querySelector('.pagination')).toBeNull();
  });

  it('renders nothing when total is zero', () => {
    const { container } = render(<Harness initialPath="/" total={0} />);
    expect(container.querySelector('.pagination')).toBeNull();
  });
});
