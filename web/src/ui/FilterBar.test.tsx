import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterBar } from './FilterBar';

describe('<FilterBar>', () => {
  it('emits ONE {filters, scope} object per change, with scope.where the SAME array as filters', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <FilterBar
        stage="extract-recipe"
        siteOptions={['punch', 'diffordsguide']}
        chipOptions={[
          { key: 'abstain', label: 'abstain' },
          { key: 'failed', label: 'failed' },
        ]}
        onChange={onChange}
      />,
    );

    await user.selectOptions(screen.getByLabelText(/site/i), 'punch');
    expect(onChange).toHaveBeenCalledTimes(1);
    let call = onChange.mock.calls[0][0];
    expect(call.filters).toEqual([{ col: 'site', op: 'eq', value: 'punch' }]);
    expect(call.scope).toEqual({
      kind: 'filter', stage: 'extract-recipe', site: 'punch', where: call.filters,
    });
    // The single-object contract: scope.where IS filters, not a copy — the
    // same array feeds usePagedQuery (what you see) and enqueue_job (what
    // you act on), so they can't drift apart.
    expect(call.scope.where).toBe(call.filters);

    await user.click(screen.getByRole('button', { name: /abstain/i }));
    call = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(call.filters).toEqual([
      { col: 'site', op: 'eq', value: 'punch' },
      { col: 'outcome', op: 'eq', value: 'abstain' },
    ]);
    expect(call.scope.where).toBe(call.filters);

    await user.type(screen.getByLabelText(/filter text/i), 'negroni');
    call = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(call.filters).toContainEqual({ col: 'name', op: 'ilike', value: '%negroni%' });
    expect(call.scope.where).toBe(call.filters);
  });

  it('reuses taxonomy/FilterChips for the chip row (composition, not reimplementation)', () => {
    render(
      <FilterBar
        chipOptions={[{ key: 'abstain', label: 'abstain' }]}
        onChange={vi.fn()}
      />,
    );
    // FilterChips renders a `role="group"` chip row; assert the role is
    // present rather than re-testing FilterChips' own toggle behavior.
    expect(screen.getByRole('group')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /abstain/i })).toBeInTheDocument();
  });
});
