import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterChips, type FilterKey } from './FilterChips';

describe('<FilterChips>', () => {
  it('renders one chip per filter key', () => {
    render(<FilterChips active={new Set()} onToggle={() => {}} />);
    for (const label of ['substance', 'expression', 'brand', 'cluster', 'orphan', 'no aliases', 'zero recipes']) {
      expect(screen.getByRole('button', { name: new RegExp(label, 'i') })).toBeInTheDocument();
    }
  });

  it('emits onToggle with the chip key when clicked', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(<FilterChips active={new Set()} onToggle={onToggle} />);
    await user.click(screen.getByRole('button', { name: /expression/i }));
    expect(onToggle).toHaveBeenCalledWith('expression' satisfies FilterKey);
  });

  it('marks active chips with aria-pressed=true', () => {
    render(<FilterChips active={new Set(['orphan'])} onToggle={() => {}} />);
    const chip = screen.getByRole('button', { name: /orphan/i });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
  });
});
