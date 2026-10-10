import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CustomSelect, type CustomSelectOption } from './CustomSelect';

afterEach(() => { vi.restoreAllMocks(); });

describe('CustomSelect', () => {
  const options: CustomSelectOption[] = [
    { value: 'm1', label: 'Model One', sublabel: 'gemini-1.5-flash' },
    { value: 'm2', label: 'Model Two', sublabel: 'gemini-1.5-pro' },
    { value: 'm3', label: 'Disabled Model', disabled: true },
  ];

  it.each([
    { triggerTop: 600, boundaryBottom: 700, direction: 'bottom-full', height: 240 },
    { triggerTop: 200, boundaryBottom: 700, direction: 'top-full', height: 240 },
    { triggerTop: 200, boundaryBottom: 300, direction: 'bottom-full', height: 94 },
  ])('fits the menu inside the scroll area: $direction, $height pixels', ({ triggerTop, boundaryBottom, direction, height }) => {
    const { getByTestId, unmount } = render(
      <div data-testid="scroll-area" style={{ overflowY: 'auto' }}>
        <CustomSelect value="m1" onChange={vi.fn()} options={options} />
      </div>,
    );
    const boundary = getByTestId('scroll-area');
    const trigger = screen.getByRole('button', { name: /Model One/i });
    const container = trigger.parentElement!;
    vi.spyOn(boundary, 'getBoundingClientRect').mockReturnValue({ top: 100, bottom: boundaryBottom } as DOMRect);
    vi.spyOn(boundary, 'clientHeight', 'get').mockReturnValue(boundaryBottom - 100);
    vi.spyOn(container, 'getBoundingClientRect').mockReturnValue({ top: triggerTop, bottom: triggerTop + 40 } as DOMRect);
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(400);
    fireEvent.click(trigger);
    const menu = screen.getByRole('listbox');
    expect(menu.classList.contains(direction)).toBe(true);
    expect(menu.style.maxHeight).toBe(`${height}px`);
    // Reposition the open menu when its scroll container moves the trigger.
    vi.mocked(container.getBoundingClientRect).mockReturnValue({ top: 110, bottom: 150 } as DOMRect);
    fireEvent.scroll(boundary);
    expect(menu.classList.contains('top-full')).toBe(true);
    unmount();
  });

  it('renders selected option and sublabel', () => {
    render(
      <CustomSelect
        value="m1"
        onChange={vi.fn()}
        options={options}
      />,
    );

    expect(screen.getAllByText('Model One').length).toBeGreaterThan(0);
    expect(screen.getByText('(gemini-1.5-flash)')).toBeTruthy();
  });

  it('opens overlay on click and selects an option', () => {
    const onChange = vi.fn();
    render(
      <CustomSelect
        value="m1"
        onChange={onChange}
        options={options}
      />,
    );

    const trigger = screen.getByRole('button', { name: /Model One/i });
    expect(trigger.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');

    // Listbox should now be visible
    expect(screen.getByRole('listbox')).toBeTruthy();

    // Click on 'Model Two'
    const optionTwo = screen.getByRole('option', { name: /Model Two/i });
    fireEvent.click(optionTwo);

    expect(onChange).toHaveBeenCalledWith('m2');
  });

  it('closes dropdown on Escape keydown', () => {
    render(
      <CustomSelect
        value="m1"
        onChange={vi.fn()}
        options={options}
      />,
    );

    const trigger = screen.getByRole('button', { name: /Model One/i });
    fireEvent.click(trigger);
    expect(screen.getByRole('listbox')).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('does not select disabled options', () => {
    const onChange = vi.fn();
    render(
      <CustomSelect
        value="m1"
        onChange={onChange}
        options={options}
      />,
    );

    const trigger = screen.getByRole('button', { name: /Model One/i });
    fireEvent.click(trigger);

    const disabledOpt = screen.getByRole('option', { name: /Disabled Model/i });
    fireEvent.click(disabledOpt);

    expect(onChange).not.toHaveBeenCalled();
  });

  it('renders badge pill when provided in trigger and dropdown', () => {
    const optionsWithBadge: CustomSelectOption[] = [
      { value: 'm1', label: 'Model One', badge: 'Default' },
      { value: 'm2', label: 'Model Two' },
    ];
    render(
      <CustomSelect
        value="m1"
        onChange={vi.fn()}
        options={optionsWithBadge}
      />,
    );

    expect(screen.getByText('Default')).toBeTruthy();

    const trigger = screen.getByRole('button', { name: /Model One/i });
    fireEvent.click(trigger);

    expect(screen.getAllByText('Default').length).toBe(2);
  });
});
