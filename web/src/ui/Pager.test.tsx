import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Pager } from './Pager';

describe('<Pager>', () => {
  it('shows the range and disables Prev on the first page', () => {
    render(<Pager page={1} pageSize={50} total={120} onPage={() => {}} unit="recipes" />);
    expect(screen.getByText('1–50 of 120 recipes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /next/i })).toBeEnabled();
  });

  it('shows the last-page range, disables Next, and pages back on Prev', async () => {
    const onPage = vi.fn();
    render(<Pager page={3} pageSize={50} total={120} onPage={onPage} />);
    expect(screen.getByText('101–120 of 120 rows')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: /prev/i }));
    expect(onPage).toHaveBeenCalledWith(2);
  });

  it('reads 0–0 of 0 and disables both ends when empty', () => {
    render(<Pager page={1} pageSize={50} total={0} onPage={() => {}} />);
    expect(screen.getByText('0–0 of 0 rows')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });
});
